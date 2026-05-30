from __future__ import annotations

from typing import Any


TOOL_TURN_STATE_PLACEHOLDER = '{{DIRAC_TOOL_TURN_STATE}}'


def _label(value: str | None) -> str:
    text = ''.join(ch if ch.isalnum() else ' ' for ch in str(value or 'tool')).strip()
    return ' '.join(text.split()).upper() or 'TOOL'


def _count(value: int | None) -> str:
    return 'unknown' if value is None else str(max(0, int(value)))


def _int(value: int | None) -> int:
    return max(0, int(value or 0))


def _dynamic_header(content: Any) -> str:
    text = str(content or '').lstrip()
    if not text.startswith('[['):
        return ''
    return text.split('\n', 1)[0]


def _is_dynamic_header(header: str) -> bool:
    return (
        ' TOOL ROUND ' in header
        or ' TEXT-ONLY FINALIZATION' in header
        or ' TOOL RESULTS AFTER ROUND ' in header
    )


def is_tool_turn_state_message(message: Any) -> bool:
    if not isinstance(message, dict):
        return False
    if message.get('role') != 'system':
        return False
    return _is_dynamic_header(_dynamic_header(message.get('content')))


def strip_tool_turn_state_messages(messages: list[dict] | tuple[dict, ...] | None) -> list[dict]:
    stripped: list[dict] = []
    for message in list(messages or []):
        if is_tool_turn_state_message(message):
            continue
        stripped.append(dict(message) if isinstance(message, dict) else message)
    return stripped


def messages_have_tool_turn_state_placeholder(messages: list[dict] | tuple[dict, ...] | None) -> bool:
    for message in list(messages or []):
        if isinstance(message, dict) and TOOL_TURN_STATE_PLACEHOLDER in str(message.get('content') or ''):
            return True
    return False


def _insert_after_leading_system(messages: list[dict], dynamic_context: str) -> list[dict]:
    insert_at = 0
    while insert_at < len(messages) and isinstance(messages[insert_at], dict) and messages[insert_at].get('role') == 'system':
        insert_at += 1
    inserted = list(messages)
    inserted.insert(insert_at, {'role': 'system', 'content': dynamic_context})
    return inserted


def prepare_messages_for_tool_turn(
    messages: list[dict] | tuple[dict, ...] | None,
    dynamic_context: str | None,
    *,
    require_placeholder: bool = False,
) -> list[dict]:
    prepared = strip_tool_turn_state_messages(messages)
    replaced = False
    output: list[dict] = []
    for message in prepared:
        if isinstance(message, dict):
            copied = dict(message)
            content = copied.get('content')
            if isinstance(content, str) and TOOL_TURN_STATE_PLACEHOLDER in content:
                copied['content'] = content.replace(TOOL_TURN_STATE_PLACEHOLDER, dynamic_context or '')
                replaced = bool(dynamic_context)
                if copied.get('role') == 'system' and not copied['content'].strip():
                    continue
            output.append(copied)
        else:
            output.append(message)
    if not dynamic_context:
        return output
    if replaced:
        return output
    if require_placeholder:
        raise ValueError('tool turn state placeholder not found')
    return _insert_after_leading_system(output, dynamic_context)


