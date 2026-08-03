# ADR 0001: Keep Phase 0 broker-free and fail closed

- Status: accepted
- Date: 2026-08-03

## Context

The architecture calls for repository and security foundations before any IBKR
connection. Introducing a read-only client early would expand the attack and
failure surface before environment, logging, configuration, arithmetic, and
emergency-state controls have evidence.

## Decision

Phase 0 contains no broker package or transport. Local and simulation profiles
may bootstrap to READY_SIMULATION. Paper and live profiles are valid schema
inputs so separation can be tested, but application startup rejects both. The
live gate always returns an explicit list of unmet controls and cannot be opened
by live_enabled alone.

The kill-switch authority is an atomic local file for this phase only. Its
failure is categorized and startup cannot infer a clear state from unreadable
content.

## Consequences

Configuration, redaction, decimal, persistence, and CI controls can be tested
without external services. No paper-connectivity claim is possible. Phase 1
must explicitly add a broker port and read-only adapter while preserving the
structural boundary and startup denials appropriate to that phase.

