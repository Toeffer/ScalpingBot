"""Documented operator commands must actually work.

A wrong command in a runbook is discovered under incident conditions, which is
the worst possible time. `AGENT.md` §3 is explicit that its command block is
the part of the contract that matters most during an incident, so it is checked
mechanically rather than by review.

Two rules follow from this file:

1. Any `uv run trading-cli ...` line written in a tracked Markdown file or shell
   script must parse against the real command-line interface. A command the
   architecture reserves for a later phase therefore must not be written in that
   form — `AGENT.md` §3.2 lists reserved commands, and none of them is a
   `trading-cli` subcommand.
2. Every subcommand the interface accepts must appear in `AGENT.md` §3.1, so a
   new operator command cannot ship undocumented.
"""

import argparse
import re
import shlex
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from conftest import REPOSITORY_ROOT
from trading_system.operations.cli import _parser

_INVOCATION = re.compile(r"uv run trading-cli\s+(?P<arguments>.+)")
_SEARCHED_SUFFIXES = (".md", ".sh")
_SEARCHED_ROOTS = ("AGENT.md", "AGENTS.md", "CLAUDE.md", "README.md", "deploy", "docs", "scripts")
_EXECUTABLE_SCRIPTS = ("scripts/run_simulation.sh", "scripts/run_paper.sh")
_MINIMUM_DOCUMENTED_INVOCATIONS = 5


def _documented_files() -> list[Path]:
    files: list[Path] = []
    for entry in _SEARCHED_ROOTS:
        root = REPOSITORY_ROOT / entry
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(
                path
                for path in sorted(root.rglob("*"))
                if path.is_file() and path.suffix in _SEARCHED_SUFFIXES
            )
    return files


def _logical_lines(text: str) -> Iterator[tuple[int, str]]:
    """Yield (first line number, line) with shell backslash continuations joined.

    Documented commands wrap, so a continuation must be rejoined before it is
    parsed. Otherwise this test reads `trading-cli start \\` as the whole
    command and reports a failure that only exists in its own extraction.
    """
    buffer = ""
    start = 0
    for number, line in enumerate(text.splitlines(), start=1):
        if not buffer:
            start = number
        stripped = line.rstrip()
        if stripped.endswith("\\"):
            buffer += f"{stripped[:-1].rstrip()} "
            continue
        yield start, buffer + line.strip()
        buffer = ""
    if buffer:
        yield start, buffer


def _documented_invocations() -> list[tuple[str, str]]:
    """Return every documented invocation as (source location, argument string)."""
    invocations: list[tuple[str, str]] = []
    for path in _documented_files():
        relative = path.relative_to(REPOSITORY_ROOT)
        for number, line in _logical_lines(path.read_text(encoding="utf-8")):
            match = _INVOCATION.search(line)
            if match is not None:
                invocations.append((f"{relative}:{number}", match.group("arguments").strip()))
    return invocations


def _subcommand_names() -> list[str]:
    """Enumerate the interface's real subcommands.

    argparse exposes no public accessor for this, so the test reads `_actions`
    — the most stable of its internals — rather than trusting a hand-kept list
    that could omit the very command this test exists to catch.
    """
    return sorted(
        name
        for action in _parser()._actions
        if isinstance(action, argparse._SubParsersAction)
        for name in action.choices
    )


def test_documented_invocations_exist_to_be_checked() -> None:
    """Guard against the extraction silently matching nothing and passing."""
    assert len(_documented_invocations()) >= _MINIMUM_DOCUMENTED_INVOCATIONS


@pytest.mark.parametrize(("location", "arguments"), _documented_invocations())
def test_documented_invocation_parses(location: str, arguments: str) -> None:
    tokens = shlex.split(arguments, comments=True)
    try:
        _parser().parse_args(tokens)
    except SystemExit as exit_signal:
        pytest.fail(
            f"documented command at {location} is rejected by the CLI: "
            f"'trading-cli {arguments}' (exit {exit_signal.code})"
        )


def test_every_subcommand_is_documented() -> None:
    documented = (REPOSITORY_ROOT / "AGENT.md").read_text(encoding="utf-8")
    available_now = documented.partition("### 3.1 Available now")[2].partition("### 3.2")[0]
    assert available_now, "AGENT.md §3.1 is missing; the command contract cannot be checked"

    undocumented = [
        name for name in _subcommand_names() if f"trading-cli {name}" not in available_now
    ]
    assert not undocumented, (
        f"operator subcommands missing from AGENT.md §3.1: {undocumented}. "
        "A command that is not in the contract will not be found during an incident."
    )


@pytest.mark.parametrize("relative_path", _EXECUTABLE_SCRIPTS)
def test_documented_run_script_is_executable(relative_path: str) -> None:
    """`./scripts/run_*.sh` is documented with a leading `./`, so the mode matters."""
    script = REPOSITORY_ROOT / relative_path
    assert script.is_file(), f"{relative_path} is missing"
    assert script.stat().st_mode & stat.S_IXUSR, (
        f"{relative_path} is not executable; the documented './{relative_path}' "
        "invocation fails with 'Permission denied'"
    )
