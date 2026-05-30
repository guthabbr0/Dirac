import asyncio
import json
import re

import aiosqlite
import pytest
import bot
from bot import SCHEMA_SQL, bootstrap_db, DbWriter, RuntimeDb, _upsert, utc_now
from dirac import memory_contract

@pytest.mark.asyncio
async def test_schema_bootstrap(db):
    cur=await db.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")
    names={r[0] for r in await cur.fetchall()}
    # SCHEMA_SQL uses simple CREATE TABLE statements; derive table names so schema additions are covered automatically.
    expected=set(re.findall(r'CREATE (?:VIRTUAL )?TABLE IF NOT EXISTS (\w+)', SCHEMA_SQL))
    for t in expected:
        assert t in names
    for table,name in [('service_providers','ollama-default'),('bot_entries','dirac'),('provider_parameters','default-balanced'),('roxanne_profiles','default')]:
        cur=await db.execute(f'SELECT name FROM {table} WHERE name=?',(name,))
        assert await cur.fetchone()
    cur=await db.execute("SELECT body FROM roxanne_memory WHERE tags LIKE '%identity%'")
    assert 'Roxanne' in (await cur.fetchone())[0]
    cur=await db.execute("SELECT level FROM permissions WHERE user_id='1482143139828596916' AND scope_type='global' AND scope_id IS NULL")
    assert await cur.fetchone()==('root',)
    cur=await db.execute("SELECT name,schedule_minutes,enabled,runtime_kind FROM agent_tasks WHERE name='rem_dream'")
    assert await cur.fetchone()==('rem_dream',10,1,'rem')
    cur=await db.execute("SELECT value FROM schema_meta WHERE key='schema_tag'")
    assert await cur.fetchone()==(bot.DB_SCHEMA_TAG,)
    cur=await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='news_items'")
    assert await cur.fetchone()
    cur=await db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_news_items_posted'")
    assert await cur.fetchone()

@pytest.mark.asyncio
async def test_bootstrap_refuses_newer_schema_tag():
    async with aiosqlite.connect(':memory:') as conn:
        await conn.execute('CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)')
        await conn.execute("INSERT INTO schema_meta(key,value,updated_at) VALUES ('schema_tag','99.0.0-local',?)",(utc_now(),))
        await conn.commit()
        with pytest.raises(RuntimeError,match='newer than source schema tag'):
            await bootstrap_db(conn)

@pytest.mark.asyncio
async def test_fts_triggers(db):
    await db.execute("INSERT INTO messages(discord_msg_id,scope_type,scope_id,author_id,author_name,content,timestamp_utc) VALUES ('m1','dm','s','u','Ann','hello zanzibar',?)",(utc_now(),)); await db.commit()
    cur=await db.execute("SELECT rowid,content FROM messages_fts WHERE messages_fts MATCH 'zanzibar'"); assert (await cur.fetchone())[1]=='hello zanzibar'
    await db.execute("UPDATE messages SET content='hello cairo' WHERE discord_msg_id='m1'"); await db.commit()
    cur=await db.execute("SELECT content FROM messages_fts WHERE messages_fts MATCH 'cairo'"); assert await cur.fetchone()
    await db.execute("DELETE FROM messages WHERE discord_msg_id='m1'"); await db.commit()
    cur=await db.execute("SELECT content FROM messages_fts WHERE messages_fts MATCH 'cairo'"); assert await cur.fetchone() is None

@pytest.mark.asyncio
async def test_wal_mode_file_db(tmp_path):
    db_path=str(tmp_path/'test_wal.sqlite')
    async with aiosqlite.connect(db_path) as conn:
        await bootstrap_db(conn)
        cur=await conn.execute('PRAGMA journal_mode')
        assert (await cur.fetchone())[0].lower() == 'wal'

