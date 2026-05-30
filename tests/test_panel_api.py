import aiosqlite
import types
import pytest
from httpx import AsyncClient, ASGITransport
import bot
from bot import app, bootstrap_db
from tests.conftest import _StubOllama

@pytest.fixture(autouse=True)
async def panel_db(tmp_path, monkeypatch):
    db=await aiosqlite.connect(':memory:'); await bootstrap_db(db)
    monkeypatch.setattr(app.state,'db',db)
    monkeypatch.setattr(app.state,'auth_token','secret')
    monkeypatch.setattr(app.state,'ollama',_StubOllama())
    monkeypatch.setattr(app.state,'config',None)
    monkeypatch.setattr(app.state,'config_path',tmp_path/'config.toml',raising=False)
    yield
    await db.close()

@pytest.mark.asyncio
async def test_auth_and_routes(monkeypatch):
    async def fake_schedule(*args,**kwargs):
        return None
    monkeypatch.setattr(bot,'schedule_agent_task',fake_schedule)
    tr=ASGITransport(app=app)
    async with AsyncClient(transport=tr, base_url='http://test') as c:
        assert (await c.get('/api/stats')).status_code==401
        assert (await c.get('/api/memory-events?minutes=60')).status_code==401
        c.cookies.set('session','bad')
        assert (await c.get('/api/stats')).status_code==401
        root=await c.get('/')
        assert root.status_code==303 and root.headers['location']=='/login'
        c.cookies.set('session','secret')
        assert (await c.get('/api/stats')).status_code==200
        panel=await c.get('/')
        assert panel.status_code==200
        assert 'Live tail' in panel.text and 'openConfig()' in panel.text and 'tail-line' in panel.text
        assert 'loadPrompts()' in panel.text and 'selectPrompt(p)' in panel.text and 'promptStatus' in panel.text
        assert 'formatCommandResult' in panel.text and 'cmdResultText' in panel.text and 'pretty(v)' in panel.text
        assert 'Tools' in panel.text and 'Skills' in panel.text and 'Tasks' in panel.text and 'loadAssets' in panel.text and 'saveTask' in panel.text and 'taskFilterScopeType' in panel.text and 'runtime_kind' in panel.text
        assert 'formatTaskTime' in panel.text and 'Europe/Madrid' in panel.text
        assert 'Providers' in panel.text and 'Provider Calls' in panel.text and 'Scopes' in panel.text and 'Task Runs' in panel.text and 'Roxanne' in panel.text
        assert 'selectTab(t)' in panel.text and 'loadTab(t)' in panel.text and 'openRoxanne()' in panel.text
        assert 'memoryEventsMinutes:60' in panel.text and 'memoryEventsStatus' in panel.text
        assert '/api/memory-events?minutes=${minutes}&limit=200' in panel.text
        assert 'startMemoryEventsRefresh()' in panel.text and "t==='Memory'" in panel.text
        assert 'roxanne-shell' in panel.text and 'loadRoxanneThread' in panel.text and 'saveRoxanneProfile' in panel.text
        assert 'roxanneOpen' not in panel.text and 'x-show="roxanneOpen"' not in panel.text
        assert "scopeQuery(this.assetScopeType,this.assetScopeId)" in panel.text
        assert "api/assets?asset_type=${kind}&scope_type=${this.assetScopeType}&scope_id=" not in panel.text
        assert 'assetScopeReady()' in panel.text and 'scope id required' in panel.text
        assert 'Debug' in panel.text and 'loadLogging' in panel.text and 'provider HTTP debug' in panel.text
        logging_cfg=(await c.get('/api/logging')).json()
        assert 'provider' in logging_cfg['components'] and 'trace' in logging_cfg['levels']
        logging_resp=await c.put('/api/logging',json={'console_level':'debug','component_levels':{'provider':'debug','discord':'info'},'provider_http_debug':True})
        assert logging_resp.status_code==200 and logging_resp.json()['config']['provider_http_debug'] is True
        assert 'component_levels = {' in app.state.config_path.read_text(encoding='utf-8')
        assert (await c.put('/api/prompts',json={'scope_type':'global','scope_id':None,'body':'hi'})).status_code==200
        prompt_rows=(await c.get('/api/prompts')).json()
        assert prompt_rows and prompt_rows[0]['body']=='hi'
        assert (await c.post('/api/permissions',json={'user_id':'u','scope_type':'global','scope_id':None,'level':'admin'})).status_code==200
        perms=(await c.get('/api/permissions')).json(); assert perms
        assert (await c.delete(f"/api/permissions/{perms[0]['id']}")).status_code==200
        root_perm=next(p for p in (await c.get('/api/permissions')).json() if p['user_id']=='1482143139828596916')
        assert root_perm['level']=='root'
        assert (await c.delete(f"/api/permissions/{root_perm['id']}")).status_code==400
        mid=(await c.post('/api/memories',json={'str_discord_id':'123456789012345678','str_annotations':'likes chess'})).json()['int_memory_id']
        assert (await c.get('/api/memories?str_query=chess')).json()
        assert (await c.put(f'/api/memories/{mid}',json={'str_discord_id':'123456789012345678','str_annotations':'likes go'})).status_code==200
        assert (await c.post(f'/api/memories/{mid}/approve')).status_code==200
        assert (await c.post('/api/panel-chat',json={'message':'hello'})).status_code==200
        assert (await c.get('/api/panel-chat')).json()
        mem_events=(await c.get('/api/memory-events?minutes=10')).json()
        assert any(r['role']=='operator' and r['content']=='hello' for r in mem_events)
        assert (await c.post('/api/discord-identity-map',json={'snowflake':'1504398705539944560','label':'Bossman','kind':'user'})).status_code==200
        identity_rows=(await c.get('/api/discord-identity-map')).json()
        assert any(r['snowflake']=='1504398705539944560' and r['label']=='Bossman' for r in identity_rows)
        assets=(await c.get('/api/assets?asset_type=tool')).json()
        assert any(a['name']=='react_emoji' for a in assets)
        assert any(a['name']=='current_time' for a in assets)
        web_fetch=next(a for a in assets if a['name']=='web_fetch')
        assert web_fetch['executor_name']=='web_fetch' and web_fetch['schema_json'] and web_fetch['globally_disabled']==0
        assert 'restoreToolSnapshot' in panel.text and 'disableAssetEverywhere' in panel.text and 'schema_json' in panel.text
        assert (await c.get('/api/assets?asset_type=tool&scope_type=global&scope_id=')).status_code==200
        assert (await c.get('/api/assets?asset_type=skill&scope_type=global&scope_id=')).status_code==200
        assert (await c.get('/api/assets?asset_type=tool&scope_type=dm&scope_id=')).status_code==400
        new_asset=await c.post('/api/assets',json={'asset_type':'tool','name':'panel_tool','description':'from panel','scope_type':'global','scope_id':None,'enabled':True})
        assert new_asset.status_code==200
        assert (await c.patch(f"/api/assets/{new_asset.json()['id']}",json={'enabled':False})).status_code==200
        assert (await c.delete(f"/api/assets/{new_asset.json()['id']}")).status_code==200
        assert (await c.patch(f"/api/assets/{web_fetch['id']}",json={'enabled':False,'globally_disabled':True})).status_code==200
        disabled=(await c.get('/api/assets?asset_type=tool')).json()
        assert next(a for a in disabled if a['name']=='web_fetch')['globally_disabled']==1
        assert (await c.delete(f"/api/assets/{web_fetch['id']}")).status_code==200
        assert all(a['name']!='web_fetch' for a in (await c.get('/api/assets?asset_type=tool')).json())
        assert (await c.post('/api/assets/snapshot/apply',json={'version':'latest'})).status_code==200
        assert any(a['name']=='web_fetch' for a in (await c.get('/api/assets?asset_type=tool')).json())
        providers=(await c.get('/api/providers')).json()
        assert providers and providers[0]['api_key_present'] is False and 'api_key' not in providers[0] and 'api_key_encrypted' not in providers[0]
        provider_resp=await c.post('/api/providers',json={'name':'openrouter_main','provider_type':'openrouter','base_url':'https://openrouter.ai/api/v1','default_model':'open/model','api_key':'secret-key','enabled':True})
        assert provider_resp.status_code==200
        provider_id=provider_resp.json()['id']
        shown=(await c.get(f'/api/providers/{provider_id}')).json()
        assert shown['api_key_present'] is True and shown['api_key_last4']=='-key' and 'secret-key' not in str(shown)
        assert (await c.post(f'/api/providers/{provider_id}/models',json={'model':'open/model','enabled':True})).status_code==200
        assert (await c.get(f'/api/providers/{provider_id}/models')).json()
        assert (await c.patch('/api/scopes/dm/scope-1',json={'provider_id':provider_id,'model':'open/model'})).status_code==200
        effective=(await c.get('/api/scopes/effective?scope_type=dm&scope_id=scope-1')).json()
        assert effective['model']=='open/model' and effective['provider']['name']=='openrouter_main'
        assert (await c.post('/api/instructions',json={'name':'default','scope_type':'global','scope_id':None,'body':'be useful'})).status_code==200
        assert (await c.get('/api/instructions')).json()
        assert (await c.get('/api/bot-entries')).json()
        assert (await c.get('/api/provider-calls/summary')).status_code==200
        assert (await c.get('/api/provider-calls')).status_code==200
        new_task=await c.post('/api/tasks',json={'name':'panel_task','prompt':'do work','schedule_minutes':30,'scope_type':'global','scope_id':None,'enabled':False})
        assert new_task.status_code==200
        assert (await c.get('/api/task-runs')).status_code==200
        assert any(t['name']=='panel_task' for t in (await c.get('/api/tasks')).json())
        guild_task=await c.post('/api/tasks',json={'name':'guild_panel_task','prompt':'guild work','schedule_minutes':45,'scope_type':'guild','scope_id':'guild-1','enabled':False})
        assert guild_task.status_code==200
        assert any(t['name']=='guild_panel_task' for t in (await c.get('/api/tasks')).json())
        assert all(t['name']!='guild_panel_task' for t in (await c.get('/api/tasks?scope_type=global')).json())
        assert any(t['name']=='guild_panel_task' for t in (await c.get('/api/tasks?scope_type=guild&scope_id=guild-1')).json())
        assert (await c.delete(f"/api/tasks/{guild_task.json()['id']}")).status_code==200
        task_id=new_task.json()['id']
        assert (await c.patch(f'/api/tasks/{task_id}',json={'prompt':'do better work','enabled':True,'schedule_minutes':31,'runtime_kind':'rem'})).status_code==200
        patched_tasks=(await c.get('/api/tasks?scope_type=global')).json()
        assert any(t['id']==task_id and t['prompt']=='do better work' and t['enabled']==1 and t['runtime_kind']=='rem' and t['next_run_utc'] for t in patched_tasks)
        assert any(t['id']==task_id and t['timezone']=='Europe/Madrid' and t['next_run_local'] for t in patched_tasks)
        task_fix=await c.post('/api/tasks/snapshot/apply',json={'version':'latest'})
        assert task_fix.status_code==200 and task_fix.json()['ok'] is True
        assert any(t['name']=='rem_dream' for t in (await c.get('/api/tasks')).json())
        assert (await c.post(f"/api/tasks/{new_task.json()['id']}/run")).status_code==200
        assert (await c.post(f"/api/tasks/{new_task.json()['id']}/disable")).status_code==200
        assert (await c.delete(f"/api/tasks/{new_task.json()['id']}")).status_code==200
        assert all(t['name']!='panel_task' for t in (await c.get('/api/tasks')).json())
        assert (await c.delete(f"/api/tasks/{new_task.json()['id']}")).status_code==404
        assert (await c.post('/api/command',json={'command':'!status'})).status_code==200
        await app.state.db.execute("INSERT INTO bot_logs(level,component,message,detail_json,timestamp_utc) VALUES ('error','discord','typing stopped',?,?)",('{"api_key":"secret-key","detail":"generation stopped"}',bot.utc_now()))
        await app.state.db.commit()
        debug_rows=(await c.get('/api/bot-logs?component=discord&min_level=debug')).json()
        assert debug_rows and debug_rows[0]['timezone']=='Europe/Madrid' and debug_rows[0]['timestamp_local']
        profile=(await c.get('/api/roxanne/profile'))
        assert profile.status_code==200
        assert 'direct operator access' in profile.json()['system_prompt']
        params=(await c.get('/api/provider-parameters')).json()
        assert params and params[0]['name']=='default-balanced'
        profile_patch=await c.patch('/api/roxanne/profile',json={'provider_id':provider_id,'model':'open/model','parameter_profile_id':params[0]['id'],'reasoning_mode':'high','tools_enabled':True})
        assert profile_patch.status_code==200
        patched_profile=(await c.get('/api/roxanne/profile')).json()
        assert patched_profile['reasoning_mode']=='high' and patched_profile['tools_enabled']==1 and patched_profile['provider']['name']=='openrouter_main'
        browser_null_patch=await c.patch('/api/roxanne/profile',json={'provider_id':'null','model':'','parameter_profile_id':'null','reasoning_mode':'inherit','tools_enabled':False,'system_prompt':''})
        assert browser_null_patch.status_code==200
        browser_null_profile=(await c.get('/api/roxanne/profile')).json()
        assert browser_null_profile['provider_id'] is None and browser_null_profile['parameter_profile_id'] is None and browser_null_profile['model'] is None and browser_null_profile['tools_enabled']==0
        rox_mem=(await c.get('/api/roxanne/memory')).json()
        assert rox_mem and 'Roxanne' in rox_mem[0]['body']
        added_mem=await c.post('/api/roxanne/memory',json={'title':'Operator note','body':'Use docs before saying no access','tags':'debug'})
        assert added_mem.status_code==200
        assert (await c.patch(f"/api/roxanne/memory/{added_mem.json()['id']}",json={'enabled':False})).status_code==200
        assert (await c.delete(f"/api/roxanne/memory/{added_mem.json()['id']}")).status_code==200
        session=await c.post('/api/roxanne/sessions',json={'title':'help','active_scope_type':'global','active_scope_id':None})
        assert session.status_code==200
        ask=await c.post('/api/roxanne/ask',json={'message':'how do providers work?','active_scope_type':'global','active_scope_id':None})
        assert ask.status_code==200 and ask.json()['message']=='stub-response'
        rox_ctx=app.state.ollama.calls[-1]['messages'][1]['content']
        assert 'Recent live DB rows' in rox_ctx and 'Roxanne static memory' in rox_ctx and 'typing stopped' in rox_ctx
        assert 'recent_memories' not in rox_ctx
        assert 'secret-key' not in rox_ctx and '***' in rox_ctx
        assert (await c.get(f"/api/roxanne/sessions/{ask.json()['session_id']}/messages")).json()
        rox_tools=(await c.get('/api/roxanne/tools')).json()
        assert {t['name'] for t in rox_tools} >= {'read_docs','web_fetch','web_search','memory_search','bash','memory_add','memory_update','memory_delete','memory_edit','memory_remove'}
        assert any(t['name']=='bash' and t['mode']=='operator_write' for t in rox_tools)
        logs=(await c.get('/api/commands-log')).json(); assert logs and logs[0]['source']=='panel'
        for url in ['/api/messages','/api/ollama-log','/api/bot-logs','/api/scopes','/api/prompts','/api/config']:
            assert (await c.get(url)).status_code==200
        assert (await c.get('/api/messages?limit=999999')).status_code==422
        assert (await c.get('/api/messages?q=%22')).status_code==200
        assert (await c.get('/api/memories?str_query=%22')).status_code==200
        assert (await c.put('/api/config',json={'panel':{'auth_token':'secret'},'bot':{'trigger_on':['ping']}})).status_code==200
        assert app.state.config_path.exists()
        assert (await c.post('/api/config/test-ollama')).status_code==200
        assert (await c.post('/api/config/test-discord')).status_code==200
        # Pydantic validation rejects invalid scope/memory fields and confidence
        assert (await c.put('/api/prompts',json={'scope_type':'bad','scope_id':None,'body':'x'})).status_code==422
        assert (await c.put('/api/prompts',json={'scope_type':'global','scope_id':'orphan','body':'x'})).status_code==400
        assert (await c.post('/api/command',json={'scope_type':'global','scope_id':'orphan','command':'!status'})).status_code==400
        assert (await c.post('/api/memories',json={'str_discord_id':'not-a-snowflake','str_annotations':'n'})).status_code==422
        assert (await c.post('/api/memories',json={'str_discord_id':'123456789012345678','str_annotations':'n','float_confidence':2.0})).status_code==422
        assert (await c.put('/api/prompts',json={'scope_type':'global','scope_id':None,'body':'x'*(bot.MAX_PROMPT_LENGTH+1)})).status_code==422
        assert (await c.post('/api/memories',json={'str_discord_id':'123456789012345678','str_annotations':'x'*(bot.MAX_MEMORY_NOTE_LENGTH+1)})).status_code==422
        assert (await c.post('/api/panel-chat',json={'message':'x'*(bot.MAX_PANEL_CHAT_LENGTH+1)})).status_code==422
        # Malformed panel command yields 400 with a logged 'malformed' command row
        bad=await c.post('/api/command',json={'command':'prompt','args':'"unterminated'}); assert bad.status_code==400
        bad_logs=(await c.get('/api/commands-log')).json(); assert any(r['reason']=='malformed' for r in bad_logs)
        panel_cmd=await c.post('/api/command',json={'command':'!status','user_id':'not-panel'}); assert panel_cmd.status_code==200
        logs=(await c.get('/api/commands-log')).json()
        assert any(r['command']=='status' and r['source']=='panel' and r['user_id']=='panel' for r in logs)

