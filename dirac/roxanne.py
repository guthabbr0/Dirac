from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote_plus

import httpx
from pydantic import BaseModel, Field, field_validator

from dirac import memory_contract
from dirac import tool_turns
from dirac.context_filters import format_dirac_block


ROXANNE_TOOL_TURN_LIMIT = 3
ROXANNE_TOOL_BATCH_LIMIT = 8


ROXANNE_TOOLS = [
    {'type':'function','function':{'name':'read_docs','description':'Read current Dirac documentation by name. Available names include admin, usage, readme, agents, help, ui.','parameters':{'type':'object','properties':{'name':{'type':'string'},'limit':{'type':'integer'}},'required':['name']}}},
    {'type':'function','function':{'name':'get_runtime_snapshot','description':'Inspect a fresh redacted runtime snapshot with logs, commands, provider calls, tasks, messages, table counts, docs, and static Roxanne memory.','parameters':{'type':'object','properties':{'scope_type':{'type':'string'},'scope_id':{'type':'string'}}}}},
    {'type':'function','function':{'name':'get_redacted_config','description':'Inspect redacted runtime configuration and secret presence/fingerprints.','parameters':{'type':'object','properties':{}}}},
    {'type':'function','function':{'name':'get_providers','description':'Inspect configured model providers with secrets redacted.','parameters':{'type':'object','properties':{'enabled_only':{'type':'boolean'}}}}},
    {'type':'function','function':{'name':'get_effective_scope','description':'Explain effective provider, parameters, tools, skills, and warnings for a selected scope.','parameters':{'type':'object','properties':{'scope_type':{'type':'string'},'scope_id':{'type':'string'}},'required':['scope_type']}}},
    memory_contract.memory_tool_schema('memory_search'),
    memory_contract.memory_tool_schema('memory_add'),
    memory_contract.memory_tool_schema('memory_update'),
    memory_contract.memory_tool_schema('memory_delete'),
    memory_contract.memory_tool_schema('memory_edit'),
    memory_contract.memory_tool_schema('memory_remove'),
    {'type':'function','function':{'name':'bash','description':'Run a Bash command for the authenticated panel operator. Prefer python doctor.py for SQLite, memory, tool, config, and online diagnostics.','parameters':{'type':'object','properties':{'command':{'type':'string'},'cwd':{'type':'string'},'timeout_s':{'type':'number'}},'required':['command']}}},
    {'type':'function','function':{'name':'diagnostic_command','description':'Run a bounded repo-local diagnostic command for the panel operator. Allowed commands are constrained by Dirac and output is redacted.','parameters':{'type':'object','properties':{'command':{'type':'string'},'argv':{'type':'array','items':{'type':'string'}},'timeout_s':{'type':'number'}}}}},
    {'type':'function','function':{'name':'search_messages','description':'Search persisted Discord messages visible to the panel.','parameters':{'type':'object','properties':{'q':{'type':'string'},'scope_type':{'type':'string'},'scope_id':{'type':'string'},'limit':{'type':'integer'}},'required':['q']}}},
    {'type':'function','function':{'name':'list_bot_logs','description':'List recent bot log rows.','parameters':{'type':'object','properties':{'level':{'type':'string'},'component':{'type':'string'},'limit':{'type':'integer'}}}}},
    {'type':'function','function':{'name':'web_fetch','description':'Fetch one public HTTP/HTTPS URL with Dirac public-web safety checks.','parameters':{'type':'object','properties':{'url':{'type':'string'},'reason':{'type':'string'}},'required':['url','reason']}}},
    {'type':'function','function':{'name':'web_search','description':'Search the public web for current docs or troubleshooting context.','parameters':{'type':'object','properties':{'query':{'type':'string'},'limit':{'type':'integer'}},'required':['query']}}},
    {'type':'function','function':{'name':'current_time','description':'Return the current date and time in Europe/Madrid and UTC.','parameters':{'type':'object','properties':{}}}},
]


class RoxanneProfilePatchIn(BaseModel):
    provider_id:int|None=None
    model:str|None=Field(default=None,max_length=200)
    parameter_profile_id:int|None=None
    reasoning_mode:Literal['inherit','off','on','low','medium','high']|None=None
    tools_enabled:bool|None=None
    system_prompt:str|None=Field(default=None,max_length=6000)

    @field_validator('provider_id','parameter_profile_id',mode='before')
    @classmethod
    def nullish_id(cls,value):
        if value is None or value=='' or str(value).lower() in {'null','none','undefined','nan'}:
            return None
        if isinstance(value,float) and value!=value:
            return None
        return value

    @field_validator('model','system_prompt',mode='before')
    @classmethod
    def empty_text(cls,value):
        if value is None:
            return None
        text=str(value)
        return text if text.strip() else None


