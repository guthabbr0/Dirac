from __future__ import annotations

import ast
import json
import re
from typing import Any


DISCORD_ID_RE = re.compile(r'^\d{15,22}$')
DISCORD_ID_SEARCH_RE = re.compile(r'(?<!\d)(\d{15,22})(?!\d)')


MEMORY_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    'memory_search': {
        'type': 'function',
        'function': {
            'name': 'memory_search',
            'description': 'Search persisted Dirac memories by text and/or one Discord snowflake id.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'str_query': {
                        'type': 'string',
                        'description': 'Optional memory search text. Multi-word searches match terms instead of one exact phrase.',
                    },
                    'str_discord_id': {
                        'type': 'string',
                        'description': 'Optional Discord snowflake id as digits only. Mentions are accepted.',
                    },
                    'int_limit': {
                        'type': 'integer',
                        'description': 'Maximum rows to return, capped by Dirac.',
                    },
                },
            },
        },
    },
    'memory_add': {
        'type': 'function',
        'function': {
            'name': 'memory_add',
            'description': 'Add one durable Dirac memory for one Discord snowflake id.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'str_discord_id': {
                        'type': 'string',
                        'description': 'Discord user/channel/guild snowflake id as digits only. Mentions are accepted.',
                    },
                    'str_annotations': {
                        'type': 'string',
                        'description': 'The durable memory text to preserve.',
                    },
                    'array_tags': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Optional short tags as strings.',
                    },
                    'float_confidence': {
                        'type': 'number',
                        'description': 'Optional confidence from 0.0 to 1.0.',
                    },
                },
                'required': ['str_discord_id', 'str_annotations'],
            },
        },
    },
    'memory_update': {
        'type': 'function',
        'function': {
            'name': 'memory_update',
            'description': 'Supersede an existing durable memory by id.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'int_memory_id': {'type': 'integer'},
                    'str_annotations': {'type': 'string'},
                    'array_tags': {'type': 'array', 'items': {'type': 'string'}},
                    'float_confidence': {'type': 'number'},
                },
                'required': ['int_memory_id', 'str_annotations'],
            },
        },
    },
    'memory_edit': {
        'type': 'function',
        'function': {
            'name': 'memory_edit',
            'description': 'Alias for memory_update.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'int_memory_id': {'type': 'integer'},
                    'str_annotations': {'type': 'string'},
                    'array_tags': {'type': 'array', 'items': {'type': 'string'}},
                    'float_confidence': {'type': 'number'},
                },
                'required': ['int_memory_id', 'str_annotations'],
            },
        },
    },
    'memory_delete': {
        'type': 'function',
        'function': {
            'name': 'memory_delete',
            'description': 'Delete a durable memory row and its superseded chain.',
            'parameters': {
                'type': 'object',
                'properties': {'int_memory_id': {'type': 'integer'}},
                'required': ['int_memory_id'],
            },
        },
    },
    'memory_remove': {
        'type': 'function',
        'function': {
            'name': 'memory_remove',
            'description': 'Alias for memory_delete.',
            'parameters': {
                'type': 'object',
                'properties': {'int_memory_id': {'type': 'integer'}},
                'required': ['int_memory_id'],
            },
        },
    },
}


MEMORY_TOOL_BODIES = {
    'memory_search': 'Parameters: str_query, str_discord_id, int_limit. Empty arguments return usage. Searches SQLite FTS by terms, not one exact phrase.',
    'memory_add': 'Parameters: str_discord_id, str_annotations, array_tags, float_confidence. Dirac stores one durable memory for one Discord snowflake id.',
    'memory_update': 'Parameters: int_memory_id, str_annotations, array_tags, float_confidence. Creates a replacement row and links the older row as superseded.',
    'memory_edit': 'Alias for memory_update. Parameters: int_memory_id, str_annotations, array_tags, float_confidence.',
    'memory_delete': 'Parameters: int_memory_id. Deletes a memory row and its superseded chain.',
    'memory_remove': 'Alias for memory_delete. Parameters: int_memory_id.',
}


