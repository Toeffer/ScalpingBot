"""Price construction. Architecture reference: §11.4."""

from decimal import Decimal, InvalidOperation, localcontext

from trading_system.domain.trading import Side


def round_to_tick(price: Decimal, tick: Decimal, *, side: Side, aggressive: bool) -> Decimal:
    if tick <= 0:
        raise ValueError("tick must be positive")
    with localcontext() as ctx:
        ctx.prec = 60
        ctx.traps[InvalidOperation] = True
        units, remainder = divmod(price, tick)
        if remainder < 0:
            units -= 1
            remainder += tick
        if remainder == 0:
            return (units * tick).quantize(tick)
        return ((units + 1 if ((side is Side.BUY) == aggressive) else units) * tick).quantize(tick)
