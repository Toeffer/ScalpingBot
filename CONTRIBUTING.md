# Contributing

This repository implements a financial control system. The contribution rules
are stricter than the code size suggests, and they are stricter on purpose.

**Read [`AGENT.md`](AGENT.md) before your first change.** It is the binding
contract for this repository — for human contributors and coding agents alike —
and it takes precedence over anything written here. This file covers mechanics:
environment, gates, review, and the shape of an acceptable change.

## Setup

Python 3.12 or later and [`uv`](https://docs.astral.sh/uv/) are required.

```shell
uv sync --frozen
uv run pre-commit install
```

`pre-commit install` registers both hook types the configuration declares:
`pre-commit` (lint, format, secret scan) and `pre-push` (types, tests, schema
integrity, release verification). Do not use `--no-verify`.

## Before you change anything

1. Find your change in the routing table in AGENT.md §6 and read the section it
   names in `docs/architecture.md`. The table exists because most changes in
   this repository touch an invariant that is documented somewhere other than
   the file you are editing.
2. If your change maps to no row in that table, say so before starting. AGENT.md
   §6 is explicit that such a change is probably larger than it looks.
3. Check `docs/decisions/` for an ADR that already settled the question.

## Quality gates

All of these must pass before merge. CI runs them, and `pre-commit` runs most
of them locally.

```shell
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict src
uv run pytest
uv run bandit -c pyproject.toml -r src scripts
uv run pip-audit --skip-editable
uv run pre-commit run detect-secrets --all-files
uv run python scripts/verify_secret_scan.py
uv run python scripts/generate_config_schema.py --check
uv run python scripts/verify_release.py
```

Branch coverage is enforced at 90%. Coverage is a floor, not a goal: a
well-covered order state machine with no crash-injection test is not tested.

## The rule that matters most

AGENT.md §2 rule 16: **never weaken a control to make a task pass.**

If a risk check, live gate, type check, or test blocks the change you were asked
to make, stop and report it. Do not raise a limit, relax a gate, mark a test
`xfail`, add a `# type: ignore`, broaden an `except`, or delete an assertion to
reach green. If you believe a control is genuinely wrong, change it in its own
pull request, with its own justification, reviewed on its own merits — never as
a step inside a change that needed it out of the way.

This applies with particular force to:

- `src/trading_system/security/live_gate.py`
- `src/trading_system/risk/`
- `tests/architecture/` and `tests/security/`
- Anything in AGENT.md §7, "Prohibited shortcuts"

Two architecture tests are designed to be deleted eventually, and only one way:
`tests/architecture/test_no_broker_connectivity.py` is Phase-0-scoped and is
removed when Phase 1 lands the real adapter — but only after confirming
`test_import_layering.py`, which is permanent, is present and passing. Read both
docstrings before touching either.

## Changing the agent contract

`AGENT.md`, `AGENTS.md`, and `CLAUDE.md` are byte-identical copies, not
symlinks, because a Windows checkout with `core.symlinks=false` turns a
committed symlink into a plain text file and silently drops the contract from
agent context.

Edit `AGENT.md`, then mirror it:

```shell
cp AGENT.md AGENTS.md && cp AGENT.md CLAUDE.md
```

`scripts/verify_release.py` and `tests/architecture/test_contract_mirrors.py`
both fail on any divergence.

If you change the operator command interface, update AGENT.md §3.1 in the same
commit. `tests/architecture/test_documented_commands.py` parses every
`uv run trading-cli` line in the tracked documentation against the real parser
and fails if a documented command would be rejected — a wrong command in a
runbook is discovered under incident conditions.

## Changing configuration models

The JSON schema in `config/schema/` is generated and checked in. After an
intentional model change:

```shell
uv run python scripts/generate_config_schema.py
uv run python scripts/generate_config_schema.py --check
```

Financial values are quoted decimal strings in YAML. An unquoted number is
parsed as a float by the YAML loader before any validator sees it, which is the
precision loss AGENT.md rule 14 forbids.

## Dependencies

Production dependencies are exactly pinned (`==`) and listed in
`config/dependency-policy.toml` with their licences.
`scripts/verify_release.py` fails if `pyproject.toml` and the policy disagree,
or if a licence is outside the allowlist.

Move a version only with `uv lock --upgrade-package <name>`, in its own pull
request, with the provenance, licence, maintenance state, and security review
AGENT.md rule 11 requires stated in the description.

## Commits and pull requests

- Small and auditable (AGENT.md rule 13). Trading code must be understandable
  under incident conditions.
- Reference the architecture section your change implements or modifies, using
  the stable `§` numbering.
- Fill in `.github/PULL_REQUEST_TEMPLATE.md` honestly. "Not applicable" is a
  fine answer; a blank safety section is not.
- Never commit `.env`, credentials, account identifiers, production hostnames,
  API logs, market-data captures, database dumps, or broker statements.
- Never use real account data in a test fixture. Tests construct realistic
  secret patterns from fragments at runtime so the repository itself contains no
  scanner exception.

## Reporting a security issue

See [`SECURITY.md`](SECURITY.md). Do not open a public issue for a
vulnerability.