class RoxanneSessionIn(BaseModel):
    title:str|None=Field(default=None,max_length=200)
    active_scope_type:Literal['global','guild','channel','dm','group','user']|None='global'
    active_scope_id:str|None=None


class RoxanneAskIn(BaseModel):
    message:str=Field(min_length=1,max_length=12000)
    session_id:int|None=None
    active_scope_type:Literal['global','guild','channel','dm','group','user']|None='global'
    active_scope_id:str|None=None


class RoxanneMemoryIn(BaseModel):
    title:str|None=Field(default=None,max_length=200)
    body:str=Field(min_length=1,max_length=8000)
    tags:str|None=Field(default=None,max_length=500)
    enabled:bool=True


class RoxanneMemoryPatchIn(BaseModel):
    title:str|None=Field(default=None,max_length=200)
    body:str|None=Field(default=None,min_length=1,max_length=8000)
    tags:str|None=Field(default=None,max_length=500)
    enabled:bool|None=None


@dataclass
class RoxanneDeps:
    utc_now: Any
    preview_text: Any
    normalize_scope_id: Any
    valid_extended_scope_pair: Any
    provider_params_for_profile: Any
    runtime_context: Any
    response_parts: Any
    tool_args: Any
    read_doc: Any
    current_time_payload: Any
    redacted_config_snapshot: Any
    list_service_providers: Any
    redact_provider: Any
    effective_scope_payload: Any
    memory_search: Any
    memory_add: Any
    memory_update: Any
    memory_delete: Any
    rows: Any
    clamp_limit: Any
    like_pattern: Any
    web_fetch: Any
    diagnostic_command: Any
    bash: Any
    db_log_error: Any


async def get_profile(db, ensure_default_records):
    cur=await db.execute("SELECT * FROM roxanne_profiles WHERE name='default' ORDER BY id LIMIT 1")
    row=await cur.fetchone()
    if not row:
        await ensure_default_records(db)
        cur=await db.execute("SELECT * FROM roxanne_profiles WHERE name='default' ORDER BY id LIMIT 1")
        row=await cur.fetchone()
    return dict(zip([c[0] for c in cur.description],row)) if row else None


async def list_memory(db):
    return await _dict_rows(db,'SELECT * FROM roxanne_memory ORDER BY enabled DESC, id DESC LIMIT 200')


async def create_memory(db, data:RoxanneMemoryIn, now, created_by='panel'):
    cur=await db.execute(
        'INSERT INTO roxanne_memory(title,body,tags,enabled,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
        (data.title,data.body,data.tags,int(data.enabled),created_by,now,now)
    )
    await db.commit()
    return {'id':int(cur.lastrowid),'ok':True}


async def patch_memory(db, memory_id:int, data:RoxanneMemoryPatchIn, now):
    fields=data.model_dump(exclude_unset=True)
    if 'enabled' in fields:
        fields['enabled']=int(bool(fields['enabled']))
    if not fields:
        return {'ok':True}
    fields['updated_at']=now
    cur=await db.execute('SELECT id FROM roxanne_memory WHERE id=?',(memory_id,))
    if not await cur.fetchone():
        return None
    await db.execute('UPDATE roxanne_memory SET '+', '.join(f'{k}=?' for k in fields)+' WHERE id=?',tuple(fields.values())+(memory_id,))
    await db.commit()
    return {'ok':True}


async def delete_memory(db, memory_id:int):
    cur=await db.execute('DELETE FROM roxanne_memory WHERE id=?',(memory_id,))
    await db.commit()
    return cur.rowcount > 0


async def static_memory_context(db):
    rows=await _dict_rows(db,'SELECT id,title,body,tags FROM roxanne_memory WHERE enabled=1 ORDER BY id ASC LIMIT 50')
    if not rows:
        return 'No Roxanne static memory rows are enabled.'
    return json.dumps(rows,indent=2)


async def web_search(query, limit=5):
    q=' '.join(str(query or '').split())[:300]
    lim=max(1,min(int(limit or 5),8))
    if not q:
        return {'error':'query_required'}
    url='https://duckduckgo.com/html/?q='+quote_plus(q)
    try:
        async with httpx.AsyncClient(timeout=8.0,follow_redirects=True,headers={'user-agent':'Dirac/Roxanne web_search','accept':'text/html'}) as client:
            resp=await client.get(url)
        text=resp.text[:200000]
    except Exception as e:
        return {'query':q,'error':type(e).__name__}
    results=[]
    for match in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',text,re.I|re.S):
        href=html.unescape(match.group(1))
        title=html.unescape(re.sub(r'<[^>]+>',' ',match.group(2)))
        title=' '.join(title.split())
        if href and title:
            results.append({'title':title[:220],'url':href[:1000]})
        if len(results)>=lim:
            break
    return {'query':q,'status_code':resp.status_code,'results':results,'truncated':len(results)>=lim}


