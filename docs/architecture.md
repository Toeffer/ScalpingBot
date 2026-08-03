# Architecture and Implementation Specification

**Companion to:** `AGENT.md` (binding rules, commands, topology)<br>
**Status:** Reference specification — read the relevant section before changing
the corresponding code<br>
**Last reviewed:** 2026-08-03

Section numbering is stable and matches the references used in `AGENT.md`,
commit messages, and code comments. Sections 1–5, 23, 24 and 27 live in
`AGENT.md`; they are listed here so the numbering does not shift.

| §    | Topic                                    | Location             |
| ---- | ---------------------------------------- | -------------------- |
| 1    | Purpose                                  | `AGENT.md` §1        |
| 2    | Binding instructions                     | `AGENT.md` §2        |
| 3    | Commands                                 | `AGENT.md` §3        |
| 4    | Non-goals                                | `AGENT.md` §4        |
| 5    | Operating topology                       | `AGENT.md` §5        |
| 6–22 | Architecture detail                      | this document        |
| 23   | Definition of done                       | `AGENT.md` §8        |
| 24   | Prohibited shortcuts                     | `AGENT.md` §7        |
| 25   | Reference implementation sketch          | this document        |
| 26   | External documentation                   | this document        |
| 27   | Final principle                          | `AGENT.md` §9        |
| 28   | Revision notes                           | this document        |

---

## 6. Core domain model

### 6.1 Contract identity

Never identify a security by ticker alone. A symbol can map to multiple
exchanges, currencies, contract months, trading classes, or instruments.

Use the IBKR contract identifier (`conId`) after contract qualification as the
canonical broker identity.

```python
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class SecurityType(StrEnum):
    STOCK = "STK"
    FUTURE = "FUT"
    CASH = "CASH"
    INDEX = "IND"
    # Extend only alongside the contract, margin and risk tests for that type.


@dataclass(frozen=True, slots=True)
class Instrument:
    con_id: int
    symbol: str
    security_type: SecurityType
    currency: str                    # ISO 4217, the contract's trading currency
    exchange: str
    primary_exchange: str | None
    local_symbol: str | None
    multiplier: Decimal | None       # contract size; None means 1
    min_tick: Decimal                # fallback only — see market rules below
    market_rule_ids: tuple[int, ...] # per-exchange price-increment rule IDs
    trading_class: str | None
    last_trade_date: str | None      # derivatives only
```

Persist the complete qualified contract metadata used for every order. Contract
definitions change over time, so a historical order record must not depend on a
mutable current lookup. Store the qualification result alongside the order, not
a foreign key into a table that will be updated later.

**Tick sizes are not always a single `minTick`.** Several IBKR products use
tiered price increments that vary by price band. `contractDetails.minTick` is the
smallest increment anywhere in the table, which means rounding to it can produce
a price the exchange rejects. Fetch the price-increment table via `reqMarketRule`
for each `marketRuleId` on the contract, cache it with the qualified contract,
and select the increment for the relevant price band. See §11.4.

**Contract identity can change.** Splits, symbol changes, mergers, and futures
rolls can retire a `conId` or change what it means. Requirements:

- Re-qualify every traded contract at startup and compare against the stored
  qualification. A changed `conId`, multiplier, or trading class halts that
  instrument pending operator review.
- Record corporate-action-driven position adjustments as explicit journal
  events, never as a silent correction to a projection.
- Never carry a cached `conId` across a futures roll. Rolls are new instruments
  and require the roll policy in §8.7.

### 6.2 Strategy identity

Every strategy instance receives an immutable identifier:

```text
mean_reversion_us_equities:v1:instance-01
trend_following_futures:v3:instance-01
```

The identifier appears in signal records, intent records, virtual positions,
allocations, risk decisions, order references, metrics, and logs.

Do not reuse an identifier for a materially different strategy implementation.
Bump the version segment instead; performance attribution and replay both key on
this string.

### 6.3 Trading intent

A strategy emits a target, not a broker order.

```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID


class IntentUrgency(StrEnum):
    PASSIVE = "passive"
    NORMAL = "normal"
    URGENT = "urgent"
    RISK_REDUCTION = "risk_reduction"


@dataclass(frozen=True, slots=True)
class TargetPositionIntent:
    intent_id: UUID
    strategy_id: str
    instrument: Instrument
    target_quantity: Decimal         # signed; long positive, in contract units
    urgency: IntentUrgency
    created_at_utc: datetime
    valid_until_utc: datetime
    reason_code: str
    model_version: str
    signal_snapshot_id: UUID
```

Target-position intents are safer than raw `BUY 100` commands because they are
idempotent and let the coordinator compute the difference between desired and
current exposure. Re-delivering the same intent twice must not double exposure.

`target_quantity` is in contract units — shares for stocks, contracts for
futures — never in notional. Notional limits are applied by the risk manager,
which knows the multiplier and the current price.

### 6.4 Virtual and broker positions

Maintain three distinct concepts:

1. **Strategy target position** — what a strategy currently wants.
2. **Strategy virtual position** — the fills internally allocated to a strategy.
3. **Broker position** — the position IBKR reports for the account.

The following invariant must hold after reconciliation, per contract:

```text
sum(strategy virtual positions)
+ explicitly tracked manual allocation
+ explicitly tracked external allocation
= broker account position
```

Any unexplained difference is a reconciliation failure. It blocks all
risk-increasing orders for that contract and raises a critical alert. It does not
block risk-reducing orders if, and only if, position and order state are fresh
enough to compute the reduction safely (§7.1).

### 6.5 Order plan

The risk manager approves an immutable plan. The OMS translates it into one or
more broker orders.

```python
from enum import StrEnum


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class TimeInForce(StrEnum):
    DAY = "DAY"
    GTC = "GTC"          # enable only after restart behavior is tested (§11.3)
    IOC = "IOC"
    FOK = "FOK"


@dataclass(frozen=True, slots=True)
class ApprovedOrderPlan:
    plan_id: UUID
    instrument: Instrument
    side: Side
    total_quantity: Decimal          # unsigned magnitude; direction is `side`
    limit_price: Decimal | None      # in instrument.currency
    max_slippage_bps: Decimal | None # vs. decision_price, basis points
    decision_price: Decimal | None   # reference price the plan was built from
    decision_price_currency: str
    time_in_force: TimeInForce
    urgency: IntentUrgency
    contributing_intent_ids: tuple[UUID, ...]
    risk_decision_id: UUID
    expires_at_utc: datetime
```

Note the unit discipline required by `AGENT.md` rule 14: slippage is basis
points, prices carry an explicit currency, and quantity is an unsigned magnitude
whose direction lives in `side`. Do not add a field whose unit is ambiguous from
its name and type.

An approved plan cannot be silently enlarged or made more aggressive. Any
material change — larger quantity, more aggressive price, different TIF —
requires a new risk decision (§11.5).

---

## 7. State machines

### 7.1 System state

```text
BOOTING
  └──► CONNECTING
          ├──► RECONCILING
          └──► HALTED

RECONCILING
  ├──► READY_SIMULATION
  ├──► READY_PAPER
  ├──► READY_LIVE
  ├──► DEGRADED
  └──► HALTED

READY_*
  ├──► DEGRADED
  ├──► RECONCILING
  ├──► DRAINING
  └──► HALTED

DEGRADED
  ├──► RECONCILING
  ├──► DRAINING
  └──► HALTED

DRAINING                      graceful stop: cancel working orders, settle
  └──► STOPPED                callbacks, flush journal, then exit

HALTED
  └──► RECONCILING            only after authorized operator reset
```

There is one ready state per environment (§16.1). The ready state carries the
environment rather than inferring it, so that a simulation run can never be
mistaken for a paper run in a log, metric, or alert.

Orders that increase risk are permitted only in `READY_SIMULATION`,
`READY_PAPER`, or `READY_LIVE`.

Risk-reducing actions may be permitted in `DEGRADED` only when position and
order state are fresh within the configured bound. If state is uncertain, prefer
cancel-only behavior over automatic flattening: flattening on a stale position
view can double exposure rather than remove it.

`DRAINING` exists so that a planned stop — a deployment, or the pre-maintenance
shutdown in §8.7 — is distinguishable from a crash in both the journal and the
alerting.

### 7.2 Order state

Use an internal state machine. Do not use broker status strings as the domain
model; map them into these states through the explicit table in §8.8.

```text
CREATED
  └──► RISK_APPROVED
          ├──► EXPIRED_BEFORE_SUBMISSION      plan expired while queued
          └──► SUBMITTING
                  ├──► ACKNOWLEDGED
                  ├──► PARTIALLY_FILLED       fill may precede the ack
                  ├──► FILLED                 immediate complete fill
                  ├──► REJECTED
                  └──► UNKNOWN

ACKNOWLEDGED
  ├──► PARTIALLY_FILLED
  ├──► FILLED
  ├──► CANCEL_PENDING
  ├──► CANCELLED
  ├──► REJECTED
  ├──► EXPIRED                                 DAY order at session end
  └──► UNKNOWN

PARTIALLY_FILLED
  ├──► PARTIALLY_FILLED                        further partial fills
  ├──► FILLED
  ├──► CANCEL_PENDING
  ├──► CANCELLED                               remainder cancelled
  ├──► EXPIRED                                 remainder expired
  └──► UNKNOWN

CANCEL_PENDING
  ├──► CANCELLED
  ├──► PARTIALLY_FILLED                        fill during cancel is valid
  ├──► FILLED                                  cancel lost the race
  └──► UNKNOWN

UNKNOWN                                        never terminal
  └──► resolved by reconciliation into exactly one of
       ACKNOWLEDGED, PARTIALLY_FILLED, FILLED,
       CANCELLED, REJECTED, EXPIRED
```

Terminal states: `FILLED`, `CANCELLED`, `REJECTED`, `EXPIRED`,
`EXPIRED_BEFORE_SUBMISSION`.

Three properties of this machine are load-bearing:

**A complete fill does not have to pass through `PARTIALLY_FILLED`.** An order
that fills in one execution goes straight to `FILLED`, and it may do so before
the acknowledgement arrives. Any implementation that only reaches `FILLED` via
`PARTIALLY_FILLED` will corrupt state on the most ordinary event in the system.

**`UNKNOWN` is never terminal.** It means the local system cannot prove the
broker outcome. It is not equivalent to cancelled or rejected. While an order is
`UNKNOWN`:

- Its worst-case remaining quantity is reserved against every limit (§9.1).
- No replacement order for the same plan may be submitted.
- New orders for the same instrument are blocked.
- A resolution deadline runs. On expiry, the instrument halts and the incident
  escalates to an operator. `UNKNOWN` must not be allowed to persist silently.

