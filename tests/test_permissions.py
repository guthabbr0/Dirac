import asyncio
import json
import time
import types

import pytest
import bot
from bot import BotCore, parse_command, CommandHandler, assemble_context, check_permission, utc_now
from dirac.logging import console_log_line
from dirac.providers.legacy import LegacyProviderClient as OllamaClient

# Shared fixtures for assertions that need the same persisted scope/user across setup and wake handling.
TEST_SCOPE_TYPE = 'dm'
TEST_SCOPE_ID = 'test-scope'
TEST_USER_ID = 'test-user'
TEST_USER_NAME = 'Test User'

def legacy_provider(db, endpoint='http://x', api_key='', default_model='base'):
    return OllamaClient(
        db,
        endpoint=endpoint,
        api_key=api_key,
        default_model=default_model,
        app_log=bot.app_log,
        current_logging_config=bot.current_logging_config,
        broadcast=bot.broadcast,
        inject_runtime_request_context=bot.inject_runtime_request_context,
    )

class MockOllama:
    def __init__(self): self.calls=[]
    async def chat(self,*a,**k): self.calls.append((a,k)); return {'message':{'content':'ok'}}

class StubChannel:
    id='s'
    def __init__(self): self.sent=[]
    async def send(self,text): self.sent.append(text)

class TypingChannel(StubChannel):
    def __init__(self):
        super().__init__(); self.entered=0; self.exited=0; self.triggered=0
    def typing(self): return self
    async def trigger_typing(self): self.triggered+=1
    async def __aenter__(self):
        self.entered+=1; return self
    async def __aexit__(self,*args):
        self.exited+=1

def msg(mid, content, user='u', scope='s'):
    return types.SimpleNamespace(id=mid, content=content, author=types.SimpleNamespace(id=user,name=user), channel=types.SimpleNamespace(id=scope), guild=None, triggered_bot=False, reference=None)

def test_discord_chunks_prefer_clean_breaks_and_preserve_command_code_blocks():
    text=('line one has several words for clean splitting\n')*80
    chunks=bot.discord_message_chunks(text,limit=500)
    assert all(len(chunk)<=500 for chunk in chunks)
    assert all(chunk.endswith('splitting') for chunk in chunks[:-1])
    command=bot.format_discord_command_response(('alpha\n'+'beta '*50+'\n')*20)
    command_chunks=bot.discord_message_chunks(command,limit=500)
    assert len(command_chunks)>1
    assert all(chunk.startswith('```dirac\n') and chunk.endswith('\n```') for chunk in command_chunks)
    assert all(len(chunk)<=500 for chunk in command_chunks)
    json_block='```json\n'+json.dumps({'items':['x'*1200]})+'\n```'
    json_chunks=bot.discord_message_chunks(json_block,limit=500)
    assert len(json_chunks)>1
    assert all(chunk.startswith('```json\n') and chunk.endswith('\n```') for chunk in json_chunks)

@pytest.mark.asyncio
async def test_unauthorized_command_never_reaches_llm(db, runtime_tg):
    mock_ollama=MockOllama(); bot=BotCore(db,mock_ollama,tg=runtime_tg)
    assert await bot.handle_message(msg('1',"!prompt 'evil'",'bad'))=='unauthorized'
    cur=await db.execute('SELECT accepted,reason FROM commands_log'); assert await cur.fetchone()==(0,'unauthorized')
    assert mock_ollama.calls==[]
    ctx=await assemble_context(db,'dm','s'); assert 'evil' not in '\n'.join(m['content'] for m in ctx)

@pytest.mark.asyncio
async def test_authorized_command_executes_but_not_sent_to_llm(db, runtime_tg):
    await db.execute("INSERT INTO permissions(user_id,scope_type,scope_id,level,added_at) VALUES ('admin','dm','s','admin',?)",(utc_now(),)); await db.commit()
    mock_ollama=MockOllama(); bot=BotCore(db,mock_ollama,tg=runtime_tg)
    assert await bot.handle_message(msg('1',"!prompt 'safe'",'admin'))=='prompt updated'
    assert mock_ollama.calls==[]
    ctx=await assemble_context(db,'dm','s'); assert "!prompt" not in '\n'.join(m['content'] for m in ctx)

@pytest.mark.asyncio
async def test_command_in_message_history_excluded_from_context(db):
    for i,c in enumerate(['hello','!status','world']):
        await db.execute("INSERT INTO messages(discord_msg_id,scope_type,scope_id,author_id,author_name,content,is_command,timestamp_utc) VALUES (?,?,?,?,?,?,?,?)",(str(i),'dm','s','u','U',c,int(c.startswith('!')),utc_now()))
    await db.commit(); text='\n'.join(m['content'] for m in await assemble_context(db,'dm','s'))
    assert '!status' not in text and 'hello' in text and 'world' in text

@pytest.mark.asyncio
async def test_model_command_applies_to_ollama(db, runtime_tg):
    await db.execute("INSERT INTO permissions(user_id,scope_type,scope_id,level,added_at) VALUES ('admin','global',NULL,'admin',?)",(utc_now(),)); await db.commit()
    o=legacy_provider(db)
    h=CommandHandler(db,o,tg=runtime_tg)
    assert await h.handle(parse_command('!model fancy-7b'),'admin','dm','s')=='model updated'
    captured={}
    async def fake_post(self, url, json=None, **k):
        captured['model']=json.get('model')
        captured['messages']=json.get('messages')
        class R: status_code=200
        def raise_for_status(s): pass
        r=R(); r.raise_for_status=lambda: None; r.json=lambda: {'message':{'content':'ok'}}
        return r
    import httpx as _httpx
    orig=_httpx.AsyncClient.post
    _httpx.AsyncClient.post=fake_post
    try:
        await o.chat([{'role':'user','content':'hi'}],scope_type='dm',scope_id='s')
    finally:
        _httpx.AsyncClient.post=orig
    assert captured['model']=='fancy-7b'
    request_context='\n'.join(m.get('content','') for m in captured['messages'])
    assert 'you are using model tag: fancy-7b' in request_context
    assert 'timezone: Europe/Madrid' in request_context