def memory_tool_schema(name: str) -> dict[str, Any] | None:
    schema = MEMORY_TOOL_SCHEMAS.get(str(name or ''))
    return json.loads(json.dumps(schema)) if schema else None


def memory_tool_body(name: str) -> str | None:
    return MEMORY_TOOL_BODIES.get(str(name or ''))


def normalize_discord_id(value: Any) -> str:
    text = str(value or '').strip()
    for prefix, suffix in (('<@!', '>'), ('<@', '>'), ('<#', '>')):
        if text.startswith(prefix) and text.endswith(suffix):
            text = text[len(prefix):-len(suffix)]
            break
    match = DISCORD_ID_SEARCH_RE.search(text)
    return match.group(1) if match else text


def is_discord_id(value: Any) -> bool:
    return bool(DISCORD_ID_RE.fullmatch(str(value or '').strip()))


def parse_tags(value: Any) -> tuple[list[str] | None, str | None]:
    if value in (None, ''):
        return None, None
    raw = value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None, None
        try:
            parsed = json.loads(text)
        except Exception:
            try:
                parsed = ast.literal_eval(text)
            except Exception:
                parsed = [part.strip() for part in text.split(',') if part.strip()]
        raw = parsed
    if not isinstance(raw, (list, tuple)):
        return None, 'array_tags must be an array of strings, for example ["rem", "z3ki"].'
    tags = []
    for item in raw:
        tag = str(item or '').strip()
        if tag:
            tags.append(tag)
    return tags or None, None


def tags_to_db(value: Any, max_chars: int | None = None) -> str | None:
    tags, error = parse_tags(value)
    if error or tags is None:
        return None
    text = json.dumps(tags, ensure_ascii=False)
    if max_chars is not None and len(text) > max_chars:
        trimmed = []
        total = 2
        for tag in tags:
            candidate = json.dumps(tag, ensure_ascii=False)
            needed = len(candidate) + (1 if trimmed else 0)
            if total + needed > max_chars:
                break
            trimmed.append(tag)
            total += needed
        text = json.dumps(trimmed, ensure_ascii=False)
    return text


def tags_from_db(value: Any) -> list[str]:
    tags, error = parse_tags(value)
    return [] if error or tags is None else tags


def fts5_terms(query: Any) -> list[str]:
    text = str(query or '').strip()
    return re.findall(r'[\w@.#:-]+', text, flags=re.UNICODE)


def fts5_query(query: Any, operator: str = 'AND') -> str | None:
    terms = fts5_terms(query)
    if not terms:
        return None
    joiner = ' OR ' if str(operator).upper() == 'OR' else ' AND '
    return joiner.join('"' + term.replace('"', '""') + '"' for term in terms)


def parse_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except Exception:
        return None


def parse_confidence(value: Any, default: float = 0.7) -> tuple[float, str | None]:
    if value in (None, ''):
        return default, None
    try:
        number = float(value)
    except Exception:
        return default, 'float_confidence must be a number from 0.0 to 1.0.'
    if number < 0.0 or number > 1.0:
        return default, 'float_confidence must be between 0.0 and 1.0.'
    return number, None


def usage(tool: str) -> dict[str, Any]:
    schema = memory_tool_schema(tool)
    return {
        'tool': tool,
        'usage': memory_tool_body(tool) or 'Use the tool schema exactly.',
        'schema': (schema or {}).get('function', {}).get('parameters') if schema else None,
    }


def validation_error(tool: str, issues: list[str]) -> dict[str, Any]:
    payload = usage(tool)
    payload.update({
        'ok': False,
        'error': 'invalid_arguments',
        'issues': issues,
        'needs_model_followup': True,
        'engine': 'MemoryManager',
    })
    return payload
