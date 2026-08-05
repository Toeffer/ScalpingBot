"""Phase-0 release invariants: schema, lock, environments, and licences."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from trading_system.config import Environment, load_config
from trading_system.decimal_context import configure_decimal_context
from trading_system.security.config_integrity import canonical_config_schema
from trading_system.security.live_gate import evaluate_live_gate

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _normalized_package_name(requirement: str) -> str:
    name = re.split(r"[<>=!~\[]", requirement, maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).casefold()


def _verify_dependencies() -> list[str]:
    failures: list[str] = []
    project = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    policy = tomllib.loads(
        (REPOSITORY_ROOT / "config" / "dependency-policy.toml").read_text(encoding="utf-8")
    )
    dependencies: list[str] = project["project"]["dependencies"]
    if any("==" not in dependency for dependency in dependencies):
        failures.append("every production dependency must be exactly pinned")
    declared = {_normalized_package_name(dependency) for dependency in dependencies}
    reviewed = {_normalized_package_name(package) for package in policy["runtime_packages"]}
    if declared != reviewed:
        failures.append("runtime dependency licence policy does not match pyproject.toml")
    allowed = set(policy["allowed_licenses"])
    for package, license_name in policy["runtime_packages"].items():
        if license_name not in allowed:
            failures.append(f"{package} has a non-allowlisted licence: {license_name}")
    return failures


def _verify_agent_contract_mirrors() -> list[str]:
    failures: list[str] = []
    contract = REPOSITORY_ROOT / "AGENT.md"
    contract_bytes = contract.read_bytes()
    for mirror_name in ("AGENTS.md", "CLAUDE.md"):
        mirror = REPOSITORY_ROOT / mirror_name
        if not mirror.is_file() or mirror.read_bytes() != contract_bytes:
            failures.append(f"{mirror_name} does not match AGENT.md")
    return failures


def _verify_configurations() -> list[str]:
    failures: list[str] = []
    configure_decimal_context()
    defaults = REPOSITORY_ROOT / "config" / "defaults.yaml"
    for environment in Environment:
        environment_path = REPOSITORY_ROOT / "config" / f"{environment.value}.example.yaml"
        try:
            config = load_config(
                defaults,
                environment_path,
                environ={"TRADING_ENV": environment.value},
            )
        except Exception as exc:  # Release verification aggregates categorized failures.
            failures.append(f"{environment.value} configuration failed: {type(exc).__name__}")
            continue
        if environment is Environment.LIVE and evaluate_live_gate(config).authorized:
            failures.append("live gate must remain closed in Phase 0")
    return failures


def main() -> int:
    """Validate release inputs without modifying the workspace."""
    failures = _verify_dependencies()
    lock_file = REPOSITORY_ROOT / "uv.lock"
    if not lock_file.is_file():
        failures.append("uv.lock is missing")
    schema_path = REPOSITORY_ROOT / "config" / "schema" / "trading-config.schema.json"
    if (
        not schema_path.is_file()
        or schema_path.read_text(encoding="utf-8") != canonical_config_schema()
    ):
        failures.append("configuration schema is missing or stale")
    failures.extend(_verify_configurations())
    failures.extend(_verify_agent_contract_mirrors())
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("release verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
