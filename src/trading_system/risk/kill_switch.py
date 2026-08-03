"""Durable, explicitly resettable kill-switch state.

This Phase-0 file store exists so a halt survives a process restart. PostgreSQL
becomes the paper/live authority in a later phase. Architecture reference: §10.6.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import suppress
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from trading_system.exceptions import KillSwitchPersistenceError

_MAX_STATE_BYTES: Final = 4_194_304


class KillSwitchScope(StrEnum):
    """Supported halt scopes from architecture §10.6."""

    GLOBAL = "global"
    STRATEGY = "strategy"
    INSTRUMENT = "instrument"
    ENTRY = "entry"


class KillSwitchAction(StrEnum):
    """Audited mutations to emergency state."""

    LATCHED = "latched"
    CLEARED = "cleared"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class KillSwitchRecord(_FrozenModel):
    """One active durable latch."""

    record_id: UUID
    scope: KillSwitchScope
    target_id: str | None
    reason: str = Field(min_length=1, max_length=500)
    actor: str = Field(min_length=1, max_length=128)
    latched_at: datetime

    @field_validator("latched_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("latched_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_target_for_scoped_latch(self) -> KillSwitchRecord:
        if self.scope is KillSwitchScope.GLOBAL and self.target_id is not None:
            raise ValueError("a global latch must not have target_id")
        if self.scope in {KillSwitchScope.STRATEGY, KillSwitchScope.INSTRUMENT} and (
            self.target_id is None or not self.target_id.strip()
        ):
            raise ValueError(f"{self.scope.value} latch requires target_id")
        return self


class KillSwitchHistoryEntry(_FrozenModel):
    """Append-only emergency-state mutation evidence."""

    action_id: UUID
    action: KillSwitchAction
    record_id: UUID
    scope: KillSwitchScope
    target_id: str | None
    reason: str = Field(min_length=1, max_length=500)
    actor: str = Field(min_length=1, max_length=128)
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value.astimezone(UTC)


class KillSwitchDocument(_FrozenModel):
    """On-disk schema; unknown fields and versions fail closed."""

    schema_version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    active: tuple[KillSwitchRecord, ...] = ()
    history: tuple[KillSwitchHistoryEntry, ...] = ()


class FileKillSwitchStore:
    """Atomically persisted Phase-0 kill-switch state."""

    def __init__(self, state_file: Path) -> None:
        self._path = state_file
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        """Return the configured emergency-state file."""
        return self._path

    def initialize(self) -> KillSwitchDocument:
        """Create clear state once, or validate existing durable state."""
        with self._lock:
            if self._path.exists():
                return self._load_unlocked()
            document = KillSwitchDocument()
            self._write_unlocked(document)
            return document

    def snapshot(self) -> KillSwitchDocument:
        """Read and strictly validate the current durable state."""
        with self._lock:
            return self._load_unlocked()

    def is_global_latched(self) -> bool:
        """Return whether startup must remain halted (§10.6)."""
        document = self.snapshot()
        return any(record.scope is KillSwitchScope.GLOBAL for record in document.active)

    def blocks(self, scope: KillSwitchScope, target_id: str | None = None) -> bool:
        """Check a scope while always honoring the global latch."""
        document = self.snapshot()
        for record in document.active:
            if record.scope is KillSwitchScope.GLOBAL:
                return True
            if record.scope is scope and record.target_id == target_id:
                return True
        return False

    def latch(
        self,
        scope: KillSwitchScope,
        *,
        reason: str,
        actor: str,
        target_id: str | None = None,
    ) -> KillSwitchRecord:
        """Latch a scope durably; repeated latches of that scope are idempotent."""
        with self._lock:
            document = self._load_unlocked()
            for record in document.active:
                if record.scope is scope and record.target_id == target_id:
                    return record
            now = datetime.now(UTC)
            record = KillSwitchRecord(
                record_id=uuid4(),
                scope=scope,
                target_id=target_id,
                reason=reason,
                actor=actor,
                latched_at=now,
            )
            history = KillSwitchHistoryEntry(
                action_id=uuid4(),
                action=KillSwitchAction.LATCHED,
                record_id=record.record_id,
                scope=record.scope,
                target_id=record.target_id,
                reason=reason,
                actor=actor,
                occurred_at=now,
            )
            updated = document.model_copy(
                update={
                    "revision": document.revision + 1,
                    "active": (*document.active, record),
                    "history": (*document.history, history),
                }
            )
            self._write_unlocked(updated)
            return record

    def clear(
        self,
        scope: KillSwitchScope,
        *,
        reason: str,
        authorized_by: str,
        target_id: str | None = None,
    ) -> bool:
        """Explicitly clear one latch and retain an audit record.

        There is deliberately no automatic or time-based reset path.
        """
        with self._lock:
            document = self._load_unlocked()
            matching = next(
                (
                    record
                    for record in document.active
                    if record.scope is scope and record.target_id == target_id
                ),
                None,
            )
            if matching is None:
                return False
            now = datetime.now(UTC)
            history = KillSwitchHistoryEntry(
                action_id=uuid4(),
                action=KillSwitchAction.CLEARED,
                record_id=matching.record_id,
                scope=matching.scope,
                target_id=matching.target_id,
                reason=reason,
                actor=authorized_by,
                occurred_at=now,
            )
            updated = document.model_copy(
                update={
                    "revision": document.revision + 1,
                    "active": tuple(record for record in document.active if record != matching),
                    "history": (*document.history, history),
                }
            )
            self._write_unlocked(updated)
            return True

    def _assert_safe_path(self) -> None:
        if self._path.is_symlink():
            raise KillSwitchPersistenceError("kill-switch state file must not be a symlink")
        for parent in self._path.parents:
            if parent.exists() and parent.is_symlink():
                raise KillSwitchPersistenceError(
                    "kill-switch state directory must not contain a symlink"
                )

    def _load_unlocked(self) -> KillSwitchDocument:
        self._assert_safe_path()
        try:
            if not self._path.is_file():
                raise KillSwitchPersistenceError("kill-switch state file is missing")
            if self._path.stat().st_size > _MAX_STATE_BYTES:
                raise KillSwitchPersistenceError("kill-switch state file exceeds size limit")
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            return KillSwitchDocument.model_validate(payload)
        except KillSwitchPersistenceError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
            raise KillSwitchPersistenceError("kill-switch state is unreadable or invalid") from exc

    def _write_unlocked(self, document: KillSwitchDocument) -> None:
        self._assert_safe_path()
        parent = self._path.parent
        temporary_path: Path | None = None
        descriptor: int | None = None
        try:
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                dir=parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                text=True,
            )
            temporary_path = Path(temporary_name)
            temporary_path.chmod(0o600)
            with os.fdopen(descriptor, mode="w", encoding="utf-8", newline="\n") as handle:
                descriptor = None
                handle.write(document.model_dump_json(indent=2))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary_path.replace(self._path)
            self._path.chmod(0o600)
        except OSError as exc:
            raise KillSwitchPersistenceError("cannot persist kill-switch state atomically") from exc
        finally:
            if descriptor is not None:
                with suppress(OSError):
                    os.close(descriptor)
            if temporary_path is not None and temporary_path.exists():
                with suppress(OSError):
                    temporary_path.unlink()
