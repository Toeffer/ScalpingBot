"""Shared safety fixtures."""

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from trading_system.decimal_context import configure_decimal_context

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULTS_PATH = REPOSITORY_ROOT / "config" / "defaults.yaml"


@pytest.fixture(autouse=True)
def pinned_decimal_context() -> Iterator[None]:
    """Every test begins and ends with the process context pinned."""
    configure_decimal_context()
    yield
    configure_decimal_context()


def write_environment_config(
    directory: Path,
    environment: str,
    *,
    live_enabled: bool = False,
) -> Path:
    """Create an isolated environment override with disposable emergency state."""
    state_directory = directory / environment
    document = {
        "environment": environment,
        "runtime": {
            "state_directory": str(state_directory),
            "live_enabled": live_enabled,
        },
        "kill_switch": {"state_file": str(state_directory / "kill-switch.json")},
    }
    path = directory / f"{environment}.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=True), encoding="utf-8")
    return path
