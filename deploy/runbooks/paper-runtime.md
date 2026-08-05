# Paper-runtime setup

The paper runtime is deliberately fail-closed. `trading-cli start` stays halted
until all of the following have been supplied outside source control: the paper
account hash, a PostgreSQL secret reference, and exactly one approved EUR cash
instrument (`con_id` plus exchange). The example values are placeholders and
must never be used for a broker session.

## Safe rollout

1. Install a reviewed TWS API Python distribution that matches the installed IB
   Gateway version, lock it in `uv.lock`, and keep imports confined to
   `trading_system.brokers.ibkr`.
2. Run Gateway and the service on the same host with the API socket bound to
   loopback. Start in Gateway Read-Only mode and verify account, base currency,
   market-data entitlement, clock, contract, and reconstruction from broker
   state.
3. Run migrations against private PostgreSQL, configure a database URL by secret
   reference, and exercise backup and restoration before any order permission.
4. Reconcile positions, open orders, and executions after every startup and
   reconnect. A mismatch or uncertain order is an instrument halt, not a retry.
5. Only after the observer and reconciliation drills pass may an operator set
   `read_only_required: false` in the paper-only deployment configuration. Live
   startup remains unconditionally denied.

The `paper_lifecycle_probe` is disabled by default. When enabled, it issues at
most one one-unit target during the configured session and then targets flat. It
is an OMS and operations test, not a profitable trading strategy.

Paper fills validate connectivity and lifecycle handling only. They do not model
queue position, market impact, or real execution quality. Record and rehearse a
Gateway restart, disconnect, kill-switch latch, and post-session reconciliation
before treating a paper run as complete.