async def run_tool(db, name, args, deps:RoxanneDeps, scope_type='global', scope_id=None):
    args=args if isinstance(args,dict) else {}
    limit=deps.clamp_limit(args.get('limit'))
    if name=='read_docs':
        return deps.read_doc(args.get('name','admin'),max_chars=limit*100)
    if name=='get_runtime_snapshot':
        st=args.get('scope_type') or scope_type
        sid=args.get('scope_id') if args.get('scope_id') is not None else scope_id
        return {'content':await deps.runtime_context(db,st,sid)}
    if name=='get_redacted_config':
        return deps.redacted_config_snapshot()
    if name=='get_providers':
        return [deps.redact_provider(r) for r in await deps.list_service_providers(db,bool(args.get('enabled_only',False)))]
    if name=='get_effective_scope':
        st=args.get('scope_type') or scope_type
        sid=deps.normalize_scope_id(st,args.get('scope_id'))
        if not deps.valid_extended_scope_pair(st,sid):
            return {'error':'invalid scope/scope_id combination'}
        return await deps.effective_scope_payload(db,st,sid)
    if name=='memory_search':
        return await deps.memory_search(args.get('str_discord_id'),args.get('str_query'),limit)
    if name=='memory_add':
        return await deps.memory_add(args)
    if name in {'memory_update','memory_edit'}:
        return await deps.memory_update(args)
    if name in {'memory_delete','memory_remove'}:
        return await deps.memory_delete(args)
    if name=='diagnostic_command':
        return await deps.diagnostic_command(args)
    if name=='bash':
        return await deps.bash(args)
    if name=='search_messages':
        p=[deps.like_pattern(args.get('q',''))]
        sql="SELECT * FROM messages WHERE content LIKE ? ESCAPE '\\'"
        if args.get('scope_type'):
            sql+=' AND scope_type=?'; p.append(args['scope_type'])
        if args.get('scope_id'):
            sql+=' AND scope_id=?'; p.append(str(args['scope_id']))
        sql+=' ORDER BY id DESC LIMIT ?'; p.append(limit)
        return await deps.rows(await db.execute(sql,tuple(p)))
    if name=='list_bot_logs':
        p=[]; sql='SELECT * FROM bot_logs WHERE 1=1'
        if args.get('level'):
            sql+=' AND level=?'; p.append(args['level'])
        if args.get('component'):
            sql+=' AND component=?'; p.append(args['component'])
        sql+=' ORDER BY id DESC LIMIT ?'; p.append(limit)
        return await deps.rows(await db.execute(sql,tuple(p)))
    if name=='web_fetch':
        return await deps.web_fetch(args.get('url'),args.get('reason') or 'Roxanne operator request')
    if name=='web_search':
        return await web_search(args.get('query'),limit)
    if name=='current_time':
        return deps.current_time_payload()
    return {'error':'unknown tool'}


