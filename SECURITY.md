# Security policy

This repository is the foundation of an automated trading system. A defect here
can move money. Please treat it accordingly.

## Reporting a vulnerability

**Do not open a public issue, pull request, or discussion for a security
issue.** A public report tells everyone who reads this repository how to
exploit it before there is a fix.

Report privately, by either route:

1. GitHub private vulnerability reporting — the **Security** tab, then **Report
   a vulnerability**. This keeps the report and the discussion private until a
   fix is published.
2. Direct contact: `<SECURITY CONTACT — fill this in>`.

> Maintainer: replace the placeholder above with a monitored address, or delete
> route 2 and enable private vulnerability reporting in the repository's
> security settings. A reporting policy nobody can act on is worse than none,
> because it looks like one.

Please include what you can: affected file or component, the architecture
section it relates to, reproduction steps, impact, and whether the issue is
already public. **Never include real credentials, real account identifiers, or
production log excerpts in a report.** Redact them, or describe them.

Expect an acknowledgement within a few working days. Please give a reasonable
window for a fix before any public disclosure, and coordinate the timing.

## Scope

In scope — anything that could cause an unauthorized, duplicated, or
unaccounted trade, or expose credentials or account data:

- The environment and live gates (`src/trading_system/security/`).
- Kill-switch durability, atomicity, and the absence of an automatic reset.
- Configuration validation, environment binding, and schema integrity.
- Log redaction (`src/trading_system/operations/redaction.py`).
- Decimal-context pinning and any path where a financial value could become a
  binary float.
- Dependency, lockfile, CI workflow, and supply-chain integrity.
- Anything that would let a strategy reach the broker directly, once strategies
  and a broker adapter exist.

Out of scope:

- Trading losses, strategy performance, or backtest results. This repository
  makes no profitability claim (AGENT.md §1) and unprofitability is not a
  vulnerability.
- Vulnerabilities in Interactive Brokers' own software or services. Report
  those to IBKR.
- The absence of a control that the current phase documents as absent. Phase 0
  deliberately has no operator authentication, no broker connection, and no
  transactional kill-switch store; `docs/threat-model.md` and
  `docs/operations/paper-readiness.md` list these as known and tracked. A report
  that one of them is *inadequately documented*, or that a control is weaker
  than its documentation claims, is very much in scope.

## Current security posture

Read [`docs/threat-model.md`](docs/threat-model.md) first. It states the
security objective, the trust boundaries, and — in §4 — the residual risk left
by each control. It is deliberately explicit that this revision is not
production-ready and that missing controls are reasons for live denial rather
than deferred warnings.

Controls currently in place and tested: environment separation with an
unconditional live denial; strict configuration validation with unknown-key
rejection; a pinned decimal context with traps; recursive log redaction; an
atomic durable kill-switch latch with no automatic reset; exact dependency pins
with a licence policy; secret scanning with a self-test that proves the scanner
rejects a synthetic key; static analysis; and architecture tests that forbid a
broker dependency.

## Handling an exposed secret

If a credential reaches this repository or its logs, deleting the file is not
remediation. Follow `docs/threat-model.md` §6: stop the affected service, revoke
or rotate the credential, preserve incident evidence, remove the value from
active history through an approved procedure, and review logs and artifacts for
further exposure.

## Supported versions

This project is pre-release and has not been deployed. Only the default branch
receives fixes. There are no supported released versions.
