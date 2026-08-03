"""Logging redaction is a security boundary, not a presentation feature."""

import io
import json
import logging
from decimal import Decimal

import pytest

from trading_system.config import Environment, LoggingConfig
from trading_system.operations.logging import configure_structured_logging
from trading_system.operations.redaction import REDACTED, redact


def _secret_fixtures() -> dict[str, str]:
    return {
        "account": "U" + "12345678",
        "aws_key": "AKIA" + "ABCDEFGHIJKLMNOP",
        "github_token": "ghp_" + "A" * 24,
        "email": "operator" + "@example.com",
        "password": "-".join(("phase", "zero", "password", "fixture")),
    }


def test_structured_logger_redacts_keys_and_realistic_patterns() -> None:
    secrets = _secret_fixtures()
    stream = io.StringIO()
    logger = configure_structured_logging(
        LoggingConfig(),
        service="security-test",
        environment=Environment.SIMULATION,
        config_hash="sha256:test",
        artifact_digest="sha256:test",
        stream=stream,
    )

    logger.info(
        "redaction_probe",
        account_id=secrets["account"],
        password=secrets["password"],
        nested={"api_key": secrets["aws_key"]},
        detail=f"token={secrets['github_token']} contact={secrets['email']}",
    )

    rendered = stream.getvalue()
    for secret in secrets.values():
        assert secret not in rendered
    payload = json.loads(rendered)
    assert payload["account_id"] == REDACTED
    assert payload["password"] == REDACTED
    assert payload["nested"]["api_key"] == REDACTED
    assert payload["event"] == "redaction_probe"
    assert payload["timestamp"].endswith("Z")


def test_exception_messages_are_redacted() -> None:
    sample_value = "sk-" + "A" * 24
    stream = io.StringIO()
    logger = configure_structured_logging(
        LoggingConfig(),
        service="security-test",
        environment=Environment.SIMULATION,
        config_hash="sha256:test",
        artifact_digest="sha256:test",
        stream=stream,
    )

    unclassified_bearer = "opaque-value-without-provider-prefix"
    error = RuntimeError(f"authorization=Bearer {unclassified_bearer} {sample_value}")
    logger.error("operation_failed", exc_info=error)

    rendered = stream.getvalue()
    assert unclassified_bearer not in rendered
    assert sample_value not in rendered
    assert REDACTED in rendered


def test_redaction_handles_binary_and_collection_values() -> None:
    result = redact({"data": b"sensitive", "items": ("safe", "U" + "12345678")})

    assert result == {"data": REDACTED, "items": ["safe", REDACTED]}


def test_logger_validates_event_name_and_serializes_decimal() -> None:
    stream = io.StringIO()
    logger = configure_structured_logging(
        LoggingConfig(),
        service="security-test",
        environment=Environment.SIMULATION,
        config_hash="sha256:test",
        artifact_digest="sha256:test",
        stream=stream,
    )

    logger.warning("limit_near", remaining=Decimal("1.25"))
    with pytest.raises(ValueError, match="lower_snake_case"):
        logger.event(logging.INFO, "Invalid Event")

    payload = json.loads(stream.getvalue())
    assert payload["remaining"] == "1.25"