**`EXPIRED` is a real outcome.** `DAY` is the default TIF, so orders expire at
session end as a matter of routine. Treating expiry as a cancellation loses the
distinction between "we withdrew it" and "the session ended", which matters when
reconstructing why exposure did not change.

Every transition is validated against this table, persisted, and idempotent.
Duplicate and out-of-order broker callbacks are normal integration conditions,
not defects, and must not corrupt state. A transition that is not in the table
is a critical fault, not a warning.

### 7.3 Intent state

```text
RECEIVED
  ├──► EXPIRED
  ├──► SUPERSEDED
  ├──► REJECTED
  └──► ACCEPTED
          ├──► ALLOCATING
          ├──► SATISFIED
          └──► CANCELLED
```

When a strategy emits a newer target for the same contract, the previous target
is superseded rather than executed independently. Superseding is recorded as an
event so that "why did that order never go out" is answerable after the fact.

---

## 8. IBKR integration requirements

### 8.1 API choice

Use the official TWS API through IB Gateway for the initial implementation. Wrap
it behind a repository-owned adapter so that strategy and domain code never
import IBKR callback classes.

The adapter owns: connection lifecycle, `EClient` calls, `EWrapper` callbacks,
reader-thread integration, request-ID allocation, order-ID allocation, contract
qualification, market-rule lookup, subscription tracking, callback normalization,
broker error classification, redaction, and rate limiting.

Nothing else in the codebase may hold a reference to the IBKR client object.
Enforce this with an import-boundary test (§18.1).

### 8.2 Client IDs

Use a fixed registry committed as non-secret configuration:

```yaml
ibkr_clients:
  execution: 1
  observer: 2
  development_tool: 20
```

Never choose a random client ID in production. Stable IDs make reconciliation
and incident analysis possible.

**On the "master" client.** A connection sees *all* account orders — including
those placed by other client IDs and by a human in TWS — only when its client ID
matches the **Master API client ID** configured in the Gateway's API settings.
This is a Gateway configuration value, not an inherent property of `clientId=0`.
Two consequences:

- If the observer connection is meant to see account-wide activity, configure the
  Gateway's Master API client ID to the observer's ID and assert that at startup.
  Do not assume `clientId=0` grants it.
- IB Gateway has no manual order-entry interface, so the "sees orders a human
  typed" behavior applies to TWS deployments. Detection of manual trading in a
  Gateway deployment relies on position and execution reconciliation (§9.4), not
  on the master client.

The main execution service uses exactly one client ID. Developer tools must
never reuse the production execution client ID; doing so silently steals order
ownership.

### 8.3 Order IDs

The adapter must receive `nextValidId` before submitting any order. Request it
explicitly rather than relying on the connect-time delivery.

Requirements:

- Order IDs are scoped per client ID. Track the counter for *your* client ID.
- Store the highest order ID observed for your client through `nextValidId`,
  `openOrder`, and `orderStatus`, and allocate strictly above it.
- Order IDs observed for *other* client IDs on a master connection are not part
  of your sequence. Recording them is useful for reconciliation; using them to
  advance your counter is not required and should not be relied on for safety.
- Allocate monotonically. Never reuse an ID after a restart.
- Never derive order identity solely from a local database sequence.
- Serialize allocation inside the broker adapter, under one lock.

Use the IBKR permanent order ID (`permId`) as the account-level broker identity
once available; it is stable across reconnects and visible to other clients.
Retain the client ID and API order ID as additional keys. Reconciliation matches
on `permId` first, then `orderRef`, then `(clientId, orderId)`.

### 8.4 Order references

Set a compact, non-sensitive `orderRef` on every order.

```text
SYS1|<strategy-code>|<short-plan-id>|<attempt>
```

Example:

```text
SYS1|MRUS|7b8a31d2|1
```

Keep the total under 40 characters and validate the length at construction —
`orderRef` is a free-text field and over-long values risk truncation, which
would break the reconciliation match in §22.4. Use short, registry-mapped
strategy codes rather than full strategy IDs.

Do not put account numbers, model parameters, user names, or secrets in
`orderRef`. It is visible in broker-side reports. The full mapping belongs in
the database.

### 8.5 Connection lifecycle

The adapter distinguishes:

- Local process to Gateway socket connection.
- Gateway to IBKR server connectivity.
- Market-data farm connectivity.
- Historical-data farm connectivity.
- Order-management availability.
- Account readiness.

A successful TCP connection alone does not make the system trade-ready.

On startup:

1. Connect to IB Gateway.
2. Confirm the expected account identifier against a stored allowlist (compare
   hashes; do not log the account number).
3. Assert the Gateway's read-only API setting matches the environment.
4. Obtain the next valid order ID.
5. Request the broker's current time and verify clock skew (§16.5).
6. Subscribe to account and position information.
7. Request open orders relevant to this client.
8. Request all visible open orders for observation where applicable.
9. Request recent executions.
10. Load local unresolved commands and orders.
11. Re-qualify traded contracts and refresh market rules (§6.1).
12. Reconcile contracts, orders, executions, positions, and cash.
13. Rebuild projections.
14. Validate market-data subscriptions and freshness.
15. Verify the kill-switch latch is clear.
16. Enter the ready state for the current environment only when every mandatory
    check passes.

### 8.6 Disconnect handling

Treat broker connectivity messages as state transitions, not as log lines.

- **Connectivity lost:** freeze new risk-increasing orders immediately.
- **Restored, data lost:** resubscribe required market data and reconcile.
- **Restored, data maintained:** still reconcile open orders and positions before
  resuming, even though resubscription is unnecessary. Order state can have
  changed while the socket was down.
- **Socket port reset:** reconnect only to an allowlisted configured port.
- **Gateway restart:** restart the entire readiness procedure from step 1.

Never submit queued strategy orders immediately after reconnect. Strategy
intents must be re-evaluated, because their reference prices and validity
windows have probably expired.

### 8.7 Sessions, maintenance, and halts

Define an operating calendar containing:

- Exchange sessions and holidays, per exchange, with DST transitions handled by
  a maintained timezone database rather than fixed offsets.
- Instrument-specific trading hours, including whether the instrument trades in
  an extended session.
- Opening and closing auction windows.
- IBKR maintenance windows.
- Strategy entry cutoffs.
- Mandatory flatten-or-hold decisions.
- Gateway restart window and post-restart reconciliation period.
- Futures roll dates and the roll policy per instrument.

The system must not initiate ordinary trading during a configured maintenance
blackout. Existing orders require an explicit policy: cancel before the blackout,
leave native broker-held orders working, or flatten before the window. Choose per
instrument and record the choice in configuration, not in code.

**Trading halts.** A halt is an ordinary event, not an exception:

- Treat a regulatory halt, LULD pause, volatility auction, or market-wide
  circuit breaker as an instrument-level trading suspension.
- Cancel or suspend risk-increasing orders for a halted instrument; do not
  assume working orders survive the halt in a usable form.
- Do not compute or act on freshness-based signals using the last pre-halt
  quote. Mark the instrument's data stale for the duration.
- Resumption often runs through an auction with wide indicative prices. Require
  a configured settle period and a fresh two-sided quote before re-enabling
  entries.
- Halts belong in the kill-switch trigger evaluation (§10.6) and in the
  reconciliation path, because orders may be cancelled by the exchange.

### 8.8 Broker errors

Map IBKR messages into categories:

```python
class BrokerErrorCategory(StrEnum):
    CONNECTIVITY = "connectivity"
    PACING = "pacing"
    MARKET_DATA_PERMISSION = "market_data_permission"
    CONTRACT = "contract"
    ORDER_REJECTED = "order_rejected"
    ORDER_WARNING = "order_warning"
    ACCOUNT = "account"
    HALT = "halt"
    TRANSIENT = "transient"
    FATAL_CONFIGURATION = "fatal_configuration"
    UNKNOWN = "unknown"
```

Maintain the mapping as data, not as a chain of conditionals, so that it can be
reviewed and tested as a table:

| Code range / example    | Category               | Action                                            |
| ----------------------- | ---------------------- | ------------------------------------------------- |
| 1100                    | `CONNECTIVITY`         | Freeze entries; await 1101/1102                   |
| 1101                    | `CONNECTIVITY`         | Restored, data lost → resubscribe + reconcile     |
| 1102                    | `CONNECTIVITY`         | Restored, data kept → reconcile before resuming   |
| 2103 / 2105 / 2157      | `CONNECTIVITY`         | Data farm down → mark affected data stale         |
| 2104 / 2106 / 2158      | `CONNECTIVITY`         | Data farm OK → clear the stale flag               |
| 100, 420                | `PACING`               | Back off; preserve cancel priority                |
| 103                     | `ORDER_REJECTED`       | Duplicate order ID → allocation fault, halt       |
| 104, 105, 106           | `ORDER_REJECTED`       | Modify rejected → re-derive state from broker     |
| 200                     | `CONTRACT`             | Ambiguous/unknown contract → halt instrument      |
| 201                     | `ORDER_REJECTED`       | Read the text; margin vs. compliance differ       |
| 202                     | `ORDER_WARNING`        | Cancelled — confirm via `orderStatus`, not text   |
| 354, 10089, 10197       | `MARKET_DATA_PERMISSION` | Missing subscription → block dependent strategy |
| 321, 512                | `FATAL_CONFIGURATION`  | Bad request construction → halt, do not retry     |
| unmapped                | `UNKNOWN`              | Log, count, alert, review. Never assume transient. |

The table above is a starting point and is not authoritative — verify every code
against the current IBKR message-code reference (§26) and keep the test suite in
sync. Unknown messages must be logged, counted in
`broker_unmapped_errors_total`, and reviewed. Do not classify unknown errors as
transient by default; the safe default for an unclassified error is to stop
increasing risk.

Advanced order-rejection details are retained in redacted structured form.

### 8.9 Request pacing and subscription budgets

Implement one token-bucket or leaky-bucket limiter per documented request class,
plus a conservative global limit below the published ceiling.

Priorities, highest first:

1. Emergency cancels.
2. Risk-reducing orders.
3. Reconciliation requests.
4. Normal orders and modifications.
5. Live market-data subscriptions.
6. Contract and reference-data requests.
7. Historical-data requests.
8. Nonessential diagnostics.

A lower-priority class must never be able to starve an emergency cancel. Test
this explicitly (§21, Phase 3 exit criteria).

**Market-data lines are a separate, hard budget.** IBKR allows a limited number
of simultaneous streaming market-data subscriptions per account, typically 100
by default and extendable by account size or purchase. This is not the same
constraint as request pacing:

- Maintain a subscription registry with an explicit configured capacity.
- Refuse a subscription that would exceed capacity, and surface it as a strategy
  startup failure rather than a silent missing feed.
- Reference-count subscriptions shared by several strategies; unsubscribe only
  when the last consumer releases.
- Alert on utilization above a threshold, because exceeding the budget manifests
  as missing data rather than an obvious error.

