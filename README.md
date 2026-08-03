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

## Setup

Python 3.12 or later and uv are required.

```shell
uv sync --frozen
uv run pre-commit install
```

Run the safe bootstrap from PowerShell:

```powershell
$env:TRADING_ENV = "simulation"
uv run trading-cli --environment-config config/simulation.example.yaml
```

The result reports READY_SIMULATION and explicitly reports that broker
connectivity is false. There is intentionally no command for live startup.

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

The binding contributor rules are in AGENT.md. The complete design is in
docs/architecture.md, and the current security analysis is in
docs/threat-model.md.
