"""Generate or verify the strict JSON configuration schema."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from trading_system.security.config_integrity import canonical_config_schema

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPOSITORY_ROOT / "config" / "schema" / "trading-config.schema.json"


def main(argv: Sequence[str] | None = None) -> int:
    """Write the model schema, or fail if the checked-in copy has drifted."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args(argv)
    expected = canonical_config_schema()
    if arguments.check:
        if not SCHEMA_PATH.is_file() or SCHEMA_PATH.read_text(encoding="utf-8") != expected:
            print("configuration schema is missing or stale")
            return 1
        print("configuration schema is current")
        return 0
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(expected, encoding="utf-8", newline="\n")
    print(f"wrote {SCHEMA_PATH.relative_to(REPOSITORY_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
