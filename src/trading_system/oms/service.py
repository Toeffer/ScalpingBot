"""Idempotent paper OMS preparation; broker submission remains transport-owned."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from trading_system.domain.trading import OrderCommand, OrderPlan
from trading_system.exceptions import PaperReadinessError
from trading_system.persistence.journal import EventJournal, JournalEvent

MAX_ORDER_REF_LENGTH = 40


class OrderIdAllocator:
    """Monotonic client-scoped broker order IDs; never reuse an observed ID."""

    def __init__(self, next_valid_id: int) -> None:
        self._highest = next_valid_id - 1

    def observe(self, broker_order_id: int) -> None:
        self._highest = max(self._highest, broker_order_id)

    def allocate(self) -> int:
        self._highest += 1
        return self._highest


@dataclass(frozen=True, slots=True)
class PreparedCommand:
    command: OrderCommand
    duplicate: bool


class PaperOms:
    """Persist intent before submission; no retry or socket call occurs here."""

    def __init__(self, journal: EventJournal, allocator: OrderIdAllocator) -> None:
        self._journal = journal
        self._allocator = allocator
        self._commands: dict[UUID, OrderCommand] = {}

    def prepare(self, command_id: UUID, plan: OrderPlan) -> PreparedCommand:
        existing = self._commands.get(command_id)
        if existing is not None:
            return PreparedCommand(existing, duplicate=True)
        order_ref = self._order_ref(plan)
        payload = self._payload(plan, order_ref)
        command = OrderCommand(
            command_id=command_id,
            plan=plan,
            broker_order_id=self._allocator.allocate(),
            order_ref=order_ref,
            payload_hash=hashlib.sha256(payload.encode()).hexdigest(),
            created_at_utc=datetime.now(UTC),
        )
        self._commands[command_id] = command
        self._journal.append(
            JournalEvent(
                event_type="BrokerSubmissionPrepared",
                aggregate_id=str(plan.plan_id),
                correlation_id=command_id,
                payload={"order_ref": order_ref, "payload_hash": command.payload_hash},
            )
        )
        return PreparedCommand(command, duplicate=False)

    @staticmethod
    def _order_ref(plan: OrderPlan) -> str:
        value = f"SYS1|{plan.strategy_id[:8]}|{str(plan.plan_id)[:8]}|1"
        if len(value) > MAX_ORDER_REF_LENGTH:
            raise PaperReadinessError("order_ref_too_long")
        return value

    @staticmethod
    def _payload(plan: OrderPlan, order_ref: str) -> str:
        return json.dumps(
            {
                "con_id": plan.instrument.con_id,
                "exchange": plan.instrument.exchange,
                "limit_price": str(plan.limit_price),
                "order_ref": order_ref,
                "quantity": str(plan.quantity),
                "side": plan.side.value,
                "time_in_force": plan.time_in_force.value,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
