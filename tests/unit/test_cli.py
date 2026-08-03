"""Narrow Phase-0 CLI tests."""

import json
from pathlib import Path

import pytest

from conftest import DEFAULTS_PATH, write_environment_config
from trading_system.operations.cli import _report_failure, main
from trading_system.operations.redaction import REDACTED

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
            "start",
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
            "start",
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

    result = main(["start"])

    payload = _last_json_line(capsys.readouterr().out)
    assert result == HALTED_EXIT_CODE
    assert payload["error_type"] == "ConfigurationError"


def test_cli_status_reports_clean_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    environment_path = write_environment_config(tmp_path, "simulation")
    monkeypatch.setenv("TRADING_ENV", "simulation")

    result = main(
        [
            "status",
            "--defaults",
            str(DEFAULTS_PATH),
            "--environment-config",
            str(environment_path),
        ]
    )

    payload = _last_json_line(capsys.readouterr().out)
    assert result == 0
    assert payload == {
        "status": "ok",
        "environment": "simulation",
        "broker_connectivity": False,
        "kill_switch": {
            "global_latched": False,
            "revision": 0,
            "active": [],
        },
    }


def test_cli_status_reports_active_global_latch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    environment_path = write_environment_config(tmp_path, "simulation")
    monkeypatch.setenv("TRADING_ENV", "simulation")
    common_arguments = [
        "--defaults",
        str(DEFAULTS_PATH),
        "--environment-config",
        str(environment_path),
    ]

    halt_result = main(
        [
            "halt",
            "--scope",
            "global",
            "--reason",
            "operator drill",
            "--actor",
            "operator:test",
            *common_arguments,
        ]
    )
    assert halt_result == 0
    capsys.readouterr()

    status_result = main(["status", *common_arguments])

    payload = _last_json_line(capsys.readouterr().out)
    assert status_result == 0
    kill_switch = payload["kill_switch"]
    assert isinstance(kill_switch, dict)
    assert kill_switch["global_latched"] is True
    assert kill_switch["revision"] == 1
    active = kill_switch["active"]
    assert isinstance(active, list)
    assert len(active) == 1
    assert active[0]["scope"] == "global"
    assert active[0]["target_id"] is None
    assert active[0]["reason"] == "operator drill"
    assert "record_id" in active[0]
    assert "latched_at" in active[0]


def test_cli_status_succeeds_on_paper_config_where_start_is_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    environment_path = write_environment_config(tmp_path, "paper")
    monkeypatch.setenv("TRADING_ENV", "paper")
    common_arguments = [
        "--defaults",
        str(DEFAULTS_PATH),
        "--environment-config",
        str(environment_path),
    ]

    start_result = main(["start", *common_arguments])
    assert start_result == HALTED_EXIT_CODE
    capsys.readouterr()

    status_result = main(["status", *common_arguments])

    payload = _last_json_line(capsys.readouterr().out)
    assert status_result == 0
    assert payload["status"] == "ok"
    assert payload["environment"] == "paper"
    assert payload["broker_connectivity"] is False


def test_cli_halt_writes_durable_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    environment_path = write_environment_config(tmp_path, "simulation")
    monkeypatch.setenv("TRADING_ENV", "simulation")

    result = main(
        [
            "halt",
            "--scope",
            "global",
            "--reason",
            "operator drill",
            "--actor",
            "operator:test",
            "--defaults",
            str(DEFAULTS_PATH),
            "--environment-config",
            str(environment_path),
        ]
    )

    payload = _last_json_line(capsys.readouterr().out)
    assert result == 0
    assert payload["status"] == "latched"
    assert payload["scope"] == "global"
    assert payload["target_id"] is None
    assert payload["reason"] == "operator drill"
    assert "record_id" in payload
    assert "latched_at" in payload
    state_file = tmp_path / "simulation" / "kill-switch.json"
    assert state_file.is_file()


def test_cli_halt_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    environment_path = write_environment_config(tmp_path, "simulation")
    monkeypatch.setenv("TRADING_ENV", "simulation")
    arguments = [
        "halt",
        "--scope",
        "global",
        "--reason",
        "operator drill",
        "--actor",
        "operator:test",
        "--defaults",
        str(DEFAULTS_PATH),
        "--environment-config",
        str(environment_path),
    ]

    first_result = main(arguments)
    first_payload = _last_json_line(capsys.readouterr().out)
    second_result = main(arguments)
    second_payload = _last_json_line(capsys.readouterr().out)

    assert first_result == 0
    assert second_result == 0
    assert first_payload == second_payload


def test_cli_halt_rejects_strategy_scope_without_target_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    environment_path = write_environment_config(tmp_path, "simulation")
    monkeypatch.setenv("TRADING_ENV", "simulation")

    result = main(
        [
            "halt",
            "--scope",
            "strategy",
            "--reason",
            "operator drill",
            "--actor",
            "operator:test",
            "--defaults",
            str(DEFAULTS_PATH),
            "--environment-config",
            str(environment_path),
        ]
    )

    payload = _last_json_line(capsys.readouterr().out)
    assert result == HALTED_EXIT_CODE
    assert payload["status"] == "rejected"
    assert payload["error_type"] == "ValidationError"


def test_cli_halt_redacts_credential_shaped_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    environment_path = write_environment_config(tmp_path, "simulation")
    monkeypatch.setenv("TRADING_ENV", "simulation")

    result = main(
        [
            "halt",
            "--scope",
            "global",
            "--reason",
            "password=hunter2 rotate before drill",
            "--actor",
            "operator:test",
            "--defaults",
            str(DEFAULTS_PATH),
            "--environment-config",
            str(environment_path),
        ]
    )

    output = capsys.readouterr().out
    payload = _last_json_line(output)
    assert result == 0
    assert "hunter2" not in output
    assert payload["reason"] == f"password={REDACTED} rotate before drill"


def test_failure_records_are_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    """A rejection can quote operator input, so it crosses the redaction boundary too."""
    sample_token = "ghp_" + "A" * 24
    error = ValueError(f"halt rejected for reason token={sample_token}")

    result = _report_failure("rejected", error)

    output = capsys.readouterr().out
    assert result == HALTED_EXIT_CODE
    assert sample_token not in output
    assert _last_json_line(output)["message"] == f"halt rejected for reason token={REDACTED}"
