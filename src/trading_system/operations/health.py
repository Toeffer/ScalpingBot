"""Separate liveness, readiness, and trading readiness status."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HealthStatus:
    live: bool
    ready: bool
    trading_ready: bool
    reasons: tuple[str, ...] = ()
