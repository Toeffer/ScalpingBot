# AGENT.md — Multi-Strategy IBKR Trading System

**Status:** Binding operating contract for this repository<br>
**Target stack:** Python 3.12+, official Interactive Brokers TWS API, IB Gateway, PostgreSQL 15+<br>
**Operating model:** Multiple strategy modules, one portfolio coordinator, one central risk manager, one order-management service, one broker connection<br>
**Full specification:** `docs/architecture.md`<br>
**Last reviewed:** 2026-08-03<br>
**Review cadence:** every release, and after every incident<br>
**Audience:** Human developers and coding agents working in this repository

---

## 0. How to use this file

This file is the part of the specification that must be in context for **every**
change to this repository. It is deliberately short so that it survives context
truncation intact. The rules in section 2 and the shortcuts in section 7 are the
ones that matter most under incident conditions, so they are here rather than in
a document that may get trimmed.

Everything else — domain model, state machines, IBKR integration detail, risk
layers, persistence, testing, deployment, runbooks — lives in
`docs/architecture.md`, which keeps the section numbering used throughout this
repository. Read the relevant section **before** changing the corresponding
code. Section 6 below is the routing table.

If your agent harness looks for `AGENTS.md` or `CLAUDE.md` rather than
`AGENT.md`, symlink it where the platform supports it. Do not copy it:

```bash
ln -s AGENT.md AGENTS.md
ln -s AGENT.md CLAUDE.md
```

Windows checkouts with `core.symlinks=false` cannot use symlinks: a committed
symlink checks out as a plain text file, and the contract silently disappears
from agent context. On those platforms the three files are byte-identical copies
instead, and their identity is enforced by `scripts/verify_release.py`, which
fails the build on any divergence. Never edit `AGENTS.md` or `CLAUDE.md`
directly — edit `AGENT.md` and mirror the change to both.

Duplicated safety rules drift apart, and a stale safety rule is worse than no
safety rule.

---

## 1. Purpose

This repository implements an automated trading system that runs multiple
strategies against one Interactive Brokers account without allowing the
strategies to interfere with one another.

Capital protection, deterministic behavior, accurate reconciliation, and
recoverability rank above trading frequency and raw throughput. A strategy may
propose trades. It may never bypass the central risk manager or communicate
directly with the broker.

The intended initial use is ordinary systematic trading with holding periods
from seconds to days. The architecture can support a shorter-horizon strategy
later, but this is not an exchange-colocated high-frequency trading system and
must not be described as one. Note in particular that IBKR's standard top-of-book
market data is sampled, not a complete tick stream (see §8.10), which bounds what
any latency-sensitive claim can honestly assert.

No code, backtest, optimization result, or paper-trading result may be described
as a guarantee of profit. Profitability is an empirical property that must be
validated after fees, spreads, slippage, latency, market impact, taxes, borrow
costs, financing costs, currency conversion, rejected orders, partial fills, and
operational failures.

---

## 2. Binding instructions for every contributor and coding agent

These rules apply to all repository changes. They are not defaults to be
weighed against convenience.

1. **Never send a live order by default.**
   The default environment is `simulation`. Paper trading must be explicitly
   selected. Live trading requires the separate multi-gate enablement in §15.4.

2. **Never let a strategy call the IBKR API directly.**
   Strategies emit intents. Only the execution service may construct, submit,
   modify, or cancel broker orders.

3. **Never place an order before reconciliation is complete.**
   Startup and reconnect procedures must first reconcile broker positions, open
   orders, recent executions, account values, and locally persisted state.

4. **Never infer an absent broker acknowledgement.**
   A network timeout does not prove an order was rejected. An order with an
   uncertain outcome enters `UNKNOWN`, reserves its worst-case exposure, and is
   reconciled before any replacement is considered.

5. **Never retry `placeOrder` blindly.**
   Retrying can create duplicate exposure. Retry only after matching by local
   command ID, `orderRef`, IBKR order ID, permanent ID, open-order callbacks,
   and execution callbacks.

6. **Never log credentials, session tokens, account numbers, full order payloads
   containing sensitive identifiers, or personally identifying data.**
   Logs use redacted or hashed identifiers.

7. **Never store secrets in source control.**
   `.env`, private keys, credentials, account IDs, production hostnames, and
   notification tokens stay outside Git.

8. **Never bypass a failed risk check.**
   A risk-service error is a rejection, not permission to continue.

9. **Never automatically re-enable trading after a critical fault.**
   A kill switch stays latched until an authorized operator investigates and
   explicitly resets it.

10. **Never modify production database state manually during a live session.**
    Use audited administrative commands with validation and dry-run support.