async def ask(db, client, message, profile, session_id, active_scope_type, active_scope_id, deps:RoxanneDeps):
    st=active_scope_type or 'global'
    sid=deps.normalize_scope_id(st,active_scope_id)
    if not deps.valid_extended_scope_pair(st,sid):
        raise ValueError('invalid scope/scope_id combination')
    now=deps.utc_now()
    if session_id is None:
        cur=await db.execute(
            'INSERT INTO roxanne_sessions(title,active_scope_type,active_scope_id,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?)',
            (deps.preview_text(message,80),st,sid,'panel',now,now)
        )
        await db.commit()
        session_id=int(cur.lastrowid)
    cur=await db.execute('SELECT id FROM roxanne_sessions WHERE id=?',(session_id,))
    if not await cur.fetchone():
        raise LookupError('roxanne session not found')
    await db.execute('INSERT INTO roxanne_messages(session_id,role,content,timestamp_utc) VALUES (?,?,?,?)',(session_id,'operator',message,deps.utc_now()))
    await db.execute('UPDATE roxanne_sessions SET active_scope_type=?,active_scope_id=?,updated_at=? WHERE id=?',(st,sid,deps.utc_now(),session_id))
    await db.commit()
    history=await _dict_rows(db,'SELECT role,content FROM roxanne_messages WHERE session_id=? ORDER BY id ASC LIMIT 50',(session_id,))
    messages=[
        {'role':'system','content':tool_turns.TOOL_TURN_STATE_PLACEHOLDER+'\n\n'+(profile.get('system_prompt') or "You are Roxanne, Dirac's WebUI assistant.")},
        {'role':'system','content':await deps.runtime_context(db,st,sid)},
    ]
    for row in history:
        if row['role']=='tool':
            messages.append({'role':'tool','content':row['content'],'name':'roxanne_tool'})
        else:
            role='assistant' if row['role']=='assistant' else 'user'
            messages.append({'role':role,'content':row['content']})
    params=await deps.provider_params_for_profile(db,profile.get('parameter_profile_id'))
    if profile.get('reasoning_mode') and profile.get('reasoning_mode')!='inherit':
        params={**params,'reasoning':profile.get('reasoning_mode')}
    tools=ROXANNE_TOOLS if int(profile.get('tools_enabled',1) or 0) else None
    content=''
    tool_calls_json=None
    latest_tool_count=0
    total_tool_count=0
    for turn in range(ROXANNE_TOOL_TURN_LIMIT):
        dynamic_context=tool_turns.render_tool_turn_state(
            'ROXANNE',
            turn+1,
            ROXANNE_TOOL_TURN_LIMIT,
            available_tool_count=len(tools or []),
            batch_limit=ROXANNE_TOOL_BATCH_LIMIT,
            previous_tool_results=latest_tool_count,
            total_tool_results=total_tool_count,
        ) if tools else None
        try:
            result=await client.chat(messages,tools=tools,model=profile.get('model'),scope_type='roxanne',scope_id=sid,source='roxanne',roxanne_profile_id=profile.get('id'),params=params,dynamic_context=dynamic_context)
        except TypeError:
            prepared=tool_turns.prepare_messages_for_tool_turn(messages,dynamic_context)
            result=await client.chat(prepared,tools=tools,model=profile.get('model'),scope_type='roxanne',scope_id=sid,source='roxanne',roxanne_profile_id=profile.get('id'),params=params)
        content,tool_calls_json=deps.response_parts(result)
        tool_calls=json.loads(tool_calls_json) if tool_calls_json else []
        if not tool_calls or not tools:
            break
        messages.append({'role':'assistant','content':content or '', 'tool_calls':tool_calls})
        limited_calls=tool_calls[:ROXANNE_TOOL_BATCH_LIMIT]
        for call in limited_calls:
            name,args=deps.tool_args(call)
            tool_result=await run_tool(db,name,args,deps,st,sid)
            tool_text=json.dumps(tool_result,ensure_ascii=False)[:12000]
            messages.append({'role':'tool','content':tool_text,'name':name or 'tool'})
            await db.execute('INSERT INTO roxanne_messages(session_id,role,content,tool_calls_json,timestamp_utc) VALUES (?,?,?,?,?)',(session_id,'tool',tool_text,json.dumps({'name':name,'arguments':args}),deps.utc_now()))
        latest_tool_count=len(limited_calls)
        total_tool_count+=latest_tool_count
    else:
        try:
            dynamic_context=tool_turns.render_tool_turn_state(
                'ROXANNE',
                ROXANNE_TOOL_TURN_LIMIT,
                ROXANNE_TOOL_TURN_LIMIT,
                latest_tool_results=latest_tool_count,
                total_tool_results=total_tool_count,
                finalization=True,
            )
            try:
                result=await client.chat(messages,tools=None,model=profile.get('model'),scope_type='roxanne',scope_id=sid,source='roxanne',roxanne_profile_id=profile.get('id'),params=params,dynamic_context=dynamic_context)
            except TypeError:
                prepared=tool_turns.prepare_messages_for_tool_turn(messages,dynamic_context)
                result=await client.chat(prepared,tools=None,model=profile.get('model'),scope_type='roxanne',scope_id=sid,source='roxanne',roxanne_profile_id=profile.get('id'),params=params)
            content,tool_calls_json=deps.response_parts(result)
            if tool_calls_json:
                if not content:
                    content=format_dirac_block('ERROR: Roxanne tool loop cut short after text-only finalization requested more tools\ncomponent=roxanne')
                tool_calls_json=None
        except Exception as e:
            await deps.db_log_error('roxanne','Roxanne tool follow-up failed',e)
            if not content:
                content=format_dirac_block('ERROR: Roxanne tool follow-up produced no text reply\ncomponent=roxanne')
    if not content:
        content=format_dirac_block('ERROR: Roxanne provider produced no text reply\ncomponent=roxanne')
    await db.execute('INSERT INTO roxanne_messages(session_id,role,content,tool_calls_json,timestamp_utc) VALUES (?,?,?,?,?)',(session_id,'assistant',content,tool_calls_json,deps.utc_now()))
    await db.commit()
    return {'session_id':session_id,'message':content}


async def _dict_rows(db, sql, params=()):
    cur=await db.execute(sql,params)
    cols=[c[0] for c in cur.description]
    return [dict(zip(cols,r)) for r in await cur.fetchall()]