Historical research workloads run in a separate process on a separate schedule
and must never compete with live execution traffic.

### 8.10 Market data

Every normalized market event includes:

```python
@dataclass(frozen=True, slots=True)
class Quote:
    instrument: Instrument
    bid: Decimal | None
    bid_size: Decimal | None
    ask: Decimal | None
    ask_size: Decimal | None
    broker_timestamp_utc: datetime | None
    received_at_utc: datetime
    sequence: int
    source: str
    data_type: MarketDataType
    subscription_mode: SubscriptionMode
```

Validate:

- Bid and ask are non-negative for instruments where negative prices are
  impossible. Do **not** apply this check to futures and spreads, where negative
  prices are legitimate (§11.4).
- Bid is not above ask, except during a brief, explicitly handled crossed or
  locked transition.
- Quote age is below the strategy's configured limit.
- The data type is live where live data is required.
- Required fields are present.
- Contract identity matches the subscription.
- Local receive latency is within tolerance.
- The stream has not silently stopped — track time since last update per
  instrument, not just process liveness.

A stale quote blocks new entries. Never fall back from live to delayed data in a
strategy that requires live data; downgrade the strategy instead.

**Know what the subscription actually delivers.** This bounds every
latency-sensitive claim the system can honestly make:

| Mode                      | Characteristic                                                  |
| ------------------------- | --------------------------------------------------------------- |
| `reqMktData` (streaming)  | **Sampled snapshots**, not every tick. Roughly 250 ms intervals for US stocks, longer for some products. Intermediate trades and quote changes are not delivered. |
| `reqTickByTickData`       | Per-tick delivery, with its own concurrency limits and permissions. Required for anything that reasons about individual prints or queue behaviour. |
| Snapshot / delayed        | Point-in-time or delayed; never valid for live entries.          |
| `reqRealTimeBars`         | 5-second aggregates. Not a substitute for either of the above.   |

Record `subscription_mode` on every quote and persist it. A freshness budget of
`max_quote_age_ms: 1000` on a stream that samples at 250 ms means "at most four
samples old" — not "at most 1 ms behind the market". Any strategy whose edge
depends on sub-sample-interval information requires tick-by-tick data and an
explicit note in its documentation. Stating this prevents the system from
implying a data quality the feed does not provide.

---

## 9. Portfolio coordination and netting

### 9.1 Target aggregation

This is the single most important calculation in the system. Define it once, in
one function, and test it exhaustively. Do not reimplement it anywhere else.

**Sign convention — normative.** Every quantity below is signed, long positive,
short negative, expressed in contract units:

- `broker_position` — signed position IBKR reports for the contract.
- `account_target` — signed desired account position.
- `working_signed_quantity` — the sum over all non-terminal orders for the
  contract of `remaining_quantity × side_sign`, where `side_sign` is `+1` for
  `BUY` and `-1` for `SELL`, and
  `remaining_quantity = total_quantity − cumulative_filled_quantity`.

Which orders count as working, and at what quantity:

| Order state         | Counts? | Quantity used                                    |
| ------------------- | ------- | ------------------------------------------------ |
| `SUBMITTING`        | yes     | full remaining                                   |
| `ACKNOWLEDGED`      | yes     | full remaining                                   |
| `PARTIALLY_FILLED`  | yes     | remaining after fills received so far            |
| `CANCEL_PENDING`    | yes     | full remaining — the cancel may lose the race    |
| `UNKNOWN`           | yes     | full remaining — worst case, always              |
| terminal states     | no      | —                                                |

Then:

```text
projected_position = broker_position + working_signed_quantity
required_change    = account_target - projected_position
```

`required_change > 0` implies a buy, `< 0` a sell, `0` no action. The account
target is itself the sum of contributions:

```text
account_target =
      sum(signed target of every active strategy)
    + manual_reserved_target
    + external_system_reserved_target
```

Two rules that follow from this and are easy to get wrong:

- **Counting `CANCEL_PENDING` and `UNKNOWN` at full remaining quantity is
  deliberate.** It over-reserves. Over-reserving costs opportunity; under-
  reserving costs money.
- **Coordination is batched, not per-intent.** Intents arriving within one
  coordination window are collected, then netted, then converted into at most
  one required change per contract. Processing intents one at a time re-creates
  exactly the accidental-netting problem the coordinator exists to solve, and
  will over-order when two strategies update simultaneously.

The canonical implementation:

```python
def required_change(
    *,
    account_target: Decimal,
    broker_position: Decimal,
    working_orders: Sequence[WorkingOrderView],
) -> Decimal:
    """Signed quantity to send. Long positive. See docs/architecture.md §9.1."""
    working = sum(
        (o.remaining_quantity * (1 if o.side is Side.BUY else -1)
         for o in working_orders if not o.state.is_terminal),
        start=Decimal(0),
    )
    return account_target - (broker_position + working)
```

Property-based tests must assert: idempotence under repeated application,
correctness under every combination of signs, that no sequence of partial fills
can make the result overshoot the target, and that reserving `UNKNOWN` orders
never produces a change in the direction of *increasing* risk.

### 9.2 Strategy allocations

When a broker execution arrives, allocate it deterministically to contributing
strategies.

Policy, in order:

1. Risk-reduction intents first.
2. Oldest valid intent first within the same priority.
3. Pro rata allocation when multiple targets were intentionally combined.
4. Decimal-safe remainder handling — define the tie-break explicitly (largest
   remainder first, then lowest strategy ID) so it is reproducible.
5. Persist the allocation decision before publishing updated virtual positions.

An execution allocation must be reproducible from persisted inputs alone. Replay
of the same executions in the same order must produce byte-identical
allocations.

### 9.3 Conflicting strategies

When one strategy wants long exposure and another short, the default is
account-level netting:

```text
A target: +100
B target:  -80
Broker target: +20
```

This avoids unnecessary turnover but makes strategy attribution dependent on
virtual accounting. The performance system computes each strategy's virtual
fills according to §9.2.

An optional configuration prohibits overlapping instruments entirely:

```yaml
strategy_universe_policy:
  allow_shared_instruments: false
```

This simpler mode is recommended for the first production release. Netting is
correct but it makes every attribution question harder to answer under
incident pressure.

### 9.4 Manual trades

Manual trades create external state. Choose one policy per deployment:

- **Strict isolation** — manual trading in bot-owned instruments is prohibited.
- **Observe and halt** — detect manual orders or unexplained executions, halt the
  affected instrument, and require operator allocation.
- **Explicit allocation** — provide an audited operator command that assigns a
  manual execution to a strategy or to an external bucket.

Never silently assign unexplained activity to a strategy. An unexplained share is
a reconciliation failure (§6.4), not a rounding issue.

---

## 10. Risk management

Risk is enforced before submission, continuously while orders work, after fills,
and after reconciliation.

### 10.1 Layered controls

1. **Intent validation** — is this request coherent and permitted?
2. **Pre-trade order validation** — is this specific order safe right now?
3. **Continuous account monitoring** — has anything changed since?
4. **Independent emergency controls** — can a human stop it?

Each layer must be able to reject on its own. A failure in any layer is a
rejection, never a pass-through.

### 10.2 Intent validation

Reject an intent when:

- It is expired.
- The strategy is disabled or circuit-broken.
- The instrument is outside the strategy allowlist.
- Required market data is stale, missing, or of the wrong subscription mode.
- The target exceeds the strategy position limit.
- The target would exceed the strategy notional limit.
- The signal snapshot is missing.
- The model version is not approved.
- The trading session is closed, in a blackout, or the instrument is halted.
- Reconciliation is incomplete for that contract.
- The contract is not fully qualified, or its qualification has changed.
- The strategy has breached its loss or drawdown limit.
- The instrument's currency is not enabled for this account (§10.7).

### 10.3 Pre-trade checks

Before every broker submission or material modification:

- Account ID matches the configured allowlist.
- Environment matches the configured account type.
- Live mode has all required gates enabled (§15.4).
- Side, quantity, order type, time in force, and price are allowlisted.
- Quantity is positive and correctly rounded to the contract's lot rules.
- Price conforms to the contract's applicable price increment (§11.4).
- Estimated notional is below the per-order limit, in base currency.
- Resulting position is below strategy and account limits.
- Resulting gross and net exposure are below limits, in base currency.
- Buying power and margin buffers remain sufficient.
- Open-order count is below limit.
- Order rate is below limit.
- Daily loss, drawdown, and consecutive-loss limits are not breached.
- Market-data age is acceptable for the subscription mode in use.
- Spread is below maximum.
- The slippage guard versus `decision_price` is satisfied.
- No conflicting pending cancellation exists.
- No unresolved (`UNKNOWN`) order exists for the same plan or instrument.
- The order plan has not expired.
- The kill switch is not latched.

Persist the input snapshot and every individual check result, not just the
verdict. "Why was this rejected" must be answerable from the journal without
re-running the check.

**Margin checks should use the broker's own answer.** For any order that could
move margin materially, submit it first with `whatIf=True`. IBKR returns the
projected initial margin, maintenance margin, and equity-with-loan change for
that specific order without placing it. Use that projection rather than a local
approximation of IBKR's margin model, which will drift from reality. Treat a
`whatIf` failure as a rejection. Budget for the extra round trip in the pacing
priorities (§8.9) and skip it only for orders that strictly reduce risk.

### 10.4 Example configuration

Conservative values belong in source-controlled examples. Real values belong in
reviewed, environment-specific configuration.

```yaml
risk:
  base_currency: "EUR"          # all limits below are in this currency
  account:
    max_gross_notional: "25000.00"
    max_net_notional: "15000.00"
    max_daily_loss: "250.00"
    max_intraday_drawdown: "300.00"
    max_open_orders: 10
    max_orders_per_minute: 20
    min_excess_liquidity: "5000.00"
  per_instrument:
    max_position: "100"          # contract units
    max_notional: "10000.00"
    max_working_quantity: "100"
    max_spread_bps: "15"
  per_order:
    max_quantity: "25"
    max_notional: "5000.00"
    max_price_deviation_bps: "20"
  currency:
    enabled_trading_currencies: ["EUR"]
    max_fx_exposure_per_currency: "2000.00"
    fx_rate_max_age_ms: 60000
  market_data:
    max_quote_age_ms: 1000
    max_clock_skew_ms: 500
```

These are examples, not recommendations for any account. Every limit is
validated against a strict schema; unknown keys fail startup (§15.6).

### 10.5 Loss limits

Define precisely, in configuration and in tests:

- Realized P&L source.
- Unrealized P&L source.
- Fee and commission treatment, including whether commissions are booked on fill
  or on the later commission report (§11.1).
- Currency conversion method and rate source (§10.7).
- Reset timezone and reset event.
- Treatment of manual and external positions.
- Behavior when P&L data is stale — the safe default is to treat stale P&L as a
  breach, not as zero.

