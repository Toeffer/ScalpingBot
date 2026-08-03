"""Narrow Phase-0 command-line entry point."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from trading_system.app import TradingApplication
from trading_system.config import selected_environment
from trading_system.exceptions import TradingSystemError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase-0 trading-system safety bootstrap")
    parser.add_argument(
        "--defaults",
        type=Path,
        default=Path("config/defaults.yaml"),
        help="path to version-controlled defaults",
    )
    parser.add_argument(
        "--environment-config",
        type=Path,
        help="path to the selected environment configuration",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Validate configuration and report the resulting safe startup state."""
    arguments = _parser().parse_args(argv)
    try:
        environment = selected_environment(os.environ)
        environment_path = arguments.environment_config
        if environment_path is None:
            environment_path = Path(f"config/{environment.value}.example.yaml")
        application = TradingApplication.bootstrap(
            arguments.defaults,
            environment_path,
            environ=os.environ,
        )
        state = application.start()
    except TradingSystemError as exc:
        print(
            json.dumps(
                {
                    "status": "halted",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "status": "ready",
                "state": state.value,
                "environment": environment.value,
                "broker_connectivity": False,
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
