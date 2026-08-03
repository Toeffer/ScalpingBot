"""Recursive log redaction.

Architecture references: AGENT.md rule 6 and architecture §15.8.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final

REDACTED: Final = "[REDACTED]"

_SENSITIVE_KEYS: Final = frozenset(
    {
        "account",
        "account_id",
        "account_number",
        "api_key",
        "apikey",
        "authorization",
        "broker_payload",
        "cookie",
        "credential",
        "credentials",
        "host_name",
        "hostname",
        "notification_destination",
        "password",
        "passwd",
        "private_key",
        "raw_api_message",
        "secret",
        "session_token",
        "token",
        "user_name",
        "username",
        "webhook",
    }
)

_LABELED_SECRET = re.compile(
    r"(?i)\b(password|passwd|token|secret|api[_-]?key|authorization)"
    r"\s*[:=]\s*(?:bearer\s+)?([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_AWS_ACCESS_KEY = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_PROVIDER_TOKEN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,})\b")
_URL_CREDENTIALS = re.compile(r"(?P<scheme>https?://)[^/\s:@]+:[^/\s@]+@")
_EMAIL = re.compile(r"\b[A-Za-z0-9.!#$%&'*+/=?^_\x60{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_IBKR_ACCOUNT = re.compile(r"\b[UDF]\d{7,10}\b")


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")


def is_sensitive_key(key: str) -> bool:
    """Return whether a structured field is unsafe to emit."""
    normalized = _normalize_key(key)
    if normalized in _SENSITIVE_KEYS:
        return True
    return normalized.endswith(("_password", "_secret", "_token", "_api_key"))


def redact_text(value: str) -> str:
    """Remove common secret and account patterns from unstructured text."""
    redacted = _LABELED_SECRET.sub(lambda match: f"{match.group(1)}={REDACTED}", value)
    redacted = _BEARER.sub(f"Bearer {REDACTED}", redacted)
    redacted = _PRIVATE_KEY.sub(REDACTED, redacted)
    redacted = _AWS_ACCESS_KEY.sub(REDACTED, redacted)
    redacted = _JWT.sub(REDACTED, redacted)
    redacted = _PROVIDER_TOKEN.sub(REDACTED, redacted)
    redacted = _URL_CREDENTIALS.sub(lambda match: f"{match.group('scheme')}{REDACTED}@", redacted)
    redacted = _EMAIL.sub(REDACTED, redacted)
    return _IBKR_ACCOUNT.sub(REDACTED, redacted)


def redact(value: object, *, key: str | None = None) -> object:
    """Recursively sanitize data before serialization to a log sink."""
    if key is not None and is_sensitive_key(key):
        return REDACTED
    if isinstance(value, Mapping):
        return {str(item_key): redact(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [redact(item) for item in value]
    if isinstance(value, bytes | bytearray | memoryview):
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    return value