A daily loss breach latches the kill switch. It normally cancels risk-increasing
orders. Automatic flattening is optional, separately configured, and separately
tested, because flattening on uncertain state can increase risk rather than
reduce it.

### 10.6 Kill switches

Provide:

- Global halt.
- Strategy halt.
- Instrument halt.
- Entry halt with exits permitted.
- Cancel-all.
- Flatten selected instrument.
- Flatten all supported instruments.

The global halt must be durable across process restarts — stored outside process
memory, checked during startup before entering any ready state (§8.5 step 15).

Triggers:

- Daily loss or drawdown breach.
- Unexplained position difference.
- Duplicate or contradictory broker execution.
- Stale market data while orders are working.
- Repeated order rejections.
- Database unavailability.
- Excessive clock skew.
- Gateway connection instability.
- Pacing violations.
- Unexpected account.
- Unexpected live environment.
- Corrupted configuration.
- Risk-service exception.
- `UNKNOWN` order past its resolution deadline.
- Market-data subscription budget exhaustion.
- Trading halt affecting an instrument with working orders.
- Operator command.

**Cancel-all has a broker-side primitive.** `reqGlobalCancel` cancels all open
orders for the account. Two properties make it the right tool for an emergency
and the wrong tool for routine use: it does not require enumerating orders, so it
works when local state is untrustworthy; and it is account-wide, so it also
cancels orders placed by other clients or by a human. Use it for the emergency
path, log it as an account-wide action, and follow it with reconciliation rather
than assuming success. For scoped cancellation — one strategy, one instrument —
enumerate and cancel individually.

Flatten commands require a fresh broker snapshot, an explicit instrument scope,
a maximum-slippage bound, and operator confirmation in live mode.

### 10.7 Currency and FX exposure

The account has one **base currency**. Instruments may trade in others. IBKR does
not auto-convert on trade: buying a USD-denominated instrument in a EUR-based
account creates a USD debit, which is an implicit FX borrowing carrying interest
and FX risk. That exposure is real, it is not visible in any single-instrument
position, and it must be modelled.

Requirements:

- Declare `base_currency` in configuration and assert it against the
  broker-reported base currency at startup. A mismatch is a fatal configuration
  error.
- Every monetary field carries its currency. Every limit states its currency.
  A `Decimal` without a currency is not a valid amount (`AGENT.md` rule 18).
- Convert to base currency for all account-level limits, P&L, and drawdown, using
  a recorded rate with a timestamp. Persist the rate used with the decision;
  never re-derive a historical number with a current rate.
- Enforce a maximum age on FX rates. A stale rate blocks new entries in
  non-base-currency instruments.
- Track per-currency cash balances and apply `max_fx_exposure_per_currency`.
- Include financing cost on negative non-base balances in strategy performance.
  A strategy that looks profitable before financing may not be after it.

Until this section is implemented and tested, restrict
`enabled_trading_currencies` to the base currency alone (`AGENT.md` §4).

---

## 11. Order-management system

### 11.1 Responsibilities

The OMS owns: approved-plan intake, parent/child order construction, submission,
acknowledgement tracking, modification and cancellation, partial-fill accounting,
timeout policy, broker identity mapping, duplicate prevention, execution
processing, commission association, final-state publication, and recovery of
unresolved orders.

**Commissions arrive separately from fills** and can lag them. An execution is
not fully booked until its commission report has been associated. Until then,
P&L for that fill is provisional and must be flagged as such in projections, not
silently treated as zero.

### 11.2 Idempotency

Each external command has an immutable UUID.

```sql
CREATE UNIQUE INDEX uq_order_command_id
    ON order_commands(command_id);

CREATE UNIQUE INDEX uq_broker_client_order
    ON broker_orders(broker_client_id, broker_order_id);

CREATE UNIQUE INDEX uq_broker_perm_id
    ON broker_orders(broker_perm_id)
    WHERE broker_perm_id IS NOT NULL;

CREATE UNIQUE INDEX uq_execution_id
    ON executions(execution_id);
```

Before submitting:

1. Begin database transaction.
2. Insert the command with its unique command ID.
3. Allocate the broker order ID.
4. Persist the intended broker payload hash.
5. Commit.
6. Submit to the broker.
7. Persist callback-driven transitions.

If the process crashes between commit and submission, the command is recoverable
and reconciliation will find no matching broker order. If it crashes after
submission but before acknowledgement, the order is `UNKNOWN` and requires
reconciliation. Both cases are required replay scenarios (§18.3).

### 11.3 Order types

The first release supports a minimal allowlist:

- Limit orders.
- Marketable limit orders for tested risk-reduction cases.
- `DAY` time in force.
- `GTC` only after restart and expiry behavior are tested.

Do not initially support: unbounded market entries, complex conditional orders,
trailing stops, algorithmic order types, multi-leg orders, orders outside regular
trading hours, options exercise, or short-sale-specific workflows.

Expand one order type at a time, with paper and small-live tests for each.

### 11.4 Price construction

All prices use `Decimal`, a pinned decimal context, and the contract's applicable
price increment.

```python
from decimal import Decimal, InvalidOperation, localcontext


def round_to_tick(
    price: Decimal,
    tick: Decimal,
    *,
    side: Side,
    aggressive: bool,
) -> Decimal:
    """Round `price` to a valid multiple of `tick`.

    Aggressive means "more likely to fill": up for BUY, down for SELL.
    Passive means the opposite.

    Correct for negative prices (futures, calendar spreads) and independent of
    the ambient decimal context. See docs/architecture.md §11.4.
    """
    if tick <= 0:
        raise ValueError("tick must be positive")

    with localcontext() as ctx:
        ctx.prec = 60
        ctx.traps[InvalidOperation] = True

        # divmod is exact. Decimal truncates toward zero, so normalise to
        # floor semantics for negative prices.
        units, remainder = divmod(price, tick)
        if remainder < 0:
            units -= 1
            remainder += tick

        if remainder == 0:
            return (units * tick).quantize(tick)

        round_up = (side is Side.BUY) == aggressive
        chosen = units + 1 if round_up else units
        return (chosen * tick).quantize(tick)
```

Four things here are deliberate and must not be simplified away:

**`localcontext()` with a pinned precision.** The obvious implementation,
`(price / tick).to_integral_value(rounding=...) * tick`, is silently wrong if any
code anywhere has lowered the global decimal precision. At `prec=7`,
`123456.78` with a `0.01` tick rounds to `123456.8` — a two-tick error, returned
without any exception. Financial arithmetic does not inherit its correctness
from ambient state.

**Trapping `InvalidOperation`.** The pinned context turns an impossible
computation into a raised exception rather than a plausible-looking wrong price.
A rejected order costs an opportunity; a mispriced order costs money.

**`divmod` rather than division.** `divmod` is exact and needs no rounding mode.
The `remainder < 0` normalisation converts Python's truncate-toward-zero
behavior into floor semantics, which is what makes the function correct for
negative prices. Negative prices are not hypothetical: front-month WTI settled at
−$37.63 in April 2020, and calendar spreads are routinely negative. Rejecting
`price <= 0` outright, as an earlier revision of this document did, is a bug for
any futures strategy.

**`.quantize(tick)`** pins the exponent to the tick's. On the path above it is
currently a no-op — `units` always has exponent 0, so `units * tick` already
carries the tick's exponent — and it is kept deliberately as a guard: it makes
the postcondition explicit, it survives a future change to how `units` is
derived, and under the trapped context it raises rather than silently returning a
value the `NUMERIC` scale cannot hold. Note that a 1/32 tick correctly yields
five decimal places (`101.50000`). Do not "tidy" that with `normalize()`; the
trailing zeros are the tick's precision, and stripping them reintroduces the
exponent mismatch this line exists to prevent.

**Selecting the tick.** For instruments with tiered price increments, the
argument passed as `tick` must be the increment for the *relevant price band*,
resolved from the market rule (§6.1) — not `contractDetails.minTick`, which is
the smallest increment anywhere in the table and will produce exchange-rejected
prices in higher bands. Resolve the band from the rounded price and re-check;
where a price sits exactly on a band boundary, choose the coarser increment.

Tests must cover: exact ticks, fractional ticks (1/32, 1/8), both sides,
aggressive and passive, negative prices, zero, tiered-increment band boundaries,
band-boundary re-check, reduced decimal contexts, and inputs that overflow the
pinned context.

### 11.5 Cancel/replace

Modification is not free. A cancel/replace can lose queue priority or race an
execution.

- Do not modify more frequently than configured.
- Track the exact remaining quantity, not the original quantity.
- Treat a fill during cancel as valid — it is a normal outcome, not an error.
- Do not submit a replacement until the cancel outcome is understood, unless the
  execution algorithm explicitly supports overlapping orders *and* risk reserves
  the exposure for both.
- Re-run the full risk check for a more aggressive price or a larger quantity.
- A less aggressive or smaller order still requires consistency validation.
- Use a new command ID for each modification attempt; the plan ID stays the same
  and the attempt counter in `orderRef` increments (§8.4).

### 11.6 Timeouts

Timeouts trigger investigation, never assumption.

```text
submission acknowledgement timeout
    -> mark UNKNOWN
    -> reserve worst-case remaining quantity
    -> block new orders for the instrument
    -> request open orders
    -> request executions
    -> match on permId, then orderRef, then (clientId, orderId)
    -> resolve into a definite state, or halt the instrument at the deadline
```

An unacknowledged order reserves its worst-case quantity until resolved (§9.1).
Every `UNKNOWN` carries a resolution deadline; expiry escalates to an operator
(§7.2, §22.4).

---

## 12. Persistence and audit trail

Use PostgreSQL in paper and live environments. SQLite is acceptable only for
local unit tests and isolated prototypes.

### 12.1 Event journal

Persist append-only domain events:

```text
MarketDataAccepted
SignalGenerated
IntentCreated
IntentSuperseded
RiskDecisionMade
OrderPlanApproved
BrokerSubmissionPrepared
BrokerSubmissionAttempted
OrderAcknowledged
OrderStatusChanged
ExecutionReceived
CommissionReceived
ExecutionAllocated
VirtualPositionChanged
BrokerPositionObserved
FxRateObserved
ContractRequalified
CorporateActionApplied
ReconciliationStarted
ReconciliationMismatchDetected
ReconciliationCompleted
InstrumentHalted
KillSwitchLatched
OperatorActionRecorded
```

Every event carries: event UUID, event type, schema version, aggregate
identifier, strategy identifier where applicable, correlation ID, causation ID,
UTC creation time, source process, artifact digest of the emitting build,
sanitized payload, and an integrity hash where enabled.

### 12.2 Projections

Build transactional projections for current strategy targets, virtual positions,
broker positions, working orders, order plans, daily P&L, per-currency balances,
risk utilization, reconciliation status, and system state.

