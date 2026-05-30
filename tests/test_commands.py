import asyncio
import types

import pytest
import bot
from bot import parse_command, CommandHandler, check_permission, utc_now

@pytest.mark.parametrize('text,args,mod',[('!prompt "hello world"',['hello world'],None),('!whitelist add 42 *',['add','42'],{'type':'global','id':None}),('!prompt hi @abc',['hi'],{'type':'specific','id':'abc'}),('!memory add <@123456789012345678> \'likes tea\' tags=a,b',['add','<@123456789012345678>','likes tea','tags=a,b'],None)])
def test_parser(text,args,mod):
    p=parse_command(text); assert p['args']==args; assert p['scope_modifier']==mod

def test_parser_malformed():
    with pytest.raises(ValueError): parse_command('nope')

def test_version_report_and_cli_info(capsys):
    report=bot.version_report()
    assert f'Dirac {bot.APP_VERSION}' in report
    assert 'commit=' in report and 'code_dir=' in report and 'released_at=' in report
    assert bot.handle_cli_info(['--version']) is True
    out=capsys.readouterr().out
    assert f'Dirac {bot.APP_VERSION}' in out and 'commit=' in out

def test_changelog_versions_are_unique():
    versions=[version for version,_ in bot.CHANGELOG]
    assert len(versions)==len(set(versions))

def test_schema_tag_tracks_app_version():
    assert bot.DB_SCHEMA_TAG==bot.APP_VERSION

@pytest.mark.asyncio
async def test_ultimate_emergency_commands_do_not_use_root_or_panel_bypass(db, monkeypatch, runtime_tg):
    bot.runtime_control.resume()
    h=CommandHandler(db,tg=runtime_tg)
    assert await h.handle(parse_command('!stop 5'),'panel','global',None,'panel')=='ultimate_only'
    assert await h.handle(parse_command('!pause'),'admin','dm','s')=='ultimate_only'
    exits=[]
    async def fake_exit(code=0,delay_s=0.25,*,tg):
        exits.append((code,delay_s))
    monkeypatch.setattr(bot,'request_process_exit',fake_exit)
    assert await h.handle(parse_command('!kill'),bot.ROOT_OPERATOR_ID,'dm','s')=='kill requested'
    assert exits==[(0,0.25)]
    bot.runtime_control.resume()

@pytest.mark.asyncio
async def test_stop_drops_non_ultimate_messages_and_suspends_background(db, monkeypatch, runtime_tg):
    bot.runtime_control.resume()
    monkeypatch.setattr(bot,'runtime_metadata_snapshot',lambda: {'pid':123,'uptime_s':0})
    h=CommandHandler(db,tg=runtime_tg)
    stopped=await h.handle(parse_command('!stop 5'),bot.ROOT_OPERATOR_ID,'dm','s')
    assert stopped.startswith('stopped for 5s')
    assert bot.runtime_control.background_suspended()
    class StubOllama:
        def __init__(self): self.calls=[]
        async def chat(self,*args,**kwargs):
            self.calls.append((args,kwargs))
            return {'message':{'content':'should not happen'}}
    ollama=StubOllama()
    core=bot.BotCore(db,ollama,user_id='bot',tg=runtime_tg)
    msg=types.SimpleNamespace(id='drop-1',content='<@bot> loop?',author=types.SimpleNamespace(id='someone',name='Someone'),channel=types.SimpleNamespace(id='s'),guild=None,reference=None,triggered_bot=True)
    assert await core.handle_message(msg) is None
    assert ollama.calls==[]
    cur=await db.execute("SELECT COUNT(*) FROM messages WHERE discord_msg_id='drop-1'")
    assert (await cur.fetchone())[0]==0
    bot.runtime_control.resume()

@pytest.mark.asyncio
async def test_stop_suppresses_inflight_non_ultimate_reply(db, runtime_tg):
    bot.runtime_control.resume()
    class StopDuringChat:
        async def chat(self,*args,**kwargs):
            bot.runtime_control.stop(30,started_by=bot.ROOT_OPERATOR_ID)
            return {'message':{'content':'too late'}}
    class Channel:
        id='s'
        def __init__(self): self.sent=[]
        async def send(self,text): self.sent.append(text)
    channel=Channel()
    msg=types.SimpleNamespace(id='inflight-1',content='<@bot> loop?',author=types.SimpleNamespace(id='someone',name='Someone'),channel=channel,guild=None,reference=None,triggered_bot=True)
    assert await bot.BotCore(db,StopDuringChat(),user_id='bot',tg=runtime_tg).handle_message(msg)=='held'
    assert channel.sent==[]
    bot.runtime_control.resume()

@pytest.mark.asyncio
async def test_pause_collects_but_suppresses_non_ultimate_reply_and_resume_lifts(db, runtime_tg):
    bot.runtime_control.resume()
    h=CommandHandler(db,tg=runtime_tg)
    assert await h.handle(parse_command('!pause'),bot.ROOT_OPERATOR_ID,'dm','s')=='paused until !resume; only the super-admin is answered'
    class StubOllama:
        def __init__(self): self.calls=[]
        async def chat(self,*args,**kwargs):
            self.calls.append((args,kwargs))
            return {'message':{'content':'model reply'}}
    ollama=StubOllama()
    reactions=[]
    async def add_reaction(emoji): reactions.append(emoji)
    channel=types.SimpleNamespace(id='s')
    msg=types.SimpleNamespace(id='pause-1',content='<@bot> are you there?',author=types.SimpleNamespace(id='someone',name='Someone'),channel=channel,guild=None,reference=None,triggered_bot=True,add_reaction=add_reaction)
    assert await bot.BotCore(db,ollama,user_id='bot',tg=runtime_tg).handle_message(msg)=='paused'
    assert ollama.calls==[]
    assert reactions==['\U0001f636']
    cur=await db.execute("SELECT content FROM messages WHERE discord_msg_id='pause-1'")
    assert (await cur.fetchone())[0]=='<@bot> are you there?'
    assert await h.handle(parse_command('!resume'),bot.ROOT_OPERATOR_ID,'dm','s')=='resumed'
    bot.runtime_control.resume()

