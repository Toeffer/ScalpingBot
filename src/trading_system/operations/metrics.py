"""Low-cardinality operational metrics for paper and future live environments."""

from prometheus_client import Counter, Gauge

SYSTEM_STATE = Gauge("trading_system_state", "Numeric lifecycle state")
TRADING_ENABLED = Gauge("trading_system_trading_enabled", "Whether order submission is enabled")
RECONCILIATION_COMPLETE = Gauge(
    "trading_system_reconciliation_complete", "Whether reconciliation is complete"
)
UNKNOWN_ORDERS = Gauge("trading_system_unknown_orders", "Unresolved broker orders")
RISK_REJECTIONS = Counter(
    "trading_system_risk_rejections_total", "Rejected plans", labelnames=("reason",)
)