@pytest.mark.asyncio
async def test_bootstrap_migrates_existing_agent_tables():
    async with aiosqlite.connect(':memory:') as conn:
        await conn.execute("CREATE TABLE agent_tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, prompt TEXT NOT NULL, status TEXT NOT NULL, requested_by TEXT NOT NULL, source TEXT NOT NULL, scope_type TEXT NOT NULL, scope_id TEXT, backend TEXT NOT NULL DEFAULT 'ollama', result TEXT, error TEXT, created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT)")
        await conn.execute("CREATE TABLE agent_assets (id INTEGER PRIMARY KEY AUTOINCREMENT, asset_type TEXT NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL, body TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL)")
        await conn.commit()
        await bootstrap_db(conn)
        cur=await conn.execute('PRAGMA table_info(agent_tasks)')
        task_cols={r[1] for r in await cur.fetchall()}
        cur=await conn.execute('PRAGMA table_info(agent_assets)')
        asset_cols={r[1] for r in await cur.fetchall()}
        assert {'name','enabled','schedule_minutes','next_run_utc','run_count'} <= task_cols
        assert {'provider_id','model','parameter_profile_id','bot_entry_id','runtime_kind','target_scope_type','target_scope_id'} <= task_cols
        assert {'scope_type','scope_id','enabled','is_builtin','schema_json','executor_name','snapshot_version','globally_disabled'} <= asset_cols
        cur=await conn.execute('PRAGMA table_info(roxanne_profiles)')
        rox_cols={r[1] for r in await cur.fetchall()}
        assert {'reasoning_mode','tools_enabled'} <= rox_cols
        cur=await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='roxanne_memory'")
        assert await cur.fetchone()
        cur=await conn.execute("SELECT COUNT(*) FROM agent_assets WHERE is_builtin=1 AND name IN ('react_emoji','silencer','current_time','web_fetch','web_search','memory_search','memory_add','memory_update','memory_delete','memory_edit','memory_remove','discord_id','discord_ground','discord_tag','dyslexic_helper','bash')")
        assert (await cur.fetchone())[0]==16
        cur=await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tool_snapshots'")
        assert await cur.fetchone()
        cur=await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_snapshots'")
        assert await cur.fetchone()
        cur=await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='news_items'")
        assert await cur.fetchone()

@pytest.mark.asyncio
async def test_schema_sql_documents_canonical_memory_contract(db):
    cur=await db.execute('PRAGMA table_info(memories)')
    cols=[row[1] for row in await cur.fetchall()]
    assert cols==[
        'int_memory_id',
        'str_discord_id',
        'str_annotations',
        'array_tags',
        'float_confidence',
        'str_created_utc',
        'str_created_by',
        'int_superseded_by',
    ]
    assert "content_rowid='int_memory_id'" in SCHEMA_SQL
    assert ('target' + '_type') not in SCHEMA_SQL
    assert ('target' + '_id') not in SCHEMA_SQL

def test_builtin_tool_snapshot_matches_memory_contract():
    snapshot=json.loads(bot.BUILTIN_TOOLS_SNAPSHOT_PATH.read_text(encoding='utf-8'))
    tools={tool['name']:tool for tool in snapshot['tools']}
    for name in memory_contract.MEMORY_TOOL_SCHEMAS:
        assert tools[name]['body']==memory_contract.memory_tool_body(name)
        assert tools[name]['schema']==memory_contract.memory_tool_schema(name)
        assert tools[name]['schema_json']==memory_contract.memory_tool_schema(name)

@pytest.mark.asyncio
async def test_builtin_tool_snapshot_restore_preserves_disable_state(db):
    await db.execute("UPDATE agent_assets SET description='broken',body='bad',schema_json=NULL,executor_name=NULL,enabled=0,globally_disabled=1 WHERE name='silencer' AND scope_type='global'")
    await db.commit()
    result=await bot.apply_builtin_tool_snapshot(db,'latest',created_by='test',preserve_state=True)
    assert result['inserted']==0 and result['restored']>=4
    cur=await db.execute("SELECT description,body,schema_json,executor_name,enabled,globally_disabled FROM agent_assets WHERE name='silencer' AND scope_type='global'")
    description,body,schema_json,executor_name,enabled,globally_disabled=await cur.fetchone()
    assert 'broken' not in description and 'triggering author' in body
    assert schema_json and executor_name=='silencer'
    assert (enabled,globally_disabled)==(0,1)

@pytest.mark.asyncio
async def test_builtin_snapshot_seeds_web_fetch(db):
    cur=await db.execute("SELECT executor_name,schema_json,enabled FROM agent_assets WHERE name='web_fetch' AND scope_type='global'")
    executor_name,schema_json,enabled=await cur.fetchone()
    assert executor_name=='web_fetch' and '"web_fetch"' in schema_json and enabled==1

