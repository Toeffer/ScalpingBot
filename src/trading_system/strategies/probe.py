"""A deterministic paper lifecycle probe, not an investment strategy."""

from datetime import datetime, time, timedelta
from decimal import Decimal

from trading_system.config import PaperProbeConfig
from trading_system.domain.trading import Instrument, Quote, TargetPositionIntent


class PaperLifecycleProbe:
    strategy_id = "paper_lifecycle_probe"

    def __init__(self, config: PaperProbeConfig, instrument: Instrument) -> None:
        self._config = config
        self._instrument = instrument
        self._entered_on: str | None = None

    def on_quote(
        self,
        quote: Quote,
        *,
        now_utc: datetime,
        virtual_position: Decimal,
    ) -> tuple[TargetPositionIntent, ...]:
        if not self._config.enabled or not quote.is_two_sided():
            return ()
        today = now_utc.date().isoformat()
        entry_time = time.fromisoformat(self._config.entry_time)
        exit_time = time.fromisoformat(self._config.exit_time)
        current_time = now_utc.time().replace(tzinfo=None)
        if current_time >= exit_time and virtual_position != 0:
            return (self._intent(Decimal("0"), quote, now_utc),)
        if (
            entry_time <= current_time < exit_time
            and self._entered_on != today
            and virtual_position == 0
        ):
            self._entered_on = today
            return (self._intent(self._config.quantity, quote, now_utc),)
        return ()

    def _intent(
        self,
        target: Decimal,
        quote: Quote,
        now_utc: datetime,
    ) -> TargetPositionIntent:
        price = quote.bid if target != 0 else quote.ask
        if price is None:
            raise ValueError("two-sided quote required")
        return TargetPositionIntent(
            strategy_id=self.strategy_id,
            instrument=self._instrument,
            target_quantity=target,
            decision_price=price,
            created_at_utc=now_utc,
            expires_at_utc=now_utc + timedelta(seconds=30),
        )
