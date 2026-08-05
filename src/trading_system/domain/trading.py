"""Immutable paper-trading contracts; all financial fields use Decimal."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"

    @property
    def sign(self) -> Decimal:
        return Decimal("1") if self is Side.BUY else Decimal("-1")


class TimeInForce(StrEnum):
    DAY = "day"


class OrderState(StrEnum):
    SUBMITTING = "submitting"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_FILLED = "partially_filled"
    CANCEL_PENDING = "cancel_pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    UNKNOWN = "unknown"

    @property
    def is_terminal(self) -> bool:
        return self in {self.FILLED, self.CANCELLED, self.REJECTED, self.EXPIRED}


@dataclass(frozen=True, slots=True)
class Instrument:
    instrument_id: str
    con_id: int
    exchange: str
    currency: str


@dataclass(frozen=True, slots=True)
class Quote:
    instrument: Instrument
    bid: Decimal | None
    ask: Decimal | None
    received_at_utc: datetime
    sequence: int
    source: str = "ibkr"

    def is_two_sided(self) -> bool:
        return self.bid is not None and self.ask is not None and self.bid <= self.ask


@dataclass(frozen=True, slots=True)
class TargetPositionIntent:
    strategy_id: str
    instrument: Instrument
    target_quantity: Decimal
    decision_price: Decimal
    created_at_utc: datetime
    expires_at_utc: datetime
    signal_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class OrderPlan:
    plan_id: UUID
    strategy_id: str
    instrument: Instrument
    side: Side
    quantity: Decimal
    limit_price: Decimal
    decision_price: Decimal
    expires_at_utc: datetime
    time_in_force: TimeInForce = TimeInForce.DAY
    risk_reducing: bool = False


@dataclass(frozen=True, slots=True)
class WorkingOrder:
    plan: OrderPlan
    state: OrderState
    cumulative_filled_quantity: Decimal = Decimal("0")

    @property
    def remaining_quantity(self) -> Decimal:
        return self.plan.quantity - self.cumulative_filled_quantity


@dataclass(frozen=True, slots=True)
class OrderCommand:
    command_id: UUID
    plan: OrderPlan
    broker_order_id: int
    order_ref: str
    payload_hash: str
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(UTC))
