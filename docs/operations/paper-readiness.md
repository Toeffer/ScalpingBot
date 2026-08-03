# Paper-trading readiness

**Status:** Gap analysis — what stands between this revision and a paper-trading run<br>
**Last reviewed:** 2026-08-03<br>
**Architecture references:** §18.5, §21 (Phases 1–3, 5–6), §22<br>
**Audience:** Anyone about to ask "can we point this at a paper account yet?"

---

## 1. The short answer

No. This revision cannot connect to a broker, and paper startup is refused in
code, not by configuration.

That refusal is one line — `assert_environment_start_allowed` in
`src/trading_system/security/live_gate.py` — and it would be trivial to delete.
Deleting it would not produce a paper-trading system. It would produce a
process that reports `ready_paper` while having no broker adapter, no order
path, no reconciliation, no risk manager, and no journal. Removing the refusal
without building what the refusal stands in for is the single most damaging
change anyone could make to this repository, and AGENT.md rule 16 prohibits it.

This document exists so that the question is answered by a list of missing
components rather than by whoever is most impatient.

## 2. What "ready for paper" actually means

Architecture §18.5 defines paper trading as validating connectivity, contract
definitions, callback handling, order lifecycle, reconciliation, operational
runbooks, alerts, Gateway restarts, and multi-strategy coordination. Every item
on that list needs a component that does not exist yet.

Note also what §18.5 says paper trading does *not* validate: queue position,
market impact, deep-book execution, and live order behavior. Paper fills come
from a simulator, not a market. A clean paper run is evidence that the control
system works. It is not evidence that the strategy makes money, and AGENT.md §1
forbids describing it as such.

## 3. Phase position

Architecture §21 defines eight phases. This revision completes Phase 0.

| Phase | Delivers | State |
| --- | --- | --- |
| 0 | Repository and security baseline | **Complete** — every §21 exit criterion has a passing test |
| 1 | Read-only IBKR observer | Not started |
| 2 | Reconciliation engine | Not started |
| 3 | Paper OMS | Not started |
| 4 | Central risk manager | Not started |
| 5 | One strategy in paper | Not started |
| 6 | Two strategies in paper | Not started |
| 7 | Small live pilot | Not started |

Phase 3 is the earliest point at which any order reaches a paper account.
Phase 5 is the earliest point at which a *strategy* trades in paper, which is
what "paper trading tests" usually means. Phase 6 is where the multi-strategy
netting that motivates this architecture (AGENT.md §5) is first exercised.

Phase 4 sits between them for a reason worth stating plainly: Phase 3 delivers
the ability to send orders and Phase 4 delivers the ability to refuse them. The
ordering means a Phase-3 paper OMS must not be run unattended against anything,
and the temptation to skip Phase 4 because "it is only paper" is exactly the
habit that later loses money on a live account.

## 4. Missing components

Measured against the repository structure in architecture §19.

### Source packages that do not exist

| Path | Purpose | Needed by |
| --- | --- | --- |
| `brokers/ibkr/` | Adapter, client, callbacks, contracts, market rules, error table, pacing, subscriptions, reconciliation | Phase 1 |
| `market_data/` | Normalization and freshness enforcement | Phase 1 |
| `persistence/` | Database, event journal, upcasters, repositories, projections | Phase 1 |
| `calendar/` | Sessions, halts, futures rolls | Phase 2 |
| `oms/` | Service, state machine, tick-size pricing, idempotency | Phase 3 |
| `portfolio/` | Coordinator (batching and netting), allocator | Phase 5 |
| `strategies/` | Base interface, registry, strategy modules | Phase 5 |

### Domain model

`src/trading_system/domain/` currently contains only `SystemState`. Architecture
§19 also requires `instruments`, `intents`, `orders`, `executions`, `positions`,
`money`, `risk`, and `events`. `money.py` matters most and is missing entirely:
AGENT.md rule 18 requires that every amount carry its currency, and today no
type enforces that. The risk configuration declares `base_currency` and an
`enabled_trading_currencies` allowlist, and a validator restricts the allowlist
to the base currency alone precisely because the §10.7 currency model does not
exist yet.

### Risk management

`src/trading_system/risk/` contains `kill_switch.py` and nothing else. Every
limit in `config/defaults.yaml` — gross and net notional, daily loss, intraday
drawdown, open orders, orders per minute, excess liquidity, per-instrument,
per-order, spread, quote age, clock skew — is **validated but not enforced**.
Nothing reads them at runtime because nothing produces an order to check them
against.

This is worth restating because a configured limit reads like a working control:
the numbers in `config/defaults.yaml` protect nothing today. They are schema
under test, not risk under management.

### Operations and deployment

Missing: `operations/health.py`, `operations/metrics.py`, `operations/alerts.py`
(§17), and `security/authorization.py` (§15.9). No `migrations/`. No
`deploy/systemd/`, `deploy/container/`, or `deploy/firewall/` (§16).

### Test tiers

`tests/unit`, `tests/security`, and `tests/architecture` exist. `tests/replay`,
`tests/integration`, and `tests/fixtures/events` do not. Deterministic replay
(§18.3) is the tier that makes reconciliation and allocation auditable, and it
must exist before it is needed, not after.

## 5. Controls that must change before paper

These are Phase-0 designs that are adequate for a broker-free process and
explicitly inadequate for one that can trade.