@pytest.mark.asyncio
async def test_discord_config_test_logs_http_failure(monkeypatch):
    monkeypatch.setattr(app.state,'config',types.SimpleNamespace(discord={'token':'bad-token'},ollama={},panel={},bot={}))
    monkeypatch.setattr(bot,'discord',object())
    class FakeClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url):
            return types.SimpleNamespace(status_code=401)
    monkeypatch.setattr(bot.httpx,'AsyncClient',FakeClient)
    tr=ASGITransport(app=app)
    async with AsyncClient(transport=tr, base_url='http://test') as c:
        c.cookies.set('session','secret')
        resp=await c.post('/api/config/test-discord')
        assert resp.json()['ok'] is False
        logs=(await c.get('/api/bot-logs')).json()
        assert logs and logs[0]['message']=='test-discord failed'

@pytest.mark.asyncio
async def test_config_update_creates_backup():
    tr=ASGITransport(app=app)
    async with AsyncClient(transport=tr, base_url='http://test') as c:
        c.cookies.set('session','secret')
        app.state.config_path.write_text('[panel]\nauth_token = "secret"\n',encoding='utf-8')
        resp=await c.put('/api/config',json={'panel':{'auth_token':'secret'},'ollama':{'default_model':'new-model'}})
        assert resp.status_code==200
        assert 'new-model' in app.state.config_path.read_text(encoding='utf-8')
        assert list(app.state.config_path.parent.glob('config.toml.*.bak'))

