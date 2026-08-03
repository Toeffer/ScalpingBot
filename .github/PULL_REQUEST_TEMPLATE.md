## What this changes

<!-- One or two sentences. What behavior is different after this merges? -->

## Why

<!-- The problem or requirement. Link an issue or ADR if one exists. -->

## Architecture sections

<!-- Which sections of docs/architecture.md does this implement or modify?
     Use the stable § numbers. AGENT.md §6 is the routing table: find your
     change there and read the section it names before opening this PR.
     If your change maps to no row in that table, say so — AGENT.md §6 notes
     that such a change is probably larger than it looks. -->

## Safety checklist

Answer every line. "Not applicable" is a fine answer; a blank section is not.

- [ ] No control was weakened to make this pass — no raised limit, relaxed
      gate, `xfail`, `# type: ignore`, broadened `except`, or deleted assertion
      (AGENT.md §2 rule 16). If a control blocked this change, it is reported
      below rather than removed.
- [ ] No strategy or non-adapter module gained broker access (rule 2).
- [ ] No new order path bypasses the risk manager (rule 8).
- [ ] Money, quantities, prices, and fees use decimal-safe types under a pinned
      context, and every amount carries its currency (rules 14, 17, 18).
- [ ] Every limit, threshold, and duration carries its unit in the name
      (`_bps`, `_ms`, or an explicit currency) (rule 14).
- [ ] Timestamps are timezone-aware and stored in UTC (rule 15).
- [ ] No credential, session token, account number, hostname, or personally
      identifying value can reach a log or this diff (rules 6, 7).
- [ ] No generated API log, market-data capture, database dump, or broker
      statement is committed (rule 12).
- [ ] No test fixture contains real account data.
- [ ] Nothing in AGENT.md §7, "Prohibited shortcuts", applies to this change.

## Blocked by a control?

<!-- If a risk check, gate, type check, or test stopped you: describe it here
     instead of working around it. This is the expected outcome of rule 16,
     not a failure. Leave blank if nothing blocked you. -->

## Gates

- [ ] `uv run ruff check .` and `uv run ruff format --check .`
- [ ] `uv run mypy --strict src`
- [ ] `uv run pytest` (branch coverage ≥ 90%)
- [ ] `uv run bandit -c pyproject.toml -r src scripts`
- [ ] `uv run pip-audit --skip-editable`
- [ ] `uv run python scripts/verify_release.py`

## Documentation

- [ ] `AGENT.md` changes are mirrored byte-for-byte to `AGENTS.md` and
      `CLAUDE.md` (`cp AGENT.md AGENTS.md && cp AGENT.md CLAUDE.md`).
- [ ] Operator command changes are reflected in AGENT.md §3.1.
- [ ] Configuration model changes regenerate `config/schema/`
      (`uv run python scripts/generate_config_schema.py`).
- [ ] A new dependency states its provenance, licence, maintenance state, and
      security review, and is added to `config/dependency-policy.toml`
      (rule 11).
- [ ] An ADR was added under `docs/decisions/` if this decision needs one — see
      that directory's README for when.
- [ ] `CHANGELOG.md` updated under Unreleased.
- [ ] `docs/threat-model.md` reviewed if this adds a broker, database, network
      listener, secret provider, administrative command, remote log sink,
      dependency, or live gate (threat model §7).

## Testing

<!-- What did you run, and what did you observe? For anything touching order
     lifecycle, reconciliation, or risk: which failure modes are covered, not
     just which lines. Coverage is a floor, not evidence. -->