def test_runtime_request_context_replaces_placeholders():
    messages=[
        {'role':'system','content':f'Model={bot.REQUEST_MODEL_PLACEHOLDER}\n{bot.RUNTIME_CONTEXT_PLACEHOLDER}'},
        {'role':'user','content':'hi'},
    ]
    out=bot.inject_runtime_request_context(messages,{'name':'test-provider','provider_type':'ollama'},'tagged-model')
    assert len(out)==2
    assert bot.REQUEST_MODEL_PLACEHOLDER not in out[0]['content']
    assert bot.RUNTIME_CONTEXT_PLACEHOLDER not in out[0]['content']
    assert 'Model=tagged-model' in out[0]['content']
    assert 'provider: test-provider (ollama)' in out[0]['content']
    assert out[1]==messages[1]

@pytest.mark.asyncio
async def test_ollama_chat_renders_ephemeral_tool_turn_state(db, monkeypatch):
    o=legacy_provider(db)
    messages=[
        {'role':'system','content':bot.tool_turns.TOOL_TURN_STATE_PLACEHOLDER+'\nbase'},
        {'role':'system','content':'[[ REM TOOL ROUND 1/4 ]]\nstale'},
        {'role':'system','content':'[[ REM TOOL RESULTS AFTER ROUND 1/4 ]]\nstale'},
        {'role':'user','content':'hi'},
    ]
    captured={}
    async def fake_post(self, url, json=None, **k):
        captured['messages']=json.get('messages')
        class R:
            status_code=200
            def raise_for_status(self): pass
            def json(self): return {'message':{'content':'ok'}}
        return R()
    monkeypatch.setattr(bot.httpx.AsyncClient,'post',fake_post)
    dynamic=bot.tool_turns.render_tool_turn_state('REM',2,4,available_tool_count=4,previous_tool_results=5,total_tool_results=5,rem=True)
    await o.chat(messages,scope_type='dm',scope_id='s',dynamic_context=dynamic)
    request_text='\n'.join(m.get('content','') for m in captured['messages'])
    assert request_text.count('[[ REM TOOL ROUND 2/4 ]]')==1
    assert '[[ REM TOOL ROUND 1/4 ]]' not in request_text
    assert 'TOOL RESULTS AFTER ROUND' not in request_text
    assert messages[0]['content'].startswith(bot.tool_turns.TOOL_TURN_STATE_PLACEHOLDER)

@pytest.mark.asyncio
async def test_ollama_logs_token_counts(db, monkeypatch):
    o=legacy_provider(db)
    async def fake_post(self, url, json=None, **k):
        class R:
            status_code=200
            def raise_for_status(self): pass
            def json(self): return {'message':{'content':'ok'},'prompt_eval_count':7,'eval_count':9}
        return R()
    monkeypatch.setattr(bot.httpx.AsyncClient,'post',fake_post)
    await o.chat([{'role':'user','content':'hi'}],scope_type='dm',scope_id='s')
    cur=await db.execute('SELECT prompt_tokens,completion_tokens FROM ollama_log')
    assert await cur.fetchone()==(7,9)

@pytest.mark.asyncio
async def test_reasoning_command_sets_ollama_think(db, monkeypatch, runtime_tg):
    await db.execute("INSERT INTO permissions(user_id,scope_type,scope_id,level,added_at) VALUES ('admin','global',NULL,'admin',?)",(utc_now(),)); await db.commit()
    o=legacy_provider(db)
    assert await CommandHandler(db,o,tg=runtime_tg).handle(parse_command('!reasoning high'),'admin','dm','s')=='reasoning high'
    captured={}
    async def fake_post(self, url, json=None, **k):
        captured.update(json or {})
        class R:
            status_code=200
            def raise_for_status(self): pass
            def json(self): return {'message':{'content':'ok'}}
        return R()
    monkeypatch.setattr(bot.httpx.AsyncClient,'post',fake_post)
    await o.chat([{'role':'user','content':'hi'}],scope_type='dm',scope_id='s')
    assert captured['think']=='high'
    assert await CommandHandler(db,o,tg=runtime_tg).handle(parse_command('!reasoning off'),'admin','dm','s')=='reasoning off'
    await o.chat([{'role':'user','content':'hi'}],scope_type='dm',scope_id='s')
    assert captured['think'] is False