@pytest.mark.asyncio
async def test_config_update_ignores_redacted_secrets():
    app.state.config=types.SimpleNamespace(
        ollama={'api_key':'real-key','default_model':'old'},
        discord={'token':'real-token','i_understand_selfbot_risk':True},
        panel={'auth_token':'secret','port':8765},
        bot={'trigger_on':['ping','reply']},
    )
    tr=ASGITransport(app=app)
    async with AsyncClient(transport=tr, base_url='http://test') as c:
        c.cookies.set('session','secret')
        resp=await c.put('/api/config',json={'ollama':{'api_key':'***','default_model':'new'},'discord':{'token':'***'},'panel':{'auth_token':'***'}})
        assert resp.status_code==200
        assert app.state.config.ollama['api_key']=='real-key'
        assert app.state.config.discord['token']=='real-token'
        assert app.state.config.panel['auth_token']=='secret'
        assert app.state.config.ollama['default_model']=='new'

@pytest.mark.asyncio
async def test_config_update_validates_inputs():
    tr=ASGITransport(app=app)
    async with AsyncClient(transport=tr, base_url='http://test') as c:
        c.cookies.set('session','secret')
        assert (await c.put('/api/config',json={'panel':{'auth_token':''}})).status_code==422
        assert (await c.put('/api/config',json={'bot':{'trigger_on':['ping','ping']}})).status_code==422
        assert (await c.put('/api/config',json={'bot':{'trigger_on':[]}})).status_code==422

