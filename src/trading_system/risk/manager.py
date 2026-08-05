"""Fail-closed pre-trade controls for the paper v1 scope."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_system.config import RiskConfig
from trading_system.domain.trading import OrderPlan, Quote, Side


@dataclass(frozen=True, slots=True)
class RiskDecision:
    approved: bool
    reasons: tuple[str, ...]


class RiskManager:
    def __init__(self, config: RiskConfig) -> None:
        self._config = config

    def evaluate(
        self,
        plan: OrderPlan,
        quote: Quote | None,
        *,
        now_utc: datetime,
        open_orders: int,
        broker_position: Decimal,
        kill_switch_latched: bool,
        reconciliation_complete: bool,
    ) -> RiskDecision:
        reasons: list[str] = []
        if kill_switch_latched:
            reasons.append("kill_switch_latched")
        if not reconciliation_complete:
            reasons.append("reconciliation_incomplete")
        if plan.instrument.currency != self._config.base_currency:
            reasons.append("non_base_currency")
        if plan.quantity <= 0 or plan.quantity > self._config.per_order.max_quantity:
            reasons.append("quantity_limit")
        if open_orders >= self._config.account.max_open_orders:
            reasons.append("open_order_limit")
        if now_utc >= plan.expires_at_utc:
            reasons.append("expired")
        if quote is None or not quote.is_two_sided():
            reasons.append("quote_invalid")
        elif (now_utc - quote.received_at_utc).total_seconds() * 1000 > (
            self._config.market_data.max_quote_age_ms
        ):
            reasons.append("quote_stale")
        if plan.side is Side.SELL and plan.quantity > broker_position and not plan.risk_reducing:
            reasons.append("short_selling_not_supported")
        return RiskDecision(approved=not reasons, reasons=tuple(reasons))
