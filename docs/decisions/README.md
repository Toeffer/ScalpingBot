# Architecture decision records

One file per decision, numbered sequentially, never renumbered. An ADR records
why a decision was made so that a future reader — human or agent — can check the
reasoning instead of re-deriving it, and can tell a deliberate constraint apart
from an accident.

`docs/architecture.md` says *what* the system does. An ADR says *why it is that
way and what was given up*.

## Index

| ADR | Title | Status | Date |
| --- | --- | --- | --- |
| [0001](0001-phase-0-boundary.md) | Keep Phase 0 broker-free and fail closed | Accepted | 2026-08-03 |

## When to write one

Write an ADR when a change:

- Adds, removes, or weakens a safety control, a risk limit, or a gate.
- Chooses between broker API libraries, persistence engines, or concurrency
  models.
- Changes an order-lifecycle, reconciliation, netting, or allocation rule.
- Adds a production dependency with a meaningful licence or supply-chain
  implication.
- Deliberately defers something the architecture requires — recording the
  deferral, its risk, and what closes it.
- Reverses an earlier ADR. Supersede it; never edit the old one to agree.

You do not need one for a bug fix, a refactor that preserves behavior, or a
change already specified in `docs/architecture.md`.

## Status values

- **Proposed** — under discussion, not yet binding.
- **Accepted** — binding. Code is expected to match it.
- **Superseded by NNNN** — replaced. Keep the file; add the pointer.
- **Deprecated** — no longer applies and nothing replaced it.

Never delete an ADR. The record of a decision that was later reversed is often
more useful than the decision that replaced it.

## Conventions

- Filename: `NNNN-short-kebab-title.md`, zero-padded to four digits.
- Reference architecture sections by their stable `§` numbers.
- Write the Consequences section honestly, including the costs. An ADR listing
  only benefits is advocacy, not a record.
- If the decision defers a control, name the phase or condition that closes the
  gap so it stays trackable.

## Template

```markdown
# ADR NNNN: <decision in one line, stated as a decision>

- Status: proposed | accepted | superseded by NNNN | deprecated
- Date: YYYY-MM-DD

## Context

The forces at play: the requirement, the constraint, the architecture sections
involved, and what makes this a real choice rather than an obvious one. State
facts, not the conclusion.

## Decision

What was decided, in the active voice. Be specific enough that a reviewer can
tell whether the code complies.

## Consequences

What follows — including what became harder, what risk was accepted, and what
is now deferred. If something is deferred, name the phase or condition that
closes it.
```