@pytest.mark.asyncio
async def test_panel_chat_executes_tool_calls():
    class ToolOllama:
        def __init__(self): self.calls=[]
        async def chat(self,messages,tools=None,**kwargs):
            prepared=bot.tool_turns.prepare_messages_for_tool_turn(messages,kwargs.get('dynamic_context'))
            self.calls.append({'messages':prepared,'raw_messages':[dict(m) for m in messages],'tools':tools})
            if len(self.calls)==1:
                return {'message':{'content':'','tool_calls':[{'function':{'name':'list_bot_logs','arguments':{'limit':5}}}]}}
            assert any(m.get('role')=='tool' for m in messages)
            return {'message':{'content':'tool result summarized'}}
    app.state.ollama=ToolOllama()
    await app.state.db.execute("INSERT INTO bot_logs(level,component,message,timestamp_utc) VALUES ('info','test','hello',?)",(bot.utc_now(),)); await app.state.db.commit()
    tr=ASGITransport(app=app)
    async with AsyncClient(transport=tr, base_url='http://test') as c:
        c.cookies.set('session','secret')
        resp=await c.post('/api/panel-chat',json={'message':'show logs'})
        assert resp.status_code==200
        assert resp.json()[-1]['content']=='tool result summarized'
        assert app.state.ollama.calls[0]['tools']
        first='\n'.join(m.get('content','') for m in app.state.ollama.calls[0]['messages'])
        second='\n'.join(m.get('content','') for m in app.state.ollama.calls[1]['messages'])
        raw='\n'.join(m.get('content','') for call in app.state.ollama.calls for m in call['raw_messages'])
        assert first.count('[[ PANEL TOOL ROUND 1/3 ]]')==1
        assert second.count('[[ PANEL TOOL ROUND 2/3 ]]')==1
        assert '[[ PANEL TOOL ROUND 1/3 ]]' not in second
        assert '[[ PANEL TOOL ROUND' not in raw