@pytest.mark.asyncio
async def test_command_effects(db, runtime_tg):
    await db.execute("INSERT INTO permissions(user_id,scope_type,scope_id,level,added_at) VALUES ('admin','global',NULL,'admin',?)",(utc_now(),)); await db.commit()
    h=CommandHandler(db,tg=runtime_tg)
    assert await h.handle(parse_command("!prompt 'be kind'"),'admin','dm','s')=='prompt updated'
    assert await h.handle(parse_command("!prompt 'be direct'"),'admin','dm','s')=='prompt updated'
    cur=await db.execute('SELECT body FROM prompts WHERE scope_type=? AND scope_id=?',('dm','s')); assert (await cur.fetchone())[0]=='be direct'
    cur=await db.execute('SELECT old_body,new_body FROM prompt_history WHERE scope_type=? AND scope_id=? ORDER BY id',('dm','s'))
    assert await cur.fetchall()==[(None,'be kind'),('be kind','be direct')]
    assert await h.handle(parse_command('!whitelist add u1'),'admin','dm','s')=='permission updated'
    assert await check_permission(db,'u1','dm','s','user')
    assert await h.handle(parse_command("!memory add 123456789012345678 'likes tea' tags=drink"),'admin','dm','s')=='memory 1 added'
    assert '#1 discord:123456789012345678 tags=drink' in await h.handle(parse_command('!memory show 123456789012345678'),'admin','dm','s')
    assert await h.handle(parse_command("!memory update #1 'likes coffee' tags=drink confidence=0.9"),'admin','dm','s')=='memory 1 superseded by 2'
    assert 'likes coffee' in await h.handle(parse_command('!memory show 123456789012345678'),'admin','dm','s')
    assert await h.handle(parse_command('!memory delete #2'),'admin','dm','s')=='memory 2 deleted'
    assert 'likes coffee' not in await h.handle(parse_command('!memory show all'),'admin','dm','s')
    assert await h.handle(parse_command('!reasoning high'),'admin','dm','s')=='reasoning high'
    assert await h.handle(parse_command('!reasoning show'),'admin','dm','s')=='reasoning=high scope=dm:s'
    assert await h.handle(parse_command('!reasoning clear'),'admin','dm','s')=='reasoning cleared'
    assert await h.handle(parse_command('!reasoning show'),'admin','dm','s')=='reasoning=inherit(api default) scope=dm:s'
    assert await h.handle(parse_command('!clear'),'admin','dm','s')=='cleared'
    assert await h.handle(parse_command('!clear'),'admin','dm','s')=='cleared'

@pytest.mark.asyncio
async def test_memory_command_help_show_defaults_and_forgiving_id_lookup(db, runtime_tg):
    await db.execute("INSERT INTO permissions(user_id,scope_type,scope_id,level,added_at) VALUES ('admin','global',NULL,'admin',?)",(utc_now(),)); await db.commit()
    h=CommandHandler(db,tg=runtime_tg)
    usage=await h.handle(parse_command('!memory'),'admin','dm','123456789012345678')
    assert '!memory add <discord_id|@user|#channel> <annotations>' in usage
    assert await h.handle(parse_command("!memory add 123456789012345678 'project notes' tags=project"),'admin','dm','123456789012345678')=='memory 1 added'
    assert await h.handle(parse_command("!memory add <@1382894657624866889> 'bot note'"),'admin','dm','123456789012345678')=='memory 2 added'
    assert await h.handle(parse_command("!memory add <#123456789012345679> 'channel note'"),'admin','dm','123456789012345678')=='memory 3 added'
    assert await h.handle(parse_command("!memory add 1382894657624866889 'normalized mention note'"),'admin','dm','123456789012345678')=='memory 4 added'
    current=await h.handle(parse_command('!memory show'),'admin','dm','123456789012345678')
    assert '#1 discord:123456789012345678 tags=project' in current and 'project notes' in current
    both=await h.handle(parse_command('!memory show 123456789012345678'),'admin','dm','123456789012345678')
    assert '#1 discord:123456789012345678' in both
    assert 'bot note' in await h.handle(parse_command('!memory show 1382894657624866889'),'admin','dm','123456789012345678')
    assert 'normalized mention note' in await h.handle(parse_command('!memory show <@1382894657624866889>'),'admin','dm','chan-1')
    assert 'channel note' in await h.handle(parse_command('!memory show <#123456789012345679>'),'admin','dm','123456789012345678')
    all_memories=await h.handle(parse_command('!memory show all'),'admin','dm','123456789012345678')
    assert 'project notes' in all_memories and 'normalized mention note' in all_memories
    bad_show=await h.handle(parse_command('!memory show not-a-snowflake'),'admin','dm','123456789012345678')
    assert bad_show.startswith('Error: expected !memory show')
    bad=await h.handle(parse_command('!memory add only-id'),'admin','dm','123456789012345678')
    assert bad.startswith('Error: expected !memory add') and '!memory show <id>' in bad

@pytest.mark.asyncio
async def test_global_prompt_rejects_scoped_id(db, runtime_tg):
    await db.execute("INSERT INTO permissions(user_id,scope_type,scope_id,level,added_at) VALUES ('admin','global',NULL,'admin',?)",(utc_now(),)); await db.commit()
    h=CommandHandler(db,tg=runtime_tg)
    assert await h.handle(parse_command("!prompt orphan @channel"),'admin','global',None)=='bad_args'
    cur=await db.execute('SELECT COUNT(*) FROM prompts')
    assert (await cur.fetchone())[0]==0

@pytest.mark.asyncio
async def test_whitelist_protects_root_operator(db, runtime_tg):
    await db.execute("INSERT INTO permissions(user_id,scope_type,scope_id,level,added_at) VALUES ('admin','global',NULL,'admin',?)",(utc_now(),)); await db.commit()
    h=CommandHandler(db,tg=runtime_tg)
    assert await h.handle(parse_command(f'!whitelist block {bot.ROOT_OPERATOR_ID}'),'admin','dm','s')=='protected root'
    assert await h.handle(parse_command(f'!whitelist add {bot.ROOT_OPERATOR_ID} admin'),'admin','dm','s')=='protected root'
    assert await h.handle(parse_command(f'!whitelist add {bot.ROOT_OPERATOR_ID} root *'),'admin','dm','s')=='permission updated'
    cur=await db.execute('SELECT scope_type,scope_id,level FROM permissions WHERE user_id=?',(bot.ROOT_OPERATOR_ID,))
    assert await cur.fetchall()==[('global',None,'root')]