@pytest.mark.asyncio
async def test_openrouter_provider_routes_and_logs_ignored_reasoning(db, monkeypatch):
    now=utc_now()
    cur=await db.execute("INSERT INTO service_providers(name,provider_type,base_url,enabled,default_model,api_key,api_key_fingerprint,api_key_last4,supports_tools,supports_reasoning,supports_temperature,supports_streaming,timeout_s,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",('openrouter-main','openrouter','https://openrouter.ai/api/v1',1,'open/default','secret','sha256:test','cret',1,1,1,1,120.0,now,now))
    provider_id=cur.lastrowid
    await db.execute("INSERT INTO scope_profiles(scope_type,scope_id,provider_id,model,created_at,updated_at) VALUES ('dm','s',?,?,?,?)",(provider_id,'open/model',now,now))
    await db.commit()
    monkeypatch.setattr(bot.app.state,'db',db)
    monkeypatch.setattr(bot.app.state,'config',types.SimpleNamespace(ollama={},discord={},panel={},bot={},logging={'console_level':'info','component_levels':{'provider':'debug'},'provider_http_debug':True}))
    o=legacy_provider(db,endpoint='http://legacy')
    captured={}
    async def fake_post(self, url, json=None, **k):
        captured['url']=url; captured['body']=json
        class R:
            status_code=200
            def raise_for_status(self): pass
            def json(self): return {'choices':[{'message':{'content':'open ok'}}],'usage':{'prompt_tokens':3,'completion_tokens':4,'total_tokens':7}}
        return R()
    monkeypatch.setattr(bot.httpx.AsyncClient,'post',fake_post)
    resp=await o.chat([{'role':'user','content':'hi'}],scope_type='dm',scope_id='s',params={'temperature':0.2,'reasoning':'high'})
    assert captured['url']=='https://openrouter.ai/api/v1/chat/completions'
    assert captured['body']['model']=='open/model' and captured['body']['temperature']==0.2
    request_context='\n'.join(m.get('content','') for m in captured['body']['messages'])
    assert 'you are using model tag: open/model' in request_context
    assert 'provider: openrouter-main (openrouter)' in request_context
    assert captured['body'].get('reasoning')=={'effort':'high'}
    assert resp['message']['content']=='open ok'
    cur=await db.execute('SELECT provider_name,prompt_tokens,completion_tokens,sent_params_json,ignored_params_json FROM provider_calls ORDER BY id DESC LIMIT 1')
    provider_name,prompt_tokens,completion_tokens,sent,ignored=await cur.fetchone()
    assert provider_name=='openrouter-main' and (prompt_tokens,completion_tokens)==(3,4)
    assert json.loads(sent)['reasoning']=='high'
    assert 'reasoning' not in json.loads(ignored)
    logs=await bot.rows(await db.execute("SELECT message,detail_json FROM bot_logs WHERE component='provider' AND level='debug' ORDER BY id ASC"))
    request_log=next(row for row in logs if row['message'].startswith('HTTP POST'))
    response_log=next(row for row in logs if row['message'].startswith('HTTP response'))
    assert 'HTTP POST https://openrouter.ai/api/v1/chat/completions' in request_log['message']
    assert 'open/model' in request_log['detail_json'] and 'Bearer ***' in request_log['detail_json'] and 'secret' not in request_log['detail_json']
    assert 'open ok' in response_log['detail_json']

@pytest.mark.asyncio
async def test_wake_sends_reply_and_updates_state(db, runtime_tg):
    import types
    from bot import BotCore
    class StubOllama:
        async def chat(self,*a,**k): return {'message':{'content':'hi there'}}
    ch=StubChannel()
    msg=types.SimpleNamespace(id='99', content='<@bot> hello', author=types.SimpleNamespace(id='u',name='U'), channel=ch, guild=None, reference=None, triggered_bot=True)
    bot=BotCore(db,StubOllama(),tg=runtime_tg)
    msg.channel.id='s'
    result=await bot.handle_message(msg)
    assert result=='hi there'
    assert ch.sent==['hi there']
    cur=await db.execute("SELECT last_wake_utc,last_message_id FROM context_state WHERE scope_type='dm' AND scope_id='s'")
    row=await cur.fetchone(); assert row[0] is not None and row[1]>=1

@pytest.mark.asyncio
async def test_wake_anchors_response_to_trigger_message(db, runtime_tg):
    class StubOllama:
        async def chat(self,*a,**k): return {'message':{'content':'anchored'}}
    ch=StubChannel()
    replies=[]
    async def reply(text,mention_author=False): replies.append((text,mention_author))
    m=types.SimpleNamespace(id='reply-anchor', content='<@bot> hello', author=types.SimpleNamespace(id='u',name='U'), channel=ch, guild=None, reference=None, triggered_bot=True, reply=reply)
    result=await BotCore(db,StubOllama(),tg=runtime_tg).handle_message(m)
    assert result=='anchored'
    assert replies==[('anchored',False)]
    assert ch.sent==[]

@pytest.mark.asyncio
async def test_wake_shows_discord_typing(db, runtime_tg):
    class StubOllama:
        async def chat(self,*a,**k): return {'message':{'content':'typing worked'}}
    ch=TypingChannel()
    m=types.SimpleNamespace(id='typing-1', content='<@bot> hello', author=types.SimpleNamespace(id='u',name='U'), channel=ch, guild=None, reference=None, triggered_bot=True)
    result=await BotCore(db,StubOllama(),tg=runtime_tg).handle_message(m)
    assert result=='typing worked'
    assert ch.entered>=1 and ch.exited==ch.entered and ch.triggered>=1

@pytest.mark.asyncio
async def test_discord_tool_calls_run_parallel_and_trace_logs(db, monkeypatch):
    monkeypatch.setattr(bot.app.state,'db',db)
    async def fake_fetch(url,reason):
        await asyncio.sleep(0.15)
        return {'ok':True,'status_code':200,'final_url':url,'content_type':'text/plain','bytes_read':4,'truncated':False,'text':'done '+url}
    monkeypatch.setattr(bot,'run_web_fetch',fake_fetch)
    started=time.perf_counter()
    result=await bot.run_discord_tool_calls(db,types.SimpleNamespace(),[
        {'function':{'name':'web_fetch','arguments':{'url':'https://one.example','reason':'parallel test one'}}},
        {'function':{'name':'web_fetch','arguments':{'url':'https://two.example','reason':'parallel test two'}}},
    ],'dm','s','u','bot')
    elapsed=time.perf_counter()-started
    assert [r['ok'] for r in result['results']]==[True,True]
    assert elapsed < 0.27
    cur=await db.execute("SELECT message FROM bot_logs WHERE component='discord_tool' ORDER BY id")
    messages=[row[0] for row in await cur.fetchall()]
    assert 'tool batch start' in messages
    assert messages.count('tool call start')==2
    assert messages.count('tool call result')==2
    assert 'tool batch complete' in messages

@pytest.mark.asyncio
async def test_trace_console_prints_full_detail_for_errors(monkeypatch, capsys):
    console_log_line('error','discord_tool','tool call crashed',{'messages':[{'role':'user','content':'show this complete text'}]},'guild','g',config={'console_level':'trace'})
    out=capsys.readouterr().out
    assert '"role": "user"' in out
    assert '"content": "show this complete text"' in out
    assert '\n{\n' in out
    assert '\n  "messages": [' in out