@pytest.mark.asyncio
async def test_roxanne_executes_tool_calls_and_followup():
    class ToolRoxanne:
        def __init__(self): self.calls=[]
        async def chat(self,messages,tools=None,**kwargs):
            prepared=bot.tool_turns.prepare_messages_for_tool_turn(messages,kwargs.get('dynamic_context'))
            self.calls.append({'messages':prepared,'raw_messages':[dict(m) for m in messages],'tools':tools,'kwargs':kwargs})
            if len(self.calls)==1:
                return {'message':{'content':'','tool_calls':[{'function':{'name':'read_docs','arguments':{'name':'admin','limit':10}}}]}}
            assert any(m.get('role')=='tool' for m in messages)
            return {'message':{'content':'Roxanne used docs'}}
    app.state.ollama=ToolRoxanne()
    tr=ASGITransport(app=app)
    async with AsyncClient(transport=tr, base_url='http://test') as c:
        c.cookies.set('session','secret')
        resp=await c.post('/api/roxanne/ask',json={'message':'read docs','active_scope_type':'global','active_scope_id':None})
        assert resp.status_code==200
        assert resp.json()['message']=='Roxanne used docs'
        assert app.state.ollama.calls[0]['tools']
        first='\n'.join(m.get('content','') for m in app.state.ollama.calls[0]['messages'])
        second='\n'.join(m.get('content','') for m in app.state.ollama.calls[1]['messages'])
        raw='\n'.join(m.get('content','') for call in app.state.ollama.calls for m in call['raw_messages'])
        assert first.count('[[ ROXANNE TOOL ROUND 1/3 ]]')==1
        assert second.count('[[ ROXANNE TOOL ROUND 2/3 ]]')==1
        assert '[[ ROXANNE TOOL ROUND 1/3 ]]' not in second
        assert '[[ ROXANNE TOOL ROUND' not in raw
        msgs=(await c.get(f"/api/roxanne/sessions/{resp.json()['session_id']}/messages")).json()
        assert any(m['role']=='tool' and 'Dirac Admin Help' in m['content'] for m in msgs)

