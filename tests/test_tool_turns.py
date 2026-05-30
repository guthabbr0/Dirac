from dirac import tool_turns


def test_prepare_messages_for_tool_turn_replaces_placeholder_without_mutating_source():
    source = [
        {'role': 'system', 'content': tool_turns.TOOL_TURN_STATE_PLACEHOLDER + '\nbase'},
        {'role': 'user', 'content': 'hello'},
    ]
    dynamic = tool_turns.render_tool_turn_state('REM', 2, 4, available_tool_count=7, previous_tool_results=5, total_tool_results=5, rem=True)
    prepared = tool_turns.prepare_messages_for_tool_turn(source, dynamic)
    assert prepared[0]['content'].startswith('[[ REM TOOL ROUND 2/4 ]]')
    assert 'previous_tool_results_received = 5' in prepared[0]['content']
    assert source[0]['content'].startswith(tool_turns.TOOL_TURN_STATE_PLACEHOLDER)
    assert prepared[1] == source[1]


def test_prepare_messages_for_tool_turn_strips_stale_rendered_state():
    source = [
        {'role': 'system', 'content': '[[ REM TOOL ROUND 1/4 ]]\nstale'},
        {'role': 'system', 'content': '[[ REM TOOL RESULTS AFTER ROUND 1/4 ]]\nstale'},
        {'role': 'system', 'content': '[[ REM TEXT-ONLY FINALIZATION ]]\nstale'},
        {'role': 'system', 'content': tool_turns.TOOL_TURN_STATE_PLACEHOLDER + '\nbase'},
        {'role': 'user', 'content': 'hello'},
    ]
    dynamic = tool_turns.render_tool_turn_state('REM', 3, 4, total_tool_results=8, previous_tool_results=3, rem=True)
    prepared = tool_turns.prepare_messages_for_tool_turn(source, dynamic)
    text = '\n'.join(m.get('content', '') for m in prepared)
    assert text.count('[[ REM TOOL ROUND 3/4 ]]') == 1
    assert '[[ REM TOOL ROUND 1/4 ]]' not in text
    assert 'TOOL RESULTS AFTER ROUND' not in text
    assert '[[ REM TEXT-ONLY FINALIZATION ]]' not in text


def test_prepare_messages_for_tool_turn_inserts_when_placeholder_missing():
    source = [
        {'role': 'system', 'content': 'base'},
        {'role': 'user', 'content': 'hello'},
    ]
    dynamic = tool_turns.render_tool_turn_state('PANEL', 1, 3, available_tool_count=4, batch_limit=8)
    prepared = tool_turns.prepare_messages_for_tool_turn(source, dynamic)
    assert len(prepared) == 3
    assert prepared[0] == source[0]
    assert prepared[1]['role'] == 'system'
    assert prepared[1]['content'].startswith('[[ PANEL TOOL ROUND 1/3 ]]')
    assert prepared[2] == source[1]


def test_prepare_messages_for_tool_turn_removes_placeholder_without_dynamic_context():
    source = [
        {'role': 'system', 'content': tool_turns.TOOL_TURN_STATE_PLACEHOLDER + '\nbase'},
        {'role': 'user', 'content': 'hello'},
    ]
    prepared = tool_turns.prepare_messages_for_tool_turn(source, None)
    text = '\n'.join(m.get('content', '') for m in prepared)
    assert tool_turns.TOOL_TURN_STATE_PLACEHOLDER not in text
    assert prepared[0]['content'].strip() == 'base'
    assert source[0]['content'].startswith(tool_turns.TOOL_TURN_STATE_PLACEHOLDER)


def test_render_tool_turn_state_finalization_has_no_tool_results_after_round_header():
    dynamic = tool_turns.render_tool_turn_state('REM', 4, 4, latest_tool_results=1, total_tool_results=9, finalization=True, rem=True)
    assert dynamic.startswith('[[ REM TEXT-ONLY FINALIZATION ]]')
    assert 'latest_tool_results_received = 1' in dynamic
    assert 'total_tool_results_seen = 9' in dynamic
    assert 'TOOL RESULTS AFTER ROUND' not in dynamic
