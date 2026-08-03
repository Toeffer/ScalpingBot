"""Pinned-decimal context tests."""

from decimal import DivisionByZero, FloatOperation, InvalidOperation, Overflow, getcontext

import pytest

from trading_system.decimal_context import (
    DECIMAL_PRECISION,
    assert_decimal_context,
    configure_decimal_context,
    financial_context,
)
from trading_system.exceptions import DecimalContextError


def test_configure_decimal_context_pins_required_settings() -> None:
    configure_decimal_context()

    context = getcontext()
    assert context.prec == DECIMAL_PRECISION
    assert context.traps[InvalidOperation]
    assert context.traps[DivisionByZero]
    assert context.traps[Overflow]
    assert context.traps[FloatOperation]
    assert_decimal_context()


def test_assert_decimal_context_detects_ambient_mutation() -> None:
    getcontext().prec = DECIMAL_PRECISION - 1

    with pytest.raises(DecimalContextError, match="precision"):
        assert_decimal_context()


def test_financial_context_is_local() -> None:
    with financial_context() as context:
        assert context.prec == DECIMAL_PRECISION
        context.prec = 12

    assert getcontext().prec == DECIMAL_PRECISION
