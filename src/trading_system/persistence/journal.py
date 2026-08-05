"""Append-only, schema-versioned event journal with an in-memory test backend."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class JournalEvent:
    event_type: str
    aggregate_id: str
    payload: Mapping[str, object]
    correlation_id: UUID
    schema_version: int = 1
    event_id: UUID = field(default_factory=uuid4)
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(UTC))


class EventJournal:
    def append(self, event: JournalEvent) -> None:
        raise NotImplementedError

    def events(self) -> tuple[JournalEvent, ...]:
        raise NotImplementedError


class InMemoryEventJournal(EventJournal):
    def __init__(self) -> None:
        self._events: list[JournalEvent] = []

    def append(self, event: JournalEvent) -> None:
        self._events.append(event)

    def events(self) -> tuple[JournalEvent, ...]:
        return tuple(self._events)
