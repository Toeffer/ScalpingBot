"""Strict configuration and environment binding tests."""

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from conftest import DEFAULTS_PATH, write_environment_config
from trading_system.config import Environment, load_config, selected_environment
from trading_system.exceptions import ConfigurationError, EnvironmentMismatchError

SHA256_URI_LENGTH = 71


def test_defaults_select_simulation_when_environment_variable_is_absent(tmp_path: Path) -> None:
    environment_path = write_environment_config(tmp_path, "simulation")

    config = load_config(DEFAULTS_PATH, environment_path, environ={})

    assert selected_environment({}) is Environment.SIMULATION
    assert config.environment is Environment.SIMULATION
    assert isinstance(config.risk.account.max_daily_loss, Decimal)
    assert config.risk.base_currency == "EUR"


def test_unknown_configuration_key_fails_startup(tmp_path: Path) -> None:
    environment_path = write_environment_config(tmp_path, "simulation")
    document = yaml.safe_load(environment_path.read_text(encoding="utf-8"))
    document["risk_limit_typo"] = "1000.00"
    environment_path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ConfigurationError, match=r"risk_limit_typo.*Extra inputs"):
        load_config(DEFAULTS_PATH, environment_path, environ={"TRADING_ENV": "simulation"})


def test_unknown_nested_configuration_key_fails_startup(tmp_path: Path) -> None:
    environment_path = write_environment_config(tmp_path, "simulation")
    document = yaml.safe_load(environment_path.read_text(encoding="utf-8"))
    document["runtime"]["state_directry"] = str(tmp_path)
    environment_path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ConfigurationError, match=r"runtime\.state_directry"):
        load_config(DEFAULTS_PATH, environment_path, environ={"TRADING_ENV": "simulation"})


def test_duplicate_yaml_key_fails_startup(tmp_path: Path) -> None:
    environment_path = tmp_path / "simulation.yaml"
    environment_path.write_text(
        "environment: simulation\nenvironment: live\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="cannot read configuration"):
        load_config(DEFAULTS_PATH, environment_path, environ={"TRADING_ENV": "simulation"})


def test_environment_mismatch_fails_startup(tmp_path: Path) -> None:
    environment_path = write_environment_config(tmp_path, "paper")

    with pytest.raises(EnvironmentMismatchError, match="does not match"):
        load_config(DEFAULTS_PATH, environment_path, environ={"TRADING_ENV": "simulation"})


def test_invalid_environment_selector_fails_closed() -> None:
    with pytest.raises(ConfigurationError, match="TRADING_ENV must be one of"):
        selected_environment({"TRADING_ENV": "production"})


def test_unquoted_financial_value_is_rejected(tmp_path: Path) -> None:
    defaults = yaml.safe_load(DEFAULTS_PATH.read_text(encoding="utf-8"))
    defaults["risk"]["account"]["max_daily_loss"] = 250.0
    defaults_path = tmp_path / "defaults.yaml"
    defaults_path.write_text(yaml.safe_dump(defaults), encoding="utf-8")
    environment_path = write_environment_config(tmp_path, "simulation")

    with pytest.raises(ConfigurationError, match="quoted decimal strings"):
        load_config(defaults_path, environment_path, environ={"TRADING_ENV": "simulation"})


def test_configuration_hash_is_canonical(tmp_path: Path) -> None:
    environment_path = write_environment_config(tmp_path, "simulation")
    first = load_config(DEFAULTS_PATH, environment_path, environ={})
    second = load_config(DEFAULTS_PATH, environment_path, environ={})

    assert first.canonical_hash() == second.canonical_hash()
    assert first.canonical_hash().startswith("sha256:")
    assert len(first.canonical_hash()) == SHA256_URI_LENGTH