@pytest.mark.asyncio
async def test_admin_help_docs_and_config_redaction(db, monkeypatch, runtime_tg):
    await db.execute("INSERT INTO permissions(user_id,scope_type,scope_id,level,added_at) VALUES ('admin','global',NULL,'admin',?)",(utc_now(),)); await db.commit()
    monkeypatch.setattr(bot.app.state,'config',types.SimpleNamespace(
        ollama={'endpoint':'https://ollama.com','api_key':'real-key','default_model':'m'},
        discord={'token':'real-token','i_understand_selfbot_risk':True},
        panel={'auth_token':'real-panel-token','host':'127.0.0.1','port':8765},
        bot={'trigger_on':['ping','reply']},
    ))
    h=CommandHandler(db,tg=runtime_tg)
    overview=await h.handle(parse_command('!help all'),'admin','dm','s')
    assert 'Dirac admin help' in overview and '!whitelist' in overview
    cfg=await h.handle(parse_command('!help config'),'admin','dm','s')
    assert '***' in cfg and 'real-key' not in cfg and 'real-token' not in cfg and 'real-panel-token' not in cfg
    docs=await h.handle(parse_command('!help docs admin'),'admin','dm','s')
    assert 'Dirac Admin Help' in docs

@pytest.mark.asyncio
async def test_status_reports_scope_usage(db, runtime_tg):
    await db.execute("INSERT INTO permissions(user_id,scope_type,scope_id,level,added_at) VALUES ('admin','global',NULL,'admin',?)",(utc_now(),))
    await db.execute("INSERT INTO ollama_log(scope_type,scope_id,model,prompt_tokens,completion_tokens,latency_ms,request_json,timestamp_utc) VALUES ('dm','s','m',12,34,56,'{}',?)",(utc_now(),))
    await db.commit()
    result=await CommandHandler(db,tg=runtime_tg).handle(parse_command('!status'),'admin','dm','s')
    assert 'prompt_tokens=12' in result and 'completion_tokens=34' in result

@pytest.mark.asyncio
async def test_reasoning_rejects_bad_mode(db, runtime_tg):
    await db.execute("INSERT INTO permissions(user_id,scope_type,scope_id,level,added_at) VALUES ('admin','global',NULL,'admin',?)",(utc_now(),)); await db.commit()
    result=await CommandHandler(db,tg=runtime_tg).handle(parse_command('!reasoning turbo'),'admin','dm','s')
    assert result=='bad_args'

@pytest.mark.asyncio
async def test_root_only_create_agent_tool_and_skill(db, monkeypatch, runtime_tg):
    async def fake_schedule(*args,**kwargs):
        return None
    monkeypatch.setattr(bot,'schedule_agent_task',fake_schedule)
    h=CommandHandler(db,tg=runtime_tg)
    assert await h.handle(parse_command('!create solve this'),'not-root','dm','s')=='root_only'
    result=await h.handle(parse_command('!create solve this'),'1482143139828596916','dm','s')
    assert result.startswith('agent task ') and result.endswith(' queued')
    cur=await db.execute("SELECT kind,prompt,status,requested_by FROM agent_tasks WHERE kind='create'")
    assert await cur.fetchone()==('create','solve this','queued','1482143139828596916')
    result=await h.handle(parse_command('!tools add scout searches things'),'panel','global',None,'panel')
    assert result.startswith('tool scout saved for global:*; agent task ')
    assert '!tool show <#id|name>' in await h.handle(parse_command('!tools'),'panel','global',None,'panel')
    assert 'scout' in await h.handle(parse_command('!tool show'),'panel','global',None,'panel')
    assert 'description:' in await h.handle(parse_command('!tool show scout'),'panel','global',None,'panel')
    assert await h.handle(parse_command('!tool disable scout'),'panel','global',None,'panel')=='tool scout disabled for global:*'
    scout_summary=await h.handle(parse_command('!tool show'),'panel','global',None,'panel')
    assert 'scout' in scout_summary and 'off' in scout_summary and '[' not in scout_summary
    assert 'scout' not in await bot.active_asset_names(db,'tool','global',None)
    assert await h.handle(parse_command('!tool enable scout'),'panel','global',None,'panel')=='tool scout enabled for global:*'
    assert await h.handle(parse_command('!tool delete scout'),'panel','global',None,'panel')=='tool scout deleted from global:*'
    assert 'current_time' in await bot.active_asset_names(db,'tool','global',None)
    assert await h.handle(parse_command('!tool delete current_time *'),'panel','dm','s','panel')=='tool current_time deleted from global:*'
    assert 'current_time' not in await bot.active_asset_names(db,'tool','global',None)
    cur=await db.execute("SELECT COUNT(*) FROM agent_assets WHERE asset_type='tool' AND name='current_time' AND scope_type='global'")
    assert (await cur.fetchone())[0]==0
    fixed=await h.handle(parse_command('!tool fix'),'panel','dm','s','panel')
    assert fixed.startswith('tool snapshot ')
    assert 'current_time' in await bot.active_asset_names(db,'tool','global',None)
    result=await h.handle(parse_command('!skills add research summarize sources'),'panel','global',None,'panel')
    assert result.startswith('skill research saved for global:*; agent task ')
    tools=await h.handle(parse_command('!agent tools'),'panel','global',None,'panel')
    assert 'default_backend' in tools

@pytest.mark.asyncio
async def test_scoped_disabled_tool_is_not_active_or_in_context(db, monkeypatch, runtime_tg):
    async def fake_schedule(*args,**kwargs):
        return None
    monkeypatch.setattr(bot,'schedule_agent_task',fake_schedule)
    h=CommandHandler(db,tg=runtime_tg)
    assert 'current_time' in await bot.active_asset_names(db,'tool','dm','s')
    assert await h.handle(parse_command('!tool disable current_time'),'panel','dm','s','panel')=='tool current_time disabled for dm:s'
    assert 'current_time' not in await bot.active_asset_names(db,'tool','dm','s')
    assert 'current_time' in await bot.active_asset_names(db,'tool','dm','other')
    context=await bot.assets_context_note(db,'dm','s')
    assert 'current_time' not in context
    assembled=await bot.assemble_context(db,'dm','s')
    assert 'Use the current_time tool' not in assembled[0]['content']
    schemas=await bot.discord_tools_for_scope(db,'dm','s')
    assert all(schema['function']['name']!='current_time' for schema in schemas)
    result=await bot.run_discord_tool_calls(db,types.SimpleNamespace(),[{'function':{'name':'current_time','arguments':{}}}],'dm','s','u','bot')
    assert result['results'][0]['ok'] is False and result['results'][0]['error']=='tool_not_enabled_or_unknown'