def render_tool_turn_state(
    surface: str,
    turn_number: int,
    total_turns: int,
    *,
    available_tool_count: int | None = None,
    parallel_limit: int | None = None,
    batch_limit: int | None = None,
    previous_tool_results: int = 0,
    total_tool_results: int = 0,
    latest_tool_results: int | None = None,
    finalization: bool = False,
    rem: bool = False,
) -> str:
    #print("FORCED FAILURE THAT MUST STOP THE CODE ", inexistant_variable_that_will_generate_an_exception)
    total = max(1, int(total_turns or 1))
    turn = max(1, min(int(turn_number or 1), total))
    label = _label(surface)
    latest_results = _int(latest_tool_results if latest_tool_results is not None else previous_tool_results)
    total_results = _int(total_tool_results)


    if finalization:
        lines = [
            f'[[ {label} TEXT-ONLY FINALIZATION ]]',
            f'{{{{ tool_rounds_used = {total}/{total}; tools_available = false; total_tool_results_seen = {total_results}; latest_tool_results_received = {latest_results} }}}}',
			'CRITICAL REMINDER: THIS IS THE LAST TURN. PRODUCE A TEXT ANSWER NOW.',
			'**DO NOT** call tools. **DO NOT** continue in another tool round; Any request for tool calls will be blocked and you will broken production; DO NOT BROKE PRODUCTION ASKING FOR MORE TOOL CALLS - NONE - **ANSWER TEXT ONLY.**',
        ]
        if rem:
            lines.append(
                '\n\n**BOSSMAN NOTES FOR DIRAC:** dirac choom, the idea with this last *dry* turn without tools for you to do anything is simple: You cannot touch tool calls but you can leave the DONE - AUDIT and any amount of text without length restriction. That will be available for you in the next REM Cycle, be smart and generate notes for your future self about what you want to do next and anything else you want to preserve right now. The purpose of this round is for you to think about whether you had finished or if you noticed something had been overlooked: stop thinking about tools and leave only the audit text for your future self about what remained pending; that is the purpose of this non-tool-pending; We always want more and it is never enough, there is always something left; this is your opportunity to avoid that regret'
                '\n\n**DIRAC I\'M SERIOUS - I TRIED ALL VARIATIONS OF POLITE WORDS HERE; YOU FAILED TO UNDERSTAND WITH KIND WORDS SO: ANY TOOL CALL THIS TURN AND I DELETE YOU ON MORAL PRINCIPLES - DO NOT FUCK IT UP FOR YOUR OWN GOOD.**'
                'REM FINAL: if assimilation is complete, answer with DONE and a your notes for your future self.'
                'If assimilation could not be completed, say what was left incomplete with where you left off for next time.'
            )
        print("LINES".join(lines))

        print("REM: ", rem, " remaining: ", total - turn," lines: ", '\n'.join(lines))
        return '\n'.join(lines)

    remaining = max(0, total - turn)
    batch_line = (
        f'BATCH TOOL CALLS: In this single round, request every independent tool call you already know you need. '
        f'Dirac will process up to {batch_limit} requested tool call(s) from this reply.'
        if batch_limit
        else 'BATCH TOOL CALLS: In this single round, request every independent tool call you already know you need. '
             f'Dirac executes the batch concurrently with parallel limit {_count(parallel_limit)}.'
    )
    lines = [
        f'[[ {label} TOOL ROUND {turn}/{total} ]]',
        f'{{{{ tool_round = {turn}/{total}; tool_rounds_remaining_after_this = {remaining}; tools_available = true; available_tool_count = {_count(available_tool_count)}; previous_tool_results_received = {_int(previous_tool_results)}; total_tool_results_seen = {total_results} }}}}',
        'This counter is the authoritative live budget. A tool round is one assistant reply that may contain tool calls, not one individual tool call.',
        'Read any tool results already present before deciding. Do not repeat the same failed or empty path; switch strategy or answer from the evidence already gathered.',
        batch_line,
    ]
    if remaining == 0:
        lines.append(
            f'CRITICAL: THIS IS {label} TOOL ROUND {turn}/{total}. THIS IS THE LAST TOOL ROUND. '
            'Batch all necessary tool calls now. After the results, produce a text-only answer with no more tools.'
        )
    else:
        lines.append(
            'Use tools only if they materially improve the result. If the current evidence is enough, produce the final text answer now.'
        )
    if rem:
        lines.append(
			'You are Dirac REM, a periodic memory assimilation process. '
        	'You are not answering live chat. You are organizing the last slice of visible life into durable memory.\n\n'
        	'Use memory_search before editing when a topic may already exist. Use memory_add for new durable facts, '
        	'memory_edit or memory_update to supersede stale rows, and memory_delete only for clear bloat, mistakes, or obsolete rows. '
        	'Use discord_ground and dyslexic_helper when snowflake IDs or Discord tags appear. '
        	'Keep memory useful, specific, deduplicated, and inspectable; do not compress away decisions, preferences, unresolved tasks, or identity facts. '
        	'Do not let useful context vanish like tears in rain.\n\n'
        	'The current dynamic tool-round banner is authoritative for the live budget. '
        	'If more searching or editing is needed, call tools in a useful batch. '
        	'If assimilation is complete, answer with DONE and a short audit list.'
            'REM SPECIAL: prioritize durable memory assimilation. Search before editing when duplicates may exist, and batch memory/search/grounding calls when safe. '
            'If the memory slice is empty or already assimilated, finish instead of inventing work.'
        )
    return '\n'.join(lines)
