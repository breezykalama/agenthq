import re
from collections.abc import Mapping, Sequence
from typing import cast
from urllib.parse import parse_qsl, urlsplit

from app.models.audit_log import JsonObject

REDACTED = "[REDACTED]"
SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "bootstrap_secret",
    "database_url",
    "invite_token",
    "jwt",
    "password",
    "password_hash",
    "refresh_token",
    "secret",
    "token",
    "token_hash",
}
BEARER_TOKEN_PATTERN = re.compile(r"^bearer\s+\S+$", re.IGNORECASE)
JWT_PATTERN = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


def redact_audit_snapshot(snapshot: JsonObject | None) -> JsonObject | None:
    if snapshot is None:
        return None
    return cast(JsonObject, redact_value(snapshot))


def redact_value(value: object, *, key: str | None = None) -> object:
    if key is not None and normalize_key(key) in SENSITIVE_KEYS:
        return REDACTED
    if isinstance(value, Mapping):
        return {
            str(nested_key): redact_value(nested_value, key=str(nested_key))
            for nested_key, nested_value in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_value(item) for item in value]
    if isinstance(value, str) and is_risky_string(value):
        return REDACTED
    return value


def normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def is_risky_string(value: str) -> bool:
    stripped_value = value.strip()
    if BEARER_TOKEN_PATTERN.match(stripped_value) or JWT_PATTERN.match(stripped_value):
        return True
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (
        parsed.username is not None
        or parsed.password is not None
        or any(normalize_key(key) in SENSITIVE_KEYS for key, _ in parse_qsl(parsed.query))
    )