@pytest.mark.asyncio
async def test_tool_edit_snapshot_and_global_disable(db, monkeypatch, runtime_tg):
    async def fake_schedule(*args,**kwargs):
        return None
    monkeypatch.setattr(bot,'schedule_agent_task',fake_schedule)
    h=CommandHandler(db,tg=runtime_tg)
    assert await h.handle(parse_command('!tool edit current_time description broken *'),'panel','dm','s','panel')=='tool current_time description updated for global:*'
    assert 'broken' in await h.handle(parse_command('!tool show current_time *'),'panel','dm','s','panel')
    schema='{"name":"current_time","description":"clock","parameters":{"type":"object","properties":{}}}'
    assert await h.handle(parse_command(f"!tool edit current_time schema '{schema}' *"),'panel','dm','s','panel')=='tool current_time schema updated for global:*'
    assert 'clock' in await h.handle(parse_command('!tool show current_time *'),'panel','dm','s','panel')
    assert await h.handle(parse_command('!tool edit current_time executor none *'),'panel','dm','s','panel')=='tool current_time executor updated for global:*'
    shown=await h.handle(parse_command('!tool show current_time *'),'panel','dm','s','panel')
    assert 'executor=-' in shown
    assert await h.handle(parse_command('!tool edit current_time executor current_time *'),'panel','dm','s','panel')=='tool current_time executor updated for global:*'
    assert await h.handle(parse_command('!tool edit current_time enabled false *'),'panel','dm','s','panel')=='tool current_time enabled updated for global:*'
    assert 'globally_disabled=true' in await h.handle(parse_command('!tool show current_time *'),'panel','dm','s','panel')
    fixed=await h.handle(parse_command('!tool fix'),'panel','dm','s','panel')
    assert fixed.startswith('tool snapshot ')
    assert 'broken' not in await h.handle(parse_command('!tool show current_time *'),'panel','dm','s','panel')
    assert await h.handle(parse_command('!tool disable silencer *'),'panel','dm','s','panel')=='tool silencer disabled for global:*'
    assert 'silencer' not in await bot.active_asset_names(db,'tool','dm','s')
    schemas=await bot.discord_tools_for_scope(db,'dm','s')
    assert all(schema['function']['name']!='silencer' for schema in schemas)
    assert await h.handle(parse_command('!tool enable silencer *'),'panel','dm','s','panel')=='tool silencer enabled for global:*'
    assert 'silencer' in await bot.active_asset_names(db,'tool','dm','s')

@pytest.mark.asyncio
async def test_tool_effective_output_and_numeric_ids_match_global_disable_reality(db, monkeypatch, runtime_tg):
    async def fake_schedule(*args,**kwargs):
        return None
    monkeypatch.setattr(bot,'schedule_agent_task',fake_schedule)
    h=CommandHandler(db,tg=runtime_tg)
    assert await h.handle(parse_command('!tool disable silencer *'),'panel','guild','g','panel')=='tool silencer disabled for global:*'
    scoped_enable=await h.handle(parse_command('!tool enable silencer'),'panel','guild','g','panel')
    assert scoped_enable.startswith('tool silencer enabled for guild:g')
    assert 'effective state is still disabled because global disable is active' in scoped_enable
    cur=await db.execute("SELECT id FROM agent_assets WHERE name='silencer' AND scope_type='guild' AND scope_id='g'")
    scoped_id=(await cur.fetchone())[0]
    summary=await h.handle(parse_command('!tool show'),'panel','guild','g','panel')
    assert 'Order: name A-Z. Use #ID or name' in summary
    assert f'#{scoped_id}' in summary and 'off(global)' in summary and '[1]' not in summary
    detail=await h.handle(parse_command(f'!tool show {scoped_id}'),'panel','guild','g','panel')
    assert 'effective_state=disabled' in detail
    assert 'stored_state=enabled' in detail
    assert 'globally_disabled=false' in detail
    assert 'disabled_by_global=true' in detail
    assert await h.handle(parse_command(f'!tool show #{scoped_id}'),'panel','guild','g','panel')==detail
    assert await h.handle(parse_command(f'!tool enable {scoped_id} *'),'panel','guild','g','panel')=='not found for global:*'
    assert await h.handle(parse_command('!tool enable silencer *'),'panel','guild','g','panel')=='tool silencer enabled for global:*'
    assert 'silencer' in await bot.active_asset_names(db,'tool','guild','g')

@pytest.mark.asyncio
async def test_version_changelog_and_recurring_task_commands(db, monkeypatch, runtime_tg):
    async def fake_schedule(*args,**kwargs):
        return None
    monkeypatch.setattr(bot,'schedule_agent_task',fake_schedule)
    await db.execute("INSERT INTO permissions(user_id,scope_type,scope_id,level,added_at) VALUES ('admin','global',NULL,'admin',?)",(utc_now(),)); await db.commit()
    h=CommandHandler(db,tg=runtime_tg)
    version=await h.handle(parse_command('!version'),'admin','dm','s')
    assert f'Dirac {bot.APP_VERSION}' in version and 'web_fetch' in version and 'REM tasks' in version
    changelog=await h.handle(parse_command('!changelog'),'admin','dm','s')
    assert 'Dirac changelog' in changelog and bot.APP_VERSION in changelog and 'canonical memory schema' in changelog
    created=await h.handle(parse_command('!task add sweep every 5m check status'),'panel','dm','s','panel')
    assert created.startswith('task ') and created.endswith(' scheduled every 5m for dm:s')
    sweep_id=int(created.split()[1])
    listed=await h.handle(parse_command('!task show'),'panel','dm','s','panel')
    assert 'Recurring tasks visible for dm:s' in listed and 'sweep' in listed and 'next=' in listed and 'Europe/Madrid' in listed
    assert '!task help|add|show|edit|run|enable|disable|delete|fix' in await h.handle(parse_command('!help'),'admin','dm','s')
    assert 'prompt=check status' in await h.handle(parse_command('!task show sweep'),'panel','dm','s','panel')
    assert await h.handle(parse_command('!task edit sweep prompt check memory'),'panel','dm','s','panel')==f'task {sweep_id} prompt updated'
    assert 'prompt=check memory' in await h.handle(parse_command('!task show sweep'),'panel','dm','s','panel')
    assert await h.handle(parse_command('!task edit sweep runtime_kind rem'),'panel','dm','s','panel')==f'task {sweep_id} runtime_kind updated'
    assert 'runtime_kind=rem' in await h.handle(parse_command('!task show sweep'),'panel','dm','s','panel')
    fixed=await h.handle(parse_command('!task fix'),'panel','dm','s','panel')
    assert fixed.startswith('task snapshot ')
    assert await h.handle(parse_command('!task run sweep'),'panel','dm','s','panel')==f'task {sweep_id} queued'
    assert await h.handle(parse_command('!task enable sweep'),'panel','dm','s','panel')==f'task {sweep_id} enabled'
    cur=await db.execute('SELECT enabled,next_run_utc FROM agent_tasks WHERE id=?',(sweep_id,))
    enabled,next_run=await cur.fetchone()
    assert enabled==1 and next_run is not None
    assert await h.handle(parse_command('!task disable sweep'),'panel','dm','s','panel')==f'task {sweep_id} disabled'
    assert await h.handle(parse_command('!task delete sweep'),'panel','dm','s','panel')==f'task {sweep_id} deleted'
    remaining=await h.handle(parse_command('!task show'),'panel','dm','s','panel')
    assert 'Recurring tasks visible for dm:s' in remaining and 'rem_dream' in remaining and 'sweep' not in remaining