11. **Never add a dependency without reviewing its provenance, license,
    maintenance state, and security implications.**
    Pin production dependencies and update them through reviewed pull requests.

12. **Never commit generated API logs, market-data captures, database dumps, or
    broker statements.**
    These files may contain account details and trading history.

13. **Prefer small, auditable changes.**
    Trading code must be understandable under incident conditions. Avoid clever
    abstractions that obscure order lifecycle or risk decisions.

14. **All financial quantities use explicit units and decimal-safe types.**
    Never use binary floating point for money, quantity, price rounding, fees,
    or realized profit and loss. Every limit, threshold, and monetary field
    carries its unit in the name or the type: `_bps`, `_ms`, or an explicit
    currency. A bare `max_slippage` is not acceptable; `max_slippage_bps` is.

15. **All timestamps are timezone-aware and stored in UTC.**
    Preserve both the broker-provided timestamp and the local receive timestamp.
    Use monotonic clocks for durations and UTC wall clocks for audit records.

16. **Never weaken a control to make a task pass.**
    If a risk check, live gate, type check, or test blocks the change you were
    asked to make, stop and report it. Do not raise a limit, relax a gate, mark
    a test `xfail`, add a `# type: ignore`, or broaden an exception handler to
    get to green. This rule exists because the most likely way this system loses
    money is an automated contributor removing the thing that was protecting it.

17. **Never rely on the ambient `decimal` context.**
    Financial arithmetic pins its own `localcontext()` and traps
    `InvalidOperation` and `DivisionByZero`. A silently mis-rounded price is
    worse than a raised exception. See §11.4.

18. **Never express an amount without its currency.**
    The account has a base currency; instruments may not trade in it. Limits,
    P&L, notionals, and buying-power checks state the currency and the
    conversion rate used. See §10.7.

---

## 3. Commands

Everything below runs from the repository root. Dependency management is `uv`.

This section is split into what works **in the current phase** and what the
architecture reserves for **a later phase**. Both halves are listed because the
command names are part of the contract, but only the first half is executable
today. A command in the second half fails with "no such file" or "no such
command" — that is the expected result, not a broken checkout. Every command in
the first half is covered by `tests/architecture/test_documented_commands.py`,
which fails the build if this section drifts from the real interface.

### 3.1 Available now

```bash
# --- setup -----------------------------------------------------------------
uv sync --frozen                    # install exactly what uv.lock pins
uv lock --upgrade-package <name>    # the only sanctioned way to move a version
uv run pre-commit install           # secret scanning + formatting on commit

# --- quality gates (all must pass before merge) ----------------------------
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict src
uv run pytest
uv run bandit -c pyproject.toml -r src scripts
uv run pip-audit --skip-editable
uv run pre-commit run detect-secrets --all-files
uv run python scripts/verify_secret_scan.py         # scanner rejects a probe
uv run python scripts/generate_config_schema.py --check
uv run python scripts/verify_release.py   # config schema, licences, mirrors

# --- tests by tier ---------------------------------------------------------
uv run pytest tests/unit                  # fast, no I/O, no broker
uv run pytest tests/security              # redaction, gates, authorization
uv run pytest tests/architecture          # import boundaries, contract mirrors
uv run pytest --lf -x                     # last failures, stop on first

# --- running the system ----------------------------------------------------
./scripts/run_simulation.sh               # no broker connection at all
uv run trading-cli status  --environment-config config/simulation.example.yaml
uv run trading-cli start   --environment-config config/simulation.example.yaml
uv run trading-cli status --history        # who latched what, when, and why
uv run trading-cli halt --scope global --reason "<text>" --actor "<who>"
```

`--actor` is required on `halt`: an unattributed latch is not an audit record.
`--environment-config` may be omitted, in which case it defaults to
`config/<TRADING_ENV>.example.yaml`; state it explicitly under incident
conditions so the target environment is never inferred.

`status --history` reads the append-only kill-switch audit trail, newest last,
bounded by `--history-limit` (default 20) and reporting `total`, `shown`, and
`truncated` so a slice is never mistaken for the whole record. It is read-only,
like the rest of `status`. There is still no command that clears a latch.

### 3.2 Reserved for a later phase — not executable today

```bash
./scripts/run_paper.sh                    # requires paper Gateway + paper DB
uv run pytest tests/replay                # deterministic end-to-end fixtures
uv run pytest tests/integration           # fake broker transport, real database
uv run python scripts/reconcile.py --dry-run
uv run alembic upgrade head
uv run alembic downgrade -1               # every migration needs a tested down
uv run python scripts/backup_verify.py    # restore into a scratch database
```

`scripts/run_paper.sh` exists and is executable, but paper startup is denied in
code until the phase that introduces broker connectivity. It exits non-zero by
design. See `docs/operations/paper-readiness.md` for what must land first.

