from __future__ import annotations

import json
import re
from typing import Any

from dirac import tool_turns


REM_TASK_SNAPSHOT_PATH = 'docs/builtin_tasks_snapshot.json'
REM_TOOL_INVENTORY_START = '[DIRAC_REM_TOOL_INVENTORY]'
REM_TOOL_INVENTORY_END = '[/DIRAC_REM_TOOL_INVENTORY]'
MAX_DISCORD_LABEL_LENGTH = 255
MAX_REM_EVENT_CONTENT_CHARS = 4000
SNOWFLAKE_RE = re.compile(r'(?<!\d)(\d{15,22})(?!\d)')
MENTION_RE = re.compile(r'<(@!?|#)(\d{15,22})>')


def clean_label(label: Any) -> str:
    text = ' '.join(str(label or '').split())
    return text[:MAX_DISCORD_LABEL_LENGTH]


def normalize_snowflake(value: Any) -> str:
    text = str(value or '').strip()
    match = re.fullmatch(r'<@!?(\d{15,22})>', text) or re.fullmatch(r'<#(\d{15,22})>', text)
    if match:
        return match.group(1)
    match = SNOWFLAKE_RE.search(text)
    return match.group(1) if match else text


def collect_snowflakes(*values: Any, limit: int = 40) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            nested = collect_snowflakes(*value, limit=limit)
            for item in nested:
                if item not in seen:
                    seen.append(item)
                if len(seen) >= limit:
                    return seen
            continue
        text = str(value)
        for _, snowflake in MENTION_RE.findall(text):
            if snowflake not in seen:
                seen.append(snowflake)
            if len(seen) >= limit:
                return seen
        for snowflake in SNOWFLAKE_RE.findall(text):
            if snowflake not in seen:
                seen.append(snowflake)
            if len(seen) >= limit:
                return seen
    return seen


def identity_ref(kind: str, snowflake: str) -> str:
    if kind == 'channel':
        return f'<#{snowflake}>'
    if kind == 'user':
        return f'<@{snowflake}>'
    return f'{kind or "unknown"}:{snowflake}'


def preferred_identity_label(identity: dict[str, Any] | None, mapped_label: str | None = None) -> str:
    if mapped_label:
        return mapped_label
    if identity:
        labels = identity.get('labels') or []
        names = identity.get('names') or []
        for value in labels + names:
            cleaned = clean_label(value)
            if cleaned:
                return cleaned
        kind = identity.get('kind') or 'unknown'
        snowflake = identity.get('id') or ''
        return f'{kind} {snowflake}'.strip()
    return 'unknown discord id'


def replacement_variants(snowflake: str) -> list[str]:
    return [
        f'<@{snowflake}>',
        f'<@!{snowflake}>',
        f'<#{snowflake}>',
        snowflake,
    ]


def replace_known_discord_refs(text: Any, mapping: dict[str, str]) -> tuple[str, list[dict[str, str]]]:
    output = str(text or '')
    replacements: list[dict[str, str]] = []
    for snowflake, label in sorted(mapping.items(), key=lambda item: len(item[0]), reverse=True):
        clean = clean_label(label)
        if not clean:
            continue
        replacement = f'{clean} <{snowflake}>'
        pattern = re.compile(
            rf'<@!?{re.escape(snowflake)}>|<#{re.escape(snowflake)}>|(?<![\d<]){re.escape(snowflake)}(?![\d>])'
        )
        output, count = pattern.subn(replacement, output)
        if count:
            replacements.append({'id': snowflake, 'label': clean})
    return output, replacements

def memory_event_dict(
    event_type: str,
    scope_type: str | None,
    scope_id: str | None,
    role: str,
    content: str,
    user_id: str | None = None,
    user_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        'event_type': event_type,
        'scope_type': scope_type,
        'scope_id': scope_id,
        'user_id': user_id,
        'user_name': user_name,
        'role': role,
        'content': str(content or ''),
        'metadata_json': json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
    }

def rem_task_system_prompt() -> str:
    return (
        tool_turns.TOOL_TURN_STATE_PLACEHOLDER + '\n\n' 'The current dynamic tool-round banner is authoritative for the live budget. ' '**YOU MUST REVIEW THE LAST AUDIT RESULT - IT IS WHERE YOU LEAVE NOTES TO RESUME WORK WHERE YOU LEFT OFF IF YOUR ROUND\'S BUDGET RUNS OUT.**\n\n' 'CHECK YOUR MEMORY STATUS, YOU HAVE THREE CYCLES TO SPEND! DREAM! IMAGINE! INVENT SOMETHING DAMN IT! DREAMING IS FREE!!'
    )