@pytest.mark.asyncio
async def test_recurring_task_ids_are_scope_checked(db, monkeypatch, runtime_tg):
    async def fake_schedule(*args,**kwargs):
        return None
    monkeypatch.setattr(bot,'schedule_agent_task',fake_schedule)
    h=CommandHandler(db,tg=runtime_tg)
    local_created=await h.handle(parse_command('!tasks add local every 5m check local'),'panel','dm','s','panel')
    other_created=await h.handle(parse_command('!tasks add other every 5m check other'),'panel','dm','other','panel')
    global_created=await h.handle(parse_command('!tasks add global every 5m check global *'),'panel','dm','s','panel')
    local_id=int(local_created.split()[1]); other_id=int(other_created.split()[1]); global_id=int(global_created.split()[1])
    assert local_created.endswith('scheduled every 5m for dm:s')
    assert other_created.endswith('scheduled every 5m for dm:other')
    assert global_created.endswith('scheduled every 5m for global:*')
    assert await h.handle(parse_command(f'!tasks show {other_id}'),'panel','dm','s','panel')=='not found'
    assert await h.handle(parse_command(f'!tasks run {other_id}'),'panel','dm','s','panel')=='not found'
    assert await h.handle(parse_command(f'!tasks disable {other_id}'),'panel','dm','s','panel')=='not found'
    assert await h.handle(parse_command(f'!tasks delete {other_id}'),'panel','dm','s','panel')=='not found'
    assert f'#{local_id} local [dm:s]' in await h.handle(parse_command(f'!tasks show {local_id}'),'panel','dm','s','panel')
    assert f'#{global_id} global [global:*]' in await h.handle(parse_command(f'!tasks show {global_id}'),'panel','dm','s','panel')
    assert await h.handle(parse_command(f'!tasks show {local_id} *'),'panel','dm','s','panel')=='not found'

@pytest.mark.asyncio
async def test_provider_and_scope_commands_are_root_only_and_effective(db, monkeypatch, runtime_tg):
    h=CommandHandler(db,tg=runtime_tg)
    assert await h.handle(parse_command('!providers list'),'not-root','dm','s')=='root_only'
    providers=await h.handle(parse_command('!providers list'),'panel','dm','s','panel')
    assert 'ollama-default' in providers and '"api_key":' not in providers and '"api_key_encrypted":' not in providers
    assert await h.handle(parse_command('!providers show ollama-default'),'panel','dm','s','panel')
    assert await h.handle(parse_command('!scope provider ollama-default scope-model'),'panel','dm','s','panel')=='scope dm:s provider=ollama-default model=scope-model'
    shown=await h.handle(parse_command('!scope show'),'panel','dm','s','panel')
    assert '"model": "scope-model"' in shown and '"source_chain"' in shown
    assert await h.handle(parse_command('!scope params default-balanced'),'panel','dm','s','panel')=='scope dm:s params=default-balanced'
    assert await h.handle(parse_command('!scope reset-provider'),'panel','dm','s','panel')=='scope dm:s provider reset'

@pytest.mark.asyncio
async def test_run_agent_task_completes(db):
    task_id=await bot.create_agent_task(db,'create','solve','panel','panel','global',None)
    class StubOllama:
        async def chat(self,*args,**kwargs): return {'message':{'content':'done'}}
    await bot.run_agent_task(db,StubOllama(),task_id)
    cur=await db.execute('SELECT status,result FROM agent_tasks WHERE id=?',(task_id,))
    assert await cur.fetchone()==('completed','done')

@pytest.mark.asyncio
async def test_rem_task_cut_short_warning_replaces_fake_done(db):
    task_id=await bot.create_agent_task(db,'task','assimilate visible slice','panel','panel','global',None,name='rem-test',runtime_kind='rem')
    class StubbornRemOllama:
        def __init__(self): self.calls=[]
        async def chat(self,messages,tools=None,**kwargs):
            prepared=bot.tool_turns.prepare_messages_for_tool_turn(messages,kwargs.get('dynamic_context'))
            self.calls.append({'messages':prepared,'raw_messages':[dict(m) for m in messages],'tools':tools})
            return {'message':{'content':'','tool_calls':[{'function':{'name':'current_time','arguments':{}}}]}}
    ollama=StubbornRemOllama()
    await bot.run_agent_task(db,ollama,task_id)
    cur=await db.execute('SELECT status,result FROM agent_tasks WHERE id=?',(task_id,))
    status,result=await cur.fetchone()
    assert status=='completed'
    assert result.startswith('[DIRAC_RUNTIME_GENERATED_TASK_WARNING]')
    assert 'THIS TASK/REM EVENT WAS CUT SHORT' in result
    assert 'not a successful DONE' in result
    assert 'DONE: no durable memory changes were needed' not in result
    first_text='\n'.join(m.get('content','') for m in ollama.calls[0]['messages'])
    second_text='\n'.join(m.get('content','') for m in ollama.calls[1]['messages'])
    final_text='\n'.join(m.get('content','') for m in ollama.calls[-1]['messages'])
    raw_text='\n'.join(m.get('content','') for call in ollama.calls for m in call['raw_messages'])
    assert first_text.count('[[ REM TOOL ROUND 1/4 ]]')==1
    assert second_text.count('[[ REM TOOL ROUND 2/4 ]]')==1
    assert '[[ REM TOOL ROUND 1/4 ]]' not in second_text
    assert final_text.count('[[ REM TEXT-ONLY FINALIZATION ]]')==1
    assert '[[ REM TOOL ROUND' not in raw_text
    assert '[[ REM TEXT-ONLY FINALIZATION ]]' not in raw_text
    events=await bot.recent_memory_events(db,10,50)
    assert 'THIS TASK/REM EVENT WAS CUT SHORT' in '\n'.join(row['content'] for row in events)

