"""Phase 0 must not gain a hidden broker connection path."""

import ast
import tomllib

from conftest import REPOSITORY_ROOT

_PROHIBITED_BROKER_PACKAGES = {"ibapi", "ib_async", "ib_insync"}


def test_source_has_no_ibkr_package_imports() -> None:
    source_root = REPOSITORY_ROOT / "src"
    imported_roots: set[str] = set()
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.partition(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_roots.add(node.module.partition(".")[0])

    assert imported_roots.isdisjoint(_PROHIBITED_BROKER_PACKAGES)


def test_project_has_no_broker_runtime_dependency() -> None:
    project = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]

    assert not any(
        dependency.partition("=")[0].casefold() in _PROHIBITED_BROKER_PACKAGES
        for dependency in dependencies
    )