@pytest.mark.asyncio
async def test_builtin_snapshot_seeds_memory_and_discord_id_tools(db):
    cur=await db.execute("SELECT name,executor_name,schema_json FROM agent_assets WHERE name IN ('memory_search','memory_add','memory_update','memory_delete','memory_edit','memory_remove','discord_id','discord_ground','discord_tag','dyslexic_helper','bash') AND scope_type='global' ORDER BY name")
    rows=await cur.fetchall()
    assert [(r[0],r[1]) for r in rows]==[('bash','bash'),('discord_ground','discord_ground'),('discord_id','discord_id'),('discord_tag','discord_tag'),('dyslexic_helper','dyslexic_helper'),('memory_add','memory_add'),('memory_delete','memory_delete'),('memory_edit','memory_update'),('memory_remove','memory_delete'),('memory_search','memory_search'),('memory_update','memory_update')]
    assert all(r[2] and r[0] in r[2] for r in rows)

@pytest.mark.asyncio
async def test_builtin_task_snapshot_restore_preserves_enabled_state(db):
    await db.execute("UPDATE agent_tasks SET prompt='broken',enabled=0,next_run_utc=NULL,runtime_kind='default' WHERE name='rem_dream'")
    await db.commit()
    result=await bot.apply_builtin_task_snapshot(db,'latest',created_by='test',preserve_enabled=True)
    assert result['restored']>=1
    cur=await db.execute("SELECT prompt,enabled,next_run_utc,runtime_kind FROM agent_tasks WHERE name='rem_dream'")
    prompt,enabled,next_run,runtime_kind=await cur.fetchone()
    assert 'Run Dirac REM memory assimilation' in prompt
    assert enabled==0 and next_run is None and runtime_kind=='rem'

@pytest.mark.asyncio
async def test_bootstrap_migrates_bot_logs_for_trace_and_scope_columns():
    async with aiosqlite.connect(':memory:') as conn:
        await conn.execute("CREATE TABLE bot_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, level TEXT NOT NULL CHECK (level IN ('debug','info','warn','error')), component TEXT NOT NULL, message TEXT NOT NULL, detail_json TEXT, timestamp_utc TEXT NOT NULL)")
        await conn.execute("INSERT INTO bot_logs(level,component,message,timestamp_utc) VALUES ('info','bot','old row',?)",(utc_now(),))
        await conn.commit()
        await bootstrap_db(conn)
        await conn.execute("INSERT INTO bot_logs(level,component,message,scope_type,scope_id,timestamp_utc) VALUES ('trace','provider','new row','dm','scope-1',?)",(utc_now(),))
        await conn.commit()
        cur=await conn.execute("SELECT level,scope_type,scope_id FROM bot_logs WHERE message='new row'")
        assert await cur.fetchone()==('trace','dm','scope-1')

@pytest.mark.asyncio
async def test_bootstrap_migrates_permissions_for_root_level():
    async with aiosqlite.connect(':memory:') as conn:
        await conn.execute("CREATE TABLE permissions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, scope_type TEXT NOT NULL CHECK (scope_type IN ('global','dm','group','guild')), scope_id TEXT, level TEXT NOT NULL CHECK (level IN ('admin','user','blocked')), added_at TEXT NOT NULL)")
        await conn.execute("INSERT INTO permissions(user_id,scope_type,scope_id,level,added_at) VALUES ('u','global',NULL,'admin',?)",(utc_now(),))
        await conn.commit()
        await bootstrap_db(conn)
        await conn.execute("INSERT INTO permissions(user_id,scope_type,scope_id,level,added_at) VALUES ('r','global',NULL,'root',?)",(utc_now(),))
        await conn.commit()
        cur=await conn.execute("SELECT level FROM permissions WHERE user_id='1482143139828596916' AND scope_type='global' AND scope_id IS NULL")
        assert await cur.fetchone()==('root',)

@pytest.mark.asyncio
async def test_writer_queue_serializes(runtime_tg):
    w=await DbWriter.for_memory(); await w.start(runtime_tg)
    async def producer(n):
        for i in range(10):
            await w.execute("INSERT INTO messages(discord_msg_id,scope_type,scope_id,author_id,author_name,content,timestamp_utc) VALUES (?,?,?,?,?,?,?)",(f'{n}-{i}','dm','s','u','U','hi',utc_now()))
    await asyncio.gather(*(producer(n) for n in range(10)))
    cur=await w.conn.execute('SELECT COUNT(*) FROM messages'); assert (await cur.fetchone())[0]==100
    await w.close()