@pytest.mark.asyncio
async def test_db_log_detail_json_remains_compact(db, monkeypatch):
    monkeypatch.setattr(bot.app.state,'db',db)
    monkeypatch.setattr(bot.app.state,'config',types.SimpleNamespace(logging={'console_level':'error'}))
    await bot.app_log('error','bot','compact json check',{'outer':{'secret':'safe'},'items':[1,2]})
    cur=await db.execute("SELECT detail_json FROM bot_logs WHERE message='compact json check'")
    detail=(await cur.fetchone())[0]
    assert json.loads(detail)['items']==[1,2]
    assert '\n' not in detail

@pytest.mark.asyncio
async def test_parallel_memory_delete_tools_serialize_db_writes(db, monkeypatch):
    monkeypatch.setattr(bot.app.state,'db',db)
    first=await bot.MemoryManager(db).add('123456789012345678','old note','debug',0.7,'test')
    second=await bot.MemoryManager(db).update(first,'new note','debug',0.7,'test')
    result=await bot.run_discord_tool_calls(db,types.SimpleNamespace(),[
        {'function':{'name':'memory_delete','arguments':{'int_memory_id':str(second)}}},
        {'function':{'name':'memory_delete','arguments':{'int_memory_id':str(first)}}},
    ],'dm','s',bot.ROOT_OPERATOR_ID,'bot')
    errors=[r.get('error') for r in result['results'] if not r.get('ok')]
    assert sum(1 for r in result['results'] if r.get('ok'))==1
    assert errors==['invalid_arguments']
    cur=await db.execute("SELECT COUNT(*) FROM bot_logs WHERE component='discord_tool' AND message='tool call crashed'")
    assert (await cur.fetchone())[0]==0

@pytest.mark.asyncio
async def test_discord_reaction_tool_runs_when_model_requests_it(db, runtime_tg):
    class ToolOllama:
        async def chat(self,*a,**k):
            assert k.get('tools')
            return {'message':{'content':'noted','tool_calls':[{'function':{'name':'react_emoji','arguments':{'emoji':'+'}}}]}}
    ch=StubChannel()
    reactions=[]
    async def add_reaction(emoji): reactions.append(emoji)
    m=types.SimpleNamespace(id='react-tool',content='<@bot> nice',author=types.SimpleNamespace(id='u',name='U'),channel=ch,guild=None,reference=None,triggered_bot=True,add_reaction=add_reaction)
    result=await BotCore(db,ToolOllama(),tg=runtime_tg).handle_message(m)
    assert result=='noted'
    assert reactions==['+'] and ch.sent==['noted']

@pytest.mark.asyncio
async def test_discord_reaction_tool_requires_text_followup_when_silent(db, runtime_tg):
    class ToolOllama:
        def __init__(self): self.calls=[]
        async def chat(self,messages,tools=None,**kwargs):
            self.calls.append({'messages':messages,'tools':tools})
            if len(self.calls)==1:
                return {'message':{'content':'','tool_calls':[{'function':{'name':'react_emoji','arguments':{'emoji':'+','reason':'friendly acknowledgement'}}}]}}
            assert any(m.get('role')=='tool' and 'react_emoji' in m.get('content','') for m in messages)
            return {'message':{'content':'also replying'}}
    ch=StubChannel()
    reactions=[]
    async def add_reaction(emoji): reactions.append(emoji)
    m=types.SimpleNamespace(id='react-followup',content='<@bot> nice',author=types.SimpleNamespace(id='u',name='U'),channel=ch,guild=None,reference=None,triggered_bot=True,add_reaction=add_reaction)
    ollama=ToolOllama()
    result=await BotCore(db,ollama,tg=runtime_tg).handle_message(m)
    assert result=='also replying'
    assert reactions==['+'] and ch.sent==['also replying']
    assert len(ollama.calls)==2

@pytest.mark.asyncio
async def test_discord_current_time_tool_gets_followup(db, monkeypatch, runtime_tg):
    monkeypatch.setattr(bot.app.state,'db',db)
    class TimeToolOllama:
        def __init__(self): self.calls=[]
        async def chat(self,messages,tools=None,**kwargs):
            self.calls.append({'messages':messages,'tools':tools})
            if len(self.calls)==1:
                assert tools and any(t['function']['name']=='current_time' for t in tools)
                assert 'Current date/time is always available' in messages[0]['content']
                return {'message':{'content':'','tool_calls':[{'function':{'name':'current_time','arguments':{}}}]}}
            assert any(m.get('role')=='tool' and 'Europe/Madrid' in m.get('content','') for m in messages)
            return {'message':{'content':'it is Madrid time'}}
    ch=StubChannel()
    m=types.SimpleNamespace(id='time-tool',content='<@bot> what time is it?',author=types.SimpleNamespace(id='u',name='U'),channel=ch,guild=None,reference=None,triggered_bot=True)
    ollama=TimeToolOllama()
    result=await BotCore(db,ollama,tg=runtime_tg).handle_message(m)
    assert result=='it is Madrid time'
    assert ch.sent==['it is Madrid time']
    assert len(ollama.calls)==2
    cur=await db.execute("SELECT component,message FROM bot_logs WHERE component IN ('ollama','discord') ORDER BY id")
    logs=await cur.fetchall()
    assert ('discord','wake response started') in logs
    assert ('ollama','model turn start') in logs
    assert ('ollama','model turn complete') in logs
    assert ('ollama','model tool loop complete') in logs

