# Runbooks

This directory holds the detailed operational procedures that
`docs/architecture.md` §22 requires; that section gives short numbered
summaries and names this directory as the place the full procedure lives.

AGENT.md §8 sets the bar: "Runbooks exist and have been exercised, not just
written." A runbook here is not done because it is written down. It is done
once it has been rehearsed against the system it describes, and the rehearsal
is recorded.

## Index

| § | Runbook | File | Status |
| --- | --- | --- | --- |
| 22.1 | Startup | — | Not written; needs Phases 1–3 (Gateway, database, reconciliation) |
| 22.2 | Unexpected disconnect | — | Not written; needs Phase 1 (connection lifecycle) |
| 22.3 | Position mismatch | — | Not written; needs Phase 2 (reconciliation) |
| 22.4 | Unknown order | — | Not written; needs Phase 3 (order lifecycle) |
| 22.5 | Daily loss breach | — | Not written; needs Phase 4 (loss limits) |
| 22.6 | Wrong account or unexpected live connection | — | Not written; needs Phase 1 (account allowlist) |
| 22.7 | Total host loss with open positions | — | Not written; needs Phase 7, **rehearse before the live pilot** |
| — | Kill switch (Phase-0 file-backed latch) | [`kill-switch.md`](kill-switch.md) | Written; **not yet recorded as rehearsed** |

## Why the empty rows stay empty

Each missing runbook describes a component that does not exist yet, so it
cannot be rehearsed and its steps cannot be verified. Writing seven procedures
against imagined behavior would produce documents that look authoritative,
have never been executed, and are consulted for the first time during an
incident. AGENT.md §0 makes the general form of this point: a stale safety rule
is worse than no safety rule.

The rows are listed rather than omitted so the gap is visible and attributable
to a phase, instead of being discovered when someone reaches for a procedure
that was never written. `docs/operations/paper-readiness.md` §6 places runbook
authoring in the ordered path to a paper run.

§22.7 deserves separate mention: it is the one procedure the architecture calls
out as needing rehearsal *before* the live pilot and annually afterwards, and
it is the failure mode the single-host topology (§16.2) knowingly accepts. Its
prerequisites — a second machine, a tested mobile app, an off-host position
export, a written per-strategy flatten-or-hold decision — take real calendar
time to arrange. Start them well before Phase 7, not during it.

## Recording a rehearsal

When a runbook is exercised, record it at the bottom of that runbook: the date,
who ran it, against which environment, what diverged from the written steps,
and what was changed as a result. A rehearsal that changed nothing in the
document is worth recording too — that is the evidence the document is
accurate. Then update the Status column above.
