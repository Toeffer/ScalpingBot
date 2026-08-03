"""Canonical configuration-schema integrity helpers (§15.6)."""

import hashlib
import json

from trading_system.config import TradingConfig


def canonical_config_schema() -> str:
    """Render the checked-in schema deterministically."""
    schema = TradingConfig.model_json_schema(mode="validation")
    return json.dumps(schema, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def config_schema_hash() -> str:
    """Return a digest suitable for release evidence."""
    payload = canonical_config_schema().encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"
