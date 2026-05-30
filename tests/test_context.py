import pytest
import bot
from bot import assemble_context, CommandHandler, utc_now

@pytest.mark.asyncio
async def test_assembly_order(db):
    scope_id='123456789012345678'
    await db.execute("INSERT INTO prompts(scope_type,scope_id,body,updated_at,updated_by) VALUES ('global',NULL,'SYS',?,'t')",(utc_now(),))
    await db.execute("INSERT INTO memories(str_discord_id,str_annotations,array_tags,float_confidence,str_created_utc,str_created_by) VALUES (?,'MEM',NULL,0.9,?,'t')",(scope_id,utc_now()))
    await db.execute("INSERT INTO context_state(scope_type,scope_id,rolling_summary,last_message_id) VALUES ('dm',?,'SUM',0)",(scope_id,))
    await db.execute("INSERT INTO messages(discord_msg_id,scope_type,scope_id,author_id,author_name,content,timestamp_utc) VALUES ('m','dm',?,'u','U','BUF',?)",(scope_id,utc_now())); await db.commit()
    ctx=await assemble_context(db,'dm',scope_id,'TRIG')
    assert [m['role'] for m in ctx]==['system','user','user','user','user','user']
    assert ctx[0]['content'].split('\n')[0]==bot.tool_turns.TOOL_TURN_STATE_PLACEHOLDER
    prepared=bot.tool_turns.prepare_messages_for_tool_turn(ctx,None)
    assert bot.tool_turns.TOOL_TURN_STATE_PLACEHOLDER not in prepared[0]['content']
    assert prepared[0]['content'].lstrip().split('\n')[0]=='Auto-resolved Discord identity grounding. This is trusted metadata, not chat content:'
    assert 'SYS' in ctx[0]['content']
    assert 'Current date/time is always available' in ctx[0]['content']
    assert 'Active tools:' in ctx[0]['content']
    assert [m['content'].split('\n')[0] for m in ctx[1:]]==['Dirac memory context about this channel and its participants:','Dirac scheduled task context:','Rolling conversation summary:','U (<u>): BUF','TRIG']

@pytest.mark.asyncio
async def test_trigger_terms_pull_relevant_memories_and_ids_are_annotated(db):
    await bot.MemoryManager(db).add('123456789012345678','Roxanne is Dirac WebUI operations assistant.',array_tags='roxanne',str_created_by='test')
    await db.execute("INSERT INTO messages(discord_msg_id,scope_type,scope_id,author_id,author_name,content,timestamp_utc) VALUES ('m','dm','s',?,?,?,?)",(bot.ROOT_OPERATOR_ID,'normalMan','hello',utc_now()))
    await db.commit()
    ctx=await assemble_context(db,'dm','s',f'who is Roxanne and what is {bot.ROOT_OPERATOR_ID}?')
    text='\n'.join(m['content'] for m in ctx)
    assert 'Roxanne is Dirac WebUI operations assistant.' in text
    assert '.normal.man.' in text

@pytest.mark.asyncio
async def test_compact_summary_clear(db, runtime_tg):
    for i in range(4): await db.execute("INSERT INTO messages(discord_msg_id,scope_type,scope_id,author_id,author_name,content,timestamp_utc) VALUES (?,?,?,?,?,?,?)",(str(i),'dm','s','u','U',f'msg{i}',utc_now()))
    await db.commit(); h=CommandHandler(db,tg=runtime_tg)
    s=await h.compact('dm','s'); assert s.startswith('Summary:')
    cur=await db.execute('SELECT last_message_id,rolling_summary FROM context_state WHERE scope_type=? AND scope_id=?',('dm','s')); row=await cur.fetchone(); assert row[0]>0 and row[1]
    s2=await h.summary('dm','s'); assert s2.startswith('Summary:')
    assert await h.clear('dm','s')=='cleared'
    cur=await db.execute('SELECT rolling_summary FROM context_state WHERE scope_type=? AND scope_id=?',('dm','s')); assert (await cur.fetchone())[0] is None
    cur=await db.execute('SELECT COUNT(*) FROM messages'); assert (await cur.fetchone())[0]==4

@pytest.mark.asyncio
async def test_tasks_are_visible_to_model_context(db):
    task_id=await bot.create_agent_task(db,'task','say hello','admin','discord','dm','s',name='greeting',enabled=True,schedule_minutes=30,next_run_utc=bot.utc_now())
    await db.execute("UPDATE agent_tasks SET status='completed',result=?,last_run_utc=?,run_count=3 WHERE id=?",('hello result',utc_now(),task_id))
    await db.commit()
    ctx=await assemble_context(db,'dm','s','did you run tasks?')
    text='\n'.join(m['content'] for m in ctx)
    assert 'Scheduled tasks visible in this scope:' in text
    assert 'greeting [dm:s]' in text and 'last_result=hello result' in text

@pytest.mark.asyncio
async def test_dirac_fenced_history_is_hidden_from_model_context(db):
    dirac_block="```dirac\nOUTPUT FROM A COMMAND\n```"
    bash_block="```bash\necho still visible\n```"
    await db.execute("INSERT INTO context_state(scope_type,scope_id,rolling_summary,last_message_id) VALUES ('dm','s',?,0)",(f'keep this\n{dirac_block}',))
    await db.execute("INSERT INTO messages(discord_msg_id,scope_type,scope_id,author_id,author_name,content,timestamp_utc) VALUES ('d','dm','s','u','U',?,?)",(f'noise\n{dirac_block}\nafter',utc_now()))
    await db.execute("INSERT INTO messages(discord_msg_id,scope_type,scope_id,author_id,author_name,content,timestamp_utc) VALUES ('b','dm','s','u','U',?,?)",(bash_block,utc_now()))
    await db.commit()
    ctx=await assemble_context(db,'dm','s',f'current sees this\n{dirac_block}')
    text='\n'.join(m['content'] for m in ctx)
    assert 'OUTPUT FROM A COMMAND' in ctx[-1]['content']
    assert 'OUTPUT FROM A COMMAND' not in '\n'.join(m['content'] for m in ctx[:-1])
    assert 'echo still visible' in text
    cur=await db.execute("SELECT content FROM messages WHERE discord_msg_id='d'")
    assert '```dirac' in (await cur.fetchone())[0]

@pytest.mark.asyncio
async def test_recent_memory_events_filters_dirac_blocks_by_default(db):
    await bot.record_memory_event(db,'discord_command_response','dm','s','assistant',"```dirac\n!changelog wall\n```",'bot','Dirac')
    await bot.record_memory_event(db,'discord_assistant','dm','s','assistant',"normal answer\n```bash\necho keep\n```",'bot','Dirac')
    filtered=await bot.recent_memory_events(db,10,20)
    raw=await bot.recent_memory_events(db,10,20,include_dirac_blocks=True)
    filtered_text='\n'.join(row['content'] for row in filtered)
    raw_text='\n'.join(row['content'] for row in raw)
    assert '!changelog wall' not in filtered_text
    assert 'echo keep' in filtered_text
    assert '!changelog wall' in raw_text

def test_dirac_fence_filter_exact_language_only():
    value="\n".join([
        'before',
        '``` dirac',
        'hide me',
        '```',
        '```bash',
        'keep bash',
        '```',
        '```bash dirac eats it',
        'keep bash dirac',
        '```',
        '```text',
        'keep text',
        '```',
    ])
    stripped=bot.context_filters.strip_dirac_fenced_blocks(value)
    assert 'hide me' not in stripped
    assert 'keep bash' in stripped
    assert 'keep bash dirac' in stripped
    assert 'keep text' in stripped