Projections may be rebuilt from the journal at any time. The journal is never
edited to correct business data; corrections are new events.

### 12.3 Database safety

- Use a dedicated role with only the required privileges.
- Require TLS for remote connections.
- Do not expose PostgreSQL publicly.
- Encrypt backups; test restoration on a schedule, not once.
- Set retention policies.
- Redact production data before any development use.
- Use migrations with tested forward and rollback paths.
- Back up before schema changes.
- Never run destructive migrations during an active session.
- Use row-level or advisory locks to serialize critical actions.
- Configure statement and lock timeouts.

### 12.4 Monetary values

Use PostgreSQL `NUMERIC`, never floating point.

```sql
quantity        NUMERIC(28, 10) NOT NULL,
price           NUMERIC(28, 10),
price_ccy       CHAR(3),
notional        NUMERIC(28, 10),
notional_ccy    CHAR(3),
commission      NUMERIC(28, 10),
commission_ccy  CHAR(3),
realized_pnl    NUMERIC(28, 10),
realized_pnl_ccy CHAR(3),
fx_rate_to_base NUMERIC(28, 12),
fx_rate_as_of   TIMESTAMPTZ
```

Every monetary column has a currency companion. Choose scale after reviewing all
intended asset classes; 10 decimal places covers equities, futures and major FX,
but confirm before enabling a new class.

**Pin the application-side decimal context** at process start, and never rely on
the default:

```python
import decimal

def configure_decimal_context() -> None:
    ctx = decimal.getcontext()
    ctx.prec = 34
    ctx.traps[decimal.InvalidOperation] = True
    ctx.traps[decimal.DivisionByZero] = True
    ctx.traps[decimal.Overflow] = True
```

Verify that the database driver returns `Decimal` rather than `float` for
`NUMERIC` columns, and assert it in a test. A driver configuration change that
silently starts returning floats would be invisible until it produced a wrong
price.

### 12.5 Event schema evolution

Deterministic replay (§18.3) is a promise that survives only if old events remain
readable. Before the first schema change, put this in place:

- Every event carries `schema_version` from day one.
- Persisted events are **immutable**. Never rewrite historical payloads to fit a
  new shape.
- Provide **upcasters**: pure functions `(version n payload) -> (version n+1
  payload)`, chained at read time. Deserialization always upcasts to the current
  version.
- Every upcaster ships with a golden fixture of the old payload and its expected
  upcast result, kept permanently in `tests/fixtures/events/`.
- Additive changes (new optional field with a default) do not need a version
  bump. Removing a field, renaming one, or changing its meaning or units does.
- Replay fixtures recorded under old schema versions stay in the regression
  suite. They are the only evidence that the upcast chain still works.
- Reject an unknown `schema_version` at read time. Do not guess.

The same discipline applies to configuration schemas, which are replay inputs
too.

---

## 13. Concurrency model

The official API uses callbacks and a reader loop. Isolate that behavior inside
the adapter.

- One thread owns the IBKR client socket and reader.
- Broker callbacks are converted immediately into immutable internal events.
- Events are placed onto a **bounded** thread-safe queue.
- An `asyncio` event loop processes domain events.
- Database writes happen through explicit transactional handlers.
- Strategy calculations run with deadlines and cannot block broker callbacks.
- CPU-heavy research or model inference runs in separate worker processes.

Rules:

- Never call blocking database or HTTP code from the IBKR callback thread.
- Never mutate shared domain state from callbacks.
- Never use an unbounded queue.
- Queue saturation is a critical fault, not a warning. Define the drop policy
  explicitly: market-data events may be dropped with a counter increment; order,
  execution and account events may **never** be dropped — saturation on those
  queues halts the system.
- Preserve per-order event ordering where possible.
- Make every handler idempotent, because global ordering is not guaranteed.
- Use monotonic clocks for durations and UTC wall clocks for audit timestamps.

Backpressure must be observable before it is fatal: export queue depth and lag
(§17.1) and alert on sustained growth, not only on overflow.

---

## 14. Strategy interface

A strategy is a pure decision component as far as practical.

```python
from typing import Protocol, Sequence


class Strategy(Protocol):
    @property
    def strategy_id(self) -> str:
        ...

    def required_instruments(self) -> Sequence[Instrument]:
        ...

    async def on_market_event(
        self,
        event: Quote,
        state: "StrategyStateView",
    ) -> Sequence[TargetPositionIntent]:
        ...

    async def on_timer(
        self,
        now_utc: datetime,
        state: "StrategyStateView",
    ) -> Sequence[TargetPositionIntent]:
        ...

    async def on_session_event(
        self,
        event: "SessionEvent",       # open, close, halt, resume, blackout
        state: "StrategyStateView",
    ) -> Sequence[TargetPositionIntent]:
        ...
```

A strategy may read its virtual position, its working allocated quantity,
approved market data, its own risk utilization, session state, and its own
historical features.

A strategy may not read broker credentials, the raw account number, other
strategies' proprietary state (unless explicitly designed for it), database
connections, OMS internals, or live-mode enablement secrets.

A strategy must be deterministic under recorded replay given the same ordered
inputs, configuration, and clock. That means: no wall-clock reads outside the
supplied `now_utc`, no unseeded randomness, no network access, and no dependence
on dictionary or set iteration order for anything that affects output.

### 14.1 Strategy resource limits

Enforce maximum callback duration, maximum memory, maximum emitted intents per
interval, maximum feature lookback, maximum log rate, and a circuit breaker after
repeated exceptions.

A failing strategy is disabled without stopping risk supervision or order
management. Disabling a strategy does not abandon its positions: the coordinator
retains its last target until an operator decides whether to flatten, transfer,
or hold. Silently dropping a disabled strategy's target would change the account
target and generate unintended orders.

---

## 15. Security architecture

### 15.1 Threat model

Protect against: credential theft; unauthorized live orders; malicious or
compromised dependencies; accidental connection to the wrong account; public
exposure of the Gateway socket or database; remote command injection; log
leakage; configuration tampering; insider misuse; replay of administrative
commands; dependency substitution; container or host compromise; excessive
privileges; denial of service through event or log flooding; and an AI coding
agent weakening controls for convenience.

That last item is not rhetorical. It is the reason for `AGENT.md` rule 16 and for
requiring a second reviewer on safety-critical code.

### 15.2 Network security

Preferred deployment puts the trading application and IB Gateway on the same
hardened host, with API access bound to loopback.

- Bind the API socket to localhost where possible.
- Configure trusted IPs narrowly.
- Deny inbound internet traffic by default.
- Allow remote administration only through a VPN or a tightly controlled bastion.
- Do not port-forward the TWS/IB Gateway API socket.
- Do not expose PostgreSQL, metrics, or debug endpoints publicly.
- Use host firewall rules in addition to cloud security groups.
- Separate production, paper, and development networks.
- Disable unused services; record administrative access.

If the application and Gateway must run on separate hosts, use a private network,
strict allowlists, encrypted transport where supported, mutual authentication at
a tunnel or service-mesh layer, and protection against route changes. Never send
the API socket over the open internet.

### 15.3 Authentication and credentials

- Do not automate collection of the IBKR username, password, or MFA challenge.
- Do not hard-code credentials.
- Store infrastructure secrets in an OS key store or managed secret manager.
- Use separate paper and live configuration identities.
- Restrict secret access to the service account that needs it.
- Rotate notification, database, and infrastructure credentials.
- Prefer short-lived credentials for cloud services.
- Require MFA for human administration.
- Remove access immediately when no longer needed.
- Never pass credentials as command-line arguments, where process listings expose
  them.

### 15.4 Live-mode gates

Live trading requires **all** of:

```text
1. Environment variable: TRADING_ENV=live
2. Read-only config file: live_enabled=true
3. Expected account hash matches the broker-reported account
4. Broker-reported base currency matches configuration
5. Host is in the production host allowlist
6. Production database is reachable and migrated to head
7. Kill switch is clear
8. Reconciliation is complete
9. Operator supplies a short-lived enable token
10. Maximum initial live limits are loaded
11. Startup banner and alert confirm live status
```

No single flag may be sufficient. Each gate is independently tested (§18.1) and
each failure is separately logged, so that "why did live not enable" is
answerable without a debugger.

The enable token authorizes enabling only; it never contains broker credentials.
Store only a hash and an expiry. Require reauthorization after a critical halt
and after each weekly Gateway reauthentication.

### 15.5 Least privilege

Run services under dedicated non-root accounts, with separate roles for trading
runtime, read-only monitoring, database migration, backup, deployment, and
incident response.

The trading runtime must not have root access, Docker socket access, general
cloud-administration rights, source-repository write access, backup-deletion
rights, unrelated SSH private keys, or permission to alter its own live risk
configuration.

### 15.6 Configuration integrity

Split configuration into version-controlled non-secret defaults,
environment-specific non-secret configuration, secret references, and runtime
emergency state.

Validate with a strict schema. **Reject unknown keys** — a typo in a limit name
must fail startup, not silently apply a default. Generate a canonical
configuration hash at startup and include it in audit records and in the startup
alert.

Production risk-limit changes require an authenticated operator, a reason, a
ticket identifier, before and after values, validation, a second approval for any
limit increase, an audit event, and a controlled reload or restart.

A strategy deployment may lower its own limits automatically. It may never raise
them.

### 15.7 Dependency and supply-chain security

- Pin exact versions in a lock file; commit the lock file.
- Verify package hashes where practical.
- Use the official IBKR API distribution or a reviewed internal package.
- Do not install packages on production hosts during trading.
- Build immutable artifacts in CI; deploy only reviewed commits from protected
  branches.
- Generate a software bill of materials.
- Run dependency vulnerability scanning, static analysis, and secret scanning.
- Sign release artifacts where the infrastructure permits.
- Record the artifact digest in startup logs and in every journal event (§12.1).
- Remove build tools from runtime images; use a minimal base image.

Third-party convenience wrappers around the TWS API require separate review. Do
not let a wrapper obscure order IDs, callbacks, error codes, or reconnect
behavior — those are exactly the things this system must reason about directly.

### 15.8 Logging security

Structured logs must be useful without exposing sensitive data.

Redact: account IDs, usernames, tokens, passwords, sensitive hostnames,
notification destinations, and full broker payloads containing identifiers.

```json
{
  "timestamp": "2026-08-03T07:24:00.000Z",
  "level": "INFO",
  "service": "oms",
  "event": "order_acknowledged",
  "correlation_id": "uuid",
  "causation_id": "uuid",
  "strategy_id": "mean_reversion:v1:instance-01",
  "instrument_con_id": 123456,
  "local_order_id": "uuid",
  "broker_order_id": 812,
  "broker_perm_id": 1234567890,
  "environment": "paper",
  "config_hash": "sha256:ab12…",
  "artifact_digest": "sha256:cd34…"
}
```