@pytest.mark.asyncio
async def test_rem_task_marks_ignored_finalization_tools_when_text_exists(db):
    task_id=await bot.create_agent_task(db,'task','assimilate visible slice','panel','panel','global',None,name='rem-text-and-tool',runtime_kind='rem')
    class TextAndToolFinalizationOllama:
        def __init__(self): self.calls=0
        async def chat(self,messages,tools=None,**kwargs):
            self.calls+=1
            if tools is None:
                return {'message':{'content':'DONE\n- assimilated available slice','tool_calls':[{'function':{'name':'current_time','arguments':{}}}]}}
            return {'message':{'content':'','tool_calls':[{'function':{'name':'current_time','arguments':{}}}]}}
    await bot.run_agent_task(db,TextAndToolFinalizationOllama(),task_id)
    cur=await db.execute('SELECT result FROM agent_tasks WHERE id=?',(task_id,))
    result=(await cur.fetchone())[0]
    assert result.startswith('DONE\n- assimilated available slice')
    assert 'THIS REM RESULT INCLUDED TEXT' in result
    assert 'ignored_tool_calls_in_text_only_finalization=1' in result

@pytest.mark.asyncio
async def test_recurring_agent_task_reschedules(db):
    task_id=await bot.create_agent_task(db,'task','solve','panel','panel','global',None,name='loop',enabled=True,schedule_minutes=5,next_run_utc=bot.utc_now(),max_runs=2)
    class StubOllama:
        async def chat(self,*args,**kwargs): return {'message':{'content':'done'}}
    await bot.run_agent_task(db,StubOllama(),task_id)
    cur=await db.execute('SELECT status,result,next_run_utc,run_count FROM agent_tasks WHERE id=?',(task_id,))
    status,result,next_run,run_count=await cur.fetchone()
    assert status=='completed' and result=='done' and next_run is not None and run_count==1

@pytest.mark.asyncio
async def test_schedule_agent_task_accepts_scheduler_next_run_flag(db, monkeypatch, runtime_tg):
    calls=[]
    async def fake_run(*args,**kwargs):
        calls.append((args,kwargs))
    monkeypatch.setattr(bot,'run_agent_task',fake_run)
    assert await bot.schedule_agent_task(db,object(),123,trigger_source='scheduler',triggered_by='scheduler',advance_next_run_on_finish=False,tg=runtime_tg) is True
    assert await bot.schedule_agent_task(db,object(),124,trigger_source='panel',triggered_by='panel',tg=runtime_tg) is True
    await asyncio.sleep(0)
    assert [call[1]['advance_next_run_on_finish'] for call in calls]==[False,True]

@pytest.mark.asyncio
async def test_scheduler_picks_one_due_task_and_advances_before_launch(db, monkeypatch, runtime_tg):
    class StopScheduler(Exception):
        pass
    launched=[]
    async def stop_after_tick(_delay):
        raise StopScheduler()
    async def fake_schedule(*args,**kwargs):
        launched.append((args,kwargs))
        return True
    monkeypatch.setattr(bot.asyncio,'sleep',stop_after_tick)
    monkeypatch.setattr(bot.random,'choice',lambda rows: rows[0])
    monkeypatch.setattr(bot,'schedule_agent_task',fake_schedule)
    chosen=await bot.create_agent_task(db,'task','chosen','panel','panel','global',None,name='chosen',enabled=True,schedule_minutes=5,next_run_utc=bot.utc_now())
    other=await bot.create_agent_task(db,'task','other','panel','panel','global',None,name='other',enabled=True,schedule_minutes=5,next_run_utc=bot.utc_now())
    running=await bot.create_agent_task(db,'task','running','panel','panel','global',None,name='running',enabled=True,schedule_minutes=5,next_run_utc=bot.utc_now())
    await db.execute("UPDATE agent_tasks SET status='queued' WHERE id=?",(chosen,))
    await db.execute("UPDATE agent_tasks SET status='completed' WHERE id=?",(other,))
    await db.execute("UPDATE agent_tasks SET status='running' WHERE id=?",(running,))
    await db.commit()
    with pytest.raises(StopScheduler):
        await bot.agent_task_scheduler(db,object(),poll_interval_s=30,tg=runtime_tg)
    assert len(launched)==1
    assert launched[0][0][2]==chosen
    assert launched[0][1]['trigger_source']=='scheduler'
    assert launched[0][1]['advance_next_run_on_finish'] is False
    cur=await db.execute('SELECT status,next_run_utc FROM agent_tasks WHERE id=?',(chosen,))
    status,next_run=await cur.fetchone()
    assert status=='running' and next_run is not None
    cur=await db.execute('SELECT status FROM agent_tasks WHERE id=?',(other,))
    assert (await cur.fetchone())[0]=='completed'

@pytest.mark.asyncio
async def test_scheduler_launches_due_task_even_if_status_is_running(db, monkeypatch, runtime_tg):
    class StopScheduler(Exception):
        pass
    launched=[]
    async def stop_after_tick(_delay):
        raise StopScheduler()
    async def fake_schedule(*args,**kwargs):
        launched.append((args,kwargs))
        return True
    monkeypatch.setattr(bot.asyncio,'sleep',stop_after_tick)
    monkeypatch.setattr(bot.random,'choice',lambda rows: rows[0])
    monkeypatch.setattr(bot,'schedule_agent_task',fake_schedule)
    task_id=await bot.create_agent_task(db,'task','still due','panel','panel','global',None,name='due_running',enabled=True,schedule_minutes=5,next_run_utc=bot.utc_now())
    await db.execute("UPDATE agent_tasks SET status='running' WHERE id=?",(task_id,))
    await db.commit()
    with pytest.raises(StopScheduler):
        await bot.agent_task_scheduler(db,object(),poll_interval_s=30,tg=runtime_tg)
    assert len(launched)==1
    assert launched[0][0][2]==task_id
    assert launched[0][1]['advance_next_run_on_finish'] is False

