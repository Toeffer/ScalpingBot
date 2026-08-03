"""Permanent import-layering boundaries for the broker integration surface.

This rule is PERMANENT: it must survive every phase of the project, not just
Phase 0. It is the durable successor to the Phase-0-only absolute ban in
`test_no_broker_connectivity.py`, which forbids broker package imports
anywhere in `src` and is expected to be deleted once Phase 1 introduces the
real broker adapter under `src/trading_system/broker/`. From that point on,
this file is what enforces the boundary: only modules inside
`src/trading_system/broker/` may import a broker package. Every other module
under `src` must not.
"""

import ast
from pathlib import Path

from conftest import REPOSITORY_ROOT

_PROHIBITED_BROKER_PACKAGES = {"ibapi", "ib_async", "ib_insync"}
_BROKER_PACKAGE_ROOT = REPOSITORY_ROOT / "src" / "trading_system" / "broker"


def _imports_broker_package(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_roots.add(node.module.partition(".")[0])
    return not imported_roots.isdisjoint(_PROHIBITED_BROKER_PACKAGES)


def test_only_broker_package_imports_ibkr_packages() -> None:
    source_root = REPOSITORY_ROOT / "src"
    offenders = [
        path
        for path in source_root.rglob("*.py")
        if _imports_broker_package(path) and not path.resolve().is_relative_to(_BROKER_PACKAGE_ROOT)
    ]

    offending_paths = sorted(str(path.resolve().relative_to(REPOSITORY_ROOT)) for path in offenders)
    assert not offending_paths, (
        "modules outside src/trading_system/broker/ must not import a broker "
        f"package ({sorted(_PROHIBITED_BROKER_PACKAGES)}); offenders: {offending_paths}"
    )
