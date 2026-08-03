# Changelog

Notable changes to this repository. Entries are grouped by implementation phase
(`docs/architecture.md` §21) rather than by semantic version, because the
version number is not meaningful until something is deployed.

Detailed reasoning for a change belongs in an ADR under `docs/decisions/`, and
the rationale for the current specification revision is in
`docs/architecture.md` §28. This file records *what* changed and when.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

- Structured log records now go to **stderr**; a command's result stays on
  stdout. `trading-cli start` previously wrote a log line and its result to the
  same stream, so `trading-cli start | jq -r .state` could read the log record
  as the answer. `logging.destination` changes from `stdout` to `stderr`
  accordingly, and the checked-in schema is regenerated. Under `systemd`
  (§16.3) both streams reach the journal, so the daemon case is unaffected.

### Added

- `trading-cli status --history` reports the append-only kill-switch audit
  trail — `action`, `actor`, `reason`, `scope`, `target_id`, `record_id`, and
  `occurred_at` per entry, newest last. Bounded by `--history-limit`
  (default 20) and reported with `total`, `shown`, and `truncated` so a slice
  is never mistaken for the complete record. Read-only; there is still no
  command that clears a latch. Previously the audit history could only be read
  by writing Python against `store.snapshot().history`, which is not something
  to ask of an operator working an incident.
- `docs/operations/paper-readiness.md` §6.1 — an executable checklist for
  verifying the §8.8 broker error-code table: the three official sources, the
  23 codes to confirm, what to check for each, two known traps, and a
  requirement to record the result as an ADR. The check itself is still
  outstanding; the environments this repository has been worked in could not
  reach the IBKR documentation hosts.

- `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, and
  `.github/PULL_REQUEST_TEMPLATE.md`.
- `docs/operations/paper-readiness.md` — the gap analysis between this revision
  and a paper-trading run, with an ordered path and the controls that must
  change first.
- `docs/decisions/README.md` — ADR index, template, and conventions.
- `tests/architecture/test_documented_commands.py` — every documented
  `uv run trading-cli` invocation is parsed against the real command-line
  interface, every subcommand must appear in AGENT.md §3.1, and the documented
  run scripts must be executable.
- `README.md` — "Where it runs" and "Running it": platform support, per-
  environment startup behavior, and exit codes.
- `deploy/runbooks/README.md` — full index of the §22 runbooks with the phase
  each one is blocked on, and how to record a rehearsal.

### Fixed

- `scripts/run_simulation.sh` and `scripts/run_paper.sh` were committed
  non-executable, so the documented `./scripts/run_simulation.sh` failed with
  "Permission denied".
- AGENT.md §3 documented `trading-cli halt --scope global --reason "<text>"`,
  which the interface rejects: `--actor` is required. The documented form of the
  most incident-critical command in the repository did not run.
- AGENT.md §3 listed commands from later phases (`alembic`, `scripts/
  reconcile.py`, `scripts/backup_verify.py`, `tests/replay`,
  `tests/integration`) alongside working ones with no distinction. Split into
  §3.1 "Available now" and §3.2 "Reserved for a later phase", and the omitted
  security gates (`bandit`, `detect-secrets`, `verify_secret_scan.py`,
  `generate_config_schema.py --check`) were added to §3.1 to match CI.
- `tests/architecture/` confined broker imports to `src/trading_system/broker/`
  while `docs/architecture.md` §19 prescribes `brokers/ibkr/`. Aligned on the
  architecture document's path, so Phase-1 code written against §19 is not
  reported as a boundary violation.

## Phase 0 — Repository and security baseline

Delivered: typed project skeleton; exactly pinned dependencies with a licence
policy; CI quality and security gates; secret scanning with a self-test;
layered YAML configuration with unknown-key rejection and a checked-in JSON
schema; explicit local, simulation, paper, and live environments;
unconditional live denial; structured JSON logging with recursive redaction; an
atomic file-backed kill switch that survives restarts with no automatic reset;
a pinned decimal context with traps; a threat model; and a release verifier.

No broker connectivity, order path, strategy, or execution surface —
deliberately, per ADR 0001.
