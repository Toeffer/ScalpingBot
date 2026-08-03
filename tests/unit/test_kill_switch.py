"""Durable kill-switch tests."""

from pathlib import Path

import pytest

from trading_system.exceptions import KillSwitchPersistenceError
from trading_system.risk.kill_switch import FileKillSwitchStore, KillSwitchAction, KillSwitchScope

CLEARED_REVISION = 2


def test_global_latch_survives_store_restart(tmp_path: Path) -> None:
    state_file = tmp_path / "state" / "kill-switch.json"
    first_store = FileKillSwitchStore(state_file)
    first_store.initialize()

    first_record = first_store.latch(
        KillSwitchScope.GLOBAL,
        reason="operator drill",
        actor="operator:test",
    )
    repeated_record = first_store.latch(
        KillSwitchScope.GLOBAL,
        reason="duplicate request",
        actor="operator:test",
    )

    restarted_store = FileKillSwitchStore(state_file)
    assert restarted_store.is_global_latched()
    assert repeated_record.record_id == first_record.record_id
    assert restarted_store.snapshot().revision == 1


def test_clear_requires_explicit_audited_action(tmp_path: Path) -> None:
    store = FileKillSwitchStore(tmp_path / "kill-switch.json")
    store.initialize()
    store.latch(
        KillSwitchScope.INSTRUMENT,
        target_id="123456",
        reason="position mismatch",
        actor="risk-manager",
    )

    cleared = store.clear(
        KillSwitchScope.INSTRUMENT,
        target_id="123456",
        reason="reconciled and approved",
        authorized_by="operator:test",
    )

    snapshot = store.snapshot()
    assert cleared
    assert not store.blocks(KillSwitchScope.INSTRUMENT, "123456")
    assert snapshot.revision == CLEARED_REVISION
    assert [entry.action for entry in snapshot.history] == [
        KillSwitchAction.LATCHED,
        KillSwitchAction.CLEARED,
    ]


def test_global_latch_blocks_every_scope(tmp_path: Path) -> None:
    store = FileKillSwitchStore(tmp_path / "kill-switch.json")
    store.initialize()
    store.latch(
        KillSwitchScope.GLOBAL,
        reason="database unavailable",
        actor="risk-manager",
    )

    assert store.blocks(KillSwitchScope.STRATEGY, "strategy:test")
    assert store.blocks(KillSwitchScope.INSTRUMENT, "123456")


def test_corrupt_state_fails_closed(tmp_path: Path) -> None:
    state_file = tmp_path / "kill-switch.json"
    state_file.write_text("{invalid", encoding="utf-8")

    with pytest.raises(KillSwitchPersistenceError, match="unreadable or invalid"):
        FileKillSwitchStore(state_file).initialize()


def test_scoped_latch_requires_target(tmp_path: Path) -> None:
    store = FileKillSwitchStore(tmp_path / "kill-switch.json")
    store.initialize()

    with pytest.raises(ValueError, match="target_id"):
        store.latch(
            KillSwitchScope.STRATEGY,
            reason="strategy fault",
            actor="risk-manager",
        )