Production logs require access control, rotation, retention, tamper resistance,
and clock synchronization. Do not enable detailed API market-data logging
continuously; use it only for a bounded incident investigation, and record who
enabled it and when.

Redaction is tested (§18.1) with fixtures containing realistic-looking secrets.
A redaction regression is a security incident.

### 15.9 Administrative interface

Do not expose a general-purpose shell or an arbitrary-code endpoint.

Provide a narrow CLI or authenticated internal API:

```text
status
reconcile [--dry-run]
halt --scope global --reason <text>
halt --strategy <id> --reason <text>
halt --instrument <con-id> --reason <text>
cancel-all --scope <scope>
flatten --instrument <con-id> --max-slippage-bps <n>
allocate-execution <execution-id> --to <strategy-id|external>
enable-paper
enable-live --token <short-lived-token>
disable
acknowledge-incident <incident-id>
```

Every mutating command requires strong authentication, authorization, a nonce or
request ID, a timestamp and expiry, dry-run output where feasible, confirmation
for destructive live actions, an audit record, and idempotency.

### 15.10 Secure development

- Threat model significant architecture changes.
- Require code review for broker, risk, security, and deployment code.
- Add a failing test before fixing a safety-critical defect.
- Keep test fixtures free of real account data.
- Scan for secrets before commit and in CI.
- Review access to source, CI, artifact registry, production, and backups.
- Track vulnerabilities and remediation.
- Preserve evidence for trading incidents.
- Conduct periodic recovery and kill-switch exercises. An untested kill switch is
  a hypothesis, not a control.

---

## 16. Deployment

### 16.1 Environments

Maintain strict separation between `local`, `simulation`, `paper`, and `live`.
Each has its own ready state (§7.1).

Use different configuration, database, Gateway port, account allowlist,
notification channel, service identity, log destination, and risk limits.

A paper executable must not become live by changing a port. The multi-gate live
enablement (§15.4) still has to pass.

### 16.2 Host

A single hardened Linux host is adequate initially.

```text
ib-gateway
trading-engine
postgresql
metrics-exporter
alert-manager
backup-agent
```

IB Gateway requires supported interactive authentication behavior. Do not build
an unsupported credential-injection mechanism to make it appear fully headless.

**A single host is a single point of failure, and this system holds positions
overnight.** That is an accepted trade-off only if the manual fallback in §22.7
exists, is documented, and has been rehearsed. Do not treat "we will rebuild the
host" as a plan while positions are open.

### 16.3 Process supervision

Use `systemd` or an equivalent.

- Restart on unexpected exit with backoff.
- Do not restart endlessly after repeated critical faults; crash-loop detection
  latches the halt.
- Persist the halt latch outside process memory.
- Set resource limits; use a dedicated working directory.
- Use read-only filesystem areas where practical.
- Restrict system calls and capabilities where compatible.
- Send startup, shutdown, crash-loop, and live-enable alerts.
- Stop the trading engine gracefully via `DRAINING` (§7.1) before Gateway
  maintenance.

### 16.4 Containers

Containers are optional. If used: never mount the Docker socket; run as non-root;
use a read-only root filesystem where feasible; drop Linux capabilities; set CPU
and memory limits; store mutable data in explicit volumes; keep Gateway GUI and
authentication requirements in mind; use immutable image digests; scan images;
never bake secrets into layers. Do not assume containerization is itself a
security boundary.

### 16.5 Clock synchronization

Accurate time is required for validity windows, latency measurement, and audit
records.

- Synchronize with a reputable NTP service; monitor the daemon, not just the
  offset at boot.
- Alert on clock offset.
- Halt new entries when skew exceeds the configured threshold.
- Store monotonic duration measurements separately from wall-clock timestamps.
- Compare local time with broker time at startup and periodically thereafter.

---

## 17. Observability

### 17.1 Metrics

At minimum:

```text
system_state
trading_enabled
kill_switch_latched
broker_socket_connected
broker_server_connected
last_broker_event_age_seconds
last_quote_age_seconds{instrument}
market_data_lines_in_use
market_data_lines_capacity
event_queue_depth{queue}
event_queue_lag_seconds{queue}
event_queue_dropped_total{queue}
database_write_latency_seconds
reconciliation_status
reconciliation_mismatch_count
open_orders{strategy,instrument}
unknown_orders
unknown_order_age_seconds
position{strategy,instrument}
broker_position{instrument}
gross_notional_base
net_notional_base
fx_exposure_base{currency}
fx_rate_age_seconds{pair}
daily_realized_pnl_base
daily_unrealized_pnl_base
pending_commission_executions
risk_limit_utilization{limit}
orders_submitted_total
orders_rejected_total{reason}
orders_cancelled_total
orders_expired_total
executions_total
partial_fills_total
pacing_events_total
broker_unmapped_errors_total{code}
strategy_callback_duration_seconds{strategy}
strategy_exceptions_total{strategy}
clock_skew_seconds
```

Avoid high-cardinality labels such as raw UUIDs.

Define an explicit target for the ones that gate trading — quote age, queue lag,
clock skew, and database write latency — so that "degraded" is a measured
condition rather than a judgement call. The alert threshold and the risk-check
threshold should be derived from the same configured value, not maintained
separately.

### 17.2 Alerts

**Critical:** live trading enabled unexpectedly; wrong account detected;
reconciliation mismatch; kill switch latched; `UNKNOWN` order past deadline;
database unavailable; broker disconnected while orders are working; stale data
while exposure exists; daily loss breach; clock skew breach; repeated order
rejection; queue saturation; crash loop; market-data line budget exhausted.

**Warning:** broker maintenance approaching; market data degraded; strategy
disabled after exception; risk utilization above threshold; unusual slippage;
commission data delayed; FX rate ageing; backup failure; certificate or secret
rotation due; unmapped broker error code observed.

Alerts must not contain sensitive account details. Every critical alert names the
runbook section that responds to it.

### 17.3 Health endpoints

Separate three concepts:

- **Liveness** — the process can respond.
- **Readiness** — safe to receive work.
- **Trading readiness** — reconciliation, market data, risk, and broker state are
  sufficient to submit orders.

A generic HTTP 200 must never be interpreted as trading readiness.

---

## 18. Testing strategy

### 18.1 Unit tests

Cover: tick rounding across the full matrix in §11.4; quantity rounding; contract
identity and re-qualification; target aggregation and `required_change`;
working-order exposure including `UNKNOWN` and `CANCEL_PENDING`; strategy
allocation and its tie-break; every risk check; currency conversion and stale-rate
handling; daily loss reset; every order state transition, including the ones that
must be rejected; duplicate callbacks; out-of-order callbacks; error
categorization against the §8.8 table; redaction; configuration validation
including unknown-key rejection; each live-mode gate independently; kill-switch
latch and persistence; decimal serialization and driver round-trip; event
upcasters against golden fixtures; and timezone handling across DST boundaries.

Two structural tests are worth calling out because they enforce architecture
rather than behavior:

- **Import boundary:** assert that no module outside `brokers/ibkr/` imports the
  IBKR package, and that `strategies/` imports neither the broker adapter nor the
  OMS nor the persistence layer.
- **Unit discipline:** assert that no public dataclass field holding an amount,
  duration, or rate lacks a unit suffix or a currency companion.

Use property-based testing for allocation, netting, and state-machine invariants.

### 18.2 Broker-adapter tests

Create a deterministic fake IBKR transport that can emit: connection success and
failure; `nextValidId`; open orders; duplicate order statuses; partial fills;
**fill before acknowledgement**; **complete fill in a single execution**; cancel
acknowledgement after fill; rejection; lost acknowledgement; disconnect codes
1100/1101/1102; data-farm messages; reconnect with data lost; reconnect with data
maintained; pacing errors; contract ambiguity; market-data permission errors;
market-data line exhaustion; trading halt and resumption; Gateway restart; and an
unexpected account.

CI must never depend on the live IBKR service.

### 18.3 Replay tests

Persist normalized event fixtures and replay them through the complete domain
pipeline. Required scenarios:

- Normal entry and exit.
- Two strategies with the same directional target.
- Two strategies with opposing targets.
- Two strategies updating within the same coordination window.
- Superseded target before submission.
- Partial fill followed by target reversal.
- Complete fill arriving before the acknowledgement.
- Manual trade detected.
- Crash after command persistence but before submission.
- Crash after submission but before acknowledgement.
- Database restart during callbacks.
- Stale quote; spread spike; trading halt and resumption.
- Session close with a working `DAY` order (expiry, not cancellation).
- Maintenance disconnect.
- Duplicate execution; corrected execution.
- Commission arriving after fill, and commission never arriving.
- Corporate action changing a `conId`.
- FX rate going stale with non-base-currency exposure.
- Kill switch latching while orders work.
- Replay of fixtures recorded under an older event schema version.

Replay must produce a deterministic final state, byte-identical across runs.

### 18.4 Backtesting

Backtesting is strategy research, not broker-integration testing. Do not let a
backtest result stand in for any claim in §18.5 or §18.6.

For short-horizon strategies, model bid and ask rather than close price;
commission; the applicable price increment; order latency; cancel latency;
partial fills; queue uncertainty; market impact; borrow and financing; currency
conversion; session boundaries; corporate actions; survivorship bias; delisted
instruments; data gaps; look-ahead bias; and parameter-selection bias.

Where the backtest uses bar data, state the bar interval next to any result, and
do not present a strategy whose horizon approaches that interval as validated.

Keep the backtester behind the same strategy interface, but do not reuse
optimistic live execution assumptions.

### 18.5 Paper trading

Paper trading validates connectivity, contract definitions, callback handling,
order lifecycle, reconciliation, operational runbooks, alerts, Gateway restarts,
and multi-strategy coordination.

It does **not** validate queue position, market impact, deep-book execution, or
all live order behavior. Paper fills are generated by a simulator, not by a
market.

Run both strategies simultaneously in paper for a sustained period. Force
disconnects, restarts, and kill-switch latches rather than testing only the happy
path.

### 18.6 Small-live validation

Live rollout starts with one instrument, one strategy, the minimum practical
size, no leverage where possible, a short operating window with an operator
present, a very low daily loss limit, an entry cutoff before session end, and
immediate post-session reconciliation.

Compare: decision price; submitted price; acknowledgement latency; fill price;
slippage; commission; partial-fill rate; cancel success rate; and paper-versus-
live divergence.

Increase exactly one dimension at a time — size, instruments, session length,
order type, or number of strategies — and record the decision each time.

---

## 19. Repository structure