@pytest.mark.asyncio
async def test_scheduler_launches_due_task_through_runtime_db_wrapper(monkeypatch, runtime_tg):
    class StopScheduler(Exception):
        pass
    launched=[]
    async def stop_after_tick(_delay):
        raise StopScheduler()
    async def fake_schedule(*args,**kwargs):
        launched.append((args,kwargs))
        return True
    writer=await bot.DbWriter.for_memory(); await writer.start(runtime_tg)
    runtime_db=bot.RuntimeDb(writer)
    try:
        monkeypatch.setattr(bot.asyncio,'sleep',stop_after_tick)
        monkeypatch.setattr(bot.random,'choice',lambda rows: rows[0])
        monkeypatch.setattr(bot,'schedule_agent_task',fake_schedule)
        task_id=await bot.create_agent_task(runtime_db,'task','via runtime db','panel','panel','global',None,name='runtime-loop',enabled=True,schedule_minutes=5,next_run_utc=bot.utc_now())
        with pytest.raises(StopScheduler):
            await bot.agent_task_scheduler(runtime_db,object(),poll_interval_s=30,tg=runtime_tg)
        assert len(launched)==1
        assert launched[0][0][2]==task_id
        assert launched[0][1]['advance_next_run_on_finish'] is False
    finally:
        await writer.close()

@pytest.mark.asyncio
async def test_scheduled_task_runner_preserves_preadvanced_next_run(db):
    task_id=await bot.create_agent_task(db,'task','solve','panel','panel','global',None,name='loop',enabled=True,schedule_minutes=5,next_run_utc='2099-01-01T00:00:00.000Z',max_runs=2)
    class StubOllama:
        async def chat(self,*args,**kwargs): return {'message':{'content':'done'}}
    await bot.run_agent_task(db,StubOllama(),task_id,advance_next_run_on_finish=False)
    cur=await db.execute('SELECT status,result,next_run_utc,run_count FROM agent_tasks WHERE id=?',(task_id,))
    assert await cur.fetchone()==('completed','done','2099-01-01T00:00:00.000Z',1)

@pytest.mark.asyncio
async def test_scheduled_task_runner_preserves_newer_preadvanced_next_run(db):
    old_next='2099-01-01T00:00:00.000Z'
    newer_next='2099-01-01T00:05:00.000Z'
    task_id=await bot.create_agent_task(db,'task','solve','panel','panel','global',None,name='overlap-loop',enabled=True,schedule_minutes=5,next_run_utc=old_next,max_runs=5)
    class UpdatingOllama:
        async def chat(self,*args,**kwargs):
            await db.execute('UPDATE agent_tasks SET next_run_utc=? WHERE id=?',(newer_next,task_id))
            await db.commit()
            return {'message':{'content':'done'}}
    await bot.run_agent_task(db,UpdatingOllama(),task_id,advance_next_run_on_finish=False)
    cur=await db.execute('SELECT status,result,next_run_utc,run_count FROM agent_tasks WHERE id=?',(task_id,))
    assert await cur.fetchone()==('completed','done',newer_next,1)

@pytest.mark.asyncio
async def test_recurring_agent_task_can_deliver_to_discord_scope(db):
    task_id=await bot.create_agent_task(db,'task','say hello','panel','panel','guild','123',name='hello',enabled=True,schedule_minutes=5,next_run_utc=bot.utc_now(),max_runs=2)
    class StubOllama:
        async def chat(self,*args,**kwargs): return {'message':{'content':'hello channel'}}
    class Channel:
        def __init__(self): self.sent=[]
        async def send(self,text): self.sent.append(text)
    ch=Channel()
    class Client:
        def get_channel(self,channel_id): return ch if channel_id==123 else None
    await bot.run_agent_task(db,StubOllama(),task_id,client=Client())
    assert ch.sent==['hello channel']

@pytest.mark.asyncio
async def test_run_agent_task_cancelled_marks_failed(db):
    task_id=await bot.create_agent_task(db,'task','solve','panel','panel','global',None,name='cancel-me',enabled=True,schedule_minutes=5,next_run_utc=bot.utc_now())
    class CancelOllama:
        async def chat(self,*args,**kwargs):
            raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await bot.run_agent_task(db,CancelOllama(),task_id)
    cur=await db.execute('SELECT status,error,next_run_utc FROM agent_tasks WHERE id=?',(task_id,))
    status,error,next_run=await cur.fetchone()
    assert status=='failed' and error=='cancelled' and next_run is not None

@pytest.mark.asyncio
async def test_reconcile_orphan_agent_tasks_recovers_stuck_rows(db):
    running_id=await bot.create_agent_task(db,'task','a','panel','panel','global',None,name='stuck-running',enabled=True,schedule_minutes=5,next_run_utc=bot.utc_now())
    queued_id=await bot.create_agent_task(db,'task','b','panel','panel','global',None,name='stuck-queued',enabled=True,schedule_minutes=5,next_run_utc=bot.utc_now())
    disabled_id=await bot.create_agent_task(db,'task','c','panel','panel','global',None,name='stuck-disabled',enabled=False,schedule_minutes=5)
    await db.execute("UPDATE agent_tasks SET status='running' WHERE id=?",(running_id,))
    await db.execute("UPDATE agent_tasks SET status='queued' WHERE id=?",(queued_id,))
    await db.execute("UPDATE agent_tasks SET status='running' WHERE id=?",(disabled_id,))
    await db.commit()
    reclaimed=await bot.reconcile_orphan_agent_tasks(db)
    assert reclaimed==3
    cur=await db.execute('SELECT id,status,next_run_utc FROM agent_tasks WHERE id IN (?,?,?) ORDER BY id',(running_id,queued_id,disabled_id))
    rows={row[0]:(row[1],row[2]) for row in await cur.fetchall()}
    assert rows[running_id][0]=='failed' and rows[running_id][1] is not None
    assert rows[queued_id][0]=='failed' and rows[queued_id][1] is not None
    # disabled+stuck must still be cleared but should not be re-scheduled
    assert rows[disabled_id][0]=='failed' and rows[disabled_id][1] is None
    assert await bot.reconcile_orphan_agent_tasks(db)==0