@pytest.mark.asyncio
async def test_runtime_db_routes_writes_through_writer(monkeypatch, runtime_tg):
    w=await DbWriter.for_memory(); await w.start(runtime_tg)
    seen=[]
    original_execute=w.execute
    async def recording_execute(sql, params=()):
        seen.append(sql)
        return await original_execute(sql, params)
    monkeypatch.setattr(w,'execute',recording_execute)
    db=RuntimeDb(w)
    await db.execute("INSERT INTO messages(discord_msg_id,scope_type,scope_id,author_id,author_name,content,timestamp_utc) VALUES (?,?,?,?,?,?,?)",('queued','dm','s','u','U','hi',utc_now()))
    await db.commit()
    cur=await db.execute('SELECT COUNT(*) FROM messages')
    assert (await cur.fetchone())[0]==1
    assert seen and seen[0].startswith('INSERT INTO messages')
    await w.close()

@pytest.mark.asyncio
async def test_writer_ignores_cancelled_queued_future(runtime_tg):
    w=await DbWriter.for_memory(); await w.start(runtime_tg)
    fut=asyncio.get_running_loop().create_future(); fut.cancel()
    await w.queue.put(("INSERT INTO messages(discord_msg_id,scope_type,scope_id,author_id,author_name,content,timestamp_utc) VALUES (?,?,?,?,?,?,?)",('cancelled','dm','s','u','U','hi',utc_now()),fut))
    await asyncio.wait_for(w.queue.join(),1)
    await w.execute("INSERT INTO messages(discord_msg_id,scope_type,scope_id,author_id,author_name,content,timestamp_utc) VALUES (?,?,?,?,?,?,?)",('after','dm','s','u','U','hi',utc_now()))
    cur=await w.conn.execute('SELECT COUNT(*) FROM messages')
    assert (await cur.fetchone())[0]==2
    await w.close()

@pytest.mark.asyncio
async def test_runtime_upsert_is_serialized(runtime_tg):
    w=await DbWriter.for_memory(); await w.start(runtime_tg)
    db=RuntimeDb(w)
    async def write_prompt(i):
        await _upsert(db,'prompts',['scope_type','scope_id'],['global',None],{'body':f'body-{i}','updated_at':utc_now(),'updated_by':'t'})
    await asyncio.gather(*(write_prompt(i) for i in range(20)))
    cur=await w.conn.execute("SELECT COUNT(*), body FROM prompts WHERE scope_type='global' AND scope_id IS NULL")
    count, body=await cur.fetchone()
    assert count==1 and body.startswith('body-')
    await w.close()

@pytest.mark.asyncio
async def test_runtime_with_statement_uses_writer(monkeypatch, runtime_tg):
    w=await DbWriter.for_memory(); await w.start(runtime_tg)
    seen=[]
    original_execute=w.execute
    async def recording_execute(sql, params=()):
        seen.append(sql)
        return await original_execute(sql, params)
    monkeypatch.setattr(w,'execute',recording_execute)
    db=RuntimeDb(w)
    await db.execute("WITH payload(v) AS (SELECT 'cte') INSERT INTO messages(discord_msg_id,scope_type,scope_id,author_id,author_name,content,timestamp_utc) SELECT v,'dm','s','u','U','hi',? FROM payload",(utc_now(),))
    assert seen and seen[0].startswith('WITH payload')
    cur=await w.conn.execute('SELECT COUNT(*) FROM messages')
    assert (await cur.fetchone())[0]==1
    await w.close()

@pytest.mark.asyncio
async def test_runtime_read_cte_returns_cursor(runtime_tg):
    w=await DbWriter.for_memory(); await w.start(runtime_tg)
    db=RuntimeDb(w)
    cur=await db.execute("WITH RECURSIVE chain(id) AS (SELECT ? UNION ALL SELECT id+1 FROM chain WHERE id<3) SELECT id FROM chain",(1,))
    assert await cur.fetchall()==[(1,),(2,),(3,)]
    await w.close()

@pytest.mark.asyncio
async def test_memory_delete_chain_works_through_runtime_db_wrapper(runtime_tg):
    w=await DbWriter.for_memory(); await w.start(runtime_tg)
    db=RuntimeDb(w)
    mm=bot.MemoryManager(db)
    old=await mm.add('123456789012345678','old note')
    new=await mm.update(old,'new note')
    await mm.delete(new)
    assert await mm.search('123456789012345678','old')==[]
    cur=await db.execute('SELECT COUNT(*) FROM memories WHERE int_memory_id IN (?,?)',(old,new))
    assert (await cur.fetchone())[0]==0
    await w.close()