@pytest.mark.asyncio
async def test_panel_finalization_tool_calls_are_ignored_not_persisted():
    class FinalizingPanel:
        def __init__(self): self.calls=[]
        async def chat(self,messages,tools=None,**kwargs):
            prepared=bot.tool_turns.prepare_messages_for_tool_turn(messages,kwargs.get('dynamic_context'))
            self.calls.append({'messages':prepared,'raw_messages':[dict(m) for m in messages],'tools':tools})
            return {'message':{'content':'','tool_calls':[{'function':{'name':'current_time','arguments':{}}}]}}
    app.state.ollama=FinalizingPanel()
    tr=ASGITransport(app=app)
    async with AsyncClient(transport=tr, base_url='http://test') as c:
        c.cookies.set('session','secret')
        resp=await c.post('/api/panel-chat',json={'message':'keep using tools'})
        assert resp.status_code==200
        rows=resp.json()
        assert rows[-1]['content'].startswith('```dirac\nERROR: panel chat cut short')
        assert rows[-1]['tool_calls_json'] is None
        final='\n'.join(m.get('content','') for m in app.state.ollama.calls[-1]['messages'])
        raw='\n'.join(m.get('content','') for call in app.state.ollama.calls for m in call['raw_messages'])
        assert final.count('[[ PANEL TEXT-ONLY FINALIZATION ]]')==1
        assert '[[ PANEL TOOL ROUND' not in raw