**Kill-switch authority.** The latch is a JSON file guarded by an in-process
lock (`FileKillSwitchStore`). It survives restarts, which is what Phase 0
needs. It provides no multi-process locking and no remote durability, so two
processes sharing a state file can lose a latch to a lost update. The threat
model (§5) already states the requirement: before paper execution, latch
authority moves to transactional storage while startup continues to fail closed
when that storage is unavailable.

**No operator authentication.** `trading-cli halt` accepts any `--actor` string.
That is honest for Phase 0 — the value is an audit label, not an identity — and
it is why there is deliberately no `clear` subcommand (see
`deploy/runbooks/kill-switch.md` §6). Paper operation needs real authorization
before any command can clear a latch or change a limit (§15.9).

**Broker error table is a draft.** Architecture §28 flags the §8.8 message-code
table as unverified against current IBKR documentation. Verify it against the
live reference before Phase 1 depends on it — misclassifying an error as
retryable is how duplicate exposure gets created. The checklist is in §6.1
below; it has not been run, because the environments this repository has been
worked in so far could not reach the IBKR documentation hosts.

**Kill-switch history has no reader.** `status` prints active latches only.
Audit inspection requires reading `store.snapshot().history` in Python. An
operator working an incident should not have to write code to see what happened.

## 6. Ordered path to a paper run

1. **Verify the §8.8 error table** against current IBKR documentation. Cheap,
   and everything downstream depends on classifying broker errors correctly.
2. **Move persistence in** (§12). PostgreSQL, migrations with tested downgrades,
   the event journal, and the `Decimal` round-trip test §12.4 requires. Move
   kill-switch authority here.
3. **Phase 1 — read-only observer** (§21). Gateway connection under
   `brokers/ibkr/`, account allowlist, base-currency assertion, contract
   qualification, subscriptions under a line budget, and the connection/error
   mapping. Read-only mode stays on at the Gateway.
4. **Phase 2 — reconciliation** (§21). Mandatory at startup and after every
   reconnect, with instrument-level halt on an unexplained position.
5. **Phase 3 — paper OMS** (§21). The full §7.2 order state machine, idempotent
   submission, `UNKNOWN` resolution with deadlines, pacing. Crash-injection
   tests at each §11.2 step before any order is sent.
6. **Phase 4 — risk manager** (§21). Make the limits in §4 above real. A
   risk-service failure must reject, never pass through.
7. **Write and exercise the §22 runbooks** as the components they describe
   arrive. Tracked in `deploy/runbooks/README.md`.
8. **Phase 5, then 6** (§21). One strategy in paper, then two, with the
   coordinator netting opposing targets into one broker target.

Do not reorder 3 before 2, or 5 before 4.

### 6.1 Verifying the §8.8 error table

Step 1 above is the cheapest item on this list and blocks the most. It needs
nothing but a browser and an hour, and it has **not been done**.

Sources, all listed in architecture §26:

- System connectivity message codes:
  <https://www.interactivebrokers.com/docs/tws-api/ref/system-message-codes>
- The consolidated message-code reference:
  <https://interactivebrokers.github.io/tws-api/message_codes.html>
- The TWS API changelog, for codes added or changed since:
  <https://www.interactivebrokers.com/docs/tws-api/changelog>

For each of the 23 codes in the §8.8 table — 100, 103, 104, 105, 106, 200, 201,
202, 321, 354, 420, 512, 1100, 1101, 1102, 2103, 2104, 2105, 2106, 2157, 2158,
10089, 10197 — confirm three things:

1. **The code still exists** and its official description still matches the
   behavior the table's Action column assumes.
2. **The category is right**, with particular attention to anything the table
   treats as recoverable. An error wrongly classified as `TRANSIENT` or
   `PACING` invites a retry, and a retried `placeOrder` is how duplicate
   exposure is created (AGENT.md rule 5).
3. **Nothing new belongs in the table.** Codes added since the table was
   written currently fall through to `UNKNOWN`. That is the safe default and
   not a bug — but a frequently-seen `UNKNOWN` is a gap, not a mystery.

Two known traps to check rather than assume:

- 2157/2158 (sec-def data farm) were added in a later Gateway build than the
  other 21xx codes, and arrive with a farm-name suffix — `2157` is not the
  whole message. Match on the code, never on the text.
- 202 means the order was cancelled, but the table already warns that the
  confirmation must come from `orderStatus`, not from the message text. Verify
  that this is still true before Phase 3 relies on it.

Record the result as an ADR under `docs/decisions/`: the date checked, the
documentation revision, every correction made, and every code confirmed
unchanged. "We checked and it was fine" is only useful if a later reader can
tell *when* fine was, and against what.

## 7. Before the first paper session

Independent of code, confirm:

- A dedicated paper account, and a paper Gateway that is **not** logged into a
  live account. Check the account number, not the window title.
- The account allowlist names the paper account, and a wrong account halts.
- The Gateway API is bound to loopback or an approved private network, never
  `0.0.0.0` (AGENT.md §7).
- Database backup and restore have been tested by restoring, not by configuring.
- Alerts have been fired and answered, not merely configured (§22.1 step 11).
- A Gateway restart during an open working order has been exercised (§8.7).
- Paper-trading limitations are recorded where a reader could otherwise mistake
  a paper fill for evidence of execution quality (§18.5, AGENT.md §4).

## 8. Review trigger

Update this document whenever a phase completes, whenever a control in §5
changes, and before any decision to begin paper trading. If it disagrees with
`docs/architecture.md` §21, the architecture document wins and this one is
stale.
