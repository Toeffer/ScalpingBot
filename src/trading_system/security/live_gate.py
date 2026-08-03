"""Phase-0 environment gate.

Live trading remains unreachable until every architecture §15.4 gate exists.
"""

from dataclasses import dataclass

from trading_system.config import Environment, TradingConfig
from trading_system.exceptions import EnvironmentUnavailableError


@dataclass(frozen=True, slots=True)
class LiveGateResult:
    """Auditable result of evaluating the intentionally incomplete live gate."""

    authorized: bool
    failed_gates: tuple[str, ...]


def evaluate_live_gate(config: TradingConfig) -> LiveGateResult:
    """Deny live mode unconditionally during Phase 0."""
    failures = [
        "phase_0_live_disabled",
        "broker_account_not_verified",
        "broker_base_currency_not_verified",
        "production_host_not_verified",
        "production_database_not_verified",
        "reconciliation_not_implemented",
        "operator_enable_token_not_implemented",
    ]
    if not config.runtime.live_enabled:
        failures.append("live_enabled_config_false")
    return LiveGateResult(authorized=False, failed_gates=tuple(failures))


def assert_environment_start_allowed(config: TradingConfig) -> None:
    """Allow only non-broker local/simulation operation in Phase 0."""
    if config.environment is Environment.LIVE:
        result = evaluate_live_gate(config)
        failures = ", ".join(result.failed_gates)
        raise EnvironmentUnavailableError(f"live startup denied: {failures}")
    if config.environment is Environment.PAPER:
        raise EnvironmentUnavailableError(
            "paper startup denied: Phase 0 contains no broker connectivity"
        )
