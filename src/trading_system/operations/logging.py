"""Structured JSON logging with mandatory redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from typing import IO, Any, Final

from trading_system.config import Environment, LoggingConfig
from trading_system.operations.redaction import redact

_EVENT_NAME: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _json_default(value: object) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


class RedactingJsonFormatter(logging.Formatter):
    """Render one sanitized JSON object per line (§15.8)."""

    def __init__(
        self,
        *,
        service: str,
        environment: Environment,
        config_hash: str,
        artifact_digest: str,
    ) -> None:
        super().__init__()
        self._base_fields = {
            "service": service,
            "environment": environment.value,
            "config_hash": config_hash,
            "artifact_digest": artifact_digest,
        }

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=UTC).isoformat(
            timespec="milliseconds"
        )
        timestamp = timestamp.replace("+00:00", "Z")
        event_name = getattr(record, "event_name", "log_message")
        event_fields = getattr(record, "event_fields", {})
        if not isinstance(event_fields, dict):
            event_fields = {"invalid_event_fields_type": type(event_fields).__name__}
        payload: dict[str, object] = {
            "timestamp": timestamp,
            "level": record.levelname,
            **event_fields,
            **self._base_fields,
            "event": event_name,
        }
        message = record.getMessage()
        if message and message != event_name:
            payload["message"] = message
        if record.exc_info is not None:
            exception_type = record.exc_info[0]
            exception_value = record.exc_info[1]
            payload["exception"] = {
                "type": exception_type.__name__ if exception_type is not None else "Unknown",
                "message": str(exception_value) if exception_value is not None else "",
            }
        sanitized = redact(payload)
        return json.dumps(
            sanitized,
            default=_json_default,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )


class StructuredLogger:
    """Small typed facade that prevents unstructured production log calls."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def event(
        self,
        level: int,
        event_name: str,
        *,
        exc_info: BaseException | None = None,
        **fields: object,
    ) -> None:
        """Emit a structured event after validating its stable event name."""
        self._emit(level, event_name, fields=fields, exc_info=exc_info)

    def _emit(
        self,
        level: int,
        event_name: str,
        *,
        fields: Mapping[str, object],
        exc_info: BaseException | None = None,
    ) -> None:
        if _EVENT_NAME.fullmatch(event_name) is None:
            raise ValueError("event_name must be lower_snake_case and at most 64 characters")
        exception_tuple: tuple[type[BaseException], BaseException, Any] | None = None
        if exc_info is not None:
            exception_tuple = (type(exc_info), exc_info, exc_info.__traceback__)
        self._logger.log(
            level,
            event_name,
            extra={"event_name": event_name, "event_fields": fields},
            exc_info=exception_tuple,
        )

    def info(self, event_name: str, **fields: object) -> None:
        """Emit an informational event."""
        self._emit(logging.INFO, event_name, fields=fields)

    def warning(self, event_name: str, **fields: object) -> None:
        """Emit a warning event."""
        self._emit(logging.WARNING, event_name, fields=fields)

    def error(
        self,
        event_name: str,
        *,
        exc_info: BaseException | None = None,
        **fields: object,
    ) -> None:
        """Emit an error event."""
        self._emit(logging.ERROR, event_name, fields=fields, exc_info=exc_info)

    def critical(
        self,
        event_name: str,
        *,
        exc_info: BaseException | None = None,
        **fields: object,
    ) -> None:
        """Emit a critical event."""
        self._emit(logging.CRITICAL, event_name, fields=fields, exc_info=exc_info)


def configure_structured_logging(
    config: LoggingConfig,
    *,
    service: str,
    environment: Environment,
    config_hash: str,
    artifact_digest: str,
    stream: IO[str] | None = None,
) -> StructuredLogger:
    """Create an isolated logger with non-optional JSON redaction.

    Records go to stderr so that stdout carries only a command's result. An
    operator piping `trading-cli status` into a JSON tool must not have a log
    line appear in the middle of the answer. Under `systemd` (§16.3) both
    streams reach the journal, so the daemon case loses nothing.
    """
    logger = logging.getLogger(f"trading_system.{service}")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(config.level.value)
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(
        RedactingJsonFormatter(
            service=service,
            environment=environment,
            config_hash=config_hash,
            artifact_digest=artifact_digest,
        )
    )
    logger.addHandler(handler)
    return StructuredLogger(logger)
