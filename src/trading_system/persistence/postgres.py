"""Async PostgreSQL journal implementation; migrations own schema changes."""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from trading_system.persistence.journal import EventJournal, JournalEvent


class PostgresEventJournal(EventJournal):
    """Append-only journal backed by the `event_journal` Alembic table."""

    def __init__(self, database_url: str) -> None:
        self._engine: AsyncEngine = create_async_engine(database_url, pool_pre_ping=True)

    async def append_async(self, event: JournalEvent) -> None:
        statement = text(
            "INSERT INTO event_journal "
            "(event_id, event_type, aggregate_id, correlation_id, schema_version, "
            "created_at_utc, payload) "
            "VALUES (:event_id, :event_type, :aggregate_id, :correlation_id, "
            ":schema_version, :created_at_utc, CAST(:payload AS jsonb))"
        )
        async with self._engine.begin() as connection:
            await connection.execute(
                statement,
                {
                    "event_id": str(event.event_id),
                    "event_type": event.event_type,
                    "aggregate_id": event.aggregate_id,
                    "correlation_id": str(event.correlation_id),
                    "schema_version": event.schema_version,
                    "created_at_utc": event.created_at_utc,
                    "payload": json.dumps(event.payload, sort_keys=True),
                },
            )

    def append(self, event: JournalEvent) -> None:
        raise RuntimeError("use append_async for PostgreSQL persistence")

    def events(self) -> tuple[JournalEvent, ...]:
        raise RuntimeError("use replay queries for PostgreSQL persistence")

    async def close(self) -> None:
        await self._engine.dispose()
