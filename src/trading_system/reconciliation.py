"""Fail-closed reconciliation primitives. Architecture reference: §8.5 and §9.4."""

from dataclasses import dataclass
from decimal import Decimal

from trading_system.exceptions import ReconciliationError


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    complete: bool
    mismatches: tuple[str, ...]


def reconcile_positions(
    *, broker_position: Decimal, local_position: Decimal, instrument_id: str
) -> ReconciliationReport:
    if broker_position != local_position:
        return ReconciliationReport(False, (f"unexplained_position:{instrument_id}",))
    return ReconciliationReport(True, ())


def require_reconciled(report: ReconciliationReport) -> None:
    if not report.complete:
        raise ReconciliationError(",".join(report.mismatches))
