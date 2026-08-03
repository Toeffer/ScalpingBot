"""AGENT.md, AGENTS.md, and CLAUDE.md must never drift apart."""

from conftest import REPOSITORY_ROOT


def test_agent_contract_mirrors_are_byte_identical() -> None:
    contract_bytes = (REPOSITORY_ROOT / "AGENT.md").read_bytes()
    for mirror_name in ("AGENTS.md", "CLAUDE.md"):
        mirror = REPOSITORY_ROOT / mirror_name
        assert mirror.is_file(), f"{mirror_name} is missing"
        assert mirror.read_bytes() == contract_bytes, f"{mirror_name} does not match AGENT.md"
