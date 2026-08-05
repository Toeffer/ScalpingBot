"""Closed order lifecycle transition table. Architecture reference: §7.2."""

from trading_system.domain.trading import OrderState
from trading_system.exceptions import OrderStateError

_ALLOWED = {
    OrderState.SUBMITTING: {
        OrderState.ACKNOWLEDGED,
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.REJECTED,
        OrderState.UNKNOWN,
    },
    OrderState.ACKNOWLEDGED: {
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.CANCEL_PENDING,
        OrderState.CANCELLED,
        OrderState.REJECTED,
        OrderState.UNKNOWN,
    },
    OrderState.PARTIALLY_FILLED: {
        OrderState.FILLED,
        OrderState.CANCEL_PENDING,
        OrderState.CANCELLED,
        OrderState.UNKNOWN,
    },
    OrderState.CANCEL_PENDING: {
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.UNKNOWN,
    },
    OrderState.UNKNOWN: {
        OrderState.ACKNOWLEDGED,
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.REJECTED,
        OrderState.EXPIRED,
    },
}


def transition(current: OrderState, target: OrderState) -> OrderState:
    if current is target:
        return current
    if target not in _ALLOWED.get(current, set()):
        raise OrderStateError(f"invalid order transition: {current} -> {target}")
    return target
