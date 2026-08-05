"""Coverage of fail-closed paper controls and persistence seams."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from conftest import DEFAULTS_PATH
from trading_system.brokers.ibkr.adapter import IbkrAdapter
from trading_system.config import BrokerConfig, load_config
from trading_system.domain.trading import (
    Instrument,
    OrderPlan,
    OrderState,
    Quote,
    Side,
    TimeInForce,
)
from trading_system.exceptions import OrderStateError, ReconciliationError
from trading_system.oms.pricing import round_to_tick
from trading_system.oms.service import OrderIdAllocator, PaperOms
from trading_system.oms.state_machine import transition
from trading_system.operations.health import HealthStatus
from trading_system.operations.metrics import RISK_REJECTIONS
from trading_system.persistence.journal import InMemoryEventJournal, JournalEvent
from trading_system.persistence.postgres import PostgresEventJournal
from trading_system.reconciliation import reconcile_positions, require_reconciled
from trading_system.risk.manager import RiskManager


class ObserverTransport:
    def __init__(
        self, *, account: str = "DU1234567", currency: str = "EUR", read_only: bool = True
    ) -> None:
        self.account = account
        self.currency = currency
        self._read_only = read_only
        self.connected = False

    def connect(self, host: str, port: int, client_id: int) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def account_id(self) -> str:
        return self.account

    def base_currency(self) -> str:
        return self.currency

    def read_only(self) -> bool:
        return self._read_only

    def current_time(self) -> datetime:
        return datetime.now(UTC)


class AsyncConnection:
    def __init__(self) -> None:
        self.parameters: dict[str, object] | None = None

    async def __aenter__(self) -> AsyncConnection:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, statement: object, parameters: dict[str, object]) -> None:
        self.parameters = parameters


class AsyncEngineFake:
    def __init__(self) -> None:
        self.connection = AsyncConnection()
        self.closed = False

    def begin(self) -> AsyncConnection:
        return self.connection

    async def dispose(self) -> None:
        self.closed = True


def _instrument() -> Instrument:
    return Instrument("paper-etf", 12345, "IBIS", "EUR")


def _plan(now: datetime, *, side: Side = Side.BUY) -> OrderPlan:
    return OrderPlan(
        plan_id=uuid4(),
        strategy_id="probe",
        instrument=_instrument(),
        side=side,
        quantity=Decimal("1"),
        limit_price=Decimal("100"),
        decision_price=Decimal("100"),
        expires_at_utc=now + timedelta(minutes=1),
        time_in_force=TimeInForce.DAY,
    )


def test_pricing_and_state_reject_invalid_inputs() -> None:
    assert round_to_tick(
        Decimal("10.01"), Decimal("0.01"), side=Side.BUY, aggressive=True
    ) == Decimal("10.01")
    assert round_to_tick(
        Decimal("-1.01"), Decimal("0.01"), side=Side.SELL, aggressive=True
    ) == Decimal("-1.01")
    with pytest.raises(ValueError, match="tick"):
        round_to_tick(Decimal("1"), Decimal("0"), side=Side.BUY, aggressive=True)
    with pytest.raises(OrderStateError):
        transition(OrderState.FILLED, OrderState.ACKNOWLEDGED)


def test_reconciliation_journal_and_oms_are_deterministic() -> None:
    report = reconcile_positions(
        broker_position=Decimal("1"),
        local_position=Decimal("1"),
        instrument_id="paper-etf",
    )
    require_reconciled(report)
    mismatch = reconcile_positions(
        broker_position=Decimal("1"),
        local_position=Decimal("0"),
        instrument_id="paper-etf",
    )
    with pytest.raises(ReconciliationError, match="unexplained_position"):
        require_reconciled(mismatch)
    journal = InMemoryEventJournal()
    allocator = OrderIdAllocator(10)
    allocator.observe(15)
    oms = PaperOms(journal, allocator)
    command_id = uuid4()
    prepared = oms.prepare(command_id, _plan(datetime.now(UTC)))
    assert prepared.command.broker_order_id == allocator.allocate() - 1
    assert oms.prepare(command_id, _plan(datetime.now(UTC))).duplicate
    assert journal.events()[0].event_type == "BrokerSubmissionPrepared"


def test_observer_checks_and_postgres_journal_use_injected_transport() -> None:

    account_hash = "sha256:" + hashlib.sha256(b"DU1234567").hexdigest()
    adapter = IbkrAdapter(
        BrokerConfig(expected_account_hash=account_hash, expected_base_currency="EUR"),
        ObserverTransport(),
    )
    assert adapter.start_observer().base_currency == "EUR"
    with pytest.raises(Exception, match="gateway_read_only_required"):
        IbkrAdapter(BrokerConfig(), ObserverTransport(read_only=False)).start_observer()
    with pytest.raises(Exception, match="unexpected_broker_account"):
        IbkrAdapter(
            BrokerConfig(expected_account_hash=account_hash), ObserverTransport(account="DU9")
        ).start_observer()
    postgres = PostgresEventJournal("postgresql+asyncpg://unused")
    engine = AsyncEngineFake()
    postgres._engine = engine  # type: ignore[assignment]
    event = JournalEvent("Test", "aggregate", {"value": "1"}, uuid4())
    asyncio.run(postgres.append_async(event))
    asyncio.run(postgres.close())
    assert engine.connection.parameters is not None
    assert engine.closed
    with pytest.raises(RuntimeError):
        postgres.append(event)
    with pytest.raises(RuntimeError):
        postgres.events()


def test_risk_rejects_stale_quote_and_short_entry() -> None:
    risk = RiskManager(
        load_config(
            DEFAULTS_PATH,
            DEFAULTS_PATH.parent / "simulation.example.yaml",
            environ={"TRADING_ENV": "simulation"},
        ).risk
    )
    now = datetime.now(UTC)
    stale = Quote(_instrument(), Decimal("99"), Decimal("100"), now - timedelta(seconds=5), 1)
    decision = risk.evaluate(
        _plan(now, side=Side.SELL),
        stale,
        now_utc=now,
        open_orders=0,
        broker_position=Decimal("0"),
        kill_switch_latched=True,
        reconciliation_complete=False,
    )
    assert not decision.approved
    assert {
        "kill_switch_latched",
        "reconciliation_incomplete",
        "quote_stale",
        "short_selling_not_supported",
    } <= set(decision.reasons)
    assert HealthStatus(True, True, False).trading_ready is False
    RISK_REJECTIONS.labels(reason="test").inc()
