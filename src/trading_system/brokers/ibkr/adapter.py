"""Dependency-inverted IBKR observer/execution adapter.

The production transport is supplied only after the official API matching the
installed Gateway has been reviewed and locked. Importing this module never
opens a socket.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from trading_system.config import BrokerConfig
from trading_system.domain.trading import Instrument, Quote
from trading_system.exceptions import PaperReadinessError


class IbkrTransport(Protocol):
    def connect(self, host: str, port: int, client_id: int) -> None: ...
    def disconnect(self) -> None: ...
    def account_id(self) -> str: ...
    def base_currency(self) -> str: ...
    def read_only(self) -> bool: ...
    def current_time(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class ObserverSnapshot:
    account_hash: str
    base_currency: str
    observed_at_utc: datetime


class IbkrAdapter:
    def __init__(self, config: BrokerConfig, transport: IbkrTransport) -> None:
        self._config = config
        self._transport = transport

    def start_observer(self) -> ObserverSnapshot:
        self._transport.connect(
            self._config.host,
            self._config.port,
            self._config.observer_client_id,
        )
        if not self._transport.read_only() and self._config.read_only_required:
            raise PaperReadinessError("gateway_read_only_required")
        account_hash = "sha256:" + hashlib.sha256(self._transport.account_id().encode()).hexdigest()
        if (
            self._config.expected_account_hash is not None
            and account_hash != self._config.expected_account_hash
        ):
            raise PaperReadinessError("unexpected_broker_account")
        if (
            self._config.expected_base_currency is not None
            and self._transport.base_currency() != self._config.expected_base_currency
        ):
            raise PaperReadinessError("broker_base_currency_mismatch")
        return ObserverSnapshot(
            account_hash=account_hash,
            base_currency=self._transport.base_currency(),
            observed_at_utc=datetime.now(UTC),
        )

    @staticmethod
    def normalize_quote(
        instrument: Instrument,
        bid: Decimal | None,
        ask: Decimal | None,
        sequence: int,
    ) -> Quote:
        return Quote(instrument, bid, ask, datetime.now(UTC), sequence)
