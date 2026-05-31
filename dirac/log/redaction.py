from __future__ import annotations

from typing import Any


SECRET_KEY_FRAGMENTS = ("token", "api_key", "authorization", "password", "secret", "bearer")
REDACTED = "***"


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            name = str(key).lower()
            out[key] = (
                REDACTED
                if item and any(fragment in name for fragment in SECRET_KEY_FRAGMENTS)
                else redact(item)
            )
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value