CI runs the §3.1 quality-gate block plus secret scanning, static security
analysis, and a license policy check. Migration validation, the replay
regression suite, and a container scan join CI when the corresponding phase
introduces migrations, replay fixtures, and containers.

There is **no** command that starts live trading from a shell. Live enablement
is the multi-gate procedure in §15.4 and requires an operator token.

---

## 4. Explicit non-goals

The initial system shall not:

- Attempt exchange-colocated or microsecond high-frequency trading.
- Depend on paper-trading fills as proof of live execution quality.
- Run unreviewed self-modifying strategy code.
- Allow a language model to place trades, alter risk limits, clear a kill
  switch, or enable live mode at runtime.
- Scrape credentials, automate multifactor-authentication challenges, or bypass
  Interactive Brokers login and session controls.
- Trade every available asset class at launch.
- Support options, multi-leg combinations, short selling, or leveraged products
  until the corresponding contract, margin, assignment, borrow, and exercise
  risks have dedicated test coverage.
- Trade instruments denominated outside the account base currency until the
  currency model in §10.7 is implemented and tested.
- Use historical candles alone to claim that a short-horizon execution strategy
  is viable.
- Treat a process heartbeat as proof that market data or account state is
  current.
- Use multiple API connections to evade broker pacing restrictions.
- Compute tax lots, wash sales, or any tax reporting. Broker statements are the
  authority for tax purposes.
- Provide investment advice, or produce any output framed as such.

---

## 5. Operating topology

One broker-facing execution process. Strategies may run in that process
initially, but remain isolated behind interfaces.

```text
                             ┌─────────────────────┐
Market data ────────────────►│ Market Data Service │
                             └──────────┬──────────┘
                                        │ normalized, freshness-checked events
                   ┌────────────────────┼────────────────────┐
                   ▼                    ▼                    ▼
            ┌────────────┐       ┌────────────┐       ┌────────────┐
            │ Strategy A │       │ Strategy B │       │ Strategy N │
            └──────┬─────┘       └──────┬─────┘       └──────┬─────┘
                   │ intents            │ intents            │ intents
                   └────────────────────┼────────────────────┘
                                        ▼
                              ┌───────────────────┐
                              │ Portfolio         │  batches intents per
                              │ Coordinator       │  coordination window,
                              └─────────┬─────────┘  then nets per contract
                                        │ net target changes
                                        ▼
                              ┌───────────────────┐
                              │ Central Risk      │
                              │ Manager           │
                              └─────────┬─────────┘
                                        │ approved order plans
                                        ▼
                              ┌───────────────────┐
                              │ Order Management  │
                              │ System            │
                              └─────────┬─────────┘
                                        │ broker commands
                                        ▼
                              ┌───────────────────┐
                              │ IBKR Adapter      │
                              │ clientId = 1      │
                              └─────────┬─────────┘
                                        │
                                  IB Gateway
                                        │
                                  IBKR account

                    ┌────────────────────────────────────────┐
                    │ Persistent event journal + projections │
                    └────────────────────────────────────────┘

                    ┌────────────────────────────────────────┐
                    │ Independent operator / risk supervisor │
                    │ Optional read-only observer connection │
                    └────────────────────────────────────────┘
```

**Why one broker-facing process.** IBKR distinguishes API connections by client
ID, but the account still holds one position per contract. Two independent bots
therefore net against each other by accident:

```text
Strategy A virtual target: +100 XYZ
Strategy B virtual target:  -40 XYZ
Required broker target:      +60 XYZ
```

If Strategy B sends its own sell order it is not opening an isolated short. It
is reducing the account's long position. The portfolio coordinator must hold
both virtual targets and produce one account-level target.

One shared order-management service also centralizes order-ID allocation, rate
limiting, duplicate-command prevention, broker callbacks, reconciliation,
account-wide loss limits, emergency cancellation, maintenance handling, and
audit logging.

An optional second connection may be used by a supervisor to observe
account-wide orders and executions. It must not compete with the execution
client for order ownership. Note that "sees all orders account-wide" is a
property of the Gateway's configured **Master API client ID** setting, not of
`clientId=0` as such — see §8.2 before relying on it.

---

## 6. Where to read before you change something

