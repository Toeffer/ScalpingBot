"""Configuration-schema artifact tests."""

import json

from trading_system.security.config_integrity import canonical_config_schema, config_schema_hash


def test_canonical_schema_is_stable_json_with_digest() -> None:
    rendered = canonical_config_schema()
    schema = json.loads(rendered)

    assert schema["title"] == "TradingConfig"
    assert schema["additionalProperties"] is False
    assert rendered.endswith("\n")
    assert config_schema_hash().startswith("sha256:")
