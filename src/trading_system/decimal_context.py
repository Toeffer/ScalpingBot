"""Pinned decimal arithmetic for all financial values.

Architecture references: AGENT.md rules 14 and 17; architecture §12.4.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    DivisionByZero,
    FloatOperation,
    InvalidOperation,
    Overflow,
    getcontext,
    localcontext,
)

from trading_system.exceptions import DecimalContextError

DECIMAL_PRECISION = 34
DECIMAL_ROUNDING = ROUND_HALF_EVEN
_REQUIRED_TRAPS = (InvalidOperation, DivisionByZero, Overflow, FloatOperation)


def configure_decimal_context() -> None:
    """Pin the current thread's decimal context at process startup (§12.4)."""
    context = getcontext()
    context.prec = DECIMAL_PRECISION
    context.rounding = DECIMAL_ROUNDING
    for signal in _REQUIRED_TRAPS:
        context.traps[signal] = True
    context.clear_flags()


def assert_decimal_context() -> None:
    """Fail closed if financial arithmetic would use an unexpected context."""
    context = getcontext()
    failures: list[str] = []
    if context.prec != DECIMAL_PRECISION:
        failures.append(f"precision={context.prec}")
    if context.rounding != DECIMAL_ROUNDING:
        failures.append(f"rounding={context.rounding}")
    failures.extend(signal.__name__ for signal in _REQUIRED_TRAPS if not context.traps[signal])
    if failures:
        detail = ", ".join(failures)
        raise DecimalContextError(f"decimal context is not pinned: {detail}")


def new_financial_context() -> Context:
    """Return an isolated pinned context; never expose the ambient context."""
    assert_decimal_context()
    context = getcontext().copy()
    context.clear_flags()
    return context


@contextmanager
def financial_context() -> Iterator[Context]:
    """Provide a local pinned context for a bounded financial calculation."""
    with localcontext(new_financial_context()) as context:
        yield context