```text
.
├── AGENT.md                       # binding contract — always in context
├── AGENTS.md -> AGENT.md          # symlink for harnesses that expect this name
├── CLAUDE.md -> AGENT.md          # symlink
├── README.md
├── pyproject.toml
├── uv.lock
├── docs/
│   ├── architecture.md            # this document
│   ├── threat-model.md
│   └── decisions/                 # one file per architecture decision
├── migrations/
├── config/
│   ├── schema/
│   ├── defaults.yaml
│   ├── simulation.example.yaml
│   ├── paper.example.yaml
│   └── live.example.yaml
├── src/
│   └── trading_system/
│       ├── app.py
│       ├── domain/
│       │   ├── instruments.py
│       │   ├── intents.py
│       │   ├── orders.py
│       │   ├── executions.py
│       │   ├── positions.py
│       │   ├── money.py           # Amount = (Decimal, currency); conversion
│       │   ├── risk.py
│       │   └── events.py
│       ├── strategies/
│       │   ├── base.py
│       │   ├── registry.py
│       │   ├── strategy_a/
│       │   └── strategy_b/
│       ├── portfolio/
│       │   ├── coordinator.py     # batching + netting; §9.1 lives here
│       │   └── allocator.py
│       ├── risk/
│       │   ├── manager.py
│       │   ├── limits.py
│       │   ├── currency.py
│       │   └── kill_switch.py
│       ├── oms/
│       │   ├── service.py
│       │   ├── state_machine.py
│       │   ├── pricing.py         # round_to_tick; §11.4 lives here
│       │   └── idempotency.py
│       ├── brokers/
│       │   └── ibkr/
│       │       ├── adapter.py
│       │       ├── client.py
│       │       ├── callbacks.py
│       │       ├── contracts.py
│       │       ├── market_rules.py
│       │       ├── errors.py      # the §8.8 table as data
│       │       ├── pacing.py
│       │       ├── subscriptions.py
│       │       └── reconciliation.py
│       ├── market_data/
│       │   ├── service.py
│       │   ├── normalization.py
│       │   └── freshness.py
│       ├── calendar/
│       │   ├── sessions.py
│       │   ├── halts.py
│       │   └── rolls.py
│       ├── persistence/
│       │   ├── database.py
│       │   ├── journal.py
│       │   ├── upcasters.py       # §12.5
│       │   ├── repositories.py
│       │   └── projections.py
│       ├── operations/
│       │   ├── cli.py
│       │   ├── health.py
│       │   ├── metrics.py
│       │   ├── alerts.py
│       │   └── redaction.py
│       └── security/
│           ├── authorization.py
│           ├── live_gate.py
│           └── config_integrity.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── replay/
│   ├── security/
│   ├── architecture/              # import boundaries, unit discipline
│   └── fixtures/
│       └── events/                # golden fixtures, incl. old schema versions
├── scripts/
│   ├── run_simulation.sh
│   ├── run_paper.sh
│   ├── reconcile.py
│   ├── backup_verify.py
│   └── verify_release.py
└── deploy/
    ├── systemd/
    ├── container/
    ├── firewall/
    └── runbooks/
```

---

## 20. Coding standards

### 20.1 Python

- Python 3.12 or later.
- `mypy --strict` on `src`. New `# type: ignore` comments require a justification
  comment and a reviewer.
- `Decimal` for every financial value, with the pinned context from §12.4.
- Frozen dataclasses for immutable domain messages.
- `Enum` or `StrEnum` for every finite set of values. A bare `str` for a side, a
  time in force, a security type, or a data type is not acceptable.
- Explicit exceptions. Do not catch `Exception` without re-raising, halting, or
  recording a categorized fault.
- No global mutable broker state.
- No wildcard imports.
- No business logic in callback classes.
- No network or database activity in constructors.
- Dependency injection at service boundaries.
- Structured logging; UTC-aware `datetime` everywhere.
- Bounded retries with jitter, and only for operations proven safe to retry.
  Order submission is not one of them.

### 20.2 Quality gates

See `AGENT.md` §3 for the commands. A merge requires all of them green, plus
secret scanning, static security analysis, migration validation, the replay
regression suite, a license policy check, and a container scan where applicable.

Safety-critical code — broker adapter, risk manager, OMS, live gate, kill switch,
`required_change`, `round_to_tick` — requires a second reviewer.

### 20.3 Comments and documentation

Comments explain why a safety rule exists, which invariant is protected, which
broker behavior motivates unusual logic, and what evidence resolves an uncertain
order. Do not write comments that restate the code.

Every function implementing a rule from this document cites its section number.
Every operational failure mode has a runbook.

---

## 21. Implementation phases

### Phase 0 — Repository and security baseline

Deliver: typed project skeleton; locked dependencies; CI quality gates; secret
scanning; configuration schema with unknown-key rejection; environment
separation; structured logging and redaction; persistent kill-switch model;
threat model; pinned decimal context. No broker connectivity yet.

Exit criteria: a secret deliberately inserted in a test branch is detected;
unknown configuration keys fail startup; live mode cannot start; logs contain no
secret fixtures; the decimal context is asserted at process start.

### Phase 1 — Read-only IBKR observer

Run the API in read-only mode.

Deliver: Gateway connection; account allowlist validation; base-currency
assertion; contract qualification and market-rule lookup; market-data
subscription with a line budget; positions; account values; open orders;
executions; connection and error mapping; persistent event journal; readiness
state.

Exit criteria: restart and reconnect rebuild the same broker projection; a wrong
account causes a halt; a data-lost reconnect resubscribes; duplicate callbacks do
not duplicate executions; no order method is reachable from outside the adapter.

### Phase 2 — Reconciliation engine

Deliver: startup reconciliation; unresolved local command matching; broker/local
position comparison; manual and external activity detection; reconciliation
report; instrument-level halt; operator allocation command.

Exit criteria: every replay crash point resolves deterministically or halts
safely; an unexplained share blocks the instrument; reconciliation is mandatory
after every reconnect.

### Phase 3 — Paper OMS

Disable IBKR read-only mode in the paper environment only.

Deliver: limit orders; order-ID allocation; `orderRef`; the full §7.2 state
machine; cancel support; partial fills; commission association; `UNKNOWN`
recovery with deadlines; conservative rate limiter.

Exit criteria: no duplicate order under forced process crashes at each of the
§11.2 steps; a complete fill arriving before the acknowledgement is handled;
fill-during-cancel is handled; a `DAY` order at session end reaches `EXPIRED`,
not `CANCELLED`; the pacing test preserves cancel priority under load; orders
cannot be sent before reconciliation.

### Phase 4 — Central risk manager

Deliver: all pre-trade checks; strategy, instrument, order, and account limits;
`whatIf` margin pre-check; loss and drawdown controls; durable kill switch;
cancel-all via `reqGlobalCancel`; carefully controlled flatten; risk decision
audit trail.

Exit criteria: every risk rejection has an explicit, persisted reason; a
risk-service failure rejects trading rather than passing through; limit increases
require an authorized configuration change; the kill switch survives restart and
has been exercised end to end.

### Phase 5 — One strategy in paper

Deliver: strategy interface; strategy state view; target intents; portfolio
coordinator with a batching window; deterministic replay; paper deployment.

Exit criteria: the architecture test proves the strategy cannot import the broker
adapter; every order maps to a signal and a risk decision; a sustained paper run
survives maintenance restarts; operational alerts have been fired and answered.

### Phase 6 — Two strategies in paper

Deliver: multiple strategy instances; shared-instrument policy; netting; virtual
fill allocation; per-strategy P&L; conflict tests.

Exit criteria: opposing targets produce the correct broker target; allocations
reproduce exactly under replay; one failing strategy does not stop risk
supervision or abandon its position; two strategies updating in the same
coordination window produce one net order, not two.

### Phase 7 — Small live pilot

Deliver: live enable-token workflow; production host hardening; backup and
restore test; incident runbooks including host loss; operator dashboard;
minimum-size live execution.

Exit criteria: human review completed; live account and host allowlists verified;
kill switch exercised against the live account; reconciliation tested with real
executions; slippage and commission reporting verified against the broker
statement; the host-loss fallback rehearsed; a formal decision recorded before
any scaling.

---

## 22. Operational runbooks

Detailed procedures live in `deploy/runbooks/`. The summaries below define the
required shape; each critical alert (§17.2) names the section that answers it.

### 22.1 Startup

1. Confirm host identity and environment.
2. Confirm the Gateway is authenticated to the intended paper or live account.
3. Confirm database health and migration state.
4. Start in a disabled state.
5. Connect and reconcile.
6. Review the mismatch report.
7. Confirm market-data freshness and line budget.
8. Confirm risk limits and the configuration hash.
9. Enable strategies.
10. Enable paper or live trading through the appropriate gate.
11. Verify alerts and dashboards are live, not just configured.

### 22.2 Unexpected disconnect

1. The system automatically freezes entries.
2. Preserve local state and working-order reservations.
3. Observe the connectivity classification (§8.8).
4. Reconnect.
5. Resubscribe where required.
6. Request open orders and executions.
7. Reconcile.
8. Resolve `UNKNOWN` orders.
9. Re-evaluate unexpired strategy targets — do not release queued orders.
10. Require an operator reset after a critical or repeated disconnect.

### 22.3 Position mismatch

1. Halt the affected instrument.
2. Cancel risk-increasing working orders.
3. Request fresh positions, orders, and executions.
4. Check partial fills and delayed callbacks.
5. Check manual trading.
6. Check corporate actions and contract re-qualification (§6.1).
7. Allocate explained external activity through the audited command.
8. Record the incident.
9. Reconcile again.
10. Authorize resume explicitly.

### 22.4 Unknown order

1. Reserve worst-case exposure (§9.1).
2. Halt new orders for the instrument.
3. Request open orders.
4. Request executions.
5. Match on `permId`, then `orderRef`, then `(clientId, orderId)`, then contract,
   side, quantity, and time.
6. Never submit a replacement until resolved.
7. At the resolution deadline, escalate: halt the instrument and page an
   operator. Do not let the order age silently.

### 22.5 Daily loss breach

1. Latch the global or strategy kill switch.
2. Block new entries.
3. Cancel entry orders.
4. Evaluate whether exits are safe given current state freshness.
5. Notify the operator.
6. Produce a loss and event report.
7. Do not auto-reset at midnight without a policy review.
8. Require explicit authorization before resuming.

### 22.6 Wrong account or unexpected live connection

1. Do not place or cancel orders automatically unless a pre-approved emergency
   policy says otherwise. The account may not be yours to act on.
2. Latch the global halt.
3. Disconnect the trading engine.
4. Alert at critical severity.
5. Preserve evidence — logs, journal, configuration hash, artifact digest.
6. Require manual investigation before any reconnection.

### 22.7 Total host loss with open positions

This is the failure mode the single-host topology (§16.2) accepts, so it needs
the most rehearsed procedure. The system cannot act; a human must.

**Prerequisites, in place before live trading:**