@pytest.mark.asyncio
async def test_news_summary_stores_memory(db, monkeypatch):
    seen={}
    async def fake_known(limit=bot.news_mod.KNOWN_NEWS_LIMIT):
        seen['known_limit']=limit
        return [{'title':'AI model release','url':'https://example.test/known','link':'https://example.test/known','source':'x','source_kind':'grounding','published_at_utc':'2026-05-23T10:00:00.000Z','date_status':'fresh'}]
    async def fake_exploratory(limit=bot.news_mod.EXPLORATORY_NEWS_LIMIT,fetcher=None):
        seen['exploratory_limit']=limit
        return [{'title':'Agent benchmark update','url':'https://example.test/explore','link':'https://example.test/explore','source':'example.test','source_kind':'exploratory','published_at_utc':None,'date_status':'unknown'}]
    monkeypatch.setattr(bot,'fetch_known_news',fake_known)
    monkeypatch.setattr(bot,'fetch_exploratory_news',fake_exploratory)
    class StubOllama:
        async def chat(self,*args,**kwargs): return {'message':{'content':'Brief news'}}
    result=await bot.build_news_summary(db,StubOllama(),store_memory=True,news_channel_id='123456789012345678')
    assert result=='Brief news'
    assert seen['known_limit']==bot.news_mod.KNOWN_NEWS_LIMIT*3
    assert seen['exploratory_limit']==bot.news_mod.EXPLORATORY_NEWS_LIMIT
    cur=await db.execute("SELECT str_annotations,array_tags FROM memories WHERE str_discord_id=?",('123456789012345678',))
    annotations,tags=await cur.fetchone()
    assert tags=='["news", "ai", "tech"]'
    assert 'Brief news' in annotations and 'AI model release' in annotations and 'Agent benchmark update' in annotations
    cur=await db.execute("SELECT url,last_posted_utc,posted_count FROM news_items ORDER BY url")
    rows=await cur.fetchall()
    assert len(rows)==2
    assert all(row[1] and row[2]==1 for row in rows)

@pytest.mark.asyncio
async def test_news_summary_logs_empty_feed(db, monkeypatch):
    async def fake_known(limit=bot.news_mod.KNOWN_NEWS_LIMIT):
        return []
    async def fake_exploratory(limit=bot.news_mod.EXPLORATORY_NEWS_LIMIT,fetcher=None):
        return []
    monkeypatch.setattr(bot,'fetch_known_news',fake_known)
    monkeypatch.setattr(bot,'fetch_exploratory_news',fake_exploratory)
    monkeypatch.setattr(bot.app.state,'db',db)
    result=await bot.build_news_summary(db,None,store_memory=True,news_channel_id='configured-channel')
    assert result=='No AI/model news feed items could be fetched right now.'
    cur=await db.execute("SELECT level,component,message FROM bot_logs WHERE component='news' ORDER BY id DESC LIMIT 1")
    assert await cur.fetchone()==('warn','news','news fetch returned no items')

@pytest.mark.asyncio
async def test_news_scheduler_sends_startup_build_banner_and_news(db, monkeypatch):
    sent=[]
    calls=[]
    class Channel:
        async def send(self,text): sent.append(text)
    class Client:
        user=types.SimpleNamespace(name='DiracTest')
        def get_channel(self,channel_id): return Channel() if channel_id==123 else None
    async def fake_summary(*args,**kwargs):
        calls.append(kwargs)
        return 'Brief news'
    async def stop_after_startup(delay):
        raise asyncio.CancelledError
    monkeypatch.setattr(bot,'build_news_summary',fake_summary)
    monkeypatch.setattr(bot.asyncio,'sleep',stop_after_startup)
    cfg=types.SimpleNamespace(bot={'news_channel_id':'123','news_summary_interval_minutes':5,'news_memory_interval_minutes':420})
    with pytest.raises(asyncio.CancelledError):
        await bot.news_scheduler(Client(),db,None,cfg)
    assert f'DiracTest online: Dirac {bot.APP_VERSION}' in sent[0]
    assert 'commit:' in sent[0] and 'release time:' in sent[0]
    assert sent[1]=='Brief news'
    assert calls and calls[0]['store_memory'] is True and calls[0]['news_channel_id']=='123'

def test_tech_news_helpers_cap_and_filter():
    assert bot.tech_news_limit(12)==bot.TECH_NEWS_MAX_ITEMS
    items=[]
    assert not bot.add_tech_news_item(items,'Ebola outbreak report','https://example.test','x',bot.TECH_NEWS_MAX_ITEMS)
    for n in range(4):
        bot.add_tech_news_item(items,f'AI model release {n}','https://example.test','x',bot.TECH_NEWS_MAX_ITEMS)
    assert len(items)==bot.TECH_NEWS_MAX_ITEMS

@pytest.mark.asyncio
async def test_news_summary_skips_recently_posted_when_fresh_alternatives_exist(db, monkeypatch):
    recent={'title':'Recent repeat','url':'https://example.test/repeat','link':'https://example.test/repeat','source':'x','source_kind':'grounding','published_at_utc':'2026-05-22T10:00:00.000Z','date_status':'fresh'}
    fresh={'title':'Fresh alternative','url':'https://example.test/fresh','link':'https://example.test/fresh','source':'x','source_kind':'grounding','published_at_utc':'2026-05-23T10:00:00.000Z','date_status':'fresh'}
    await bot.news_mod.upsert_news_item(db,recent)
    await bot.news_mod.mark_news_items_posted(db,[recent])
    async def fake_known(limit=bot.news_mod.KNOWN_NEWS_LIMIT):
        return [recent,fresh]
    async def fake_exploratory(limit=bot.news_mod.EXPLORATORY_NEWS_LIMIT,fetcher=None):
        return []
    monkeypatch.setattr(bot,'fetch_known_news',fake_known)
    monkeypatch.setattr(bot,'fetch_exploratory_news',fake_exploratory)
    result=await bot.build_news_summary(db,None,store_memory=False,news_channel_id='configured-channel')
    assert 'Fresh alternative' in result
    assert 'Recent repeat' not in result

@pytest.mark.asyncio
async def test_news_summary_labels_repeats_when_no_fresh_alternatives(db, monkeypatch):
    repeat={'title':'Recent repeat','url':'https://example.test/repeat','link':'https://example.test/repeat','source':'x','source_kind':'grounding','published_at_utc':None,'date_status':'unknown'}
    await bot.news_mod.upsert_news_item(db,repeat)
    await bot.news_mod.mark_news_items_posted(db,[repeat])
    async def fake_known(limit=bot.news_mod.KNOWN_NEWS_LIMIT):
        return [repeat]
    async def fake_exploratory(limit=bot.news_mod.EXPLORATORY_NEWS_LIMIT,fetcher=None):
        return []
    monkeypatch.setattr(bot,'fetch_known_news',fake_known)
    monkeypatch.setattr(bot,'fetch_exploratory_news',fake_exploratory)
    result=await bot.build_news_summary(db,None,store_memory=False,news_channel_id='configured-channel')
    assert 'No fresh unseen items found' in result
    assert 'date_unknown' in result

def test_news_dates_are_normalized():
    item=bot.news_mod.news_item('AI model release','https://example.test/date','x','exploratory','Sat, 23 May 2026 10:15:00 GMT')
    assert item['published_at_utc']=='2026-05-23T10:15:00.000Z'
