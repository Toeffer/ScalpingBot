"""System lifecycle states from architecture §7.1."""

from enum import StrEnum


class SystemState(StrEnum):
    """Explicit lifecycle and environment-specific ready states."""

    BOOTING = "booting"
    CONNECTING = "connecting"
    RECONCILING = "reconciling"
    READY_SIMULATION = "ready_simulation"
    READY_PAPER = "ready_paper"
    READY_LIVE = "ready_live"
    DEGRADED = "degraded"
    DRAINING = "draining"
    HALTED = "halted"
    STOPPED = "stopped"
