from __future__ import annotations

import ast
import json
import re
from typing import Any


DISCORD_ID_RE = re.compile(r"^\d{15,22}$")
DISCORD_ID_SEARCH_RE = re.compile(r"(?<!\d)(\d{15,22})(?!\d)")


def normalize_discord_id(value: Any) -> str:
    text = str(value or "").strip()
    for prefix, suffix in (("<@!", ">"), ("<@", ">"), ("<#", ">")):
        if text.startswith(prefix) and text.endswith(suffix):
            text = text[len(prefix) : -len(suffix)]
            break
    match = DISCORD_ID_SEARCH_RE.search(text)
    return match.group(1) if match else text


def is_discord_id(value: Any) -> bool:
    return bool(DISCORD_ID_RE.fullmatch(str(value or "").strip()))


def parse_tags(value: Any) -> tuple[tuple[str, ...], str | None]:
    if value in (None, ""):
        return (), None
    raw = value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return (), None
        try:
            raw = json.loads(text)
        except Exception:
            try:
                raw = ast.literal_eval(text)
            except Exception:
                raw = [part.strip() for part in text.split(",") if part.strip()]
    if not isinstance(raw, (list, tuple)):
        return (), 'array_tags must be an array of strings, for example ["quiet", "identity"].'
    return tuple(str(item).strip() for item in raw if str(item).strip()), None


def parse_confidence(value: Any, default: float = 0.7) -> tuple[float, str | None]:
    if value in (None, ""):
        return default, None
    try:
        number = float(value)
    except Exception:
        return default, "float_confidence must be a number from 0.0 to 1.0."
    if number < 0.0 or number > 1.0:
        return default, "float_confidence must be between 0.0 and 1.0."
    return number, None


def usage(tool_name: str) -> dict[str, Any]:
    return {
        "tool": tool_name,
        "usage": "Use the current memory tool parameter names exactly: str_query, str_discord_id, int_limit, int_memory_id, str_annotations, array_tags, float_confidence.",
    }


def validation_error(tool_name: str, issues: list[str]) -> dict[str, Any]:
    payload = usage(tool_name)
    payload.update(
        {"ok": False, "error": "invalid_arguments", "issues": issues, "needs_model_followup": True}
    )
    return payload
