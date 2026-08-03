"""Narrow Phase-0 command-line entry point."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from trading_system.app import TradingApplication
from trading_system.config import Environment, selected_environment
from trading_system.exceptions import TradingSystemError
from trading_system.operations.redaction import redact
from trading_system.risk.kill_switch import KillSwitchDocument, KillSwitchScope

DEFAULT_HISTORY_LIMIT = 20


def _common_arguments() -> argparse.ArgumentParser:
    """Parent parser carrying the arguments shared by every subcommand."""
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--defaults",
        type=Path,
        default=Path("config/defaults.yaml"),
        help="path to version-controlled defaults",
    )
    parent.add_argument(
        "--environment-config",
        type=Path,
        help="path to the selected environment configuration",
    )
    return parent


def _positive_int(value: str) -> int:
    """Reject a non-positive limit rather than silently showing nothing."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _parser() -> argparse.ArgumentParser:
    common = _common_arguments()
    parser = argparse.ArgumentParser(description="Phase-0 trading-system safety bootstrap")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "start",
        parents=[common],
        help="bootstrap configuration and enter the safe startup state",
    )
    status_parser = subparsers.add_parser(
        "status",
        parents=[common],
        help="report environment and kill-switch status without starting",
    )
    status_parser.add_argument(
        "--history",
        action="store_true",
        help="also report the append-only kill-switch audit history",
    )
    status_parser.add_argument(
        "--history-limit",
        type=_positive_int,
        default=DEFAULT_HISTORY_LIMIT,
        help=f"most recent history entries to report (default {DEFAULT_HISTORY_LIMIT})",
    )
    halt_parser = subparsers.add_parser(
        "halt",
        parents=[common],
        help="durably latch a kill switch",
    )
    halt_parser.add_argument(
        "--scope",
        required=True,
        choices=[scope.value for scope in KillSwitchScope],
        help="kill-switch scope to latch",
    )
    halt_parser.add_argument(
        "--reason",
        required=True,
        help="operator-stated reason for the halt",
    )
    halt_parser.add_argument(
        "--actor",
        required=True,
        help="operator identity performing the halt",
    )
    halt_parser.add_argument(
        "--target-id",
        default=None,
        help="scoped target for strategy or instrument halts",
    )
    return parser


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _environment_and_path(arguments: argparse.Namespace) -> tuple[Environment, Path]:
    environment = selected_environment(os.environ)
    environment_path = arguments.environment_config
    if environment_path is None:
        environment_path = Path(f"config/{environment.value}.example.yaml")
    return environment, environment_path


def _run_start(arguments: argparse.Namespace) -> int:
    """Bootstrap and start; unchanged behavior, output shape, and exit codes."""
    environment, environment_path = _environment_and_path(arguments)
    application = TradingApplication.bootstrap(
        arguments.defaults,
        environment_path,
        environ=os.environ,
    )
    state = application.start()
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


def _history_payload(document: KillSwitchDocument, limit: int) -> dict[str, object]:
    """Summarize the append-only audit trail, newest last.

    Entries stay in the order they were appended so the output reads as a
    timeline. `total` and `truncated` are reported alongside, because an
    operator must be able to tell a complete history from a slice of one.
    """
    entries = document.history[-limit:]
    return {
        "total": len(document.history),
        "shown": len(entries),
        "truncated": len(entries) < len(document.history),
        "entries": [
            {
                "action_id": str(entry.action_id),
                "action": entry.action.value,
                "record_id": str(entry.record_id),
                "scope": entry.scope.value,
                "target_id": entry.target_id,
                "reason": entry.reason,
                "actor": entry.actor,
                "occurred_at": _iso_utc(entry.occurred_at),
            }
            for entry in entries
        ],
    }


def _run_status(arguments: argparse.Namespace) -> int:
    """Report kill-switch and environment status without starting the application."""
    environment, environment_path = _environment_and_path(arguments)
    application = TradingApplication.bootstrap(
        arguments.defaults,
        environment_path,
        environ=os.environ,
    )
    document = application.kill_switch.snapshot()
    global_latched = any(record.scope is KillSwitchScope.GLOBAL for record in document.active)
    kill_switch: dict[str, object] = {
        "global_latched": global_latched,
        "revision": document.revision,
        "active": [
            {
                "record_id": str(record.record_id),
                "scope": record.scope.value,
                "target_id": record.target_id,
                "reason": record.reason,
                "latched_at": _iso_utc(record.latched_at),
            }
            for record in document.active
        ],
    }
    if arguments.history:
        kill_switch["history"] = _history_payload(document, arguments.history_limit)
    payload: dict[str, object] = {
        "status": "ok",
        "environment": environment.value,
        "broker_connectivity": False,
        "kill_switch": kill_switch,
    }
    print(json.dumps(redact(payload), ensure_ascii=True, sort_keys=True))
    return 0


def _run_halt(arguments: argparse.Namespace) -> int:
    """Durably latch a kill-switch scope; idempotent for a scope already latched."""
    _, environment_path = _environment_and_path(arguments)
    application = TradingApplication.bootstrap(
        arguments.defaults,
        environment_path,
        environ=os.environ,
    )
    record = application.kill_switch.latch(
        KillSwitchScope(arguments.scope),
        reason=arguments.reason,
        actor=arguments.actor,
        target_id=arguments.target_id,
    )
    payload: dict[str, object] = {
        "status": "latched",
        "record_id": str(record.record_id),
        "scope": record.scope.value,
        "target_id": record.target_id,
        "latched_at": _iso_utc(record.latched_at),
        "reason": record.reason,
    }
    print(json.dumps(redact(payload), ensure_ascii=True, sort_keys=True))
    return 0


def _report_failure(status: str, exc: Exception) -> int:
    """Emit a redacted failure record.

    A rejection message can quote operator-supplied text such as --reason, so it
    passes through the same redaction boundary as every other emitted payload.
    """
    payload: dict[str, object] = {
        "status": status,
        "error_type": type(exc).__name__,
        "message": str(exc),
    }
    print(json.dumps(redact(payload), ensure_ascii=True, sort_keys=True))
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch the requested operator subcommand with fail-closed error handling."""
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "status":
            return _run_status(arguments)
        if arguments.command == "halt":
            return _run_halt(arguments)
        return _run_start(arguments)
    except TradingSystemError as exc:
        return _report_failure("halted", exc)
    except ValidationError as exc:
        return _report_failure("rejected", exc)


if __name__ == "__main__":
    raise SystemExit(main())