- A second machine with TWS installed and able to log into the same account.
- The IBKR mobile app installed and tested on an operator device.
- The IBKR client-services phone number recorded somewhere reachable without the
  host — printed, or on a phone.
- A current export of open positions and working orders, written to off-host
  storage on a schedule and after every fill.
- A written statement, per strategy, of what its positions mean and whether the
  default action is to flatten or to hold.

**Procedure:**

1. Confirm the host is genuinely unreachable rather than merely unresponsive; a
   half-alive host that resumes trading mid-recovery is worse than a dead one.
2. Fence it. Revoke its credentials or block it at the network layer so it cannot
   resume unilaterally.
3. Log into TWS or the mobile app on the fallback device.
4. Read the actual account position from the broker. Do not act on the last
   known local state.
5. Cancel all working orders through the broker interface.
6. Apply the documented per-strategy decision: flatten or hold.
7. Record every manual action with timestamps — these become the external
   allocations the system must reconcile against on recovery (§9.4).
8. On rebuild, start in `simulation`, reconcile against the broker, allocate the
   manual actions explicitly, and require a full startup runbook before
   re-enabling.

Rehearse this at least once before the live pilot and once per year afterwards.
An unrehearsed fallback is not a fallback.

---

## 25. Reference implementation sketch

Illustrative structure, not production code. It is included because coding agents
copy sketches, so it must model the rules rather than contradict them: the kill
switch is checked before any ready state, failures land in `HALTED` rather than
leaving the state stuck, and coordination is batched rather than per-intent.

```python
class TradingApplication:
    def __init__(
        self,
        *,
        environment: Environment,
        broker: "BrokerPort",
        journal: "EventJournal",
        reconciler: "Reconciler",
        market_data: "MarketDataService",
        coordinator: "PortfolioCoordinator",
        risk: "RiskManager",
        kill_switch: "KillSwitch",
        oms: "OrderManagementService",
        strategies: list["Strategy"],
        live_gate: "LiveGate",
        intent_buffer: "IntentBuffer",
    ) -> None:
        self._environment = environment
        self._broker = broker
        self._journal = journal
        self._reconciler = reconciler
        self._market_data = market_data
        self._coordinator = coordinator
        self._risk = risk
        self._kill_switch = kill_switch
        self._oms = oms
        self._strategies = strategies
        self._live_gate = live_gate
        self._intent_buffer = intent_buffer
        self._state = SystemState.BOOTING

    async def start(self) -> None:
        try:
            self._state = SystemState.CONNECTING
            await self._broker.connect()

            # §10.6: a latched kill switch survives restarts and is checked
            # before anything can become ready.
            if await self._kill_switch.is_latched():
                await self._enter_halted("kill_switch_latched", cancel=False)
                return

            self._state = SystemState.RECONCILING
            report = await self._reconciler.run_full()
            if not report.safe_to_trade:
                await self._enter_halted("startup_reconciliation_failed")
                return

            await self._market_data.start()

            readiness = await self._verify_readiness()
            if not readiness.ok:
                await self._enter_halted(f"readiness:{readiness.first_failure}")
                return

            self._state = self._ready_state()
        except Exception as exc:
            # An unguarded failure must not leave the system in CONNECTING.
            await self._enter_halted("startup_exception", exc=exc)
            raise

    def _ready_state(self) -> SystemState:
        """One ready state per environment — §7.1, §16.1."""
        match self._environment:
            case Environment.LIVE:
                if not self._live_gate.is_live_authorized():
                    raise LiveGateNotSatisfied(self._live_gate.failed_gates())
                return SystemState.READY_LIVE
            case Environment.PAPER:
                return SystemState.READY_PAPER
            case _:
                return SystemState.READY_SIMULATION

    async def submit_intent(self, intent: TargetPositionIntent) -> None:
        """Called by strategies. Buffers only — never reaches the broker."""
        await self._journal.record_intent_created(intent)
        self._intent_buffer.add(intent)

    async def run_coordination_window(self) -> None:
        """Drain, net, then submit at most one change per contract — §9.1."""
        intents = self._intent_buffer.drain()
        if not intents:
            return

        if not self._state.allows_new_orders:
            for intent in intents:
                await self._journal.record_intent_rejected(
                    intent, reason="system_not_ready"
                )
            return

        # Netting happens across the whole batch. Handling intents one at a
        # time re-creates the accidental-netting problem the coordinator exists
        # to prevent, and over-orders when two strategies update together.
        for proposal in await self._coordinator.net(intents):
            decision = await self._risk.evaluate(proposal)
            if not decision.approved:
                await self._journal.record_risk_rejection(decision)
                continue
            await self._oms.execute(decision.approved_plan)

    async def _enter_halted(
        self,
        reason: str,
        *,
        cancel: bool = True,
        exc: BaseException | None = None,
    ) -> None:
        self._state = SystemState.HALTED
        await self._journal.record_halt(reason, exc)
        await self._risk.latch_global_kill_switch(reason)
        if cancel:
            await self._oms.cancel_risk_increasing_orders()
```

The real implementation additionally needs transactional behavior, cancellation
races, callback handling, persistence, observability, and the recovery paths
described elsewhere in this document.

---

## 26. External documentation

Review the current official documentation before changing broker integration.
IBKR behavior, supported versions, message limits, and API fields change, and
several details in this document — message codes, pacing limits, market-data line
allowances — are exactly the kind that go stale. Verify rather than trust.

**Interactive Brokers**

- TWS API documentation: <https://www.interactivebrokers.com/campus/ibkr-api-page/twsapi-doc/>
- TWS API introduction: <https://www.interactivebrokers.com/docs/tws-api/doc/introduction>
- IB Gateway architecture and restart behavior: <https://www.interactivebrokers.com/docs/tws-api/doc/architecture/the-trader-workstation/the-ib-gateway>
- API configuration and read-only mode: <https://www.interactivebrokers.com/campus/trading-lessons/installing-configuring-tws-for-the-api/>
- System connectivity message codes: <https://www.interactivebrokers.com/docs/tws-api/ref/system-message-codes>
- Order submission: <https://www.interactivebrokers.com/docs/tws-api/doc/orders/place-order/introduction>
- Order modification: <https://www.interactivebrokers.com/docs/tws-api/doc/orders/modifying-orders>
- Execution fields: <https://www.interactivebrokers.com/docs/tws-api/ref/execution-class-reference/introduction>
- Account updates: <https://www.interactivebrokers.com/docs/tws-api/doc/account-portfolio-data/account-updates/receiving-account-updates>
- Paper-trading limitations: <https://www.interactivebrokers.com/campus/glossary-terms/paper-trading-account/>
- TWS API changelog: <https://www.interactivebrokers.com/docs/tws-api/changelog>

Also confirm, against current documentation rather than this file: market-data
line allowances and how they scale with the account; `reqMarketRule` and the
price-increment tables; `whatIf` order behavior and its supported fields;
`reqGlobalCancel` semantics; and tick-by-tick data limits and permissions.

**Security**

- NIST Secure Software Development Framework, SP 800-218: <https://csrc.nist.gov/pubs/sp/800/218/final>

---

## 28. Revision notes

Changes in this revision, against the previous single-file `AGENT.md`. Recorded
so that reviewers can check the reasoning rather than re-derive it.

**Split.** The specification was one 2,374-line file loaded into every agent
session. The binding rules, commands, topology, prohibited shortcuts, and
acceptance criteria now live in `AGENT.md`; the reference detail moved here.
Section numbers are unchanged so existing references still resolve.

**Corrections**

| §    | Was                                                                 | Now                                                                                                  |
| ---- | ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| 7.2  | `FILLED` reachable only via `PARTIALLY_FILLED`; `UNKNOWN` terminal; no `EXPIRED` | Direct paths to `FILLED`, including before acknowledgement; `UNKNOWN` explicitly non-terminal with a resolution deadline; `EXPIRED` added for `DAY` orders |
| 11.4 | `price / tick` under the ambient decimal context; rejected `price <= 0`; exponent not normalised | Pinned `localcontext()` with `InvalidOperation` trapped; exact `divmod` with floor normalisation; negative prices supported; `.quantize(tick)`; tiered price increments via market rules |
| 9.1  | Formula with unstated sign convention, then disclaimed as incomplete | Normative sign convention, a table of which order states count and at what quantity, the canonical function, and the batching requirement |
| 6.5  | `max_slippage`, `side: str`, `time_in_force: str`                   | `max_slippage_bps`, `Side`, `TimeInForce`, explicit currencies — the document now obeys its own rule 14 and §20.1 |
| 7.1  | Two ready states against four environments                          | One ready state per environment, plus `DRAINING` and `STOPPED`                                        |
| 25   | Sketch skipped the kill-switch check, left state stuck on failure, and processed intents one at a time | Kill switch checked before ready; failures reach `HALTED`; coordination batched                        |
| 5, 8.2 | "master clientId = 0"                                             | Master API client ID described as the Gateway setting it is, with the Gateway-vs-TWS difference noted   |

**Additions**

- §6.1 — market rules for tiered tick sizes; contract re-qualification; corporate
  actions changing `conId`.
- §8.7 — trading halts, LULD pauses, auctions, and futures rolls.
- §8.8 — the error mapping as a reviewable table, with the caveat that it must be
  verified against current IBKR documentation.
- §8.9 — market-data line budget as a distinct constraint from request pacing.
- §8.10 — what each subscription mode actually delivers; `reqMktData` is sampled,
  not tick-by-tick, which bounds any latency claim.
- §10.3 — `whatIf` for margin pre-checks.
- §10.6 — `reqGlobalCancel` for the emergency path; halts as a trigger.
- §10.7 — currency and FX exposure; implicit FX borrowing on non-base trades.
- §11.1 — commissions lag fills; provisional P&L must be flagged.
- §12.4 — pinned application decimal context; currency companions on monetary
  columns; a test that the driver returns `Decimal`.
- §12.5 — event schema evolution and upcasters, without which deterministic
  replay does not survive the first schema change.
- §13 — an explicit queue drop policy.
- §14.1 — a disabled strategy's target is retained, not silently dropped.
- §18.1 — architecture tests for import boundaries and unit discipline.
- §22.7 — total host loss with open positions, the gap the single-host topology
  creates.
- `AGENT.md` §3 — a command reference, previously absent.
- `AGENT.md` rules 16–18 — do not weaken a control to pass; do not rely on the
  ambient decimal context; do not state an amount without its currency.

**Still open**

- The §8.8 code table needs verification against the current IBKR message-code
  reference before Phase 1. Treat it as a draft.
- Options, multi-leg, and short selling remain out of scope and are not specified
  here; each needs its own contract, margin, assignment, borrow, and exercise
  sections before being enabled.
- Per-strategy performance attribution under netting is defined operationally
  (§9.2) but has no stated reporting format.