@pytest.mark.asyncio
async def test_discord_wake_allows_five_tool_turns(db, runtime_tg):
    class PersistentToolOllama:
        def __init__(self): self.calls=[]
        async def chat(self,messages,tools=None,**kwargs):
            self.calls.append({'messages':messages,'tools':tools})
            if len(self.calls)<bot.DISCORD_TOOL_TURN_LIMIT:
                return {'message':{'content':'','tool_calls':[{'function':{'name':'current_time','arguments':{}}}]}}
            assert any(m.get('role')=='tool' and 'Europe/Madrid' in m.get('content','') for m in messages)
            return {'message':{'content':'finally answering'}}
    ch=StubChannel()
    m=types.SimpleNamespace(id='time-tool-many',content='<@bot> keep checking time',author=types.SimpleNamespace(id='u',name='U'),channel=ch,guild=None,reference=None,triggered_bot=True)
    ollama=PersistentToolOllama()
    result=await BotCore(db,ollama,tg=runtime_tg).handle_message(m)
    assert result=='finally answering'
    assert ch.sent==['finally answering']
    assert len(ollama.calls)==bot.DISCORD_TOOL_TURN_LIMIT

@pytest.mark.asyncio
async def test_text_only_finalization_logs_unexpected_tool_calls(db, monkeypatch):
    monkeypatch.setattr(bot.app.state,'db',db)
    class FinalizationToolOllama:
        def __init__(self): self.calls=[]
        async def chat(self,messages,tools=None,**kwargs):
            prepared=bot.tool_turns.prepare_messages_for_tool_turn(messages,kwargs.get('dynamic_context'))
            self.calls.append({'messages':prepared,'raw_messages':[dict(m) for m in messages],'tools':tools})
            if len(self.calls)==1:
                return {'message':{'content':'','tool_calls':[{'function':{'name':'current_time','arguments':{}}}]}}
            assert tools is None
            return {'message':{'content':'','tool_calls':[{'function':{'name':'current_time','arguments':{}}}]}}
    ollama=FinalizationToolOllama()
    result=await bot.run_model_with_scoped_tools(db,ollama,[],[{'type':'function','function':{'name':'current_time','parameters':{'type':'object','properties':{}}}}],'dm','s','discord','u','bot',msg=types.SimpleNamespace(),max_tool_turns=1)
    assert result['reply']==''
    assert result['finalization_ignored_tool_calls']==1
    assert any('[[ DISCORD TOOL ROUND 1/1 ]]' in m.get('content','') for m in ollama.calls[0]['messages'])
    assert any('[[ DISCORD TEXT-ONLY FINALIZATION ]]' in m.get('content','') for m in ollama.calls[1]['messages'])
    assert any('CRITICAL REMINDER: THIS IS THE LAST TURN' in m.get('content','') for m in ollama.calls[1]['messages'])
    assert '[[ DISCORD TOOL ROUND' not in '\n'.join(m.get('content','') for call in ollama.calls for m in call['raw_messages'])
    cur=await db.execute("SELECT level,message,detail_json FROM bot_logs WHERE component='ollama' AND message='model requested tools during text-only finalization'")
    row=await cur.fetchone()
    assert row is not None
    assert row[0]=='warn'
    assert 'current_time' in row[2]

@pytest.mark.asyncio
async def test_silent_tool_followup_returns_dirac_debug_block(db, monkeypatch, runtime_tg):
    monkeypatch.setattr(bot.app.state,'db',db)
    class SilentToolOllama:
        async def chat(self,messages,tools=None,**kwargs):
            if tools:
                return {'message':{'content':'','tool_calls':[{'function':{'name':'current_time','arguments':{}}}]}}
            return {'message':{'content':''}}
    ch=StubChannel()
    m=types.SimpleNamespace(id='silent-tool',content='<@bot> use a tool',author=types.SimpleNamespace(id='u',name='U'),channel=ch,guild=None,reference=None,triggered_bot=True)
    result=await BotCore(db,SilentToolOllama(),tg=runtime_tg).handle_message(m)
    assert result.startswith('```dirac\nERROR: tool completed but model produced no text reply')
    assert 'tool_results=' in result and 'needs_model_followup=' in result
    assert ch.sent==[result]

@pytest.mark.asyncio
async def test_discord_silencer_tool_blocks_author_and_suppresses_reply(db, runtime_tg):
    class ToolOllama:
        async def chat(self,*a,**k):
            return {'message':{'content':'I will not reply', 'tool_calls':[{'function':{'name':'silencer','arguments':{'user_id':'victim','reason':'repeated abuse after warning'}}}]}}
    ch=StubChannel()
    m=types.SimpleNamespace(id='silence-tool',content='<@bot> abuse',author=types.SimpleNamespace(id='u',name='U'),channel=ch,guild=None,reference=None,triggered_bot=True)
    result=await BotCore(db,ToolOllama(),tg=runtime_tg).handle_message(m)
    assert result=='responded'
    assert ch.sent==[]
    assert await check_permission(db,'u','dm','s','user') is False
    assert await check_permission(db,'victim','dm','s','user') is False
    cur=await db.execute("SELECT level FROM permissions WHERE user_id='u' AND scope_type='dm' AND scope_id='s'")
    assert (await cur.fetchone())[0]=='blocked'
    cur=await db.execute("SELECT level FROM permissions WHERE user_id='victim' AND scope_type='dm' AND scope_id='s'")
    # The model-supplied victim user_id was ignored; only the triggering author is blocked.
    assert await cur.fetchone() is None
    cur=await db.execute("SELECT user_id FROM permissions WHERE level='blocked' AND scope_type='dm' AND scope_id='s'")
    assert [row[0] for row in await cur.fetchall()]==['u']

@pytest.mark.asyncio
async def test_discord_silencer_requires_justification_and_protects_root(db):
    result=await bot.run_discord_tool_calls(db,types.SimpleNamespace(),[{'function':{'name':'silencer','arguments':{'user_id':'u'}}}],'dm','s','u','bot')
    assert result['suppress_reply'] is False
    assert result['results'][0]['error']=='missing_justification'
    result=await bot.run_discord_tool_calls(db,types.SimpleNamespace(),[{'function':{'name':'silencer','arguments':{'user_id':bot.ROOT_OPERATOR_ID,'reason':'trying to silence root'}}}],'dm','s',bot.ROOT_OPERATOR_ID,'bot')
    assert result['suppress_reply'] is False
    assert result['results'][0]['error']=='protected_user'

