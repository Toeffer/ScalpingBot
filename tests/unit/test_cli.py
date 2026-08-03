"""Narrow Phase-0 CLI tests."""

import json
from pathlib import Path

import pytest

from conftest import DEFAULTS_PATH, write_environment_config
from trading_system.operations.cli import main

HALTED_EXIT_CODE = 2


def _last_json_line(output: str) -> dict[str, object]:
    return json.loads(output.strip().splitlines()[-1])


def test_cli_reports_simulation_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    environment_path = write_environment_config(tmp_path, "simulation")
    monkeypatch.setenv("TRADING_ENV", "simulation")

    result = main(
        [
            "--defaults",
            str(DEFAULTS_PATH),
            "--environment-config",
            str(environment_path),
        ]
    )

    payload = _last_json_line(capsys.readouterr().out)
    assert result == 0
    assert payload == {
        "broker_connectivity": False,
        "environment": "simulation",
        "state": "ready_simulation",
        "status": "ready",
    }


def test_cli_reports_denied_live_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    environment_path = write_environment_config(tmp_path, "live", live_enabled=True)
    monkeypatch.setenv("TRADING_ENV", "live")

    result = main(
        [
            "--defaults",
            str(DEFAULTS_PATH),
            "--environment-config",
            str(environment_path),
        ]
    )

    payload = _last_json_line(capsys.readouterr().out)
    assert result == HALTED_EXIT_CODE
    assert payload["status"] == "halted"
    assert payload["error_type"] == "EnvironmentUnavailableError"


def test_cli_rejects_invalid_environment(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TRADING_ENV", "production")

    result = main([])

    payload = _last_json_line(capsys.readouterr().out)
    assert result == HALTED_EXIT_CODE
    assert payload["error_type"] == "ConfigurationError"
