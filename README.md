# ScalpingBot trading-system foundation

This repository currently implements Phase 0 of the architecture: a typed,
security-first Python foundation for a future multi-strategy IBKR trading
system. It deliberately contains no broker client, order API, strategy, or
execution path.

The safe default is simulation. Paper and live startup are both rejected in
code during Phase 0, including when the live configuration flag is true. This
is a control-system foundation, not a claim of profitability or production
readiness.

## What Phase 0 provides

- Strict layered YAML configuration with unknown-key rejection and a checked-in
  JSON schema.
- Explicit local, simulation, paper, and live environment profiles.
- An unconditional Phase-0 live gate and a structural test forbidding IBKR
  dependencies.
- Pinned decimal context with traps for invalid operations, division by zero,
  overflow, and float conversion.
- Structured JSON logs with recursive key and value redaction.
- An atomic file-backed kill-switch latch that survives process restarts and
  has no automatic reset path.
- Locked dependencies, pre-commit checks, CI quality gates, dependency audit,
  static security analysis, and a secret-scanner self-test.
- A Phase-0 threat model and release verifier.

## Where it runs

Phase 0 runs anywhere Python 3.12 or later and `uv` run: Linux, macOS, and
Windows. Nothing else is required — there is no broker connection, no IB
Gateway, no database, no network listener, and no outbound network call at
runtime. The process reads two YAML files, writes one JSON state file under
the configured `state_directory`, and logs to stdout.

That list is the point rather than an omission: everything Phase 0 does can be
run and verified on a laptop, offline. A future phase that needs IB Gateway,
PostgreSQL, and a hardened host is described in `docs/architecture.md` §16, and
the gap between here and there is tracked in
[`docs/operations/paper-readiness.md`](docs/operations/paper-readiness.md).

Windows note: the repository ships `AGENT.md`, `AGENTS.md`, and `CLAUDE.md` as
byte-identical copies rather than symlinks, because a checkout with
`core.symlinks=false` turns a committed symlink into a plain text file and
silently drops the contract. `scripts/verify_release.py` fails the build if the
three ever diverge. Edit `AGENT.md` and mirror it to both.

## Setup

```shell
uv sync --frozen
uv run pre-commit install
```

`uv sync --frozen` installs exactly what `uv.lock` pins and will fetch a
Python 3.12 toolchain if the host does not have one.

## Running it

Everything runs from the repository root. `TRADING_ENV` selects the
environment and must match the `environment:` key of the config file passed to
`--environment-config`; a mismatch is rejected rather than reconciled.

```shell
# bash / zsh
TRADING_ENV=simulation uv run trading-cli start \
  --environment-config config/simulation.example.yaml

# or the wrapper, which sets TRADING_ENV for you
./scripts/run_simulation.sh
```

```powershell
# PowerShell
$env:TRADING_ENV = "simulation"
uv run trading-cli start --environment-config config/simulation.example.yaml
```

The result reports `ready_simulation` and explicitly reports that broker
connectivity is false. There is intentionally no command for live startup.

`--environment-config` may be omitted, in which case it defaults to
`config/<TRADING_ENV>.example.yaml`. Pass it explicitly during an incident so
the target environment is never inferred from an environment variable alone.

### What each environment does today

| `TRADING_ENV` | `start` result | Why |
| --- | --- | --- |
| `simulation` | `ready_simulation`, exit 0 | The safe default; no broker path exists to use |
| `local` | `ready_simulation`, exit 0 | Same startup path as simulation |
| `paper` | denied, exit 2 | Phase 0 contains no broker connectivity |
| `live` | denied, exit 2 | Every §15.4 gate is reported unmet, including with `live_enabled: true` |

`./scripts/run_paper.sh` exists and is executable, and it exits non-zero by
design. It is a placeholder for the phase that introduces broker connectivity,
not a broken script.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | The command succeeded |
| 2 | Refused: a safety control, configuration validation, or argument check rejected the request |

A refusal prints a single redacted JSON object with `status`, `error_type`, and
`message`. Startup failures additionally emit a `CRITICAL` structured log
record. Both go to stdout; if you are piping the output, parse it line by line
rather than as one document.

## Operator commands

`status` is read-only: it bootstraps configuration, logging, and the
kill-switch store, then reports environment and kill-switch state without
starting the application. It works even when `start` would be denied, which is
exactly when status is needed most.

```powershell
uv run trading-cli status --environment-config config/simulation.example.yaml
```

`halt` durably latches a kill switch so a subsequent `start` is refused until
an operator investigates:

```powershell
uv run trading-cli halt --scope global --reason "<text>" --actor "<who>"
```

There is deliberately no CLI command to clear a latch in Phase 0: Phase 0 has
no operator authentication, so clearing a latch must stay a deliberate
out-of-band action. That out-of-band procedure is documented in
[`deploy/runbooks/kill-switch.md`](deploy/runbooks/kill-switch.md).

## Configuration

Configuration is built by recursively overlaying one environment profile on
config/defaults.yaml. The merged document is validated once against frozen
Pydantic models that reject every unknown key. Financial values must be quoted
decimal strings. TRADING_ENV must exactly match the profile's environment.

The files under config are examples and contain no credentials. Secrets must
come from an operating-system key store or managed secret manager in a later
phase; .env files, private keys, database dumps, and captures are ignored and
must never be committed.

Regenerate the checked-in schema after an intentional model change:

```shell
uv run python scripts/generate_config_schema.py
uv run python scripts/generate_config_schema.py --check
```

## Quality and security gates

Run the same gates used in CI:

```shell
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict src
uv run pytest
uv run bandit -c pyproject.toml -r src scripts
uv run pip-audit --skip-editable
uv run python scripts/verify_secret_scan.py
uv run python scripts/verify_release.py
```

## Documentation map

| Document | What it answers |
| --- | --- |
| [`AGENT.md`](AGENT.md) | The binding contract. Rules, commands, topology, prohibited shortcuts, definition of done. Mirrored byte-for-byte to `AGENTS.md` and `CLAUDE.md` |
| [`docs/architecture.md`](docs/architecture.md) | The complete design, §6–§28. §6 in AGENT.md routes you to the section to read before a given change |
| [`docs/threat-model.md`](docs/threat-model.md) | Security objective, trust boundaries, and the residual risk left by each control |
| [`docs/operations/paper-readiness.md`](docs/operations/paper-readiness.md) | What stands between this revision and a paper-trading run, and in what order |
| [`docs/decisions/`](docs/decisions/README.md) | Architecture decision records — why things are the way they are |
| [`deploy/runbooks/`](deploy/runbooks/README.md) | Operational procedures, and which §22 runbooks are still missing |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Environment, gates, review expectations, how to change the contract |
| [`SECURITY.md`](SECURITY.md) | How to report a vulnerability privately, and what is in scope |
| [`CHANGELOG.md`](CHANGELOG.md) | What changed, by phase |

## Status

Phase 0 of eight (`docs/architecture.md` §21) is complete. Phase 1 — a
read-only IBKR observer — has not started. Paper trading is reached at Phase 3
at the earliest, and a strategy trading in paper at Phase 5.

Nothing here is production-ready, and no output of this repository may be
described as a guarantee of profit.