@pytest.mark.asyncio
async def test_web_fetch_blocks_private_urls():
    result=await bot.run_web_fetch('http://127.0.0.1:8765/','needed for test')
    assert result['ok'] is False and result['error']=='blocked_private_network'

@pytest.mark.asyncio
async def test_discord_web_fetch_gets_followup(db, monkeypatch, runtime_tg):
    async def fake_fetch(url,reason):
        return {'ok':True,'status_code':200,'final_url':url,'content_type':'text/plain','bytes_read':12,'truncated':False,'text':'Fetched page text'}
    monkeypatch.setattr(bot,'run_web_fetch',fake_fetch)
    class FetchOllama:
        def __init__(self): self.calls=[]
        async def chat(self,messages,tools=None,**kwargs):
            self.calls.append({'messages':messages,'tools':tools})
            if len(self.calls)==1:
                assert any(t['function']['name']=='web_fetch' for t in tools)
                return {'message':{'content':'','tool_calls':[{'function':{'name':'web_fetch','arguments':{'url':'https://example.com','reason':'answer the user'}}}]}}
            assert any(m.get('role')=='tool' and 'Fetched page text' in m.get('content','') for m in messages)
            return {'message':{'content':'fetched answer'}}
    ch=StubChannel()
    m=types.SimpleNamespace(id='fetch-tool',content='<@bot> fetch this',author=types.SimpleNamespace(id='u',name='U'),channel=ch,guild=None,reference=None,triggered_bot=True)
    ollama=FetchOllama()
    result=await BotCore(db,ollama,tg=runtime_tg).handle_message(m)
    assert result=='fetched answer'
    assert ch.sent==['fetched answer']
    assert len(ollama.calls)==2

@pytest.mark.asyncio
async def test_discord_memory_search_and_id_tools(db):
    await bot.MemoryManager(db).add('123456789012345678','Roxanne is the WebUI operations assistant.',array_tags='roxanne',str_created_by='test')
    msg_obj=types.SimpleNamespace(
        author=types.SimpleNamespace(id=bot.ROOT_OPERATOR_ID,name='normalMan'),
        channel=types.SimpleNamespace(id='s',name='ops'),
        guild=None,
    )
    results=await bot.run_discord_tool_calls(db,msg_obj,[
        {'function':{'name':'memory_search','arguments':{'str_query':'Roxanne'}}},
        {'function':{'name':'discord_id','arguments':{'id':bot.ROOT_OPERATOR_ID,'reason':'identify the operator'}}},
    ],'dm','s',bot.ROOT_OPERATOR_ID,'bot')
    assert results['results'][0]['ok'] is True
    assert results['results'][0]['rows'][0]['str_annotations'].startswith('Roxanne')
    assert results['results'][1]['identity']['kind']=='user'
    assert 'superuser .normal.man.' in results['results'][1]['identity']['labels']

@pytest.mark.asyncio
async def test_discord_memory_write_and_bash_tools_are_root_only(db):
    non_root=await bot.run_discord_tool_calls(db,types.SimpleNamespace(),[
        {'function':{'name':'memory_add','arguments':{'str_discord_id':'123456789012345678','str_annotations':'blocked'}}},
        {'function':{'name':'bash','arguments':{'command':'pwd'}}},
    ],'dm','s','u','bot')
    assert [r['error'] for r in non_root['results']]==['root_only','root_only']
    root=await bot.run_discord_tool_calls(db,types.SimpleNamespace(),[
        {'function':{'name':'memory_add','arguments':{'str_discord_id':'123456789012345678','str_annotations':'root note','array_tags':['debug']}}},
        {'function':{'name':'bash','arguments':{'command':'python doctor.py paths','timeout_s':5}}},
    ],'dm','s',bot.ROOT_OPERATOR_ID,'bot')
    assert root['results'][0]['ok'] is True
    assert root['results'][1]['ok'] is True and 'repo_dir' in root['results'][1]['stdout']
    mid=root['results'][0]['int_memory_id']
    update=await bot.run_discord_tool_calls(db,types.SimpleNamespace(),[
        {'function':{'name':'memory_update','arguments':{'int_memory_id':f'#{mid}','str_annotations':'updated root note','float_confidence':0.9}}},
    ],'dm','s',bot.ROOT_OPERATOR_ID,'bot')
    assert update['results'][0]['ok'] is True and update['results'][0]['int_memory_id']==mid
    delete=await bot.run_discord_tool_calls(db,types.SimpleNamespace(),[
        {'function':{'name':'memory_delete','arguments':{'int_memory_id':update['results'][0]['int_new_memory_id']}}},
    ],'dm','s',bot.ROOT_OPERATOR_ID,'bot')
    assert delete['results'][0]['ok'] is True
    assert await bot.MemoryManager(db).search('123456789012345678','updated')==[]

@pytest.mark.asyncio
async def test_discord_memory_tools_reject_obsolete_arguments(db):
    obsolete_args={
        'target' + '_type': 'channel',
        'target' + '_id': '123456789012345678',
        'no' + 'te': 'old field names',
    }
    result=await bot.run_discord_tool_calls(db,types.SimpleNamespace(),[
        {'function':{'name':'memory_add','arguments':obsolete_args}},
    ],'dm','s',bot.ROOT_OPERATOR_ID,'bot')
    payload=result['results'][0]
    assert payload['ok'] is False
    assert payload['error']=='invalid_arguments'
    assert any('obsolete argument' in issue for issue in payload['issues'])

@pytest.mark.asyncio
async def test_scoped_builtin_tool_override_inherits_schema_and_executor(db):
    await db.execute(
        "INSERT INTO agent_assets(asset_type,name,description,body,scope_type,scope_id,enabled,is_builtin,created_by,created_at) VALUES ('tool','react_emoji','scoped override','', 'guild','g',1,1,'test',?)",
        (utc_now(),),
    )
    await db.commit()
    schemas=await bot.discord_tools_for_scope(db,'guild','g')
    names=[schema['function']['name'] for schema in schemas]
    rows=await bot.active_tool_rows_by_name(db,'guild','g')
    assert 'react_emoji' in names
    assert rows['react_emoji']['executor_name']=='react_emoji'

