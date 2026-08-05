"""Deterministic paper-runtime tests; these never open a real broker socket."""

import hashlib
import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import yaml

from conftest import DEFAULTS_PATH
from trading_system.app import PaperRuntime, TradingApplication
from trading_system.brokers.ibkr.adapter import IbkrAdapter
from trading_system.config import BrokerConfig, PaperProbeConfig
from trading_system.domain.system import SystemState
from trading_system.domain.trading import (
    Instrument,
    OrderPlan,
    OrderState,
    Quote,
    Side,
    TimeInForce,
    WorkingOrder,
)
from trading_system.oms.pricing import round_to_tick
from trading_system.oms.state_machine import transition
from trading_system.portfolio.coordinator import required_change
from trading_system.reconciliation import ReconciliationReport
from trading_system.strategies.probe import PaperLifecycleProbe

PAPER_PORT = 4002
OBSERVER_CLIENT_ID = 2


class FakeTransport:
    def __init__(self) -> None:
        self.connected = False

    def connect(self, host: str, port: int, client_id: int) -> None:
        self.connected = (
            host == "127.0.0.1" and port == PAPER_PORT and client_id == OBSERVER_CLIENT_ID
        )

    def disconnect(self) -> None:
        self.connected = False

    def account_id(self) -> str:
        return "DU1234567"

    def base_currency(self) -> str:
        return "EUR"

    def read_only(self) -> bool:
        return True

    def current_time(self) -> datetime:
        return datetime.now(UTC)


def _instrument() -> Instrument:
    return Instrument("paper-etf", 12345, "IBIS", "EUR")


def _plan(now: datetime, side: Side = Side.BUY) -> OrderPlan:
    return OrderPlan(
        uuid4(),
        "probe",
        _instrument(),
        side,
        Decimal("1"),
        Decimal("100.00"),
        Decimal("100.00"),
        now + timedelta(minutes=1),
        TimeInForce.DAY,
    )


def test_pricing_state_machine_and_working_order_reservation() -> None:
    now = datetime.now(UTC)
    assert round_to_tick(
        Decimal("10.011"), Decimal("0.01"), side=Side.BUY, aggressive=False
    ) == Decimal("10.01")
    assert transition(OrderState.SUBMITTING, OrderState.FILLED) is OrderState.FILLED
    order = WorkingOrder(_plan(now), OrderState.UNKNOWN)
    assert required_change(
        account_target=Decimal("1"),
        broker_position=Decimal("0"),
        working_orders=[order],
    ) == Decimal("0")


def test_probe_emits_one_entry_then_exit() -> None:
    probe = PaperLifecycleProbe(
        PaperProbeConfig(enabled=True, entry_time="10:00", exit_time="10:05"),
        _instrument(),
    )
    quote = Quote(
        _instrument(),
        Decimal("99.99"),
        Decimal("100.00"),
        datetime(2026, 1, 2, 10, 0, tzinfo=UTC),
        1,
    )
    entry = probe.on_quote(quote, now_utc=quote.received_at_utc, virtual_position=Decimal("0"))
    assert entry[0].target_quantity == Decimal("1")
    assert not probe.on_quote(quote, now_utc=quote.received_at_utc, virtual_position=Decimal("0"))
    exit_at = datetime(2026, 1, 2, 10, 5, tzinfo=UTC)
    exit_quote = Quote(_instrument(), Decimal("100"), Decimal("100.01"), exit_at, 2)
    exit_intent = probe.on_quote(exit_quote, now_utc=exit_at, virtual_position=Decimal("1"))
    assert exit_intent[0].target_quantity == Decimal("0")


def test_paper_start_requires_observer_and_clean_reconciliation(tmp_path: Path) -> None:
    account_hash = "sha256:" + hashlib.sha256(b"DU1234567").hexdigest()
    environment = {
        "environment": "paper",
        "runtime": {"state_directory": str(tmp_path / "state")},
        "kill_switch": {"state_file": str(tmp_path / "state" / "kill.json")},
        "broker": {"expected_account_hash": account_hash, "expected_base_currency": "EUR"},
        "paper_instrument": {
            "instrument_id": "paper-etf",
            "con_id": 12345,
            "exchange": "IBIS",
            "currency": "EUR",
        },
        "persistence": {"database_url_secret_ref": "paper-postgres"},
    }
    path = tmp_path / "paper.yaml"
    path.write_text(yaml.safe_dump(environment), encoding="utf-8")
    runtime = PaperRuntime(
        IbkrAdapter(
            BrokerConfig(expected_account_hash=account_hash, expected_base_currency="EUR"),
            FakeTransport(),
        ),
        ReconciliationReport(True, ()),
    )
    app = TradingApplication.bootstrap(
        DEFAULTS_PATH,
        path,
        environ={"TRADING_ENV": "paper"},
        log_stream=io.StringIO(),
        paper_runtime=runtime,
    )
    assert app.start() is SystemState.READY_PAPER
