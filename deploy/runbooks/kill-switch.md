# Kill-switch runbook

This procedure covers latching and clearing the Phase-0 kill switch. It
answers the "kill-switch reset" line of the threat model (§5) and is the
out-of-band procedure referenced from the top-level README's operator-commands
section.

## 1. Scope

This runbook is Phase 0 only: the latch is a single file on a single host,
read and written by `FileKillSwitchStore`. There is no multi-process locking
and no remote durability. Phase 1 and later must move latch authority to
transactional storage — the PostgreSQL journal referenced elsewhere in the
architecture docs — and add an authenticated operator command for clearing a
latch. This runbook does not anticipate what that future command looks like;
it documents only the Phase-0 file-backed procedure below.

## 2. Inspect current state

Run:

```powershell
uv run trading-cli status --environment-config config/simulation.example.yaml
```

This is read-only: it does not start the application. The `kill_switch` object
in the printed JSON has three fields to read:

- `global_latched` — `true` if a `global`-scope latch is currently active.
  A global latch blocks startup regardless of any other scope.
- `revision` — an integer that increments by one each time durable state
  actually changes. Use it to confirm that an action you took was recorded.
  Note that an idempotent repeat latch (step 3) changes nothing and therefore
  leaves `revision` unchanged; that is expected, not a failed write.
- `active` — the list of currently active latches, each with `record_id`,
  `scope`, `target_id`, `reason`, and `latched_at`. An empty list means
  nothing is latched.

## 3. Latch

Run:

```powershell
uv run trading-cli halt --scope global --reason "<text>" --actor "<who>"
```

`--scope` accepts `global`, `strategy`, `instrument`, or `entry`. `global`
forbids `--target-id`; `strategy` and `instrument` require it. A repeat halt
of a scope that is already latched is idempotent: it returns the existing
record instead of erroring or creating a duplicate.

## 4. Verify the latch holds

Re-run `status` (step 2) and confirm the scope you latched appears in
`active`. Independently, attempt `trading-cli start` against the same
environment config: startup must raise `KillSwitchLatchedError` and the CLI
must exit with code 2. Both checks should agree; if they do not, treat the
state file as suspect and stop.

## 5. Investigate before clearing

AGENT.md §2 rule 9 requires that a kill switch stay latched until an
authorized operator investigates and explicitly resets it. Before clearing
anything, establish and be ready to state:

- The root cause of the fault that triggered or motivated the latch.
- Confirmation that no order, position, or reconciliation issue remains
  unresolved.
- Who is authorizing the clear, and on what basis.
- That this investigation is recorded somewhere durable. The `reason` and
  `authorized_by` values passed to `.clear()` in step 6 are that record: they
  are written into the kill-switch document's append-only history, so choose
  wording that would make sense to someone reading the audit trail later, not
  just to yourself right now.

## 6. Clear (authorized operators only)

There is deliberately no CLI path for this. Phase 0 has no operator
authentication, so a `trading-cli clear` command would let anyone who can run
the CLI clear a latch with no accountability. That friction is the control,
not an oversight to work around.

The designed path is to construct a `FileKillSwitchStore` against the same
`kill_switch.state_file` path the environment config uses, and call
`.clear()` directly. `.clear()` returns `bool`: `True` if it found and cleared
a matching active latch, `False` if no matching active latch existed.

```python
from pathlib import Path

from trading_system.risk.kill_switch import FileKillSwitchStore, KillSwitchScope

# Must match the kill_switch.state_file value in whichever environment config
# --environment-config pointed at (config/simulation.example.yaml here).
store = FileKillSwitchStore(Path("var/simulation/kill-switch.json"))

cleared = store.clear(
    KillSwitchScope.GLOBAL,
    reason="root cause identified: <summary>; no unresolved order/reconciliation issue",
    authorized_by="<operator name or identity>",
)
print(cleared)
```

Run this from the repository root with the same environment (`uv run python
-c "..."` or as a short script) so relative paths resolve the same way the
CLI resolved them. For a `strategy` or `instrument` scope, pass the matching
`target_id=` keyword argument as well.

## 7. Never do this

Never delete or hand-edit the kill-switch state file. Two separate failures
follow from that:

- It destroys the append-only audit history — the record of every latch and
  clear, and the reasons given for each — with no recovery path.
- `FileKillSwitchStore.initialize()` treats a missing state file as "nothing
  has ever happened here": if the file does not exist, it creates a fresh
  `KillSwitchDocument` at revision 0 with no active latches. Deleting the file
  to work around a latch does not just lose history — it silently recreates
  clean state on the next startup, making a latched halt vanish entirely.

This is exactly the shortcut AGENT.md §7 prohibits ("Clears a kill switch
automatically after restart") and it is manual production state modification
of the kind AGENT.md §2 rule 10 forbids. Use `.clear()` (step 6), never the
filesystem directly.

## 8. Verify after clearing

Re-run `status` (step 2) and confirm:

- The scope you cleared no longer appears in `active`.
- `revision` incremented by one from the value you observed in step 4.

The CLI's `status` output only surfaces active latches, not history. Full
audit inspection — including the `cleared` entry the `.clear()` call in step 6
just appended — currently requires reading `store.snapshot().history`
directly; there is no CLI command that prints it today.