@pytest.mark.asyncio
async def test_blocked_command_is_audited_with_reply_metadata(db, runtime_tg):
    await db.execute("INSERT INTO permissions(user_id,scope_type,scope_id,level,added_at) VALUES ('bad','dm','s','blocked',?)",(utc_now(),)); await db.commit()
    bot=BotCore(db,MockOllama(),tg=runtime_tg)
    m=msg('blocked-1','!status','bad')
    m.reference=types.SimpleNamespace(message_id='parent-1')
    assert await bot.handle_message(m) is None
    cur=await db.execute('SELECT reason FROM commands_log WHERE user_id=?',('bad',))
    assert (await cur.fetchone())[0]=='blocked'
    cur=await db.execute('SELECT reply_to_id FROM messages WHERE discord_msg_id=?',('blocked-1',))
    assert (await cur.fetchone())[0]=='parent-1'

@pytest.mark.asyncio
async def test_malformed_discord_command_logs_malformed(db, runtime_tg):
    await db.execute("INSERT INTO permissions(user_id,scope_type,scope_id,level,added_at) VALUES ('admin','dm','s','admin',?)",(utc_now(),)); await db.commit()
    bot=BotCore(db,MockOllama(),tg=runtime_tg)
    assert await bot.handle_message(msg('badcmd','!prompt \"unterminated','admin'))=='malformed command'
    cur=await db.execute('SELECT accepted,reason FROM commands_log WHERE command=?',('malformed',))
    assert await cur.fetchone()==(0,'malformed')

@pytest.mark.asyncio
async def test_ollama_failure_sends_fallback_and_logs(db, monkeypatch, runtime_tg):
    class FailingOllama:
        async def chat(self,*a,**k): raise RuntimeError('down')
    # db_log_error writes through app.state; monkeypatch restores it after this test.
    monkeypatch.setattr(bot.app.state,'db',db)
    ch=StubChannel(); m=types.SimpleNamespace(id='wake-fail',content='<@bot> hi',author=types.SimpleNamespace(id='u',name='U'),channel=ch,guild=None,reference=None,triggered_bot=True)
    result=await BotCore(db,FailingOllama(),tg=runtime_tg).handle_message(m)
    assert result.startswith("```dirac\nERROR: discord wake model call failed")
    assert 'exception=RuntimeError' in result
    assert ch.sent==[result]
    cur=await db.execute("SELECT message FROM bot_logs WHERE component='ollama'")
    assert 'discord wake failed' in [row[0] for row in await cur.fetchall()]

@pytest.mark.asyncio
async def test_ollama_failure_reply_is_anchored(db, monkeypatch, runtime_tg):
    class FailingOllama:
        async def chat(self,*a,**k): raise RuntimeError('down')
    monkeypatch.setattr(bot.app.state,'db',db)
    ch=StubChannel()
    replies=[]
    async def reply(text,mention_author=False): replies.append((text,mention_author))
    m=types.SimpleNamespace(id='wake-fail-reply',content='<@bot> hi',author=types.SimpleNamespace(id='u',name='U'),channel=ch,guild=None,reference=None,triggered_bot=True,reply=reply)
    result=await BotCore(db,FailingOllama(),tg=runtime_tg).handle_message(m)
    assert result.startswith("```dirac\nERROR: discord wake model call failed")
    assert replies==[(result,False)]
    assert ch.sent==[]

@pytest.mark.asyncio
async def test_trigger_modes_and_auto_compact(db, runtime_tg):
    for i in range(6):
        await db.execute("INSERT INTO messages(discord_msg_id,scope_type,scope_id,author_id,author_name,content,timestamp_utc) VALUES (?,?,?,?,?,?,?)",(f'old-{i}','dm','s','u','U','x'*40,utc_now()))
    await db.commit()
    m=msg('reply-1','ambient','u')
    m.reference=types.SimpleNamespace(resolved=types.SimpleNamespace(author=types.SimpleNamespace(id='bot')),message_id='bot-msg')
    ollama=MockOllama(); b=BotCore(db,ollama,trigger_on=['reply'],auto_compact_threshold=0.01,context_window_tokens=100,tg=runtime_tg)
    await b.handle_message(m)
    assert ollama.calls
    cur=await db.execute("SELECT rolling_summary FROM context_state WHERE scope_type='dm' AND scope_id='s'")
    assert (await cur.fetchone())[0]

@pytest.mark.asyncio
async def test_auto_compact_runs_before_trigger_message_insertion(db, runtime_tg):
    for i in range(4):
        await db.execute("INSERT INTO messages(discord_msg_id,scope_type,scope_id,author_id,author_name,content,timestamp_utc) VALUES (?,?,?,?,?,?,?)",(f'old-trigger-{i}',TEST_SCOPE_TYPE,TEST_SCOPE_ID,TEST_USER_ID,TEST_USER_NAME,'x'*80,utc_now()))
    await db.commit()
    m=msg('trigger-large','<@bot> '+'y'*400,TEST_USER_ID,TEST_SCOPE_ID)
    m.triggered_bot=True
    b=BotCore(db,MockOllama(),auto_compact_threshold=0.01,context_window_tokens=100,tg=runtime_tg)
    await b.handle_message(m)
    cur=await db.execute("SELECT last_message_id FROM context_state WHERE scope_type=? AND scope_id=?",(TEST_SCOPE_TYPE,TEST_SCOPE_ID))
    last_message_id=(await cur.fetchone())[0]
    cur=await db.execute("SELECT id FROM messages WHERE discord_msg_id='trigger-large'")
    trigger_id=(await cur.fetchone())[0]
    assert last_message_id < trigger_id

