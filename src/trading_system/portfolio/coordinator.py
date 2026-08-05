"""Single-strategy target aggregation. Architecture reference: §9.1."""

from collections.abc import Sequence
from decimal import Decimal

from trading_system.domain.trading import WorkingOrder


def required_change(
    *, account_target: Decimal, broker_position: Decimal, working_orders: Sequence[WorkingOrder]
) -> Decimal:
    working = sum(
        (
            order.remaining_quantity * order.plan.side.sign
            for order in working_orders
            if not order.state.is_terminal
        ),
        start=Decimal("0"),
    )
    return account_target - (broker_position + working)