@pytest.mark.asyncio
async def test_roxanne_finalization_tool_calls_are_ignored_not_persisted():
    class FinalizingRoxanne:
        def __init__(self): self.calls=[]
        async def chat(self,messages,tools=None,**kwargs):
            prepared=bot.tool_turns.prepare_messages_for_tool_turn(messages,kwargs.get('dynamic_context'))
            self.calls.append({'messages':prepared,'raw_messages':[dict(m) for m in messages],'tools':tools})
            return {'message':{'content':'','tool_calls':[{'function':{'name':'read_docs','arguments':{'name':'admin','limit':3}}}]}}
    app.state.ollama=FinalizingRoxanne()
    tr=ASGITransport(app=app)
    async with AsyncClient(transport=tr, base_url='http://test') as c:
        c.cookies.set('session','secret')
        resp=await c.post('/api/roxanne/ask',json={'message':'keep using tools','active_scope_type':'global','active_scope_id':None})
        assert resp.status_code==200
        data=resp.json()
        assert data['message'].startswith('```dirac\nERROR: Roxanne tool loop cut short')
        msgs=(await c.get(f"/api/roxanne/sessions/{data['session_id']}/messages")).json()
        assert msgs[-1]['role']=='assistant'
        assert msgs[-1]['tool_calls_json'] is None
        final='\n'.join(m.get('content','') for m in app.state.ollama.calls[-1]['messages'])
        raw='\n'.join(m.get('content','') for call in app.state.ollama.calls for m in call['raw_messages'])
        assert final.count('[[ ROXANNE TEXT-ONLY FINALIZATION ]]')==1
        assert '[[ ROXANNE TOOL ROUND' not in raw