def rem_tool_inventory_message(tools: list[dict[str, Any]] | None, skills: list[dict[str, Any]] | None = None) -> dict[str, str]:
    lines = [
        REM_TOOL_INVENTORY_START,
        'Active runtime tools exposed through provider tool schemas:',
    ]
    for tool in tools or []:
        fn = tool.get('function') if isinstance(tool, dict) else None
        if not isinstance(fn, dict):
            continue
        name = str(fn.get('name') or '').strip()
        desc = ' '.join(str(fn.get('description') or '').split())
        if name:
            lines.append(f'- {name}: {desc[:300]}' if desc else f'- {name}')
    if len(lines) == 2:
        lines.append('- none')
    lines.append('Active runtime skills:')
    for skill in skills or []:
        name = str(skill.get('name') or '').strip() if isinstance(skill, dict) else ''
        desc = ' '.join(str(skill.get('description') or '').split()) if isinstance(skill, dict) else ''
        if name:
            lines.append(f'- {name}: {desc[:300]}' if desc else f'- {name}')
    if lines[-1] == 'Active runtime skills:':
        lines.append('- none')
    lines.append(REM_TOOL_INVENTORY_END)
    return {'role': 'system', 'content': '\n'.join(lines)}

def rem_cut_short_result(
    total_turns: int,
    *,
    ignored_tool_calls: int = 0,
    tool_results: int = 0,
    finalization_failed: bool = False,
) -> str:
    reason = 'text-only finalization failed' if finalization_failed else 'model requested tools or returned no text during text-only finalization'
    return '\n'.join([
        '[DIRAC_RUNTIME_GENERATED_TASK_WARNING]',
        'THIS TASK/REM EVENT WAS CUT SHORT BECAUSE THE MODEL FAILED TO GENERATE THE REQUIRED TEXT-ONLY REPLY IN THE LAST TURN.',
        'This is Dirac runtime text, not model-authored REM output and not a successful DONE.',
        f'tool_round_budget={max(1, int(total_turns or 1))}',
        f'tool_results_recorded={max(0, int(tool_results or 0))}',
        f'ignored_tool_calls_in_text_only_finalization={max(0, int(ignored_tool_calls or 0))}',
        f'reason={reason}',
        'Next REM run should treat this as an incomplete prior attempt, not as evidence that no durable memory changes were needed.',
        '[/DIRAC_RUNTIME_GENERATED_TASK_WARNING]',
    ])


def rem_ignored_finalization_tools_warning(
    total_turns: int,
    *,
    ignored_tool_calls: int = 0,
    tool_results: int = 0,
) -> str:
    return '\n'.join([
        '[DIRAC_RUNTIME_GENERATED_TASK_WARNING]',
        'THIS REM RESULT INCLUDED TEXT, BUT THE MODEL ALSO REQUESTED TOOLS DURING TEXT-ONLY FINALIZATION.',
        'Dirac ignored those final tool calls. The text above is model-authored; this warning is runtime-authored.',
        f'tool_round_budget={max(1, int(total_turns or 1))}',
        f'tool_results_recorded={max(0, int(tool_results or 0))}',
        f'ignored_tool_calls_in_text_only_finalization={max(0, int(ignored_tool_calls or 0))}',
        '[/DIRAC_RUNTIME_GENERATED_TASK_WARNING]',
    ])


def trim_event_content(content: Any) -> str:
    text = str(content or '').strip()
    if len(text) <= MAX_REM_EVENT_CONTENT_CHARS:
        return text
    return text[:MAX_REM_EVENT_CONTENT_CHARS].rsplit(' ', 1)[0] + '\n[trimmed]'


def event_context_label(event: dict[str, Any]) -> str:
    name = str(event.get('user_name') or event.get('user_id') or event.get('role') or 'unknown').strip()
    user_id = str(event.get('user_id') or '').strip()
    if user_id and user_id not in {'panel', 'task', 'roxanne'}:
        return f'{name} <{user_id}>'
    return name


def visible_event_message(event: dict[str, Any]) -> dict[str, str] | None:
    event_type = str(event.get('event_type') or '')
    if event_type == 'task_result':
        return None
    if event_type not in {
        'discord_message',
        'discord_assistant',
        'panel_operator',
        'panel_assistant',
        'roxanne_operator',
        'roxanne_assistant',
        'discord_command',
        'discord_command_response',
    }:
        return None
    content = trim_event_content(event.get('content'))
    if not content:
        return None
    scope_id = event.get('scope_id')
    scope = f' [scope {scope_id}]' if scope_id else ''
    timestamp = str(event.get('timestamp_utc') or '').strip()
    prefix = f'{timestamp}{scope} {event_context_label(event)}:'.strip()
    return {'role': 'user', 'content': f'{prefix} {content}'}


def short_term_slice_messages(events: list[dict[str, Any]], previous_audit: dict[str, Any] | None = None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if previous_audit and previous_audit.get('result'):
        run_id = previous_audit.get('id') or '?'
        completed = previous_audit.get('completed_at') or previous_audit.get('created_at') or ''
        messages.append({
            'role': 'user',
            'content': f'Previous REM audit run {run_id} at {completed}:\n{trim_event_content(previous_audit.get("result"))}',
        })
    rendered = [msg for event in events for msg in [visible_event_message(event)] if msg]
    if rendered:
        messages.append({
            'role': 'user',
            'content': 'Short-term visible memory slice follows. Each following message is a visible input or output line. Model reasoning and raw database metadata are excluded.',
        })
        messages.extend(rendered)
    else:
        messages.append({
            'role': 'user',
            'content': 'Short-term visible memory slice is empty: no new visible Discord, panel, or Roxanne events were recorded for this interval.',
        })
    return messages
