"""Environment and live-start authorization tests."""

import io
from decimal import getcontext
from pathlib import Path

import pytest

from conftest import DEFAULTS_PATH, write_environment_config
from trading_system.app import TradingApplication
from trading_system.domain.system import SystemState
from trading_system.exceptions import (
    DecimalContextError,
    EnvironmentUnavailableError,
    KillSwitchLatchedError,
)
from trading_system.risk.kill_switch import FileKillSwitchStore, KillSwitchScope


def test_simulation_can_reach_only_simulation_ready_state(tmp_path: Path) -> None:
    environment_path = write_environment_config(tmp_path, "simulation")
    application = TradingApplication.bootstrap(
        DEFAULTS_PATH,
        environment_path,
        environ={"TRADING_ENV": "simulation"},
        log_stream=io.StringIO(),
    )

    assert application.start() is SystemState.READY_SIMULATION
    assert application.stop() is SystemState.STOPPED


def test_live_cannot_start_even_when_config_flag_is_true(tmp_path: Path) -> None:
    environment_path = write_environment_config(tmp_path, "live", live_enabled=True)
    application = TradingApplication.bootstrap(
        DEFAULTS_PATH,
        environment_path,
        environ={"TRADING_ENV": "live"},
        log_stream=io.StringIO(),
    )

    with pytest.raises(EnvironmentUnavailableError, match="phase_0_live_disabled"):
        application.start()
    assert application.state is SystemState.HALTED


def test_paper_cannot_start_without_broker_phase(tmp_path: Path) -> None:
    environment_path = write_environment_config(tmp_path, "paper")
    application = TradingApplication.bootstrap(
        DEFAULTS_PATH,
        environment_path,
        environ={"TRADING_ENV": "paper"},
        log_stream=io.StringIO(),
    )

    with pytest.raises(EnvironmentUnavailableError, match="no broker connectivity"):
        application.start()
    assert application.state is SystemState.HALTED


def test_durable_global_latch_blocks_startup_after_restart(tmp_path: Path) -> None:
    environment_path = write_environment_config(tmp_path, "simulation")
    state_file = tmp_path / "simulation" / "kill-switch.json"
    store = FileKillSwitchStore(state_file)
    store.initialize()
    store.latch(
        KillSwitchScope.GLOBAL,
        reason="operator test",
        actor="operator:test",
    )
    application = TradingApplication.bootstrap(
        DEFAULTS_PATH,
        environment_path,
        environ={"TRADING_ENV": "simulation"},
        log_stream=io.StringIO(),
    )

    with pytest.raises(KillSwitchLatchedError):
        application.start()
    assert application.state is SystemState.HALTED


def test_decimal_context_is_reasserted_and_failure_halts_startup(tmp_path: Path) -> None:
    environment_path = write_environment_config(tmp_path, "simulation")
    application = TradingApplication.bootstrap(
        DEFAULTS_PATH,
        environment_path,
        environ={"TRADING_ENV": "simulation"},
        log_stream=io.StringIO(),
    )
    getcontext().prec = 9

    with pytest.raises(DecimalContextError):
        application.start()
    assert application.state is SystemState.HALTED
