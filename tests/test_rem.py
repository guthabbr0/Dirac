from dirac import rem, tool_turns


def test_dyslexic_helper_replaces_discord_refs_once():
    text = '<@1504398705539944560> pinged 1504398705539944560 in <#1504398705539944511>'
    mapping = {
        '1504398705539944560': 'Bossman',
        '1504398705539944511': 'Ops channel',
    }
    normalized, replacements = rem.replace_known_discord_refs(text, mapping)
    assert normalized == 'Bossman <1504398705539944560> pinged Bossman <1504398705539944560> in Ops channel <1504398705539944511>'
    assert replacements == [
        {'id': '1504398705539944560', 'label': 'Bossman'},
        {'id': '1504398705539944511', 'label': 'Ops channel'},
    ]
    assert 'Bossman <Bossman' not in normalized


def test_identity_ref_keeps_non_mention_entities_out_of_mention_format():
    assert rem.identity_ref('user', '1504398705539944560') == '<@1504398705539944560>'
    assert rem.identity_ref('channel', '1504398705539944511') == '<#1504398705539944511>'
    assert rem.identity_ref('guild', '1504398705539944000') == 'guild:1504398705539944000'


def test_rem_prompt_uses_dynamic_placeholder_not_rendered_round_state():
    prompt = rem.rem_task_system_prompt()
    assert prompt.startswith(tool_turns.TOOL_TURN_STATE_PLACEHOLDER)
    assert '[[ REM TOOL ROUND 1/4 ]]' not in prompt
    assert '[[ REM TOOL ROUND 2/4 ]]' not in prompt
    assert 'current dynamic tool-round banner is authoritative' in prompt
    assert 'You have 3 REM tool turn(s) left after this call' not in prompt


def test_rem_cut_short_result_is_not_fake_done():
    text = rem.rem_cut_short_result(3, ignored_tool_calls=1, tool_results=4)
    assert 'THIS TASK/REM EVENT WAS CUT SHORT' in text
    assert 'not a successful DONE' in text
    assert 'ignored_tool_calls_in_text_only_finalization=1' in text
    assert not text.startswith('DONE')


def test_rem_ignored_finalization_tools_warning_marks_runtime_text():
    text = rem.rem_ignored_finalization_tools_warning(3, ignored_tool_calls=2, tool_results=5)
    assert 'THIS REM RESULT INCLUDED TEXT' in text
    assert 'text above is model-authored; this warning is runtime-authored' in text
    assert 'ignored_tool_calls_in_text_only_finalization=2' in text
