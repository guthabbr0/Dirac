from __future__ import annotations

import re
from typing import Any


DIRAC_FENCE_LANGUAGE = 'dirac'
DIRAC_FENCE_RE = re.compile(r'(?ms)^```\s*dirac\s*\n.*?^```\s*$', re.MULTILINE)


def format_dirac_block(text: Any) -> str:
    body = str(text or '').replace('```', "'''")
    return f'```{DIRAC_FENCE_LANGUAGE}\n{body}\n```'


def strip_dirac_fenced_blocks(text: Any) -> str:
    value = str(text or '')
    stripped = DIRAC_FENCE_RE.sub('', value)
    stripped = re.sub(r'\n{3,}', '\n\n', stripped)
    return stripped.strip()


def contains_dirac_fenced_block(text: Any) -> bool:
    return bool(DIRAC_FENCE_RE.search(str(text or '')))


def filter_dirac_blocks_from_events(events: list[dict]) -> list[dict]:
    filtered = []
    for event in events:
        row = dict(event)
        content = strip_dirac_fenced_blocks(row.get('content', ''))
        if not content:
            continue
        row['content'] = content
        filtered.append(row)
    return filtered