| If you are changing…                                   | Read first                        |
| ------------------------------------------------------ | --------------------------------- |
| Contract identity, instrument metadata                 | `docs/architecture.md` §6.1       |
| Anything a strategy emits                              | §6.3, §14                         |
| Position accounting, virtual vs broker                 | §6.4, §9.2                        |
| Order lifecycle, any state transition                  | §7.2, §11                         |
| Connection, reconnect, or startup sequence             | §8.5, §8.6, §8.7                  |
| Order IDs, `orderRef`, client IDs                      | §8.2, §8.3, §8.4                  |
| Error handling for broker messages                     | §8.8                              |
| Rate limiting, pacing, subscription budgets            | §8.9, §8.10                       |
| Market-data validation or freshness                    | §8.10                             |
| Netting, aggregation, the `required_change` formula    | §9.1                              |
| Execution-to-strategy allocation                       | §9.2                              |
| Any risk check, limit, or kill switch                  | §10 (all)                         |
| Currency, FX exposure, base-currency conversion        | §10.7                             |
| Price construction, tick rounding                      | §11.4                             |
| Cancel/replace, timeouts, unknown orders               | §11.5, §11.6                      |
| Database schema, journal, projections                  | §12                               |
| Event schema changes or replay compatibility           | §12.5                             |
| Threading, queues, callback handling                   | §13                               |
| The strategy interface or its sandbox                  | §14                               |
| Anything security-relevant                             | §15 (all)                         |
| Live enablement                                        | §15.4                             |
| Deployment, systemd, containers, clocks                | §16                               |
| Metrics, alerts, health endpoints                      | §17                               |
| Tests — before adding or changing any                  | §18                               |
| Rollout sequencing                                     | §21                               |
| Incident response                                      | §22                               |

If the change does not map to a row above, it is probably larger than it looks.
Say so before starting.

---

## 7. Prohibited shortcuts

Do not write, approve, or merge a change that:

- Adds `LIVE=true` as the only live safeguard.
- Uses ticker symbols as unique contract keys.
- Uses floats for prices, quantities, or money.
- Relies on the ambient `decimal` context for price arithmetic.
- Replaces reconciliation with "trust the database."
- Retries orders after timeout without a broker lookup.
- Clears a kill switch automatically after restart.
- Lets a strategy call `placeOrder` or `cancelOrder`.
- Opens the Gateway socket to `0.0.0.0` without an approved private-network
  design.
- Stores the IBKR password in `.env`, in a command-line argument, or in any
  automated login mechanism.
- Uses production account data in test fixtures.
- Disables certificate verification.
- Swallows broker errors, or treats all broker errors as retryable.
- Uses an unbounded queue.
- Logs full API messages in normal production operation.
- Runs the service as root, or mounts the Docker socket.
- Lets an AI model alter live risk limits or execute operator commands.
- Enables a new asset class or currency without contract-specific and
  risk-specific tests.
- Raises a limit, skips a check, or disables a test in order to make a task
  complete.
- Claims profitability from a backtest or paper account alone.

---

## 8. Definition of done for production readiness

The system is not production-ready until all of these hold:

- No strategy holds broker credentials or broker API access.
- All orders pass through the central risk manager.
- Startup and reconnect reconciliation are mandatory and enforced in code.
- `UNKNOWN` orders are resolved by broker evidence, never by blind retry, and
  every `UNKNOWN` has a resolution deadline that escalates to an instrument halt.
- Duplicate and out-of-order callbacks are covered by tests.
- Broker positions equal explained virtual plus external allocations.
- The global kill switch is durable across restarts and has been exercised.
- Live mode requires multiple independent gates; no single flag suffices.
- The expected account is allowlisted and verified against the broker report.
- Market-data freshness is enforced, and the sampling characteristics of the
  subscribed data type are documented per strategy.
- Money and quantity use decimal-safe types with pinned contexts, and every
  amount carries a currency.
- Logs are redacted; secrets are outside source control.
- Dependencies are pinned, hash-verified where practical, and scanned.
- Database backups and restoration are tested, not merely configured.
- The Gateway API is not reachable from the public internet.
- Paper-trading limitations are documented where they could mislead.
- A documented manual fallback exists for total host loss while positions are
  open (§22.7).
- Small-live validation precedes any scaling, one dimension at a time.
- Runbooks exist and have been exercised, not just written.
- A human has reviewed every risk limit and every enabled order type.
- The system can explain every live order from signal through execution.

---

## 9. Final principle

A trading system is a financial control system, not a script that calls a broker
API.

The implementation is acceptable only when it can answer, reliably and from
durable evidence:

- Why was this order proposed?
- Which strategy requested it?
- Which market data and model version were used?
- Which risk limits were checked, and what were the inputs?
- What exactly was submitted?
- What did IBKR acknowledge?
- What filled, at what price, in what currency, with what commission?
- How was the execution allocated across strategies?
- What is the current broker position?
- What is each strategy's virtual position?
- What happens safely if any of those answers is unknown?

When evidence is incomplete, the correct default is to stop increasing risk,
reconcile, and require deliberate operator action.