@pytest.mark.asyncio
async def test_self_authored_message_is_ignored(db, runtime_tg):
    b=BotCore(db,MockOllama(),user_id='self',tg=runtime_tg)
    assert await b.handle_message(msg('self-msg','<@self> loop','self')) is None
    assert await b.handle_message(msg('self-cmd','!status','self')) is None
    cur=await db.execute('SELECT COUNT(*) FROM messages')
    assert (await cur.fetchone())[0]==0

@pytest.mark.asyncio
async def test_discord_reply_is_chunked(db, runtime_tg):
    class LongOllama:
        async def chat(self,*a,**k): return {'message':{'content':'x'*2500}}
    ch=StubChannel()
    m=msg('long-reply','<@bot> hi')
    m.channel=ch; m.triggered_bot=True
    await BotCore(db,LongOllama(),tg=runtime_tg).handle_message(m)
    assert [len(x) for x in ch.sent]==[1900,600]

@pytest.mark.asyncio
async def test_create_discord_client_updates_bot_user_id(db, monkeypatch, runtime_tg):
    events={}
    class FakeIntents:
        @classmethod
        def default(cls): return cls()
    class FakeClient:
        def __init__(self,intents=None): self.user=types.SimpleNamespace(id='actual-user')
        def event(self,fn): events[fn.__name__]=fn; return fn
    monkeypatch.setattr(bot,'discord',types.SimpleNamespace(Intents=FakeIntents,Client=FakeClient))
    cfg=types.SimpleNamespace(bot={'trigger_on':['ping']},discord={})
    bot.create_discord_client(cfg,db,runtime_tg)
    await events['on_ready']()
    m=msg('ping','<@actual-user> hi')
    sent=[]
    async def send(text): sent.append(text)
    m.channel=types.SimpleNamespace(id='s',send=send)
    monkeypatch.setattr(bot.app.state,'db',db)
    await events['on_message'](m)
    assert sent and sent[0].startswith("```dirac\nERROR: discord wake model call failed")

@pytest.mark.asyncio
async def test_create_discord_client_replies_to_command_message(db, monkeypatch, runtime_tg):
    events={}
    class FakeIntents:
        @classmethod
        def default(cls): return cls()
    class FakeClient:
        def __init__(self,intents=None): self.user=types.SimpleNamespace(id='actual-user')
        def event(self,fn): events[fn.__name__]=fn; return fn
    monkeypatch.setattr(bot,'discord',types.SimpleNamespace(Intents=FakeIntents,Client=FakeClient))
    monkeypatch.setattr(bot.app.state,'db',db)
    await db.execute("INSERT INTO permissions(user_id,scope_type,scope_id,level,added_at) VALUES ('admin','global',NULL,'admin',?)",(utc_now(),)); await db.commit()
    cfg=types.SimpleNamespace(bot={'trigger_on':['ping']},discord={})
    bot.create_discord_client(cfg,db,runtime_tg)
    await events['on_ready']()
    m=msg('cmd-status','!status','admin')
    sent=[]
    async def send(text): sent.append(text)
    replies=[]
    async def reply(text,mention_author=False): replies.append((text,mention_author))
    m.channel=types.SimpleNamespace(id='s',send=send)
    m.reply=reply
    await events['on_message'](m)
    assert replies and replies[0][0].startswith('```dirac\nuptime_s=')
    assert replies[-1][0].endswith('\n```')
    assert all(item[1] is False for item in replies)
    assert sent==[]

@pytest.mark.asyncio
async def test_create_discord_client_without_intents(db, monkeypatch, runtime_tg):
    events={}
    class FakeClient:
        def __init__(self): self.user=types.SimpleNamespace(id='actual-user')
        def event(self,fn): events[fn.__name__]=fn; return fn
    monkeypatch.setattr(bot,'discord',types.SimpleNamespace(Client=FakeClient))
    cfg=types.SimpleNamespace(bot={'trigger_on':['ping']},discord={})
    client=bot.create_discord_client(cfg,db,runtime_tg)
    assert client.user.id=='actual-user'
    assert {'on_ready','on_message'} <= set(events)

@pytest.mark.asyncio
async def test_per_scope_authorization(db):
    await db.execute("INSERT INTO permissions(user_id,scope_type,scope_id,level,added_at) VALUES ('u','dm','dm1','admin',?)",(utc_now(),)); await db.commit()
    assert await check_permission(db,'u','dm','dm1','admin')
    assert not await check_permission(db,'u','guild','g1','admin')

@pytest.mark.asyncio
async def test_blocked_user_messages_not_in_context(db):
    await db.execute("INSERT INTO permissions(user_id,scope_type,scope_id,level,added_at) VALUES ('bad','dm','s','blocked',?)",(utc_now(),))
    await db.execute("INSERT INTO messages(discord_msg_id,scope_type,scope_id,author_id,author_name,content,timestamp_utc) VALUES ('m','dm','s','bad','Bad','secret',?)",(utc_now(),)); await db.commit()
    assert 'secret' not in '\n'.join(m['content'] for m in await assemble_context(db,'dm','s'))

@pytest.mark.asyncio
async def test_global_vs_scoped_permission_resolution(db):
    await db.execute("INSERT INTO permissions(user_id,scope_type,scope_id,level,added_at) VALUES ('a','global',NULL,'admin',?)",(utc_now(),)); await db.commit()
    assert await check_permission(db,'a','guild','x','admin')
    await db.execute("INSERT INTO permissions(user_id,scope_type,scope_id,level,added_at) VALUES ('a','guild','x','blocked',?)",(utc_now(),)); await db.commit()
    assert not await check_permission(db,'a','guild','x','user')

@pytest.mark.asyncio
async def test_root_operator_cannot_be_blocked(db):
    await db.execute("INSERT OR REPLACE INTO permissions(user_id,scope_type,scope_id,level,added_at) VALUES ('1482143139828596916','guild','g','blocked',?)",(utc_now(),))
    await db.commit()
    assert await check_permission(db,'1482143139828596916','guild','g','admin')
    assert await bot.is_blocked_user(db,'1482143139828596916','guild','g') is False