@pytest.mark.asyncio
async def test_roxanne_can_call_memory_and_bash_tools():
    class ToolRoxanne:
        def __init__(self): self.calls=[]
        async def chat(self,messages,tools=None,**kwargs):
            self.calls.append({'messages':messages,'tools':tools,'kwargs':kwargs})
            if len(self.calls)==1:
                return {'message':{'content':'','tool_calls':[
                    {'function':{'name':'memory_add','arguments':{'str_discord_id':'123456789012345678','str_annotations':'roxanne note'}}},
                    {'function':{'name':'bash','arguments':{'command':'python doctor.py paths','timeout_s':5}}},
                ]}}
            assert any(m.get('role')=='tool' and 'memory_add' in m.get('name','') and '"ok": true' in m.get('content','') for m in messages)
            assert any(m.get('role')=='tool' and 'repo_dir' in m.get('content','') for m in messages)
            return {'message':{'content':'Roxanne repaired state'}}
    app.state.ollama=ToolRoxanne()
    tr=ASGITransport(app=app)
    async with AsyncClient(transport=tr, base_url='http://test') as c:
        c.cookies.set('session','secret')
        resp=await c.post('/api/roxanne/ask',json={'message':'add memory and inspect paths','active_scope_type':'global','active_scope_id':None})
        assert resp.status_code==200
        assert resp.json()['message']=='Roxanne repaired state'
        rows=await bot.MemoryManager(app.state.db).search('123456789012345678','roxanne note')
        assert rows and rows[0]['str_created_by']=='roxanne'

@pytest.mark.asyncio
async def test_panel_chat_ollama_failure_logs_and_returns_502():
    class AlwaysFailingOllama:
        async def chat(self,*args,**kwargs): raise RuntimeError('down')
    app.state.ollama=AlwaysFailingOllama()
    tr=ASGITransport(app=app)
    async with AsyncClient(transport=tr, base_url='http://test') as c:
        c.cookies.set('session','secret')
        resp=await c.post('/api/panel-chat',json={'message':'hello'})
        assert resp.status_code==502
        logs=(await c.get('/api/bot-logs')).json()
        assert any(r['component']=='ollama' and r['message']=='panel chat failed' for r in logs)

@pytest.mark.asyncio
async def test_panel_tool_errors_are_bounded():
    assert await bot._run_panel_tool(app.state.db,'missing_tool',{'limit':999999})=={'error':'unknown tool'}
    rows=await bot._run_panel_tool(app.state.db,'messages_search',{'q':'100% literal','limit':999999})
    assert rows==[]
    docs=await bot._run_panel_tool(app.state.db,'read_docs',{'name':'admin','limit':5})
    assert docs['name']=='admin' and 'Dirac Admin Help' in docs['content']
    now=await bot._run_panel_tool(app.state.db,'current_time',{})
    assert now['timezone']=='Europe/Madrid' and now['local_iso']
    added=await bot._run_panel_tool(app.state.db,'memory_add',{'str_discord_id':'123456789012345678','str_annotations':'panel note'})
    assert added['ok'] is True
    updated=await bot._run_panel_tool(app.state.db,'memory_update',{'int_memory_id':str(added['int_memory_id']),'str_annotations':'panel updated'})
    assert updated['ok'] is True and updated['int_memory_id']==added['int_memory_id']
    shell=await bot._run_panel_tool(app.state.db,'bash',{'command':'python doctor.py paths','timeout_s':5})
    assert shell['ok'] is True and 'repo_dir' in shell['stdout']
    deleted=await bot._run_panel_tool(app.state.db,'memory_delete',{'int_memory_id':str(updated['int_new_memory_id'])})
    assert deleted['ok'] is True
