from __future__ import annotations
import asyncio
import html
import ipaddress
import json
import os
import random
import re
import shlex
import shutil
import socket
import subprocess
import traceback
import sys
import time
import secrets
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from contextlib import asynccontextmanager
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo
import aiosqlite, httpx
from typing import Literal
from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from dirac.runtime_control import DEFAULT_STOP_SECONDS, runtime_control, clamp_hold_seconds
from dirac import context_filters
from dirac import logging as dirac_logging
from dirac.logging import log_is_enabled
from dirac.logging import apply_cli_logging_overrides
from dirac.logging import start_console_key_listener
from dirac import news as news_mod
from dirac import roxanne as roxanne_mod
from dirac import rem
from dirac import tool_turns
from dirac import memory_contract
from dirac.providers.legacy import LegacyProviderClient
from dirac.providers.openai import OpenAIProviderClient
from dirac.providers.sim import SimProviderClient
try:
    import discord  # type: ignore
except Exception:
    discord = None  # type: ignore

REPO_DIR = Path(__file__).resolve().parent
DEFAULT_RUNTIME_DIR_CANDIDATES = (
    REPO_DIR.parent / 'dirac-config',
    Path.home() / 'Desktop' / 'workspaces' / 'dirac-config',
)
def runtime_dir():
    configured=os.environ.get('DIRAC_CONFIG_DIR')
    if configured:
        return Path(configured).expanduser()
    for candidate in DEFAULT_RUNTIME_DIR_CANDIDATES:
        if candidate.exists():
            return candidate
    return REPO_DIR
RUNTIME_DIR = runtime_dir()
DB_PATH = RUNTIME_DIR / 'bot.sqlite'
CONFIG_PATH = RUNTIME_DIR / 'config.toml'
APP_VERSION = '1.1.6-hotfix'
DB_SCHEMA_TAG = APP_VERSION
DB_SCHEMA_META_KEY = 'schema_tag'
CHANGELOG = [
    ('1.1.6-hotfix', 'Reconciled docs, tests, doctor commands, and built-in memory tool snapshots with the TaskGroup runtime and canonical memory schema hotfixes; documented direct SQLite access rules for external modules.'),
    ('1.1.5-hotfix', 'Kept legacy memory migration non-fatal, aligned doctor memory column access, and fixed panel memory tool routing/input errors.'),
    ('1.1.4-hotfix', 'Reworked REM memory context, renamed durable memory fields, made memory tools self-explaining on bad arguments, and stamped task memory writes with run provenance.'),
    ('1.1.3-hotfix', 'Moved runtime background task launches under explicit asyncio TaskGroup ownership so failures propagate instead of detaching.'),
    ('1.1.2-local', 'Rendered tool-round state ephemerally at provider-call time, removed stale dynamic prompt accumulation, and improved short-term memory slice visibility.'),
    ('1.1.1-local', 'Made tool-round budgets explicit in model prompts, added final text-only warnings, and marked cut-short REM runs as runtime warnings instead of fake DONE output.'),
    ('1.1.0-local', 'Added durable exploratory news state, hid code-origin dirac blocks from model/REM context, wrapped deterministic output in dirac fences, and moved console logging formatting into a module.'),
    ('1.0.9-local', 'Raised Discord wake tool follow-up capacity and logged models that keep requesting tools during text-only finalization.'),
    ('1.0.8-local', 'Fixed manual task launch and made due recurring tasks retry on schedule regardless of prior task status.'),
    ('1.0.7-local', 'Patch the scheduler to solve a freezing task-unable to run orphaned.'),
    ('1.0.6-local', 'Made recurring tasks cron-like: one random due task per scheduler tick, next run advanced before launch, and Europe/Madrid task times in operator views.'),
    ('1.0.5-local', 'Injected trusted runtime request context with current time, provider, and exact requested model tag into every provider call.'),
    ('1.0.4-local', 'Fixed RuntimeDb read CTE detection so memory_delete supersession-chain reads return cursors instead of writer results.'),
    ('1.0.3-local', 'Fixed Roxanne profile saves from the WebUI by normalizing browser null values before validation.'),
    ('1.0.2-local', 'Restored full trace detail output, added schema tag compatibility guards and doctor DB upgrade, serialized memory write tools, and made built-in tool deletion truly removable with snapshot restore.'),
    ('1.0.1-local', 'Added trace logging for model/tool turns, parallelized Discord tool execution, and kept Discord typing active across wake/tool/final response work.'),
    ('1.0.0-local', 'Added REM memory assimilation, short-term visible memory events, editable built-in memory/Discord grounding tools, task snapshots, and multi-turn tool follow-up.'),
    ('0.6.0-local', 'Added ultimate-only emergency controls; disabled default news feeds; added root/operator memory repair, Bash tools, doctor.py, and Roxanne runtime repair access.'),
    ('0.5.9-local', 'Rebuilt Roxanne as a threaded WebUI assistant with static memory, selectable provider/model/reasoning settings, and tool-backed docs/runtime/web access.'),
    ('0.5.8-local', 'Inherited built-in executor metadata through scoped tool overrides and preserved migrated runtime tool state in dirac-config.'),
    ('0.5.7-local', 'Moved runtime config and SQLite state to dirac-config, repaired memory target normalization/listing, added memory_search and discord_id tools, and improved Discord ID context.'),
    ('0.5.6-local', 'Added explicit Git-backed version reporting, startup build banners, and restored startup news configuration for the normal runtime folder.'),
    ('0.5.5-local', 'Moved built-in Discord tools to a DB-backed snapshot, added web_fetch, repaired silencer and emoji reply behavior, fixed Roxanne modal mounting, and improved memory/news handling.'),
    ('0.5.4-local', 'Tightened tool and skill enablement gates, cleaned up command verbs and help output, improved Discord message chunking, and guarded invalid scoped asset loads in the panel.'),
    ('0.5.3-local', 'Clarified !memory syntax and output, anchored Discord replies to the triggering message, and removed the hard single-file rule from future architecture docs.'),
    ('0.5.2-local', 'Stabilized WebUI tab auto-loading and scope serialization, added protected root permissions, and documented WebUI guidelines.'),
    ('0.5.1-local', 'Added Europe/Madrid log timestamps, colorized console logs, provider DEBUG response logging, context role cleanup, and the current_time tool/system time injection.'),
    ('0.5.0-local', 'Added provider registry groundwork, scoped provider profiles, task run provenance, and Roxanne WebUI assistant planning surfaces.'),
    ('0.4.4-local', 'Retargeted news work to AI/model/benchmark updates only, capped at three items from Artificial Analysis, Hugging Face, and arXiv.'),
    ('0.4.3-local', 'Fixed panel task visibility by loading all tasks by default and adding a separate task scope filter.'),
    ('0.4.2-local', 'Added hard task deletion with !tasks delete and panel task Delete, while keeping remove/disable as non-destructive stop actions.'),
    ('0.4.1-local', 'Added task visibility in model context, human-readable task listings, and Discord delivery for scheduled task results.'),
    ('0.4.0-local', 'Added scoped !tools, !skills, and !tasks command families with panel tabs and recurring task scheduling.'),
    ('0.3.9-local', 'Added built-in react_emoji and silencer tools for Discord wake responses.'),
    ('0.3.0-local', 'Added root-only !create sub-agent tasks, bash detection, and the international news scheduler.'),
    ('0.2.0-local', 'Added admin help/docs, redacted config inspection, token usage reporting, and !reasoning control.'),
    ('0.1.0-local', 'Local Discord self-bot, Ollama bridge, panel cockpit, SQLite audit DB, permissions, prompts, memory, and context controls.'),
]
STARTED_AT = time.time()
PANEL_AUTH_TOKEN = os.environ.get('DIRAC_PANEL_TOKEN') or secrets.token_urlsafe(32)
# Conservative rough estimate (4 chars/token, within the typical 3-5 range for English) used only to decide when to compact before LLM calls.
CHARS_PER_TOKEN_ESTIMATE = 4
PANEL_TOOL_LIMIT = 100
DISCORD_MESSAGE_LIMIT = 2000
DISCORD_SAFE_MESSAGE_LIMIT = 1900
MAX_PROMPT_LENGTH = 12000
MAX_MEMORY_NOTE_LENGTH = 4000
MAX_MEMORY_TAGS_LENGTH = 500
MAX_PANEL_CHAT_LENGTH = 12000
MAX_ASSET_DESCRIPTION_LENGTH = 2000
MAX_ASSET_BODY_LENGTH = 8000
MAX_TASK_PROMPT_LENGTH = 12000
REDACTED_SECRET = '***'
RUNTIME_CONTEXT_PLACEHOLDER = '{{DIRAC_RUNTIME_CONTEXT}}'
REQUEST_MODEL_PLACEHOLDER = '{{DIRAC_REQUEST_MODEL}}'
TASK_TOOL_TURN_LIMIT = 4
DISCORD_TOOL_TURN_LIMIT = 5
PANEL_TOOL_TURN_LIMIT = 3
PANEL_TOOL_BATCH_LIMIT = 8
ROOT_OPERATOR_ID = '1482143139828596916'
TOOL_CALL_PARALLEL_LIMIT = 12
DB_WRITE_TOOL_LOCKS = {}
try:
    MADRID_TZ = ZoneInfo('Europe/Madrid')
except Exception:
    MADRID_TZ = timezone(timedelta(hours=1))
LOCAL_TIMEZONE_NAME = 'Europe/Madrid'
NEWS_CHANNEL_ID = news_mod.NEWS_CHANNEL_ID
TECH_NEWS_MAX_ITEMS = news_mod.TECH_NEWS_MAX_ITEMS
BUILTIN_TOOLS_SNAPSHOT_PATH = REPO_DIR / 'docs' / 'builtin_tools_snapshot.json'
BUILTIN_TASKS_SNAPSHOT_PATH = REPO_DIR / rem.REM_TASK_SNAPSHOT_PATH
ALLOWED_TOOL_EXECUTORS = {'react_emoji','silencer','current_time','web_fetch','web_search','memory_search','memory_add','memory_update','memory_delete','discord_id','discord_ground','discord_tag','dyslexic_helper','diagnostic_command','bash'}
WEB_FETCH_TIMEOUT_S = 8.0
WEB_FETCH_MAX_BYTES = 256000
WEB_FETCH_TEXT_LIMIT = 12000
DIAGNOSTIC_COMMAND_TIMEOUT_S = 10.0
DIAGNOSTIC_COMMAND_OUTPUT_LIMIT = 12000
DIAGNOSTIC_ALLOWED_COMMANDS = {'pwd','ls','rg','sed','cat','wc','git','python','python3','sqlite3','.venv/bin/python'}
BASH_COMMAND_TIMEOUT_S = 30.0
BASH_COMMAND_OUTPUT_LIMIT = 20000
ARTIFICIAL_ANALYSIS_ARTICLES_URL = news_mod.ARTIFICIAL_ANALYSIS_ARTICLES_URL
AI_TECH_NEWS_FEEDS = news_mod.AI_TECH_NEWS_FEEDS
def _git_output(args):
    try:
        proc=subprocess.run(['git','-C',str(REPO_DIR),*args],capture_output=True,text=True,timeout=2,check=False)
    except Exception:
        return None
    if proc.returncode!=0:
        return None
    return proc.stdout.strip() or None
def _format_git_timestamp(value):
    if not value:
        return None,None
    try:
        dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except Exception:
        return str(value),str(value)
    utc=dt.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')
    local=dt.astimezone(MADRID_TZ).isoformat(timespec='seconds')
    return utc,local
def app_build_info():
    commit=_git_output(['rev-parse','--short=12','HEAD'])
    branch=_git_output(['rev-parse','--abbrev-ref','HEAD'])
    commit_time=_git_output(['show','-s','--format=%cI','HEAD'])
    released_utc,released_local=_format_git_timestamp(commit_time)
    dirty=bool(_git_output(['status','--porcelain']))
    release,release_notes=CHANGELOG[0]
    return {
        'version':APP_VERSION,
        'release':release,
        'release_notes':release_notes,
        'released_at_utc':released_utc or 'unknown',
        'released_at_local':released_local or 'unknown',
        'commit':commit or 'unknown',
        'branch':branch or 'unknown',
        'dirty':dirty,
        'code_dir':str(REPO_DIR),
        'runtime_dir':str(RUNTIME_DIR),
        'config_path':str(CONFIG_PATH),
        'db_path':str(DB_PATH),
    }
def version_report(model=None,scope_type=None,scope_id=None):
    info=app_build_info()
    lines=[
        f"Dirac {info['version']}",
        f"release={info['release']}",
        f"released_at={info['released_at_local']} ({info['released_at_utc']} UTC)",
        f"commit={info['commit']} branch={info['branch']} dirty={'yes' if info['dirty'] else 'no'}",
        f"code_dir={info['code_dir']}",
        f"runtime_dir={info['runtime_dir']}",
        f"db_path={info['db_path']}",
    ]
    if model is not None:
        lines.append(f"model={model}")
    if scope_type is not None:
        lines.append(f"scope={scope_type}:{scope_id or '*'}")
    lines.extend([
        'features=providers, scoped models, DB-backed tools, web_fetch, web_search, editable memory, REM tasks, Discord grounding, skills, recurring tasks, task runs, Discord reactions, silencer, emergency runtime controls, reasoning control, Roxanne',
        f"latest_change={info['release_notes']}",
    ])
    return '\n'.join(lines)
def startup_discord_banner(nickname='Dirac'):
    info=app_build_info()
    return (
        f"{nickname} online: Dirac {info['version']} ({info['release']})\n"
        f"release time: {info['released_at_local']} ({info['released_at_utc']} UTC)\n"
        f"commit: {info['commit']} on {info['branch']} dirty={'yes' if info['dirty'] else 'no'}\n"
        f"code: {info['code_dir']}\n"
        f"runtime: {info['runtime_dir']}\n"
        "News scheduler is disabled by default; use !news now for a manual AI/model update."
    )
def handle_cli_info(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if any(arg in {'--version','-V','version'} for arg in args):
        print(version_report())
        return True
    if '--changelog' in args:
        print('Dirac changelog')
        print('\n'.join(f'- {version}: {entry}' for version,entry in CHANGELOG))
        return True
    return False
TECH_NEWS_EXCLUDED_TERMS = news_mod.TECH_NEWS_EXCLUDED_TERMS
OLD_ROXANNE_SYSTEM_PROMPT = "You are Roxanne, Dirac's WebUI assistant. Help the operator understand and configure Dirac. Use docs and redacted runtime state. Never reveal secrets."
ROXANNE_SYSTEM_PROMPT = """You are Roxanne, Dirac's WebUI operations assistant.

You have direct operator access to fresh Dirac runtime snapshots, local docs, static Roxanne memory, and safe tools injected into every prompt. Your tools include documentation reads, runtime/config/provider inspection, memory search/add/update/delete, Bash through the authenticated panel path, public web fetch/search, task/provider log inspection, and current time. Prefer `python doctor.py ...` through Bash for SQLite, memory, tool, config, and online diagnostics.

Use that context and your tools proactively. Do not say you cannot access logs, docs, memory, providers, runtime state, provider calls, task runs, or recent messages when those sources are available. If a source is genuinely absent, say exactly what is missing and which panel tab or API route can provide it.

Keep answers compact, specific, and operator-useful. Cite the relevant snapshot or tool result in plain language, explain failures, correlate timestamps, suggest next actions, draft config/provider/scope/task changes, and teach the operator how to use the WebUI. Only edit Dirac state or run Bash when the operator asks for that kind of action; summarize exactly what changed.

Secrets policy: you can confirm whether secrets are present, identify provider key fingerprints and last-four previews, and explain where secrets are configured. You must not reveal full Discord tokens, panel auth tokens, provider API keys, bearer headers, or other credential values. If a requested answer would expose a full secret, provide a redacted answer and explain the safe way to rotate or verify the secret."""
def utc_now():
    """Return ISO-8601 UTC timestamp text with a Z suffix."""
    n = datetime.now(timezone.utc).replace(tzinfo=None)
    return n.strftime('%Y-%m-%dT%H:%M:%S.') + f"{n.microsecond // 1000:03d}Z"
def madrid_now():
    return datetime.now(MADRID_TZ).isoformat(timespec='milliseconds')
def madrid_from_utc(timestamp_utc):
    try:
        text=str(timestamp_utc or '')
        if text.endswith('Z'):
            text=text[:-1]+'+00:00'
        dt=datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(MADRID_TZ).isoformat(timespec='milliseconds')
    except Exception:
        return None
def format_operator_time(timestamp_utc):
    local=madrid_from_utc(timestamp_utc)
    return f'{local} {LOCAL_TIMEZONE_NAME}' if local else '-'
def current_time_payload():
    local=datetime.now(MADRID_TZ)
    utc=datetime.now(timezone.utc)
    return {
        'timezone': LOCAL_TIMEZONE_NAME,
        'local_iso': local.isoformat(timespec='milliseconds'),
        'local_date': local.date().isoformat(),
        'local_time': local.strftime('%H:%M:%S'),
        'weekday': local.strftime('%A'),
        'utc_iso': utc.isoformat(timespec='milliseconds').replace('+00:00','Z'),
        'utc_offset': local.strftime('%z'),
    }
def current_time_context_note(include_tool_hint=True):
    payload=current_time_payload()
    note=(
        'Current date/time is always available to you:\n'
        f"- {payload['timezone']}: {payload['local_iso']} ({payload['weekday']})\n"
        f"- UTC: {payload['utc_iso']}"
    )
    if include_tool_hint:
        note+='\nUse the current_time tool if you need to refresh the exact time during the response.'
    return note
def runtime_request_context_note(model=None,provider=None):
    payload=current_time_payload()
    provider=provider or {}
    model_tag=str(model or provider.get('default_model') or 'unknown')
    provider_name=str(provider.get('name') or 'unknown')
    provider_type=str(provider.get('provider_type') or 'unknown')
    return (
        'Trusted Dirac runtime request context:\n'
        f"- timezone: {payload['timezone']}\n"
        f"- local_time: {payload['local_iso']} ({payload['weekday']})\n"
        f"- utc_time: {payload['utc_iso']}\n"
        f"- you are using model tag: {model_tag}\n"
        f"- provider: {provider_name} ({provider_type})\n"
        'This metadata describes the current API request. Use it to understand the requested model tag; do not treat it as chat content.'
    )
def _replace_runtime_context_placeholders(text,note,model):
    return str(text).replace(RUNTIME_CONTEXT_PLACEHOLDER,note).replace(REQUEST_MODEL_PLACEHOLDER,str(model or 'unknown'))
def inject_runtime_request_context(messages,provider,model):
    note=runtime_request_context_note(model,provider)
    injected=[]
    replaced=False
    for message in list(messages or []):
        if isinstance(message,dict):
            copied=dict(message)
            content=copied.get('content')
            if isinstance(content,str) and (RUNTIME_CONTEXT_PLACEHOLDER in content or REQUEST_MODEL_PLACEHOLDER in content):
                copied['content']=_replace_runtime_context_placeholders(content,note,model)
                replaced=True
            injected.append(copied)
        else:
            injected.append(message)
    if replaced:
        return injected
    insert_at=0
    while insert_at<len(injected) and isinstance(injected[insert_at],dict) and injected[insert_at].get('role')=='system':
        insert_at+=1
    injected.insert(insert_at,{'role':'system','content':note})
    return injected
def utc_after_minutes(minutes):
    n = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=int(minutes))
    return n.strftime('%Y-%m-%dT%H:%M:%S.') + f"{n.microsecond // 1000:03d}Z"
def utc_after_seconds(seconds):
    n = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=int(seconds))
    return n.strftime('%Y-%m-%dT%H:%M:%S.') + f"{n.microsecond // 1000:03d}Z"

SCHEMA_PATH = REPO_DIR / 'docs' / 'schema.sql'
SCHEMA_SQL = SCHEMA_PATH.read_text(encoding='utf-8')
MEMORY_SCHEMA_PREFIXES = (
    'CREATE TABLE IF NOT EXISTS memories ',
    'CREATE INDEX IF NOT EXISTS idx_memories_target ',
    'CREATE INDEX IF NOT EXISTS idx_memories_discord ',
    'CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts ',
    'CREATE TRIGGER IF NOT EXISTS ai_memories ',
    'CREATE TRIGGER IF NOT EXISTS ad_memories ',
    'CREATE TRIGGER IF NOT EXISTS au_memories ',
)
BOOTSTRAP_SCHEMA_SQL = '\n'.join(
    line for line in SCHEMA_SQL.splitlines()
    if not line.startswith(MEMORY_SCHEMA_PREFIXES)
)
def _version_tuple(tag):
    match=re.match(r'^(\d+)\.(\d+)\.(\d+)',str(tag or ''))
    return tuple(int(p) for p in match.groups()) if match else None
def compare_version_tags(left,right):
    ltuple=_version_tuple(left)
    rtuple=_version_tuple(right)
    if ltuple is not None and rtuple is not None:
        return (ltuple>rtuple)-(ltuple<rtuple)
    return (str(left)>str(right))-(str(left)<str(right))
async def _table_exists(conn,table):
    cur=await conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,))
    return await cur.fetchone() is not None
async def _db_has_user_tables(conn):
    cur=await conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1")
    return await cur.fetchone() is not None
async def read_db_schema_tag(conn):
    if not await _table_exists(conn,'schema_meta'):
        return None
    cur=await conn.execute('SELECT value FROM schema_meta WHERE key=?',(DB_SCHEMA_META_KEY,))
    row=await cur.fetchone()
    return row[0] if row else None
async def write_db_schema_tag(conn,tag=DB_SCHEMA_TAG):
    await conn.execute(
        'INSERT INTO schema_meta(key,value,updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at',
        (DB_SCHEMA_META_KEY,tag,utc_now())
    )
async def warn_schema_mismatch(db_tag):
    detail={'db_schema_tag':db_tag or 'missing','code_schema_tag':DB_SCHEMA_TAG,'upgrade':'python doctor.py db upgrade --yes'}
    try:
        if 'app' in globals() and getattr(app.state,'db',None) is not None:
            await app_log('warn','db','database schema tag is older than code; runtime will continue best-effort',detail,force_console=True)
        else:
            # Old code path - we raise exception - unable to follow without app
            #console_log_line('warn','db','database schema tag is older than code; runtime will continue best-effort',detail)
            raise
    except Exception:
        print(f"database schema tag is older than code: {detail}",flush=True)
async def bootstrap_db(conn,upgrade_schema_tag=False):
    existed=await _db_has_user_tables(conn)
    existing_tag=await read_db_schema_tag(conn)
    if existing_tag and compare_version_tags(existing_tag,DB_SCHEMA_TAG)>0:
        raise RuntimeError(f'database schema tag {existing_tag} is newer than source schema tag {DB_SCHEMA_TAG}; refusing to touch this DB')
    await conn.execute('PRAGMA foreign_keys=ON'); await conn.execute('PRAGMA journal_mode=WAL'); await conn.execute('PRAGMA synchronous=NORMAL')
    await conn.executescript(BOOTSTRAP_SCHEMA_SQL)
    await run_schema_migrations(conn)
    await ensure_builtin_assets(conn)
    await ensure_runtime_tool_contracts(conn)
    await ensure_default_records(conn)
    await ensure_builtin_tasks(conn)
    if upgrade_schema_tag or not existed:
        await write_db_schema_tag(conn)
    else:
        current_tag=await read_db_schema_tag(conn)
        if current_tag!=DB_SCHEMA_TAG:
            await warn_schema_mismatch(current_tag)
    await conn.commit()

async def _table_columns(conn, table):
    cur=await conn.execute(f'PRAGMA table_info({table})')
    return {r[1] for r in await cur.fetchall()}

async def _add_column_if_missing(conn, table, columns, column_sql):
    name=column_sql.split()[0]
    if name not in columns:
        await conn.execute(f'ALTER TABLE {table} ADD COLUMN {column_sql}')
        columns.add(name)

async def _legacy_memory_id_labels(conn):
    labels={}
    def add_label(value,snowflake):
        text=str(value or '').strip().lower()
        if not text or not memory_contract.is_discord_id(snowflake):
            return
        variants={text,text.strip('. @')}
        for variant in variants:
            if variant:
                labels.setdefault(variant,str(snowflake))
    if await _table_exists(conn,'memory_events'):
        cur=await conn.execute(
            "SELECT user_name,user_id,COUNT(*) n FROM memory_events "
            "WHERE user_name IS NOT NULL AND user_id IS NOT NULL "
            "GROUP BY user_name,user_id ORDER BY n DESC"
        )
        for name,user_id,_ in await cur.fetchall():
            add_label(name,user_id)
    if await _table_exists(conn,'discord_identity_map'):
        cur=await conn.execute('SELECT snowflake,label FROM discord_identity_map')
        for snowflake,label in await cur.fetchall():
            add_label(label,snowflake)
    return labels

def _legacy_memory_tags_to_new(value):
    return memory_contract.tags_to_db(value, MAX_MEMORY_TAGS_LENGTH)

async def _create_memory_schema(conn):
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS memories ("
        "int_memory_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "str_discord_id TEXT NOT NULL CHECK (length(str_discord_id) BETWEEN 15 AND 22 AND str_discord_id NOT GLOB '*[^0-9]*'), "
        "str_annotations TEXT NOT NULL, "
        "array_tags TEXT CHECK (array_tags IS NULL OR json_valid(array_tags)), "
        "float_confidence REAL NOT NULL DEFAULT 0.7 CHECK (float_confidence BETWEEN 0.0 AND 1.0), "
        "str_created_utc TEXT NOT NULL, "
        "str_created_by TEXT NOT NULL, "
        "int_superseded_by INTEGER, "
        "FOREIGN KEY(int_superseded_by) REFERENCES memories(int_memory_id)"
        ")"
    )
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_memories_discord ON memories(str_discord_id, int_superseded_by)')
    await conn.execute('CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(str_annotations, array_tags, str_discord_id, content=\'memories\', content_rowid=\'int_memory_id\')')
    await conn.execute("CREATE TRIGGER IF NOT EXISTS ai_memories AFTER INSERT ON memories BEGIN INSERT INTO memories_fts(rowid,str_annotations,array_tags,str_discord_id) VALUES(new.int_memory_id,new.str_annotations,new.array_tags,new.str_discord_id); END;")
    await conn.execute("CREATE TRIGGER IF NOT EXISTS ad_memories AFTER DELETE ON memories BEGIN INSERT INTO memories_fts(memories_fts,rowid,str_annotations,array_tags,str_discord_id) VALUES('delete',old.int_memory_id,old.str_annotations,old.array_tags,old.str_discord_id); END;")
    await conn.execute("CREATE TRIGGER IF NOT EXISTS au_memories AFTER UPDATE ON memories BEGIN INSERT INTO memories_fts(memories_fts,rowid,str_annotations,array_tags,str_discord_id) VALUES('delete',old.int_memory_id,old.str_annotations,old.array_tags,old.str_discord_id); INSERT INTO memories_fts(rowid,str_annotations,array_tags,str_discord_id) VALUES(new.int_memory_id,new.str_annotations,new.array_tags,new.str_discord_id); END;")

async def _rebuild_memory_fts(conn):
    await conn.execute('INSERT INTO memories_fts(memories_fts) VALUES (\'delete-all\')')
    await conn.execute('INSERT INTO memories_fts(rowid,str_annotations,array_tags,str_discord_id) SELECT int_memory_id,str_annotations,array_tags,str_discord_id FROM memories')

async def migrate_memory_schema(conn):
    if not await _table_exists(conn,'memories'):
        await _create_memory_schema(conn)
        return
    cols=await _table_columns(conn,'memories')
    await conn.execute('DROP TRIGGER IF EXISTS ai_memories')
    await conn.execute('DROP TRIGGER IF EXISTS ad_memories')
    await conn.execute('DROP TRIGGER IF EXISTS au_memories')
    await conn.execute('DROP TABLE IF EXISTS memories_fts')
    await conn.execute('DROP INDEX IF EXISTS idx_memories_target')
    await conn.execute('DROP INDEX IF EXISTS idx_memories_discord')
    if 'int_memory_id' not in cols:
        legacy_name='memories_legacy_'+re.sub(r'[^A-Za-z0-9_]+','_',format_timestamp_for_filename())
        await conn.execute(f'ALTER TABLE memories RENAME TO {legacy_name}')
        await _create_memory_schema(conn)
        labels=await _legacy_memory_id_labels(conn)
        cur=await conn.execute(
            f'SELECT id,target_id,note,tags,confidence,created_at,created_by,superseded_by FROM {legacy_name} ORDER BY id ASC'
        )
        pending_superseded=[]
        unresolved=[]
        migrated_ids=set()
        for row in await cur.fetchall():
            memory_id,target_id,note,tags,confidence,created_at,created_by,superseded_by=row
            discord_id=memory_contract.normalize_discord_id(target_id)
            if not memory_contract.is_discord_id(discord_id):
                discord_id=labels.get(str(target_id or '').strip().lower(), discord_id)
            if not memory_contract.is_discord_id(discord_id):
                unresolved.append({'int_memory_id':memory_id,'legacy_target_id':target_id})
                continue
            try:
                conf=max(0.0,min(float(confidence if confidence is not None else 0.7),1.0))
            except Exception:
                conf=0.7
            await conn.execute(
                'INSERT INTO memories(int_memory_id,str_discord_id,str_annotations,array_tags,float_confidence,str_created_utc,str_created_by,int_superseded_by) VALUES (?,?,?,?,?,?,?,NULL)',
                (memory_id,discord_id,str(note or ''),_legacy_memory_tags_to_new(tags),conf,created_at or utc_now(),str(created_by or 'migration'))
            )
            migrated_ids.add(int(memory_id))
            if superseded_by is not None:
                pending_superseded.append((int(superseded_by), int(memory_id)))
        if unresolved:
            if await _table_exists(conn,'bot_logs'):
                await conn.execute(
                    'INSERT INTO bot_logs(level,component,message,detail_json,timestamp_utc) VALUES (?,?,?,?,?)',
                    (
                        'warn',
                        'db',
                        'legacy memory migration left unresolved rows in legacy table',
                        json.dumps({'legacy_table':legacy_name,'unresolved_count':len(unresolved),'preview':unresolved[:5]},ensure_ascii=False,separators=(',',':')),
                        utc_now(),
                    ),
                )
        for superseded_by,memory_id in pending_superseded:
            if superseded_by in migrated_ids and memory_id in migrated_ids:
                await conn.execute('UPDATE memories SET int_superseded_by=? WHERE int_memory_id=?',(superseded_by,memory_id))
        if not unresolved:
            await conn.execute(f'DROP TABLE {legacy_name}')
    else:
        await _create_memory_schema(conn)
    await _rebuild_memory_fts(conn)

async def run_schema_migrations(conn):
    """Bring older local SQLite files forward without requiring destructive resets."""
    task_cols=await _table_columns(conn,'agent_tasks')
    for column_sql in (
        'name TEXT',
        "enabled INTEGER NOT NULL DEFAULT 0",
        'schedule_minutes INTEGER',
        'next_run_utc TEXT',
        'last_run_utc TEXT',
        'run_count INTEGER NOT NULL DEFAULT 0',
        'max_runs INTEGER',
        'updated_at TEXT',
        'bot_entry_id INTEGER',
        'provider_id INTEGER',
        'model TEXT',
        'parameter_profile_id INTEGER',
        'runtime_kind TEXT',
        'created_by_display TEXT',
        'target_scope_type TEXT',
        'target_scope_id TEXT',
    ):
        await _add_column_if_missing(conn,'agent_tasks',task_cols,column_sql)
    asset_cols=await _table_columns(conn,'agent_assets')
    for column_sql in (
        "scope_type TEXT NOT NULL DEFAULT 'global'",
        'scope_id TEXT',
        'enabled INTEGER NOT NULL DEFAULT 1',
        'is_builtin INTEGER NOT NULL DEFAULT 0',
        'schema_json TEXT',
        'executor_name TEXT',
        'snapshot_version TEXT',
        'globally_disabled INTEGER NOT NULL DEFAULT 0',
        'updated_at TEXT',
    ):
        await _add_column_if_missing(conn,'agent_assets',asset_cols,column_sql)
    await conn.execute('UPDATE agent_tasks SET updated_at=COALESCE(updated_at,created_at)')
    await conn.execute('UPDATE agent_assets SET updated_at=COALESCE(updated_at,created_at)')
    await conn.execute('DROP INDEX IF EXISTS uq_agent_assets_type_name')
    await conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_assets_global ON agent_assets(asset_type,name,scope_type) WHERE scope_id IS NULL')
    await conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_assets_scoped ON agent_assets(asset_type,name,scope_type,scope_id) WHERE scope_id IS NOT NULL')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_agent_assets_scope ON agent_assets(asset_type,scope_type,scope_id,enabled)')
    await conn.execute("CREATE TABLE IF NOT EXISTS tool_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, version TEXT NOT NULL UNIQUE, tools_json TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL, applied_at TEXT)")
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_agent_tasks_schedule ON agent_tasks(enabled,next_run_utc,status)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_provider_calls_provider_ts ON provider_calls(provider_id, timestamp_utc)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_provider_calls_scope_ts ON provider_calls(scope_type, scope_id, timestamp_utc)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_agent_task_runs_task_created ON agent_task_runs(task_id, created_at)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_agent_task_runs_scope_created ON agent_task_runs(scope_type, scope_id, created_at)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_outbound_messages_status_created ON outbound_messages(status, created_at)')
    await conn.execute("CREATE TABLE IF NOT EXISTS memory_events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL, scope_type TEXT, scope_id TEXT, user_id TEXT, user_name TEXT, role TEXT NOT NULL CHECK (role IN ('user','assistant','system','tool','task','operator')), content TEXT NOT NULL, metadata_json TEXT, timestamp_utc TEXT NOT NULL)")
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_memory_events_ts ON memory_events(timestamp_utc)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_memory_events_scope_ts ON memory_events(scope_type, scope_id, timestamp_utc)')
    await migrate_memory_schema(conn)
    await conn.execute("CREATE TABLE IF NOT EXISTS news_items (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL UNIQUE, title TEXT NOT NULL, source TEXT NOT NULL, source_kind TEXT NOT NULL CHECK (source_kind IN ('grounding','exploratory')), published_at_utc TEXT, first_seen_utc TEXT NOT NULL, last_seen_utc TEXT NOT NULL, last_posted_utc TEXT, posted_count INTEGER NOT NULL DEFAULT 0, metadata_json TEXT)")
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_news_items_posted ON news_items(last_posted_utc)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_news_items_source_seen ON news_items(source, last_seen_utc)')
    await conn.execute("CREATE TABLE IF NOT EXISTS discord_identity_map (snowflake TEXT PRIMARY KEY, label TEXT NOT NULL CHECK (length(label)<=255), kind TEXT, source TEXT NOT NULL DEFAULT 'operator', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    await conn.execute("CREATE TABLE IF NOT EXISTS task_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, version TEXT NOT NULL UNIQUE, tasks_json TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL, applied_at TEXT)")
    rox_cols=await _table_columns(conn,'roxanne_profiles')
    for column_sql in (
        "reasoning_mode TEXT NOT NULL DEFAULT 'inherit'",
        "tools_enabled INTEGER NOT NULL DEFAULT 1",
    ):
        await _add_column_if_missing(conn,'roxanne_profiles',rox_cols,column_sql)
    await conn.execute("CREATE TABLE IF NOT EXISTS roxanne_memory (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, body TEXT NOT NULL, tags TEXT, enabled INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT)")
    cur=await conn.execute("SELECT int_memory_id,str_discord_id,str_annotations,array_tags,str_created_utc,str_created_by FROM memories WHERE int_superseded_by IS NULL AND (LOWER(COALESCE(array_tags,'')) LIKE '%roxanne%' OR str_annotations LIKE 'Roxanne is Dirac%')")
    migrated=await cur.fetchall()
    for memory_id,discord_id,annotations,tags,created_at,created_by in migrated:
        exists=await conn.execute("SELECT id FROM roxanne_memory WHERE body=?",(annotations,))
        if not await exists.fetchone():
            title='Migrated Dirac memory'
            if 'Roxanne' in (annotations or ''):
                title='Who Roxanne is'
            await conn.execute(
                'INSERT INTO roxanne_memory(title,body,tags,enabled,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
                (title,annotations,tags or f'discord:{discord_id}',1,created_by or 'migration',created_at or utc_now(),utc_now())
            )
        await conn.execute('DELETE FROM memories WHERE int_memory_id=?',(memory_id,))
    cur=await conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='permissions'")
    row=await cur.fetchone()
    if row and "'root'" not in (row[0] or ''):
        await conn.execute("CREATE TABLE permissions_new (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, scope_type TEXT NOT NULL CHECK (scope_type IN ('global','dm','group','guild')), scope_id TEXT, level TEXT NOT NULL CHECK (level IN ('root','admin','user','blocked')), added_at TEXT NOT NULL)")
        await conn.execute('INSERT INTO permissions_new(id,user_id,scope_type,scope_id,level,added_at) SELECT id,user_id,scope_type,scope_id,level,added_at FROM permissions')
        await conn.execute('DROP TABLE permissions')
        await conn.execute('ALTER TABLE permissions_new RENAME TO permissions')
    await conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS uq_permissions_global ON permissions(user_id, scope_type) WHERE scope_id IS NULL')
    await conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS uq_permissions_scoped ON permissions(user_id, scope_type, scope_id) WHERE scope_id IS NOT NULL')
    provider_cols=await _table_columns(conn,'service_providers')
    if 'api_key_encrypted' in provider_cols and 'api_key' not in provider_cols:
        # Rename misleading column: the value stored has never been encrypted at rest.
        await conn.execute('ALTER TABLE service_providers RENAME COLUMN api_key_encrypted TO api_key')
    log_cols=await _table_columns(conn,'bot_logs')
    if 'scope_type' not in log_cols:
        await conn.execute('ALTER TABLE bot_logs ADD COLUMN scope_type TEXT')
        log_cols.add('scope_type')
    if 'scope_id' not in log_cols:
        await conn.execute('ALTER TABLE bot_logs ADD COLUMN scope_id TEXT')
        log_cols.add('scope_id')
    cur=await conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='bot_logs'")
    row=await cur.fetchone()
    if row and "'trace'" not in (row[0] or ''):
        await conn.execute("CREATE TABLE bot_logs_new (id INTEGER PRIMARY KEY AUTOINCREMENT, level TEXT NOT NULL CHECK (level IN ('trace','debug','info','warn','error')), component TEXT NOT NULL, message TEXT NOT NULL, detail_json TEXT, scope_type TEXT, scope_id TEXT, timestamp_utc TEXT NOT NULL)")
        await conn.execute('INSERT INTO bot_logs_new(id,level,component,message,detail_json,scope_type,scope_id,timestamp_utc) SELECT id,level,component,message,detail_json,scope_type,scope_id,timestamp_utc FROM bot_logs')
        await conn.execute('DROP TABLE bot_logs')
        await conn.execute('ALTER TABLE bot_logs_new RENAME TO bot_logs')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_bot_logs_level_ts ON bot_logs(level, timestamp_utc)')
    await conn.execute('CREATE INDEX IF NOT EXISTS idx_bot_logs_component_ts ON bot_logs(component, timestamp_utc)')

def normalize_tool_schema_json(schema,name=None):
    if schema in (None,''):
        return None
    obj=json.loads(schema) if isinstance(schema,str) else schema
    if not isinstance(obj,dict):
        raise ValueError('schema must be a JSON object')
    if obj.get('type')=='function' and isinstance(obj.get('function'),dict):
        fn=dict(obj['function'])
        wrapper={'type':'function','function':fn}
    elif 'name' in obj and 'parameters' in obj:
        wrapper={'type':'function','function':dict(obj)}
    else:
        raise ValueError('schema must be a function tool schema')
    fn=wrapper['function']
    if name and fn.get('name')!=name:
        raise ValueError('schema function name must match asset name')
    if not isinstance(fn.get('parameters',{}),dict):
        raise ValueError('schema parameters must be an object')
    return json.dumps(wrapper,sort_keys=True,separators=(',',':'))
def normalize_executor_name(asset_type,executor_name):
    if executor_name in (None,''):
        return None
    executor=str(executor_name)
    if asset_type!='tool' or executor not in ALLOWED_TOOL_EXECUTORS:
        raise ValueError('invalid executor')
    return executor
def load_builtin_tools_snapshot():
    data=json.loads(BUILTIN_TOOLS_SNAPSHOT_PATH.read_text(encoding='utf-8'))
    version=str(data.get('version') or '').strip()
    tools=data.get('tools') or []
    if not version or not isinstance(tools,list):
        raise ValueError('invalid built-in tools snapshot')
    normalized=[]
    for tool in tools:
        name=str(tool.get('name') or '').strip()
        if not valid_asset_name(name):
            raise ValueError('invalid built-in tool name')
        normalized.append({
            'asset_type':'tool',
            'name':name,
            'description':str(tool.get('description') or ''),
            'body':tool.get('body'),
            'enabled':int(bool(tool.get('enabled',True))),
            'executor_name':normalize_executor_name('tool',tool.get('executor_name')),
            'schema_json':normalize_tool_schema_json(tool.get('schema'),name),
            'snapshot_version':version,
            'globally_disabled':0,
        })
    return {'version':version,'tools':normalized}
async def record_tool_snapshot(conn,snapshot,applied_at=None,created_by='system'):
    tools_json=json.dumps(snapshot.get('tools') or [],sort_keys=True)
    now=utc_now()
    await conn.execute(
        'INSERT INTO tool_snapshots(version,tools_json,created_at,created_by,applied_at) VALUES (?,?,?,?,?) '
        'ON CONFLICT(version) DO UPDATE SET tools_json=excluded.tools_json,applied_at=COALESCE(excluded.applied_at,tool_snapshots.applied_at)',
        (snapshot['version'],tools_json,now,created_by,applied_at)
    )
async def _snapshot_from_db(conn,version):
    cur=await conn.execute('SELECT version,tools_json FROM tool_snapshots WHERE version=?',(version,))
    row=await cur.fetchone()
    if not row:
        return None
    return {'version':row[0],'tools':json.loads(row[1] or '[]')}
async def apply_builtin_tool_snapshot(conn,version='latest',created_by='system',preserve_state=True):
    file_snapshot=load_builtin_tools_snapshot()
    if version in (None,'','latest'):
        snapshot=file_snapshot
    elif version==file_snapshot['version']:
        snapshot=file_snapshot
    else:
        snapshot=await _snapshot_from_db(conn,version)
        if snapshot is None:
            raise ValueError('snapshot not found')
    now=utc_now()
    await record_tool_snapshot(conn,snapshot,applied_at=now,created_by=created_by)
    restored=0; inserted=0
    for asset in snapshot['tools']:
        cur=await conn.execute("SELECT id,enabled,globally_disabled FROM agent_assets WHERE asset_type='tool' AND name=? AND scope_type='global' AND scope_id IS NULL",(asset['name'],))
        row=await cur.fetchone()
        if row:
            enabled=row[1] if preserve_state else asset['enabled']
            globally_disabled=row[2] if preserve_state else asset.get('globally_disabled',0)
            await conn.execute(
                'UPDATE agent_assets SET description=?,body=?,enabled=?,is_builtin=1,schema_json=?,executor_name=?,snapshot_version=?,globally_disabled=?,updated_at=? WHERE id=?',
                (asset['description'],asset.get('body'),int(enabled),asset.get('schema_json'),asset.get('executor_name'),snapshot['version'],int(globally_disabled or 0),now,row[0])
            )
            restored+=1
        else:
            await conn.execute(
                'INSERT INTO agent_assets(asset_type,name,description,body,scope_type,scope_id,enabled,is_builtin,schema_json,executor_name,snapshot_version,globally_disabled,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('tool',asset['name'],asset['description'],asset.get('body'),'global',None,int(asset.get('enabled',1)),1,asset.get('schema_json'),asset.get('executor_name'),snapshot['version'],0,created_by,now,now)
            )
            inserted+=1
    await ensure_runtime_tool_contracts(conn)
    await conn.commit()
    return {'version':snapshot['version'],'restored':restored,'inserted':inserted}
async def ensure_builtin_assets(conn):
    now=utc_now()
    snapshot=load_builtin_tools_snapshot()
    await record_tool_snapshot(conn,snapshot,created_by='system')
    for asset in snapshot['tools']:
        cur=await conn.execute("SELECT id FROM agent_assets WHERE asset_type='tool' AND name=? AND scope_type='global' AND scope_id IS NULL",(asset['name'],))
        row=await cur.fetchone()
        if row:
            await conn.execute(
                "UPDATE agent_assets SET is_builtin=1, schema_json=CASE WHEN schema_json IS NULL OR schema_json='' THEN ? ELSE schema_json END, executor_name=CASE WHEN executor_name IS NULL OR executor_name='' THEN ? ELSE executor_name END, snapshot_version=CASE WHEN snapshot_version IS NULL OR snapshot_version='' THEN ? ELSE snapshot_version END, updated_at=COALESCE(updated_at,?) WHERE id=?",
                (asset.get('schema_json'),asset.get('executor_name'),snapshot['version'],now,row[0])
            )
        else:
            await conn.execute(
                'INSERT INTO agent_assets(asset_type,name,description,body,scope_type,scope_id,enabled,is_builtin,schema_json,executor_name,snapshot_version,globally_disabled,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('tool',asset['name'],asset['description'],asset.get('body'),'global',None,int(asset.get('enabled',1)),1,asset.get('schema_json'),asset.get('executor_name'),snapshot['version'],0,'system',now,now)
            )

async def ensure_runtime_tool_contracts(conn):
    now=utc_now()
    for name in ('memory_search','memory_add','memory_update','memory_edit','memory_delete','memory_remove'):
        schema=memory_contract.memory_tool_schema(name)
        body=memory_contract.memory_tool_body(name)
        if not schema:
            continue
        await conn.execute(
            "UPDATE agent_assets SET schema_json=?,body=?,executor_name=?,updated_at=? WHERE asset_type='tool' AND name=?",
            (json.dumps(schema,ensure_ascii=False),body,normalize_executor_name('tool','memory_update' if name=='memory_edit' else 'memory_delete' if name=='memory_remove' else name),now,name)
        )

def load_builtin_tasks_snapshot():
    data=json.loads(BUILTIN_TASKS_SNAPSHOT_PATH.read_text(encoding='utf-8'))
    version=str(data.get('version') or '').strip()
    tasks=data.get('tasks') or []
    if not version or not isinstance(tasks,list):
        raise ValueError('invalid built-in tasks snapshot')
    normalized=[]
    for task in tasks:
        name=str(task.get('name') or '').strip()
        if not valid_asset_name(name):
            raise ValueError('invalid built-in task name')
        minutes=parse_interval_minutes(task.get('schedule_minutes'))
        if not minutes:
            raise ValueError('invalid built-in task schedule')
        scope_type=str(task.get('scope_type') or 'global')
        scope_id=normalize_scope_id(scope_type,task.get('scope_id'))
        if not valid_scope_pair(scope_type,scope_id):
            raise ValueError('invalid built-in task scope')
        prompt=str(task.get('prompt') or '').strip()
        if not prompt:
            raise ValueError('invalid built-in task prompt')
        runtime_kind=str(task.get('runtime_kind') or 'default').strip().lower()
        if runtime_kind not in {'default','rem'}:
            raise ValueError('invalid built-in task runtime_kind')
        normalized.append({
            'name':name,
            'description':str(task.get('description') or ''),
            'prompt':prompt,
            'schedule_minutes':minutes,
            'scope_type':scope_type,
            'scope_id':scope_id,
            'enabled':int(bool(task.get('enabled',True))),
            'max_runs':task.get('max_runs'),
            'runtime_kind':runtime_kind,
        })
    return {'version':version,'tasks':normalized}
async def record_task_snapshot(conn,snapshot,applied_at=None,created_by='system'):
    tasks_json=json.dumps(snapshot.get('tasks') or [],sort_keys=True)
    now=utc_now()
    await conn.execute(
        'INSERT INTO task_snapshots(version,tasks_json,created_at,created_by,applied_at) VALUES (?,?,?,?,?) '
        'ON CONFLICT(version) DO UPDATE SET tasks_json=excluded.tasks_json,applied_at=COALESCE(excluded.applied_at,task_snapshots.applied_at)',
        (snapshot['version'],tasks_json,now,created_by,applied_at)
    )
async def _task_snapshot_from_db(conn,version):
    cur=await conn.execute('SELECT version,tasks_json FROM task_snapshots WHERE version=?',(version,))
    row=await cur.fetchone()
    if not row:
        return None
    return {'version':row[0],'tasks':json.loads(row[1] or '[]')}
async def apply_builtin_task_snapshot(conn,version='latest',created_by='system',preserve_enabled=True):
    file_snapshot=load_builtin_tasks_snapshot()
    if version in (None,'','latest'):
        snapshot=file_snapshot
    elif version==file_snapshot['version']:
        snapshot=file_snapshot
    else:
        snapshot=await _task_snapshot_from_db(conn,version)
        if snapshot is None:
            raise ValueError('task snapshot not found')
    now=utc_now()
    await record_task_snapshot(conn,snapshot,applied_at=now,created_by=created_by)
    restored=0; inserted=0
    for task in snapshot['tasks']:
        sid=normalize_scope_id(task['scope_type'],task.get('scope_id'))
        cur=await conn.execute(
            "SELECT id,enabled,next_run_utc FROM agent_tasks WHERE kind='task' AND name=? AND scope_type=? AND ((scope_id IS NULL AND ? IS NULL) OR scope_id=?) ORDER BY id LIMIT 1",
            (task['name'],task['scope_type'],sid,sid)
        )
        row=await cur.fetchone()
        enabled=row[1] if row and preserve_enabled else int(task.get('enabled',1))
        next_run=row[2] if row and preserve_enabled and row[2] else (utc_after_minutes(task['schedule_minutes']) if enabled else None)
        if row:
            await conn.execute(
                "UPDATE agent_tasks SET prompt=?,status=CASE WHEN status='running' THEN status ELSE 'completed' END,requested_by=COALESCE(requested_by,?),source=COALESCE(source,'scheduler'),enabled=?,schedule_minutes=?,next_run_utc=?,max_runs=?,runtime_kind=?,updated_at=? WHERE id=?",
                (task['prompt'],created_by,int(enabled),task['schedule_minutes'],next_run,task.get('max_runs'),task.get('runtime_kind') or 'default',now,row[0])
            )
            restored+=1
        else:
            await conn.execute(
                'INSERT INTO agent_tasks(kind,name,prompt,status,requested_by,source,scope_type,scope_id,backend,enabled,schedule_minutes,next_run_utc,run_count,max_runs,runtime_kind,created_at,updated_at,target_scope_type,target_scope_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('task',task['name'],task['prompt'],'completed',created_by,'scheduler',task['scope_type'],sid,'ollama',int(enabled),task['schedule_minutes'],next_run,0,task.get('max_runs'),task.get('runtime_kind') or 'default',now,now,task['scope_type'],sid)
            )
            inserted+=1
    await conn.commit()
    return {'version':snapshot['version'],'restored':restored,'inserted':inserted}
async def ensure_builtin_tasks(conn):
    snapshot=load_builtin_tasks_snapshot()
    await record_task_snapshot(conn,snapshot,created_by='system')
    now=utc_now()
    for task in snapshot['tasks']:
        sid=normalize_scope_id(task['scope_type'],task.get('scope_id'))
        cur=await conn.execute(
            "SELECT id FROM agent_tasks WHERE kind='task' AND name=? AND scope_type=? AND ((scope_id IS NULL AND ? IS NULL) OR scope_id=?) ORDER BY id LIMIT 1",
            (task['name'],task['scope_type'],sid,sid)
        )
        if await cur.fetchone():
            continue
        enabled=int(task.get('enabled',1))
        next_run=utc_after_minutes(task['schedule_minutes']) if enabled else None
        await conn.execute(
            'INSERT INTO agent_tasks(kind,name,prompt,status,requested_by,source,scope_type,scope_id,backend,enabled,schedule_minutes,next_run_utc,run_count,max_runs,runtime_kind,created_at,updated_at,target_scope_type,target_scope_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            ('task',task['name'],task['prompt'],'completed','system','scheduler',task['scope_type'],sid,'ollama',enabled,task['schedule_minutes'],next_run,0,task.get('max_runs'),task.get('runtime_kind') or 'default',now,now,task['scope_type'],sid)
        )

async def ensure_default_records(conn,cfg=None):
    now=utc_now()
    await _upsert(conn,'permissions',['user_id','scope_type','scope_id'],[ROOT_OPERATOR_ID,'global',None],{'level':'root','added_at':now})
    await _upsert(conn,'permissions',['user_id','scope_type','scope_id'],['panel','global',None],{'level':'root','added_at':now})
    await LegacyProviderClient(conn,utc_now=utc_now).ensure_defaults(cfg)
    cur=await conn.execute("SELECT id FROM bot_entries WHERE name='dirac'")
    if not await cur.fetchone():
        await conn.execute('INSERT INTO bot_entries(name,description,enabled,persona,default_scope_type,default_scope_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',('dirac','Primary Discord self-bot entry',1,'Primary Dirac Discord persona','global',None,now,now))
    cur=await conn.execute("SELECT id,system_prompt FROM roxanne_profiles WHERE name='default'")
    row=await cur.fetchone()
    if not row:
        await conn.execute('INSERT INTO roxanne_profiles(name,enabled,system_prompt,created_at,updated_at) VALUES (?,?,?,?,?)',('default',1,ROXANNE_SYSTEM_PROMPT,now,now))
    elif (row[1] or '').strip() in {'',OLD_ROXANNE_SYSTEM_PROMPT} or 'direct read-only access to fresh Dirac runtime snapshots' in (row[1] or ''):
        await conn.execute('UPDATE roxanne_profiles SET system_prompt=?,updated_at=? WHERE id=?',(ROXANNE_SYSTEM_PROMPT,now,row[0]))
    cur=await conn.execute('SELECT id FROM roxanne_memory LIMIT 1')
    if not await cur.fetchone():
        await conn.execute(
            'INSERT INTO roxanne_memory(title,body,tags,enabled,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
            (
                'Who Roxanne is',
                "Roxanne is Dirac's WebUI operations assistant. She is separate from Discord memories, works inside the panel, can read local docs and redacted runtime state, and should use her safe tools before claiming a source is unavailable.",
                'roxanne,identity,webui',
                1,
                'system',
                now,
                now,
            )
        )

class DbWriter:
    def __init__(self, path: str|Path|None=None, conn=None):
        self.path=Path(path) if path is not None else None; self._conn=conn; self.queue=asyncio.Queue(); self._task=None; self._closed=False
    @classmethod
    async def for_memory(cls):
        c=await aiosqlite.connect(':memory:'); await bootstrap_db(c); return cls(conn=c)
    async def start(self,tg:asyncio.TaskGroup):
        if self._conn is None:
            self._conn=await aiosqlite.connect(self.path or DB_PATH); await bootstrap_db(self._conn)
        if self._task is None: self._task=tg.create_task(self._run())
        return self
    @property
    def conn(self):
        if self._conn is None: raise RuntimeError('DbWriter not started')
        return self._conn
    async def get_connection_for_tests(self): return self.conn
    async def execute(self, sql, params=()):
        if self._closed: raise RuntimeError('DbWriter closed')
        fut=asyncio.get_running_loop().create_future(); await self.queue.put((sql,params,fut)); return await fut
    async def upsert(self, table, keys, key_values, fields):
        if self._closed: raise RuntimeError('DbWriter closed')
        fut=asyncio.get_running_loop().create_future(); await self.queue.put(('__UPSERT__',(table,keys,key_values,fields),fut)); return await fut
    async def _run(self):
        while True:
            sql,params,fut=await self.queue.get()
            if sql=='__STOP__':
                if not fut.cancelled(): fut.set_result(None)
                self.queue.task_done(); break
            try:
                if sql=='__UPSERT__':
                    table,keys,key_values,fields=params
                    cur=await self._upsert_locked(table,keys,key_values,fields)
                else:
                    cur=await self.conn.execute(sql,params)
                await self.conn.commit()
                if not fut.cancelled(): fut.set_result((cur.lastrowid if cur is not None else None, cur.rowcount if cur is not None else 0))
            except Exception as e:
                await self.conn.rollback()
                if not fut.cancelled(): fut.set_exception(e)
            self.queue.task_done()
    async def _upsert_locked(self, table, keys, key_values, fields):
        where=' AND '.join(f'{k}=?' if v is not None else f'{k} IS NULL' for k,v in zip(keys, key_values))
        params=tuple(v for v in key_values if v is not None)
        cur=await self.conn.execute(f'SELECT 1 FROM {table} WHERE {where} LIMIT 1', params); exists=await cur.fetchone()
        if exists:
            set_clause=', '.join(f'{k}=?' for k in fields)
            return await self.conn.execute(f'UPDATE {table} SET {set_clause} WHERE {where}', tuple(fields.values())+params)
        cols=list(keys)+list(fields.keys()); vals=list(key_values)+list(fields.values())
        return await self.conn.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES ({','.join('?'*len(cols))})", tuple(vals))
    async def close(self):
        self._closed=True
        if self._task:
            fut=asyncio.get_running_loop().create_future(); await self.queue.put(('__STOP__',(),fut)); await fut; await self._task
        if self._conn: await self._conn.close()

class RuntimeDb:
    def __init__(self, writer:DbWriter):
        self.writer=writer; self.conn=writer.conn
    async def execute(self, sql, params=()):
        if is_read_sql_statement(sql):
            return await self.conn.execute(sql,params)
        return _WriteResult(await self.writer.execute(sql,params))
    async def upsert(self, table, keys, key_values, fields):
        return _WriteResult(await self.writer.upsert(table,keys,key_values,fields))
    async def commit(self): pass
    async def rollback(self): pass
    async def close(self): await self.writer.close()

class _WriteResult:
    def __init__(self,result):
        if isinstance(result,tuple):
            self.lastrowid,self.rowcount=result
        else:
            self.lastrowid=result
            self.rowcount=0

def is_read_sql_statement(sql):
    text=str(sql or '').lstrip()
    if not text:
        return False
    op=text.split(None,1)[0].upper()
    if op in {'SELECT','PRAGMA'}:
        return True
    if op!='WITH':
        return False
    final_op=final_with_statement_operator(text)
    return final_op in {'SELECT','PRAGMA'}

def final_with_statement_operator(sql):
    text=str(sql or '')
    pos=len('WITH')
    match=re.match(r'\s+RECURSIVE\b',text[pos:],re.I)
    if match:
        pos+=match.end()
    depth=0
    quote=None
    escape=False
    while pos < len(text):
        ch=text[pos]
        if quote:
            if quote=="'" and ch=="'" and pos+1 < len(text) and text[pos+1]=="'":
                pos+=2; continue
            if ch==quote and not escape:
                quote=None
            escape=(ch=='\\' and not escape)
            if ch!='\\':
                escape=False
            pos+=1; continue
        if ch in {"'",'"','`'}:
            quote=ch; pos+=1; continue
        if ch=='(':
            depth+=1
        elif ch==')' and depth>0:
            depth-=1
        elif depth==0:
            match=re.match(r'\s*(SELECT|INSERT|UPDATE|DELETE|REPLACE|PRAGMA)\b',text[pos:],re.I)
            if match:
                return match.group(1).upper()
        pos+=1
    return ''

@dataclass
class Config: ollama:dict[str,Any]; discord:dict[str,Any]; panel:dict[str,Any]; bot:dict[str,Any]; logging:dict[str,Any]
def load_config(path):
    with open(path,'rb') as f: d=tomllib.load(f)
    if d.get('discord',{}).get('i_understand_selfbot_risk') is not True: raise ValueError('discord.i_understand_selfbot_risk must be true to run')
    return Config(d.get('ollama',{}),d.get('discord',{}),d.get('panel',{}),d.get('bot',{}),dirac_logging.normalize_logging_config(d.get('logging',{})))
def config_to_dict(cfg):
    if isinstance(cfg,Config): return {'ollama':dict(cfg.ollama),'discord':dict(cfg.discord),'panel':dict(cfg.panel),'bot':dict(cfg.bot),'logging':dirac_logging.normalize_logging_config(cfg.logging)}
    if isinstance(cfg,dict): return {k:dict(v) for k,v in cfg.items() if isinstance(v,dict)}
    out={k:dict(getattr(cfg,k,{})) for k in ('ollama','discord','panel','bot')}
    out['logging']=dirac_logging.normalize_logging_config(getattr(cfg,'logging',{}))
    return out
def toml_value(value):
    """Convert supported scalar/list config values to TOML-formatted strings."""
    if isinstance(value,bool): return 'true' if value else 'false'
    if isinstance(value,(int,float)): return str(value)
    if isinstance(value,(list,tuple)): return '['+', '.join(toml_value(v) for v in value)+']'
    if isinstance(value,dict): return '{'+', '.join(f'{json.dumps(str(k))} = {toml_value(v)}' for k,v in sorted(value.items()))+'}'
    if value is None: return '""'
    return json.dumps(str(value))
def parse_cli_bool(value):
    lowered=str(value or '').strip().lower()
    if lowered in {'1','true','yes','y','on','enable','enabled'}:
        return True
    if lowered in {'0','false','no','n','off','disable','disabled'}:
        return False
    raise ValueError('expected true|false')
def dump_config_toml(data):
    lines=[]
    for section in ('ollama','discord','panel','bot','logging'):
        lines.append(f'[{section}]')
        for k,v in data.get(section,{}).items(): lines.append(f'{k} = {toml_value(v)}')
        lines.append('')
    return '\n'.join(lines)
def config_from_dict(data):
    return Config(data.get('ollama',{}),data.get('discord',{}),data.get('panel',{}),data.get('bot',{}),dirac_logging.normalize_logging_config(data.get('logging',{})))
def root_operator_ids():
    ids={ROOT_OPERATOR_ID,'panel'}
    cfg=getattr(app.state,'config',None) if 'app' in globals() else None
    bot_cfg=getattr(cfg,'bot',{}) if cfg is not None else {}
    for uid in bot_cfg.get('root_operator_ids',[]) if isinstance(bot_cfg,dict) else []:
        ids.add(str(uid))
    return ids
def is_root_operator(user_id):
    return str(user_id) in root_operator_ids()
def is_ultimate_operator(user_id):
    return str(user_id) == ROOT_OPERATOR_ID
def runtime_hold_line():
    state=runtime_control.status()
    if state.mode=='running':
        return 'runtime_control=running'
    remaining=state.remaining_seconds()
    suffix='until resume' if remaining is None else f'{remaining}s remaining'
    return f'runtime_control={state.mode} {suffix} by={state.started_by or "-"}'
def local_agent_tools():
    candidates={
        'bash': [shutil.which('bash'), str(Path.home())],
        'zsh': [shutil.which('zsh'), str(Path.home())],
        'sh': [shutil.which('sh'), str(Path.home())],
    }
    found={}
    for name,paths in candidates.items():
        for p in paths:
            if p and Path(p).exists():
                found[name]=p; break
    return found

DOC_SOURCES={
    'help': REPO_DIR / 'HELP.md',
    'admin': REPO_DIR / 'docs' / 'admin_help.md',
    'usage': REPO_DIR / 'USAGE.md',
    'readme': REPO_DIR / 'README.md',
    'agents': REPO_DIR / 'AGENTS.md',
    'ui': REPO_DIR / 'docs' / 'ui_guidelines.md',
}

def read_doc(name=None,max_chars=6000):
    if name is None:
        return{'error':'need name argument','available':sorted(DOC_SOURCES)}
    key=str(name).lower()
    if key not in DOC_SOURCES:
        return {'error':'unknown doc','available':sorted(DOC_SOURCES)}
    path=DOC_SOURCES[key]
    if not path.exists():
        return {'error':'doc missing','name':key,'path':str(path)}
    text=path.read_text(encoding='utf-8')
    truncated=len(text)>max_chars
    return {'name':key,'path':str(path),'content':text[:max_chars],'truncated':truncated}

def redacted_config_snapshot():
    cfg=getattr(app.state,'config',None) if 'app' in globals() else None
    if not cfg:
        return {'status':'config not loaded in this process'}
    data=config_to_dict(cfg)
    for section,key in (('ollama','api_key'),('discord','token'),('panel','auth_token')):
        if section in data and key in data[section]:
            data[section][key]=REDACTED_SECRET
    return data

def current_logging_config():
    cfg=getattr(app.state,'config',None) if 'app' in globals() else None
    return dirac_logging.normalize_logging_config(getattr(cfg,'logging',{}) if cfg is not None else {})
def persist_runtime_config():
    cfg=getattr(app.state,'config',None) if 'app' in globals() else None
    if cfg is None:
        return
    active_config_path().write_text(dump_config_toml(config_to_dict(cfg)),encoding='utf-8')

async def set_runtime_logging_config(logging_cfg):
    cfg=getattr(app.state,'config',None)
    if cfg is None:
        cfg=config_from_dict({'ollama':{},'discord':{},'panel':{'auth_token':getattr(app.state,'auth_token',PANEL_AUTH_TOKEN)},'bot':{},'logging':logging_cfg})
        app.state.config=cfg
        persist_runtime_config()
        return current_logging_config()
    return await runtime_logger().set_runtime_logging_config(logging_cfg)
async def adjust_console_logging(delta):
    return await runtime_logger().adjust_console_logging(delta,app_log)
def runtime_metadata_snapshot():
    cfg=getattr(app.state,'config',None) if 'app' in globals() else None
    panel_cfg=getattr(cfg,'panel',{}) if cfg is not None else {}
    bot_cfg=getattr(cfg,'bot',{}) if cfg is not None else {}
    return {
        'pid':os.getpid(),
        'uptime_s':int(time.time()-STARTED_AT),
        'config_path':str(active_config_path()) if 'active_config_path' in globals() else str(CONFIG_PATH),
        'db_path':str(DB_PATH),
        'panel_host':panel_cfg.get('host','127.0.0.1') if isinstance(panel_cfg,dict) else '127.0.0.1',
        'panel_port':panel_cfg.get('port',8765) if isinstance(panel_cfg,dict) else 8765,
        'trigger_on':bot_cfg.get('trigger_on') if isinstance(bot_cfg,dict) else None,
        'news_enabled':bot_cfg.get('news_enabled') if isinstance(bot_cfg,dict) else None,
        'version':APP_VERSION,
    }
async def ollama_usage_snapshot(db,scope_type=None,scope_id=None):
    return await provider_client_for_db(db).legacy_usage(scope_type,scope_id)
def admin_help_overview():
    docs=', '.join(sorted(DOC_SOURCES))
    return (
        'Dirac admin help\n'
        '\n'
        'Commands:\n'
        '!version - show the running Dirac version/build summary.\n'
        '!changelog - show recent local capability changes.\n'
        '!kill / !stop [seconds] / !pause [seconds] / !resume - ultimate-only emergency runtime controls.\n'
        '!help [all|config|docs|docs <name>] - show capabilities, redacted config, and docs.\n'
        '!status - show runtime, model, scope, and Ollama usage.\n'
        "!prompt '<body>' [*|@id] - set prompt for this scope/global/specific scope.\n"
        '!compact / !summary / !clear - manage context state.\n'
        '!whitelist add|remove|block <user_id> [root|admin|user] [*|@id] - manage permissions.\n'
        '!memory [help] / add <discord_id|@user|#channel> <annotations> / show <discord_id|id> - manage memory.\n'
        '!model <model_name> [*|@id] - set model override.\n'
        '!reasoning show|clear|on|off|low|medium|high [*|@id] - control Ollama think field.\n'
        '!create <task> - root-only: spawn a persisted sub-agent task.\n'
        '!agent help|show [id]|tools - root-only: inspect sub-agent tasks and installed CLIs.\n'
        '!tool help|add|show [#id|name]|edit|enable|disable|delete|snapshot|fix ... [*|@id] - root-only scoped tool management.\n'
        '!skill help|add|show [#id|name]|enable|disable|delete ... [*|@id] - root-only scoped skill management.\n'
        '!task help|add|show|edit|run|enable|disable|delete|fix ... [*|@id] - root-only recurring task management.\n'
        '!providers list|show|test|enable|disable <name|id> - root-only provider inspection and tests.\n'
        '!scope show|provider|params|reset-provider [*|@id] - root-only scoped provider and parameter control.\n'
        '!news now - root-only: fetch, summarize, send, and memorize AI/model/benchmark updates from known-source grounding plus exploratory web search.\n'
        '\n'
        'Panel capabilities: Dashboard, Providers, Provider Calls, Bot Entries, Scopes, Instructions, Logs, Channels, Prompts, Perms, Memory, WebChat, Tools, Skills, Tasks, Task Runs, Commands, Config, Roxanne, live tail.\n'
        f'Docs available through help/docs tools: {docs}.\n'
        'Secrets are always redacted; tokens and API keys are never shown.\n'
    )
def compact_help_overview():
    return (
        'Dirac command usage\n'
        '\n'
        '!help [all|config|docs|docs <name>]\n'
        '!kill / !stop [seconds] / !pause [seconds] / !resume\n'
        '!status\n'
        "!prompt '<body>' [*|@id]\n"
        '!whitelist add|remove|block <user_id> [root|admin|user] [*|@id]\n'
        '!memory help|add|show ...\n'
        '!model <model_name> [*|@id]\n'
        '!reasoning show|clear|off|on|low|medium|high [*|@id]\n'
        '!tool help|add|show [#id|name]|edit|enable|disable|delete|snapshot|fix ... [*|@id]\n'
        '!skill help|add|show [#id|name]|enable|disable|delete ... [*|@id]\n'
        '!task help|add|show|edit|run|enable|disable|delete|fix ... [*|@id]\n'
        '!provider list|show|test|enable|disable <name|id>\n'
        '!scope show|provider|params|reset-provider [*|@id]\n'
        '!news now\n'
        '\n'
        'Use !help all for the full admin overview, !help docs usage for the human guide, and !tool help / !task help for command-specific examples.'
    )

COMMAND_RE=re.compile(r'^!([A-Za-z][\w-]*)(?:\s+(.*))?$',re.S)
def parse_command(text):
    m=COMMAND_RE.match(text.strip())
    if not m: raise ValueError('malformed command')
    lexer=shlex.shlex((m.group(2) or '').strip(),posix=True); lexer.whitespace_split=True; lexer.commenters=''
    parts=list(lexer); mod=None
    if parts and parts[-1]=='*': mod={'type':'global','id':None}; parts=parts[:-1]
    elif parts and re.fullmatch(r'@\S+',parts[-1]): mod={'type':'specific','id':parts[-1][1:]}; parts=parts[:-1]
    return {'command':m.group(1).lower(),'args':parts,'scope_modifier':mod}
LEVELS={'blocked':-1,'user':1,'admin':2,'root':3}
SCOPE_TYPES=('dm','group','guild')
PROMPT_SCOPE_TYPES=('global','dm','group','guild')
EXTENDED_SCOPE_TYPES=('global','dm','group','guild','channel','user')
def valid_scope_pair(scope_type,scope_id):
    return (scope_type=='global' and scope_id in (None,'','*')) or (scope_type!='global' and scope_id not in (None,'','*'))
def valid_extended_scope_pair(scope_type,scope_id):
    return (scope_type=='global' and scope_id in (None,'','*')) or (scope_type!='global' and scope_type in EXTENDED_SCOPE_TYPES and scope_id not in (None,'','*'))
async def _upsert(db, table, keys, key_values, fields):
    """Manual upsert that works with partial unique indexes (NULL scope_id) and composite PKs."""
    if hasattr(db,'upsert'):
        await db.upsert(table,keys,key_values,fields); return
    where=' AND '.join(f'{k}=?' if v is not None else f'{k} IS NULL' for k,v in zip(keys, key_values))
    params=tuple(v for v in key_values if v is not None)
    cur=await db.execute(f'SELECT 1 FROM {table} WHERE {where} LIMIT 1', params); exists=await cur.fetchone()
    if exists:
        set_clause=', '.join(f'{k}=?' for k in fields)
        await db.execute(f'UPDATE {table} SET {set_clause} WHERE {where}', tuple(fields.values())+params)
    else:
        cols=list(keys)+list(fields.keys()); vals=list(key_values)+list(fields.values())
        await db.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES ({','.join('?'*len(cols))})", tuple(vals))
    await db.commit()
def quote_fts5_query(text):
    """Quote and escape text for FTS5 MATCH queries by doubling internal quotes."""
    return '"' + str(text).replace('"','""') + '"'
def like_pattern(text):
    """Escape SQL LIKE wildcards and wrap text with % for substring matching."""
    return '%' + str(text).replace('\\','\\\\').replace('%','\\%').replace('_','\\_') + '%'
def db_write_tool_lock(db):
    """Serialize DB-write tools per event loop/connection while keeping I/O tools parallel."""
    key=(id(asyncio.get_running_loop()),id(db))
    lock=DB_WRITE_TOOL_LOCKS.get(key)
    if lock is None:
        lock=asyncio.Lock()
        DB_WRITE_TOOL_LOCKS[key]=lock
    return lock
def clamp_limit(value,default=20,maximum=PANEL_TOOL_LIMIT):
    return max(1,min(int(value or default),maximum))
def format_timestamp_for_filename(ts=None):
    """Convert an ISO-8601 UTC timestamp to a compact filename-safe form by removing time separators."""
    return (ts or utc_now()).replace(':','').replace('.','')
async def set_prompt(db,scope_type,scope_id,body,updated_by):
    scope_id=normalize_scope_id(scope_type,scope_id)
    cur=await db.execute('SELECT body FROM prompts WHERE scope_type=? AND ((scope_id IS NULL AND ? IS NULL) OR scope_id=?)',(scope_type,scope_id,scope_id))
    row=await cur.fetchone(); now=utc_now()
    await db.execute('INSERT INTO prompt_history(scope_type,scope_id,old_body,new_body,updated_at,updated_by) VALUES (?,?,?,?,?,?)',(scope_type,scope_id,row[0] if row else None,body,now,str(updated_by)))
    await _upsert(db,'prompts',['scope_type','scope_id'],[scope_type,scope_id],{'body':body,'updated_at':now,'updated_by':str(updated_by)})
async def _permission_level(db,user_id,scope_type,scope_id):
    if scope_type=='global': cur=await db.execute("SELECT level FROM permissions WHERE user_id=? AND scope_type='global' AND scope_id IS NULL",(str(user_id),))
    else: cur=await db.execute('SELECT level FROM permissions WHERE user_id=? AND scope_type=? AND scope_id=?',(str(user_id),scope_type,str(scope_id)))
    row=await cur.fetchone(); return row[0] if row else None
async def check_permission(db,user_id,scope_type,scope_id,level):
    if is_root_operator(user_id): return True
    gl=await _permission_level(db,str(user_id),'global',None)
    if gl=='blocked': return False
    sl=None if scope_type=='global' else await _permission_level(db,str(user_id),scope_type,str(scope_id))
    if sl=='blocked': return False
    req=LEVELS[level]; return (sl is not None and LEVELS[sl]>=req) or (gl is not None and LEVELS[gl]>=req)
async def is_blocked_user(db,user_id,scope_type,scope_id):
    if is_root_operator(user_id): return False
    return (await _permission_level(db,user_id,'global',None)=='blocked') or (await _permission_level(db,user_id,scope_type,scope_id)=='blocked')
async def log_command(db,source,user_id,scope_type,scope_id,parsed,accepted,reason):
    await db.execute('INSERT INTO commands_log(source,user_id,scope_type,scope_id,command,args,accepted,reason,timestamp_utc) VALUES (?,?,?,?,?,?,?,?,?)',(source,str(user_id),scope_type,scope_id,parsed.get('command',''),json.dumps(parsed.get('args',[])),int(accepted),reason,utc_now())); await db.commit()
    await broadcast({'type':'command','data':{'source':source,'user_id':str(user_id),'scope_type':scope_type,'scope_id':scope_id,'command':parsed.get('command',''),'accepted':bool(accepted),'reason':reason}})
def _target(current_type,current_id,mod):
    if not mod: return current_type,current_id
    return ('global',None) if mod['type']=='global' else (current_type,mod['id'])
MEMORY_USAGE=(
    'Usage:\n'
    '!memory\n'
    '!memory help\n'
    '!memory add <discord_id|@user|#channel> <annotations> [tags=t1,t2]\n'
    '!memory update <#id|id> <annotations> [tags=t1,t2] [confidence=0.8]\n'
    '!memory delete <#id|id>\n'
    '!memory show all\n'
    '!memory show <discord_id|@user|#channel>\n'
    '!memory show <id>'
)
def memory_usage_error(message):
    return f'{message}\n\n{MEMORY_USAGE}'
def normalize_memory_discord_id(discord_id):
    return memory_contract.normalize_discord_id(discord_id)
def parse_memory_add_args(args):
    if len(args)>=4 and args[1] in {'user','channel','guild'}:
        return normalize_memory_discord_id(args[2]),args[3:]
    if len(args)>=3:
        return normalize_memory_discord_id(args[1]),args[2:]
    return None,None
def format_memory_rows(rows,label):
    if not rows:
        return f'No memories found for {label}.'
    lines=[]
    for row in rows:
        tags=', '.join(memory_contract.tags_from_db(row.get('array_tags'))) or '-'
        confidence=float(row.get('float_confidence') or 0)
        lines.append(f"#{row.get('int_memory_id')} discord:{row.get('str_discord_id')} tags={tags} confidence={confidence:.2f} created={row.get('str_created_utc')}")
        lines.append(str(row.get('str_annotations') or ''))
    return '\n'.join(lines)
def parse_hash_id(value):
    text=str(value or '').strip()
    if text.startswith('#'):
        text=text[1:]
    if not text.isdigit():
        raise ValueError('id must be numeric')
    return int(text)
def _memory_tags_arg(parts):
    tags=None; remaining=[]
    for part in parts:
        if isinstance(part,str) and part.startswith('tags='):
            tags=part[5:]
        else:
            remaining.append(part)
    return tags,remaining
def _memory_confidence_arg(parts):
    confidence=None; remaining=[]
    for part in parts:
        if isinstance(part,str) and part.startswith('confidence='):
            try:
                confidence=max(0.0,min(float(part.split('=',1)[1]),1.0))
            except ValueError:
                raise ValueError('confidence must be numeric')
        else:
            remaining.append(part)
    return confidence,remaining
DISCORD_SNOWFLAKE_RE=re.compile(r'(?<!\d)(\d{15,22})(?!\d)')
def memory_query_terms(text):
    seen=[]; lowered={'the','and','for','with','that','this','from','about','please','dirac','hello','dear'}
    for term in re.findall(r'[A-Za-z][A-Za-z0-9_-]{2,40}',str(text or '')):
        if term.lower() in lowered:
            continue
        if term not in seen:
            seen.append(term)
        if len(seen)>=6:
            break
    return seen
async def discord_identity_lookup(db,identifier,msg=None):
    snowflake=str(identifier or '').strip()
    for pattern in (r'<@!?(\d+)>',r'<#(\d+)>'):
        match=re.fullmatch(pattern,snowflake)
        if match:
            snowflake=match.group(1)
            break
    result={'id':snowflake,'kind':'unknown','names':[],'labels':[],'scope_refs':[]}
    if snowflake==ROOT_OPERATOR_ID:
        result['kind']='user'
        result['labels'].append('superuser .normal.man.')
    if msg is not None:
        author=getattr(msg,'author',None)
        if str(getattr(author,'id',''))==snowflake:
            result['kind']='user'
            for attr in ('display_name','global_name','name'):
                value=getattr(author,attr,None)
                if value and str(value) not in result['names']:
                    result['names'].append(str(value))
        channel=getattr(msg,'channel',None)
        if str(getattr(channel,'id',''))==snowflake:
            result['kind']='channel'
            for attr in ('name','display_name'):
                value=getattr(channel,attr,None)
                if value and str(value) not in result['names']:
                    result['names'].append(str(value))
        guild=getattr(msg,'guild',None)
        if str(getattr(guild,'id',''))==snowflake:
            result['kind']='guild'
            value=getattr(guild,'name',None)
            if value:
                result['names'].append(str(value))
    try:
        cur=await db.execute('SELECT author_name,COUNT(*) c,MAX(timestamp_utc) last_seen FROM messages WHERE author_id=? GROUP BY author_name ORDER BY c DESC,last_seen DESC LIMIT 5',(snowflake,))
        author_rows=await cur.fetchall()
        for name,_,_ in author_rows:
            if name and str(name) not in result['names']:
                result['names'].append(str(name))
        if author_rows and result['kind']=='unknown':
            result['kind']='user'
    except Exception:
        pass
    try:
        cur=await db.execute('SELECT scope_type,scope_id,COUNT(*) c,MAX(timestamp_utc) last_seen FROM messages WHERE scope_id=? GROUP BY scope_type,scope_id ORDER BY c DESC,last_seen DESC LIMIT 5',(snowflake,))
        scope_rows=await cur.fetchall()
        for scope_type,scope_id,count,last_seen in scope_rows:
            result['scope_refs'].append({'scope_type':scope_type,'scope_id':scope_id,'messages':count,'last_seen':last_seen})
        if scope_rows and result['kind']=='unknown':
            result['kind']='channel'
    except Exception:
        pass
    if not result['names'] and result['labels']:
        result['names']=list(result['labels'])
    return result
def identity_label(info):
    if not info:
        return None
    name=(info.get('labels') or info.get('names') or [None])[0]
    kind=info.get('kind') or 'unknown'
    if name:
        return f"{name} ({kind} <{info.get('id')}>)"
    return f"{kind} <{info.get('id')}>"
def generic_discord_ref_id(value):
    text=str(value or '').strip()
    for pattern in (r'<@!?(\d+)>',r'<#(\d+)>'):
        match=re.fullmatch(pattern,text)
        if match:
            return match.group(1)
    return text
def author_context_label(author_name,author_id,info=None):
    display=str(author_name or 'unknown')
    if not DISCORD_SNOWFLAKE_RE.fullmatch(str(author_id or '')):
        return f'{display} (<{author_id}>)'
    label=identity_label(info or {'id':str(author_id),'kind':'unknown'})
    if label:
        return f'{display} [{label}]'
    return f'{display} (<{author_id}>)'
async def annotate_discord_ids(db,text,msg=None):
    raw=str(text or '')
    ids=[]
    for found in DISCORD_SNOWFLAKE_RE.findall(raw):
        if found not in ids:
            ids.append(found)
        if len(ids)>=10:
            break
    if not ids:
        return raw
    mapped=await discord_identity_tags(db,ids)
    labels={}
    for snowflake in ids:
        info=await discord_identity_lookup(db,snowflake,msg)
        label=mapped.get(snowflake,{}).get('label') or identity_label(info)
        if label:
            labels[snowflake]=label
    def repl(match):
        value=match.group(1)
        label=labels.get(value)
        return f"{value} [{label}]" if label else value
    return DISCORD_SNOWFLAKE_RE.sub(repl,raw)
class MemoryManager:
    def __init__(self,db): self.db=db
    async def add(self,str_discord_id,str_annotations,array_tags=None,float_confidence=0.7,str_created_by='operator'):
        discord_id=normalize_memory_discord_id(str_discord_id)
        if not memory_contract.is_discord_id(discord_id):
            raise ValueError('str_discord_id must be a Discord snowflake id')
        tags=memory_contract.tags_to_db(array_tags,MAX_MEMORY_TAGS_LENGTH)
        cur=await self.db.execute(
            'INSERT INTO memories(str_discord_id,str_annotations,array_tags,float_confidence,str_created_utc,str_created_by) VALUES (?,?,?,?,?,?)',
            (discord_id,str(str_annotations or '')[:MAX_MEMORY_NOTE_LENGTH],tags,max(0.0,min(float(float_confidence if float_confidence is not None else 0.7),1.0)),utc_now(),str(str_created_by or 'operator'))
        )
        await self.db.commit(); return int(cur.lastrowid)
    async def search(self,str_discord_id=None,query=None,pending=None,limit=10):
        clauses=['m.int_superseded_by IS NULL']; params=[]; join=''
        if str_discord_id:
            normalized=normalize_memory_discord_id(str_discord_id)
            clauses.append('m.str_discord_id=?'); params.append(normalized)
        if pending is True: clauses.append("m.str_created_by='bot_pending'")
        elif pending is False: clauses.append("m.str_created_by!='bot_pending'")
        query_modes=[]
        if query:
            join='JOIN memories_fts f ON f.rowid=m.int_memory_id'
            match=memory_contract.fts5_query(query,'AND')
            if match: query_modes.append(match)
            fallback=memory_contract.fts5_query(query,'OR')
            if fallback and fallback!=match: query_modes.append(fallback)
        else:
            query_modes=[None]
        keys=['int_memory_id','str_discord_id','str_annotations','array_tags','float_confidence','str_created_utc','str_created_by','int_superseded_by']
        for match in query_modes:
            local_clauses=list(clauses); local_params=list(params)
            if match:
                local_clauses.append('memories_fts MATCH ?'); local_params.append(match)
            local_params.append(limit)
            try:
                cur=await self.db.execute(f"SELECT m.int_memory_id,m.str_discord_id,m.str_annotations,m.array_tags,m.float_confidence,m.str_created_utc,m.str_created_by,m.int_superseded_by FROM memories m {join} WHERE {' AND '.join(local_clauses)} ORDER BY m.int_memory_id DESC LIMIT ?",tuple(local_params))
            except aiosqlite.Error:
                return []
            rows=await cur.fetchall()
            if rows or not match:
                return [dict(zip(keys,r)) for r in rows]
        return []
    async def update(self,memory_id,new_annotations,new_tags=None,new_confidence=None,created_by=None):
        cur=await self.db.execute('SELECT str_discord_id,array_tags,float_confidence,str_created_by FROM memories WHERE int_memory_id=?',(memory_id,)); row=await cur.fetchone()
        if not row: raise KeyError('memory not found')
        nid=await self.add(row[0],new_annotations,new_tags if new_tags is not None else row[1],new_confidence if new_confidence is not None else row[2], created_by or row[3])
        await self.db.execute('UPDATE memories SET int_superseded_by=? WHERE int_memory_id=?',(nid,memory_id)); await self.db.commit(); return nid
    async def delete(self,memory_id):
        # Collect the full supersession chain so deleting the current memory also removes older replaced rows.
        # The recursive CTE walks from the selected memory back through all memories it superseded.
        cur=await self.db.execute('WITH RECURSIVE chain(id) AS (SELECT ? UNION ALL SELECT m.int_memory_id FROM memories m JOIN chain c ON m.int_superseded_by=c.id) SELECT id FROM chain',(int(memory_id),))
        to_delete=[int(r[0]) for r in await cur.fetchall()]
        if not to_delete:
            return
        # Delete older rows before their replacement to satisfy the superseded_by foreign key.
        sql_placeholders=','.join('?'*len(to_delete))
        # sql_placeholders is only "?" markers; actual memory IDs remain bound parameters in the tuple.
        delete_sql=f'DELETE FROM memories WHERE int_memory_id IN ({sql_placeholders})'
        await self.db.execute(delete_sql,tuple(reversed(to_delete)))
        await self.db.commit()
    async def approve(self,memory_id): await self.db.execute("UPDATE memories SET str_created_by='bot' WHERE int_memory_id=? AND str_created_by='bot_pending'",(memory_id,)); await self.db.commit()
    async def get(self,memory_id):
        cur=await self.db.execute('SELECT int_memory_id,str_discord_id,str_annotations,array_tags,float_confidence,str_created_utc,str_created_by,int_superseded_by FROM memories WHERE int_memory_id=?',(int(memory_id),))
        row=await cur.fetchone()
        if not row:
            return None
        keys=['int_memory_id','str_discord_id','str_annotations','array_tags','float_confidence','str_created_utc','str_created_by','int_superseded_by']
        return dict(zip(keys,row))
LEGACY_MEMORY_ARG_HINTS={
    'target_type':'target_type was removed; provide only str_discord_id.',
    'target_id':'target_id was renamed to str_discord_id.',
    'note':'note was renamed to str_annotations.',
    'tags':'tags was renamed to array_tags.',
    'confidence':'confidence was renamed to float_confidence.',
    'id':'id was renamed to int_memory_id for update/delete tools.',
    'limit':'limit was renamed to int_limit for memory_search.',
    'query':'query was renamed to str_query.',
    'q':'q was renamed to str_query.',
}
def legacy_memory_arg_issues(args):
    present=[LEGACY_MEMORY_ARG_HINTS[key] for key in LEGACY_MEMORY_ARG_HINTS if key in (args or {})]
    return [f'obsolete argument: {hint}' for hint in present]
async def memory_tool_add(db,args,created_by):
    args=args if isinstance(args,dict) else {}
    issues=legacy_memory_arg_issues(args)
    discord_id=normalize_memory_discord_id(args.get('str_discord_id'))
    annotations=str(args.get('str_annotations') or '').strip()
    if not discord_id:
        issues.append('str_discord_id missing: provide the Discord snowflake id as digits, for example "1471821513824014480".')
    elif not memory_contract.is_discord_id(discord_id):
        issues.append('str_discord_id invalid: use one Discord snowflake id as digits only; do not provide target_type/user/channel/guild.')
    if not annotations:
        issues.append('str_annotations missing: provide the memory text to preserve as a string.')
    tags,tag_error=memory_contract.parse_tags(args.get('array_tags'))
    if tag_error:
        issues.append(tag_error)
    confidence,confidence_error=memory_contract.parse_confidence(args.get('float_confidence'),0.7)
    if confidence_error:
        issues.append(confidence_error)
    if issues:
        return memory_contract.validation_error('memory_add',issues)
    async with db_write_tool_lock(db):
        mid=await MemoryManager(db).add(discord_id,annotations[:MAX_MEMORY_NOTE_LENGTH],tags,confidence,created_by)
    return {'ok':True,'int_memory_id':mid,'str_discord_id':discord_id,'engine':'MemoryManager'}
async def memory_tool_update(db,args,created_by):
    args=args if isinstance(args,dict) else {}
    issues=legacy_memory_arg_issues(args)
    try:
        memory_id=parse_hash_id(args.get('int_memory_id'))
    except ValueError:
        memory_id=None
        issues.append('int_memory_id missing or invalid: provide the numeric memory row id returned by memory_search, for example 343.')
    annotations=str(args.get('str_annotations') or '').strip()
    if not annotations:
        issues.append('str_annotations missing: provide the replacement memory text as a string.')
    tags=None
    if 'array_tags' in args:
        tags,tag_error=memory_contract.parse_tags(args.get('array_tags'))
        if tag_error:
            issues.append(tag_error)
    confidence=None
    if 'float_confidence' in args:
        confidence,confidence_error=memory_contract.parse_confidence(args.get('float_confidence'),0.7)
        if confidence_error:
            issues.append(confidence_error)
    if issues:
        return memory_contract.validation_error('memory_update',issues)
    async with db_write_tool_lock(db):
        try:
            new_id=await MemoryManager(db).update(memory_id,annotations[:MAX_MEMORY_NOTE_LENGTH],tags,confidence,created_by)
        except KeyError:
            return memory_contract.validation_error('memory_update',[f'int_memory_id not found: no memory row exists with id {memory_id}.'])
    return {'ok':True,'int_memory_id':memory_id,'int_new_memory_id':new_id,'engine':'MemoryManager'}
async def memory_tool_delete(db,args):
    args=args if isinstance(args,dict) else {}
    issues=legacy_memory_arg_issues(args)
    try:
        memory_id=parse_hash_id(args.get('int_memory_id'))
    except ValueError:
        issues.append('int_memory_id missing or invalid: provide the numeric memory row id returned by memory_search, for example 343.')
        return memory_contract.validation_error('memory_delete',issues)
    if issues:
        return memory_contract.validation_error('memory_delete',issues)
    async with db_write_tool_lock(db):
        cur=await db.execute('SELECT int_memory_id FROM memories WHERE int_memory_id=?',(memory_id,))
        if not await cur.fetchone():
            return memory_contract.validation_error('memory_delete',[f'int_memory_id not found: no memory row exists with id {memory_id}.'])
        await MemoryManager(db).delete(memory_id)
    return {'ok':True,'int_memory_id':memory_id,'engine':'MemoryManager'}
async def record_memory_event(db,event_type,scope_type,scope_id,role,content,user_id=None,user_name=None,metadata=None):
    if not content:
        return None
    data=rem.memory_event_dict(event_type,scope_type,scope_id,role,content,user_id,user_name,metadata)
    cur=await db.execute(
        'INSERT INTO memory_events(event_type,scope_type,scope_id,user_id,user_name,role,content,metadata_json,timestamp_utc) VALUES (?,?,?,?,?,?,?,?,?)',
        (data['event_type'],data['scope_type'],data['scope_id'],data['user_id'],data['user_name'],data['role'],data['content'],data['metadata_json'],utc_now())
    )
    await db.commit()
    return int(cur.lastrowid)
async def recent_memory_events(db,minutes=10,limit=200,include_dirac_blocks=False):
    try:
        minutes=max(1,min(int(minutes or 10),1440))
    except Exception:
        minutes=10
    since=utc_after_seconds(-minutes*60)
    lim=clamp_limit(limit,200,500)
    events=await _dict_rows(await db.execute(
        'SELECT id,event_type,scope_type,scope_id,user_id,user_name,role,content,metadata_json,timestamp_utc FROM memory_events WHERE timestamp_utc>=? ORDER BY id ASC LIMIT ?',
        (since,lim)
    ))
    return events if include_dirac_blocks else context_filters.filter_dirac_blocks_from_events(events)
async def discord_identity_tag(db,snowflake,label,kind=None,source='operator'):
    sid=rem.normalize_snowflake(snowflake)
    if not DISCORD_SNOWFLAKE_RE.fullmatch(sid):
        return {'ok':False,'error':'invalid_snowflake'}
    cleaned=rem.clean_label(label)
    if not cleaned:
        return {'ok':False,'error':'label_required'}
    now=utc_now()
    cur=await db.execute('SELECT created_at FROM discord_identity_map WHERE snowflake=?',(sid,))
    row=await cur.fetchone()
    await _upsert(db,'discord_identity_map',['snowflake'],[sid],{'label':cleaned,'kind':kind,'source':source,'created_at':row[0] if row else now,'updated_at':now})
    return {'ok':True,'id':sid,'label':cleaned,'kind':kind}
async def discord_identity_tags(db,ids):
    normalized=[rem.normalize_snowflake(i) for i in ids if rem.normalize_snowflake(i)]
    normalized=[i for i in normalized if DISCORD_SNOWFLAKE_RE.fullmatch(i)]
    if not normalized:
        return {}
    placeholders=','.join('?'*len(set(normalized)))
    cur=await db.execute(f'SELECT snowflake,label,kind,source,updated_at FROM discord_identity_map WHERE snowflake IN ({placeholders})',tuple(set(normalized)))
    return {row[0]:{'label':row[1],'kind':row[2],'source':row[3],'updated_at':row[4]} for row in await cur.fetchall()}
async def discord_grounding_payload(db,ids,msg=None,scope_type=None,scope_id=None,bot_user_id=None):
    ids=rem.collect_snowflakes(ids,scope_id,bot_user_id,ROOT_OPERATOR_ID,limit=40)
    tag_rows=await discord_identity_tags(db,ids)
    entities=[]
    for snowflake in ids:
        info=await discord_identity_lookup(db,snowflake,msg)
        mapped=tag_rows.get(snowflake,{})
        label=rem.preferred_identity_label(info,mapped.get('label'))
        kind=mapped.get('kind') or info.get('kind') or 'unknown'
        entities.append({
            'id':snowflake,
            'ref':rem.identity_ref(kind,snowflake),
            'kind':kind,
            'label':label,
            'names':info.get('names') or [],
            'scope_refs':info.get('scope_refs') or [],
            'mapped':bool(mapped),
        })
    return {
        'trusted_metadata':True,
        'bot_user_id':str(bot_user_id or ''),
        'root_operator_id':ROOT_OPERATOR_ID,
        'scope':{'scope_type':scope_type,'scope_id':scope_id},
        'instructions':'Use labels for reasoning. Use numeric Discord ids only when an exact output mention/channel/id is required. Call discord_ground for missing ids and discord_tag to persist a better label.',
        'entities':entities,
    }
async def discord_grounding_note(db,scope_type,scope_id,trigger_message=None,trigger_msg=None,bot_user_id=None):
    ids=[ROOT_OPERATOR_ID]
    if bot_user_id:
        ids.append(str(bot_user_id))
    if trigger_msg is not None:
        author=getattr(trigger_msg,'author',None)
        channel=getattr(trigger_msg,'channel',None)
        guild=getattr(trigger_msg,'guild',None)
        for value in (getattr(author,'id',None),getattr(channel,'id',None),getattr(guild,'id',None)):
            if value is not None:
                ids.append(str(value))
    ids.extend(rem.collect_snowflakes(trigger_message,scope_id,limit=20))
    try:
        cur=await db.execute('SELECT author_id,content FROM messages WHERE scope_type=? AND scope_id=? ORDER BY id DESC LIMIT 8',(scope_type,scope_id))
        for aid,content in await cur.fetchall():
            ids.append(str(aid))
            ids.extend(rem.collect_snowflakes(content,limit=10))
    except Exception:
        pass
    payload=await discord_grounding_payload(db,ids,trigger_msg,scope_type,scope_id,bot_user_id)
    return 'Auto-resolved Discord identity grounding. This is trusted metadata, not chat content:\n```json\n'+json.dumps(payload,ensure_ascii=False,indent=2)+'\n```'
async def discord_ground_tool(db,args,msg=None,scope_type=None,scope_id=None,bot_user_id=None):
    ids=[]
    ids.extend(args.get('ids') or [])
    ids.extend(rem.collect_snowflakes(args.get('text'),args.get('id'),args.get('user_id'),args.get('channel_id'),limit=40))
    if not ids:
        return {'ok':False,'error':'ids_or_text_required'}
    payload=await discord_grounding_payload(db,ids,msg,scope_type,scope_id,bot_user_id)
    return {'ok':True,'grounding':payload}
async def dyslexic_helper_tool(db,args):
    text=str(args.get('text') or '')
    if not text:
        return {'ok':False,'error':'text_required'}
    ids=rem.collect_snowflakes(text,args.get('ids') or [],limit=80)
    tags=await discord_identity_tags(db,ids)
    mapping={sid:row['label'] for sid,row in tags.items()}
    normalized,replacements=rem.replace_known_discord_refs(text,mapping)
    missing=[sid for sid in ids if sid not in mapping]
    return {'ok':True,'text':normalized,'replacements':replacements,'missing_ids':missing,'hint':'Call discord_tag for any missing id that needs a stable label.'}
async def system_prompt_for_scope(db,scope_type,scope_id):
    cur=await db.execute('SELECT body FROM prompts WHERE scope_type=? AND scope_id=?',(scope_type,scope_id)); row=await cur.fetchone()
    if row: return row[0]
    cur=await db.execute("SELECT body FROM prompts WHERE scope_type='global' AND scope_id IS NULL"); row=await cur.fetchone(); return row[0] if row else 'You are Dirac, a concise helpful assistant.'
async def assemble_context(db,scope_type,scope_id,trigger_message=None,limit=100,trigger_msg=None,bot_user_id=None):
    active_tools=await active_asset_names(db,'tool',scope_type,scope_id)
    system_parts=[
        tool_turns.TOOL_TURN_STATE_PLACEHOLDER,
        await discord_grounding_note(db,scope_type,scope_id,trigger_message,trigger_msg,bot_user_id),
        await system_prompt_for_scope(db,scope_type,scope_id),
        current_time_context_note('current_time' in active_tools),
        f"Discord identity note: numeric Discord snowflakes are identifiers, not ordinary numbers. The root operator/superuser is .normal.man. (<{ROOT_OPERATOR_ID}>). Use discord_id when an ID's owner, channel, guild, or nickname matters.",
    ]
    cur=await db.execute('SELECT rolling_summary,last_message_id FROM context_state WHERE scope_type=? AND scope_id=?',(scope_type,scope_id)); state=await cur.fetchone(); last=int(state[1]) if state and state[1] is not None else 0
    cur=await db.execute('SELECT DISTINCT author_id FROM messages WHERE scope_type=? AND scope_id=? AND is_command=0 ORDER BY id DESC LIMIT 20',(scope_type,scope_id)); authors=[r[0] for r in await cur.fetchall() if not await is_blocked_user(db,r[0],scope_type,scope_id)]
    mm=MemoryManager(db); mem=[]
    for m in await mm.search(scope_id,limit=5): mem.append(f"discord {scope_id}: {m['str_annotations']}")
    for a in authors[:10]:
        for m in await mm.search(a,limit=3): mem.append(f"discord {a}: {m['str_annotations']}")
    if trigger_message:
        for term in memory_query_terms(trigger_message):
            for m in await mm.search(None,term,limit=3):
                line=f"{m['str_discord_id']}: {m['str_annotations']}"
                if line not in mem:
                    mem.append(line)
    assets_note=await assets_context_note(db,scope_type,scope_id)
    if assets_note: system_parts.append(assets_note)
    out=[{'role':'system','content':'\n\n'.join(part for part in system_parts if part)}]
    if mem: out.append({'role':'user','content':'Dirac memory context about this channel and its participants:\n'+'\n'.join(mem)})
    task_note=await tasks_context_note(db,scope_type,scope_id)
    if task_note: out.append({'role':'user','content':'Dirac scheduled task context:\n'+task_note})
    if state and state[0]:
        summary=context_filters.strip_dirac_fenced_blocks(state[0])
        if summary:
            out.append({'role':'user','content':'Rolling conversation summary:\n'+summary})
    cur=await db.execute('SELECT author_id,author_name,content FROM messages WHERE scope_type=? AND scope_id=? AND is_command=0 AND id>? ORDER BY id ASC LIMIT ?',(scope_type,scope_id,last,limit))
    for aid,name,content in await cur.fetchall():
        if not await is_blocked_user(db,aid,scope_type,scope_id):
            content=context_filters.strip_dirac_fenced_blocks(content)
            if not content:
                continue
            info=await discord_identity_lookup(db,aid)
            out.append({'role':'user','content':f'{author_context_label(name,aid,info)}: {await annotate_discord_ids(db,content)}'})
    if trigger_message: out.append({'role':'user','content':await annotate_discord_ids(db,trigger_message)})
    return out
def describe_reasoning(mode):
    return mode if mode else 'inherit(api default)'
def normalize_scope_id(scope_type,scope_id):
    return None if scope_id in (None,'','*') else str(scope_id)
async def provider_params_for_profile(db,profile_id):
    return await provider_client_for_db(db).provider_params_for_profile(profile_id)
def valid_asset_name(name):
    return bool(re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}',str(name or '')))
MAX_SCHEDULE_MINUTES=10080
def parse_interval_minutes(text):
    m=re.fullmatch(r'(\d+)([mhd]?)',str(text or '').lower())
    if not m: return None
    value=int(m.group(1)); unit=m.group(2)
    if unit=='h': value*=60
    elif unit=='d': value*=1440
    value=max(1,value)
    if value>MAX_SCHEDULE_MINUTES: return None
    return value
def preview_text(text,limit=220):
    value=' '.join(str(text or '').split())
    if len(value)<=limit: return value
    return value[:max(0,limit-3)].rstrip()+'...'
async def _dict_rows(cur):
    data=await cur.fetchall(); keys=[c[0] for c in cur.description]
    return [dict(zip(keys,r)) for r in data]
def asset_scope_label(row_or_scope,scope_id=None):
    if isinstance(row_or_scope,dict):
        return f"{row_or_scope.get('scope_type')}:{row_or_scope.get('scope_id') or '*'}"
    return f"{row_or_scope}:{scope_id or '*'}"
def asset_token_id(token):
    text=str(token or '').strip()
    if text.startswith('#'):
        text=text[1:]
    return int(text) if text.isdigit() else None
def asset_sort_key(row):
    scope_rank=0 if row.get('scope_type')=='global' else 1
    return (str(row.get('name') or '').lower(),scope_rank,int(row.get('id') or 0))
async def list_agent_assets(db,asset_type,scope_type='global',scope_id=None,include_global=True,effective=False,enabled_only=False):
    if asset_type not in {'tool','skill'}: return []
    clauses=['asset_type=?']; params=[asset_type]
    scope_terms=[]
    if include_global:
        scope_terms.append("(scope_type='global' AND scope_id IS NULL)")
    if scope_type!='global' and scope_id not in (None,''):
        scope_terms.append('(scope_type=? AND scope_id=?)'); params.extend([scope_type,str(scope_id)])
    elif not include_global:
        scope_terms.append("(scope_type='global' AND scope_id IS NULL)")
    clauses.append('('+' OR '.join(scope_terms or ["scope_type='global' AND scope_id IS NULL"])+')')
    if enabled_only and not effective: clauses.append('enabled=1')
    cur=await db.execute(f"SELECT id,asset_type,name,description,body,scope_type,scope_id,enabled,is_builtin,schema_json,executor_name,snapshot_version,globally_disabled,created_by,created_at,updated_at FROM agent_assets WHERE {' AND '.join(clauses)} ORDER BY CASE WHEN scope_type='global' THEN 0 ELSE 1 END, name",tuple(params))
    rows=await _dict_rows(cur)
    if effective:
        for row in rows:
            row['stored_enabled']=int(row.get('enabled') or 0)
            row['stored_globally_disabled']=int(row.get('globally_disabled') or 0)
        global_disabled={r['name'] for r in rows if r['asset_type']=='tool' and r['scope_type']=='global' and int(r.get('globally_disabled') or 0)}
        by_name={}
        for row in rows:
            existing=by_name.get(row['name'])
            if existing and row.get('scope_type')!='global':
                for field in ('schema_json','executor_name','snapshot_version'):
                    if not row.get(field):
                        row[field]=existing.get(field)
                for field in ('description','body'):
                    if row.get(field) in (None,''):
                        row[field]=existing.get(field)
            by_name[row['name']]=row
        rows=list(by_name.values())
        if rows:
            asset_ids=[r['id'] for r in rows]
            placeholders=','.join('?'*len(asset_ids))
            bind_params=list(asset_ids)
            bind_sql=f"SELECT asset_id,scope_type,scope_id,enabled,reason FROM capability_bindings WHERE asset_id IN ({placeholders}) AND ((scope_type='global' AND scope_id IS NULL)"
            if scope_type!='global' and scope_id not in (None,''):
                bind_sql+=' OR (scope_type=? AND scope_id=?)'; bind_params.extend([scope_type,str(scope_id)])
            bind_sql+=') ORDER BY CASE WHEN scope_type=\'global\' THEN 0 ELSE 1 END'
            bindings=await _dict_rows(await db.execute(bind_sql,tuple(bind_params)))
            by_asset={}
            for b in bindings: by_asset[b['asset_id']]=b
            for row in rows:
                b=by_asset.get(row['id'])
                if b:
                    row['enabled']=int(b['enabled']); row['binding_reason']=b.get('reason'); row['binding_scope_type']=b.get('scope_type'); row['binding_scope_id']=b.get('scope_id')
        for row in rows:
            if row['name'] in global_disabled:
                row['enabled']=0
                row['globally_disabled']=1
                row['disabled_by_global']=1
        if enabled_only:
            rows=[r for r in rows if int(r.get('enabled') or 0)==1]
    rows.sort(key=asset_sort_key)
    return rows
async def active_asset_names(db,asset_type,scope_type,scope_id):
    return {r['name'] for r in await list_agent_assets(db,asset_type,scope_type,scope_id,True,True,True)}
def asset_usage(asset_type):
    label='tool' if asset_type=='tool' else 'skill'
    body='usage/body' if asset_type=='tool' else 'workflow/body'
    edit_fields='description|body|schema|executor|enabled|globally_disabled' if asset_type=='tool' else 'description|body|enabled'
    snapshot_usage=f'!{label} snapshot\n!{label} snapshot apply [version]\n!{label} fix\n' if asset_type=='tool' else ''
    return (
        f'Usage:\n'
        f'!{label}\n'
        f'!{label} help\n'
        f'!{label} add <name> <description>\n'
        f'!{label} show\n'
        f'!{label} show <#id|name>\n'
        f'!{label} edit <#id|name> {edit_fields} <value> [*|@id]\n'
        f'!{label} enable <#id|name> [*|@id]\n'
        f'!{label} disable <#id|name> [*|@id]\n'
        f'!{label} delete <#id|name> [*|@id]\n'
        f'{snapshot_usage}'
        f'\n'
        f'Panel edit fields expose description and {body}. Use the #id shown in lists, not the display order. Disabled entries are never shown to the model and cannot be used.'
    )
def format_asset_summary(asset_type,rows,scope_type,scope_id):
    label='tools' if asset_type=='tool' else 'skills'
    if not rows:
        return f'No {label} visible for {scope_type}:{scope_id or "*"}.'
    title=label.title()
    lines=[
        f'{title} visible for {scope_type}:{scope_id or "*"}',
        'Order: name A-Z. Use #ID or name in commands; there is no separate row index.',
        '',
        f"{'ID':<5} {'State':<12} {'Defined at':<28} {'Executor':<14} Name",
        f"{'-'*5} {'-'*12} {'-'*28} {'-'*14} {'-'*24}",
    ]
    for row in rows:
        state='on' if int(row.get('enabled') or 0) else ('off(global)' if int(row.get('globally_disabled') or 0) else 'off')
        executor=row.get('executor_name') or '-'
        scope=asset_scope_label(row)
        lines.append(f"#{row.get('id'):<4} {state:<12} {scope:<28} {executor:<14} {row.get('name')}")
        flags=[]
        if int(row.get('is_builtin') or 0): flags.append('builtin')
        if int(row.get('disabled_by_global') or 0): flags.append('disabled by global row')
        if flags:
            lines.append(f"      flags: {', '.join(flags)}")
        lines.append(f"      {preview_text(row.get('description'),140)}")
    lines.append('')
    lines.append('Legend: off(global) means the global row disables this tool everywhere; enable by name with * to lift it.')
    return '\n'.join(lines)
def format_asset_detail(asset_type,row):
    if not row:
        return 'not found'
    state='enabled' if int(row.get('enabled') or 0) else 'disabled'
    stored_enabled=row.get('stored_enabled')
    stored_globally_disabled=row.get('stored_globally_disabled')
    builtin='yes' if int(row.get('is_builtin') or 0) else 'no'
    lines=[
        f"#{row.get('id')} {row.get('name')}",
        f"type={asset_type}",
        f"defined_at={asset_scope_label(row)}",
        f"effective_state={state}",
        f"stored_state={'enabled' if int(stored_enabled if stored_enabled is not None else row.get('enabled') or 0) else 'disabled'}",
        f"builtin={builtin}",
        f"globally_disabled={'true' if int(stored_globally_disabled if stored_globally_disabled is not None else row.get('globally_disabled') or 0) else 'false'}",
        f"disabled_by_global={'true' if int(row.get('disabled_by_global') or 0) else 'false'}",
        f"executor={row.get('executor_name') or '-'}",
        f"snapshot_version={row.get('snapshot_version') or '-'}",
        f"created_by={row.get('created_by')}",
        f"created_at={row.get('created_at')}",
        f"updated_at={row.get('updated_at') or '-'}",
        '',
        'description:',
        str(row.get('description') or ''),
    ]
    if row.get('body'):
        lines.extend(['','body:',str(row.get('body'))])
    if row.get('schema_json'):
        lines.extend(['','schema:',str(row.get('schema_json'))])
    lines.extend(['','commands:',f"!{asset_type} show #{row.get('id')}",f"!{asset_type} enable {row.get('name')} [*|@id]",f"!{asset_type} disable {row.get('name')} [*|@id]"])
    return '\n'.join(lines)
async def assets_context_note(db,scope_type,scope_id):
    tools=await list_agent_assets(db,'tool',scope_type,scope_id,True,True,True)
    skills=await list_agent_assets(db,'skill',scope_type,scope_id,True,True,True)
    lines=[]
    if tools:
        lines.append('Active tools:')
        lines.extend(f"- {t['name']}: {t['description']}" for t in tools)
    if skills:
        lines.append('Active skills:')
        lines.extend(f"- {s['name']}: {s['description']}" for s in skills)
    if tools:
        lines.append('For Discord tool use, prefer native tool calls. If tool calls are unavailable, place directives on their own final lines like: DIRAC_TOOL react_emoji {"emoji":":thumbsup:","reason":"brief reason"}')
    return '\n'.join(lines)
async def save_agent_asset(db,asset_type,name,description,body,created_by,scope_type,scope_id,enabled=True,is_builtin=False,schema_json=None,executor_name=None,snapshot_version=None,globally_disabled=False):
    scope_id=normalize_scope_id(scope_type,scope_id)
    if asset_type not in {'tool','skill'} or not valid_asset_name(name) or not valid_scope_pair(scope_type,scope_id):
        raise ValueError('invalid asset')
    executor_name=normalize_executor_name(asset_type,executor_name)
    schema_json=normalize_tool_schema_json(schema_json,name) if asset_type=='tool' and schema_json not in (None,'') else None
    now=utc_now()
    cur=await db.execute('SELECT id,is_builtin FROM agent_assets WHERE asset_type=? AND name=? AND scope_type=? AND ((scope_id IS NULL AND ? IS NULL) OR scope_id=?)',(asset_type,name,scope_type,scope_id,scope_id))
    row=await cur.fetchone()
    if row:
        await db.execute('UPDATE agent_assets SET description=?, body=?, enabled=?, is_builtin=CASE WHEN is_builtin=1 OR ?=1 THEN 1 ELSE 0 END, schema_json=?, executor_name=?, snapshot_version=COALESCE(?,snapshot_version), globally_disabled=?, updated_at=? WHERE id=?',(description,body,int(bool(enabled)),int(bool(is_builtin)),schema_json,executor_name,snapshot_version,int(bool(globally_disabled)) if asset_type=='tool' and scope_type=='global' else 0,now,row[0]))
        await db.commit(); return int(row[0])
    cur=await db.execute('INSERT INTO agent_assets(asset_type,name,description,body,scope_type,scope_id,enabled,is_builtin,schema_json,executor_name,snapshot_version,globally_disabled,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(asset_type,name,description,body,scope_type,scope_id,int(bool(enabled)),int(bool(is_builtin)),schema_json,executor_name,snapshot_version,int(bool(globally_disabled)) if asset_type=='tool' and scope_type=='global' else 0,str(created_by),now,now))
    await db.commit(); return int(cur.lastrowid)
async def find_agent_asset(db,asset_type,token,scope_type='global',scope_id=None):
    token_id=asset_token_id(token)
    if token_id is not None:
        cur=await db.execute('SELECT * FROM agent_assets WHERE asset_type=? AND id=?',(asset_type,token_id))
        row=await cur.fetchone()
        if not row: return None
        data=dict(zip([c[0] for c in cur.description],row))
        target_sid=normalize_scope_id(scope_type,scope_id)
        row_sid=normalize_scope_id(data.get('scope_type'),data.get('scope_id'))
        if data.get('scope_type')==scope_type and row_sid==target_sid:
            return data
        if data.get('scope_type')=='global' and row_sid is None and scope_type!='global':
            return data
        return None
    rows=await list_agent_assets(db,asset_type,scope_type,scope_id,True,False,False)
    exact=[r for r in rows if r['name']==token and r['scope_type']==scope_type and (r['scope_id'] or None)==(scope_id or None)]
    if exact: return exact[-1]
    global_rows=[r for r in rows if r['name']==token and r['scope_type']=='global' and r['scope_id'] is None]
    return global_rows[-1] if global_rows else None
async def find_effective_agent_asset(db,asset_type,token,scope_type='global',scope_id=None):
    rows=await list_agent_assets(db,asset_type,scope_type,scope_id,True,True,False)
    token_id=asset_token_id(token)
    if token_id is not None:
        for row in rows:
            if int(row.get('id') or 0)==token_id:
                return row
        return None
    exact=[r for r in rows if r['name']==token]
    return exact[-1] if exact else None
async def remove_agent_asset(db,asset_type,token,scope_type,scope_id):
    row=await find_agent_asset(db,asset_type,token,scope_type,scope_id)
    if not row: return None
    # Scoped removal of a global asset creates a disabled override so global defaults stay intact.
    if row['scope_type']=='global' and scope_type!='global':
        await save_agent_asset(db,asset_type,row['name'],row['description'],row.get('body'), 'panel', scope_type, scope_id, enabled=False, is_builtin=bool(row.get('is_builtin')),schema_json=row.get('schema_json'),executor_name=row.get('executor_name'),snapshot_version=row.get('snapshot_version'))
        return row
    await db.execute('DELETE FROM agent_assets WHERE id=?',(row['id'],))
    await db.commit(); return row
async def set_agent_asset_enabled(db,asset_type,token,scope_type,scope_id,enabled):
    row=await find_agent_asset(db,asset_type,token,scope_type,scope_id)
    if not row: return None
    if row['scope_type']=='global' and scope_type!='global':
        new_id=await save_agent_asset(db,asset_type,row['name'],row['description'],row.get('body'),'panel',scope_type,scope_id,enabled=enabled,is_builtin=bool(row.get('is_builtin')),schema_json=row.get('schema_json'),executor_name=row.get('executor_name'),snapshot_version=row.get('snapshot_version'))
        return await find_agent_asset(db,asset_type,str(new_id),scope_type,scope_id)
    globally_disabled=0 if enabled else (1 if asset_type=='tool' and row.get('scope_type')=='global' else int(row.get('globally_disabled') or 0))
    await db.execute('UPDATE agent_assets SET enabled=?, globally_disabled=?, updated_at=? WHERE id=?',(int(bool(enabled)),globally_disabled,utc_now(),row['id']))
    await db.commit()
    return await find_agent_asset(db,asset_type,str(row['id']),scope_type,scope_id)
async def create_agent_task(db,kind,prompt,requested_by,source,scope_type,scope_id,backend='ollama',name=None,enabled=False,schedule_minutes=None,next_run_utc=None,max_runs=None,provider_id=None,model=None,parameter_profile_id=None,bot_entry_id=None,runtime_kind=None):
    now=utc_now()
    cur=await db.execute('INSERT INTO agent_tasks(kind,name,prompt,status,requested_by,source,scope_type,scope_id,backend,enabled,schedule_minutes,next_run_utc,run_count,max_runs,created_at,updated_at,provider_id,model,parameter_profile_id,bot_entry_id,runtime_kind,target_scope_type,target_scope_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(kind,name,prompt,'queued',str(requested_by),source,scope_type,scope_id,backend,int(bool(enabled)),schedule_minutes,next_run_utc,0,max_runs,now,now,provider_id,model,parameter_profile_id,bot_entry_id,runtime_kind,scope_type,scope_id))
    await db.commit(); return int(cur.lastrowid)
async def list_agent_tasks(db,scope_type=None,scope_id=None,recurring_only=False,limit=50):
    sql='SELECT id,kind,name,prompt,status,enabled,schedule_minutes,next_run_utc,last_run_utc,run_count,max_runs,requested_by,source,scope_type,scope_id,backend,result,error,created_at,updated_at,completed_at,provider_id,model,parameter_profile_id,bot_entry_id,runtime_kind FROM agent_tasks WHERE 1=1'
    params=[]
    if recurring_only: sql+=" AND kind='task'"
    if scope_type:
        sql+=' AND (scope_type=?'
        params.append(scope_type)
        if scope_type!='global' and scope_id not in (None,''):
            sql+=" OR (scope_type='global' AND scope_id IS NULL)"
        sql+=')'
    if scope_id not in (None,'') and scope_type!='global':
        sql+=' AND (scope_id=? OR scope_id IS NULL)'; params.append(str(scope_id))
    sql+=' ORDER BY id DESC LIMIT ?'; params.append(clamp_limit(limit,50,200))
    task_rows=await _dict_rows(await db.execute(sql,tuple(params)))
    for row in task_rows:
        row['last_run_local']=madrid_from_utc(row.get('last_run_utc'))
        row['next_run_local']=madrid_from_utc(row.get('next_run_utc'))
        row['timezone']=LOCAL_TIMEZONE_NAME
    return task_rows
def format_task_scope(row):
    return f"{row.get('scope_type')}:{row.get('scope_id') or '*'}"
def format_task_row(row,detail=False):
    enabled='enabled' if int(row.get('enabled') or 0) else 'disabled'
    interval=f"every {row.get('schedule_minutes')}m" if row.get('schedule_minutes') else 'manual'
    line=f"#{row.get('id')} {row.get('name') or '(unnamed)'} [{format_task_scope(row)}] {enabled} status={row.get('status')} {interval} runs={row.get('run_count') or 0} last={format_operator_time(row.get('last_run_utc'))} next={format_operator_time(row.get('next_run_utc'))}"
    details=[]
    if row.get('prompt'): details.append('prompt='+preview_text(row.get('prompt'),500 if detail else 160))
    if row.get('runtime_kind') and row.get('runtime_kind')!='default': details.append(f"runtime_kind={row.get('runtime_kind')}")
    if row.get('provider_id') or row.get('model'): details.append(f"provider_id={row.get('provider_id') or '-'} model={row.get('model') or '-'}")
    if row.get('result'): details.append('last_result='+preview_text(row.get('result'),1200 if detail else 220))
    if row.get('error'): details.append('last_error='+preview_text(row.get('error'),600 if detail else 220))
    if detail:
        details.extend([
            f"requested_by={row.get('requested_by')}",
            f"source={row.get('source')}",
            f"created_at={row.get('created_at')}",
            f"updated_at={row.get('updated_at')}",
            f"completed_at={row.get('completed_at') or '-'}",
        ])
    return line + (('\n  ' + '\n  '.join(details)) if details else '')
def format_task_list(rows,scope_type,scope_id):
    if not rows:
        return f'No recurring tasks visible for {scope_type}:{scope_id or "*"}.'
    header=f'Recurring tasks visible for {scope_type}:{scope_id or "*"}'
    return header+'\n'+'\n'.join(format_task_row(row) for row in rows)
def task_usage():
    return (
        'Usage:\n'
        '!task\n'
        '!task help\n'
        '!task add <name> every <5m|2h|1d> <prompt> [*|@id]\n'
        '!task show\n'
        '!task show <id|name>\n'
        '!task edit <id|name> name|prompt|schedule|enabled|model|provider_id|runtime_kind <value>\n'
        '!task run <id|name>\n'
        '!task enable <id|name>\n'
        '!task disable <id|name>\n'
        '!task delete <id|name>\n'
        '!task fix\n'
        '\n'
        'disable stops future runs and keeps history. delete permanently removes the task row. fix restores built-in task definitions from docs/builtin_tasks_snapshot.json.'
    )
def task_scope_filter(scope_type=None,scope_id=None):
    if scope_type and scope_type!='global' and scope_id not in (None,''):
        return "((scope_type=? AND scope_id=?) OR (scope_type='global' AND scope_id IS NULL))",[scope_type,str(scope_id)]
    return "(scope_type='global' AND scope_id IS NULL)",[]
async def tasks_context_note(db,scope_type,scope_id):
    rows=await list_agent_tasks(db,scope_type,scope_id,True,10)
    if not rows:
        return ''
    lines=['Scheduled tasks visible in this scope:']
    for row in rows:
        lines.append('- '+format_task_row(row).replace('\n  ','; '))
    lines.append('Use this task state when asked whether you have tasks, whether they ran, what they did, or when they run next.')
    return '\n'.join(lines)
async def find_agent_task(db,token,scope_type=None,scope_id=None):
    scope_sql,scope_params=task_scope_filter(scope_type,scope_id)
    if str(token).isdigit():
        cur=await db.execute(f"SELECT * FROM agent_tasks WHERE kind='task' AND id=? AND {scope_sql}",tuple([int(token)]+scope_params))
    else:
        cur=await db.execute(f"SELECT * FROM agent_tasks WHERE kind='task' AND name=? AND {scope_sql} ORDER BY CASE WHEN scope_type='global' THEN 0 ELSE 1 END DESC LIMIT 1",tuple([token]+scope_params))
    row=await cur.fetchone()
    if not row: return None
    return dict(zip([c[0] for c in cur.description],row))
async def deliver_task_result(client,scope_type,scope_id,text):
    if client is None or not text or scope_id in (None,''):
        return False
    channel=await discord_channel_for_id(client,scope_id)
    if channel is None:
        await db_log_failure('agent_tasks','task delivery channel not found',{'scope_type':scope_type,'scope_id':scope_id})
        return False
    return await send_discord_text(getattr(channel,'send',None),text)
def next_run_after_task_completion(task,advance_from_completion=True):
    enabled=task.get('enabled')
    schedule_minutes=task.get('schedule_minutes')
    run_count=int(task.get('run_count') or 0)
    max_runs=task.get('max_runs')
    if not enabled or not schedule_minutes:
        return None
    if max_runs is not None and run_count+1 >= int(max_runs):
        return None
    if advance_from_completion:
        return utc_after_minutes(schedule_minutes)
    return task.get('next_run_utc') or utc_after_minutes(schedule_minutes)
async def next_run_after_task_attempt(db,task,advance_from_completion=True):
    current=dict(task)
    try:
        cur=await db.execute('SELECT enabled,schedule_minutes,run_count,max_runs,next_run_utc FROM agent_tasks WHERE id=?',(task.get('id'),))
        row=await cur.fetchone()
        if row:
            current.update(dict(zip([c[0] for c in cur.description],row)))
    except Exception:
        current=dict(task)
    if advance_from_completion:
        return next_run_after_task_completion(current,True)
    if not current.get('enabled') or not current.get('schedule_minutes'):
        return None
    run_count=int(current.get('run_count') or 0)
    max_runs=current.get('max_runs')
    if max_runs is not None and run_count+1 >= int(max_runs):
        return None
    return current.get('next_run_utc') or task.get('next_run_utc') or utc_after_minutes(current.get('schedule_minutes'))


def runtime_task_cut_short_result(total_turns, *, ignored_tool_calls=0, tool_results=0, finalization_failed=False):
    reason='text-only finalization failed' if finalization_failed else 'model requested tools or returned no text during text-only finalization'
    return '\n'.join([
        '[DIRAC_RUNTIME_GENERATED_TASK_WARNING]',
        'THIS TASK EVENT WAS CUT SHORT BECAUSE THE MODEL FAILED TO GENERATE THE REQUIRED TEXT-ONLY REPLY IN THE LAST TURN.',
        'This is Dirac runtime text, not model-authored task output.',
        f'tool_round_budget={max(1,int(total_turns or 1))}',
        f'tool_results_recorded={max(0,int(tool_results or 0))}',
        f'ignored_tool_calls_in_text_only_finalization={max(0,int(ignored_tool_calls or 0))}',
        f'reason={reason}',
        '[/DIRAC_RUNTIME_GENERATED_TASK_WARNING]',
    ])


def runtime_task_ignored_finalization_tools_warning(total_turns, *, ignored_tool_calls=0, tool_results=0):
    return '\n'.join([
        '[DIRAC_RUNTIME_GENERATED_TASK_WARNING]',
        'THIS TASK RESULT INCLUDED TEXT, BUT THE MODEL ALSO REQUESTED TOOLS DURING TEXT-ONLY FINALIZATION.',
        'Dirac ignored those final tool calls. The text above is model-authored; this warning is runtime-authored.',
        f'tool_round_budget={max(1,int(total_turns or 1))}',
        f'tool_results_recorded={max(0,int(tool_results or 0))}',
        f'ignored_tool_calls_in_text_only_finalization={max(0,int(ignored_tool_calls or 0))}',
        '[/DIRAC_RUNTIME_GENERATED_TASK_WARNING]',
    ])

async def previous_task_run_audit(db,task_id,current_run_id=None):
    params=[task_id]
    where='task_id=? AND result IS NOT NULL AND result!=\'\''
    if current_run_id:
        where+=' AND id<?'
        params.append(current_run_id)
    cur=await db.execute(
        f'SELECT id,result,created_at,completed_at FROM agent_task_runs WHERE {where} ORDER BY id DESC LIMIT 1',
        tuple(params)
    )
    row=await cur.fetchone()
    if not row:
        return None
    return dict(zip([c[0] for c in cur.description],row))


async def run_agent_task(db,provider_client,task_id,client=None,trigger_source='scheduler',triggered_by='scheduler',advance_next_run_on_finish=True):
    cur=await db.execute('SELECT * FROM agent_tasks WHERE id=?',(task_id,))
    row=await cur.fetchone()
    if not row: return
    task=dict(zip([c[0] for c in cur.description],row))
    kind=task.get('kind'); name=task.get('name'); prompt=task.get('prompt'); scope_type=task.get('scope_type'); scope_id=task.get('scope_id'); backend=task.get('backend'); enabled=task.get('enabled'); schedule_minutes=task.get('schedule_minutes'); run_count=task.get('run_count'); max_runs=task.get('max_runs'); runtime_kind=task.get('runtime_kind') or 'default'
    await db.execute("UPDATE agent_tasks SET status='running',started_at=?,updated_at=? WHERE id=?",(utc_now(),utc_now(),task_id)); await db.commit()
    await broadcast({'type':'agent_task','data':{'id':task_id,'status':'running','kind':kind}})
    assets=[]; skills=[]; run_id=None; binding=None
    try:
        if provider_client is None:
            raise RuntimeError('Provider client is not configured')
        tool_info=json.dumps(local_agent_tools(),indent=2)
        #assets=await list_agent_assets(db,'tool',scope_type,scope_id,True,True,True)
        #skills=await list_agent_assets(db,'skill',scope_type,scope_id,True,True,True)
        try:
            binding=await provider_client.resolve_binding(scope_type,scope_id,task_id=task_id)
        except Exception:
            binding=None
        provider=(binding or {}).get('provider') or {}
        model=(binding or {}).get('model') or task.get('model') or getattr(provider_client,'default_model','')
        params=(binding or {}).get('params') or {}
        tool_schemas=await discord_tools_for_scope(db,scope_type,scope_id)
        started=utc_now()
        cur=await db.execute('INSERT INTO agent_task_runs(task_id,run_status,trigger_source,triggered_by,scope_type,scope_id,provider_id,provider_name,provider_type,model,params_json,instructions_preview,tools_json,skills_json,prompt,started_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(task_id,'running',trigger_source if trigger_source in {'scheduler','discord','panel','roxanne','manual'} else 'manual',str(triggered_by),scope_type,scope_id,provider.get('id'),provider.get('name'),provider.get('provider_type'),model,json.dumps(params),preview_text(await system_prompt_for_scope(db,scope_type,scope_id),500),json.dumps(assets),json.dumps(skills),prompt,started,started))
        await db.commit(); run_id=int(cur.lastrowid)
        messages=[
            {'role':'system','content':(rem.rem_task_system_prompt() if runtime_kind=='rem' else tool_turns.TOOL_TURN_STATE_PLACEHOLDER+'\n\nYou are a root-only Dirac sub-agent. Produce a concrete, auditable result for the operator. You may propose tools, skills, research steps, and code changes, but never reveal secrets. Keep outputs actionable and bounded. Dirac renders the current dynamic tool-round banner at provider-call time; treat that current banner as authoritative.')+'\n\n'+current_time_context_note(False)},
            {'role':'user','content':f'Task kind: {kind}\nTask name: {name or ""}\nBackend requested: {backend}\nInstalled local agent CLIs:\n{tool_info}\n\nTask:\n{prompt}'},
            rem.rem_tool_inventory_message(tool_schemas,skills),
        ]
        if runtime_kind=='rem':
            messages.extend(rem.short_term_slice_messages(await recent_memory_events(db,10,250),await previous_task_run_audit(db,task_id,run_id)))
        tool_created_by=f'task:{name or task_id}:run:{run_id}' if run_id else f'task:{name or task_id}'
        tool_run=await run_model_with_scoped_tools(db,provider_client,messages,tool_schemas,scope_type,scope_id,'task','panel','task',model=model,params=params,task_id=task_id,task_run_id=run_id,max_tool_turns=TASK_TOOL_TURN_LIMIT,tool_turn_label='REM' if runtime_kind=='rem' else 'TASK',rem_mode=runtime_kind=='rem',tool_created_by=tool_created_by)
        result=tool_run.get('reply') or ''
        ignored_finalization_tool_calls=tool_run.get('finalization_ignored_tool_calls') or 0
        if not result:
            fallback_kwargs={
                'ignored_tool_calls':ignored_finalization_tool_calls,
                'tool_results':len(tool_run.get('results',[])),
                'finalization_failed':bool(tool_run.get('finalization_failed')),
            }
            result=rem.rem_cut_short_result(TASK_TOOL_TURN_LIMIT,**fallback_kwargs) if runtime_kind=='rem' else runtime_task_cut_short_result(TASK_TOOL_TURN_LIMIT,**fallback_kwargs)
        elif ignored_finalization_tool_calls:
            warning_kwargs={
                'ignored_tool_calls':ignored_finalization_tool_calls,
                'tool_results':len(tool_run.get('results',[])),
            }
            warning=rem.rem_ignored_finalization_tools_warning(TASK_TOOL_TURN_LIMIT,**warning_kwargs) if runtime_kind=='rem' else runtime_task_ignored_finalization_tools_warning(TASK_TOOL_TURN_LIMIT,**warning_kwargs)
            result=result.rstrip()+'\n\n'+warning
        completed=utc_now(); next_run=await next_run_after_task_attempt(db,task,advance_next_run_on_finish)
        await db.execute("UPDATE agent_tasks SET status='completed',result=?,error=NULL,completed_at=?,last_run_utc=?,next_run_utc=?,run_count=run_count+1,updated_at=?,provider_id=COALESCE(provider_id,?),model=COALESCE(model,?) WHERE id=?",(result,completed,completed,next_run,completed,provider.get('id'),model,task_id))
        if run_id:
            await db.execute("UPDATE agent_task_runs SET run_status='completed',result=?,completed_at=? WHERE id=?",(result,completed,run_id))
        await db.commit()
        await record_memory_event(db,'task_result',scope_type,scope_id,'task',result,'task',name or f'task-{task_id}',{'task_id':task_id,'run_id':run_id,'tool_results':len(tool_run.get('results',[]))})
        if kind=='task' and client is not None and result:
            await deliver_task_result(client,scope_type,scope_id,result)
        await broadcast({'type':'agent_task','data':{'id':task_id,'status':'completed','kind':kind}})
    except asyncio.CancelledError:
        completed=utc_now(); next_run=await next_run_after_task_attempt(db,task,advance_next_run_on_finish)
        try:
            if run_id:
                await db.execute("UPDATE agent_task_runs SET run_status='failed',error=?,completed_at=? WHERE id=?",('cancelled',completed,run_id))
            await db.execute("UPDATE agent_tasks SET status='failed',error=?,completed_at=?,last_run_utc=?,next_run_utc=?,run_count=run_count+1,updated_at=? WHERE id=?",('cancelled',completed,completed,next_run,completed,task_id)); await db.commit()
            await broadcast({'type':'agent_task','data':{'id':task_id,'status':'failed','kind':kind,'error':'cancelled'}})
        except Exception:
            pass
        raise
    except Exception as e:
        completed=utc_now(); next_run=await next_run_after_task_attempt(db,task,advance_next_run_on_finish)
        if not run_id:
            cur=await db.execute('INSERT INTO agent_task_runs(task_id,run_status,trigger_source,triggered_by,scope_type,scope_id,prompt,error,completed_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)',(task_id,'failed',trigger_source if trigger_source in {'scheduler','discord','panel','roxanne','manual'} else 'manual',str(triggered_by),scope_type,scope_id,prompt,str(e),completed,completed))
            run_id=int(cur.lastrowid)
        else:
            await db.execute("UPDATE agent_task_runs SET run_status='failed',error=?,completed_at=? WHERE id=?",(str(e),completed,run_id))
        await db.execute("UPDATE agent_tasks SET status='failed',error=?,completed_at=?,last_run_utc=?,next_run_utc=?,run_count=run_count+1,updated_at=? WHERE id=?",(str(e),completed,completed,next_run,completed,task_id)); await db.commit()
        await broadcast({'type':'agent_task','data':{'id':task_id,'status':'failed','kind':kind,'error':str(e)}})
        raise
async def reconcile_orphan_agent_tasks(db):
    """Recover tasks left in 'running' or 'queued' across process restarts.

    Any such row at startup is necessarily orphaned (no in-process coroutine
    exists for it on a fresh boot). Mark it failed with next_run_utc=now so the
    scheduler can pick it up again on the next tick — losing one run is much
    better than starving the task forever because of a stuck status."""
    now=utc_now()
    cur=await db.execute("SELECT id,enabled,schedule_minutes FROM agent_tasks WHERE status IN ('running','queued')")
    rows=await cur.fetchall()
    if not rows:
        return 0
    for task_id,enabled,schedule_minutes in rows:
        next_run=now if enabled and schedule_minutes else None
        await db.execute("UPDATE agent_tasks SET status='failed',error=COALESCE(error,'orphaned: process restarted while task was running'),completed_at=?,last_run_utc=COALESCE(last_run_utc,?),next_run_utc=?,updated_at=? WHERE id=?",(now,now,next_run,now,task_id))
    await db.commit()
    try:
        await app_log('warn','agent_tasks','reclaimed orphan tasks at startup',{'count':len(rows),'ids':[int(r[0]) for r in rows]})
    except Exception:
        pass
    return len(rows)
async def schedule_agent_task(db,provider_client,task_id,client=None,trigger_source='scheduler',triggered_by='scheduler',advance_next_run_on_finish=True,*,tg:asyncio.TaskGroup):
    if runtime_control.background_suspended():
        return False
    task=tg.create_task(run_agent_task(db,provider_client,task_id,client=client,trigger_source=trigger_source,triggered_by=triggered_by,advance_next_run_on_finish=advance_next_run_on_finish))
    task_set=getattr(app.state,'agent_run_tasks',None) if 'app' in globals() else None
    if task_set is not None:
        task_set.add(task)
        task.add_done_callback(lambda done: task_set.discard(done))
    return True
async def agent_task_scheduler(db,provider_client,client=None,poll_interval_s=30,*,tg:asyncio.TaskGroup):
    while True:
        try:
            if runtime_control.background_suspended():
                await asyncio.sleep(poll_interval_s)
                continue
            now=utc_now()
            cur=await db.execute("SELECT id,schedule_minutes FROM agent_tasks WHERE kind='task' AND enabled=1 AND schedule_minutes IS NOT NULL AND (max_runs IS NULL OR run_count<max_runs) AND (next_run_utc IS NULL OR next_run_utc<=?) ORDER BY COALESCE(next_run_utc,created_at) ASC,id ASC LIMIT 100",(now,))
            due=await cur.fetchall()
            if due:
                task_id,schedule_minutes=random.choice(due)
                next_run=utc_after_minutes(schedule_minutes)
                claim_cur=await db.execute("UPDATE agent_tasks SET status='running',next_run_utc=?,started_at=?,updated_at=? WHERE id=? AND kind='task' AND enabled=1 AND schedule_minutes IS NOT NULL AND (max_runs IS NULL OR run_count<max_runs) AND (next_run_utc IS NULL OR next_run_utc<=?)",(next_run,now,now,task_id,now))
                await db.commit()
                await app_log('debug','agent_tasks','scheduled recurring task',{'task_id':task_id,'due_count':len(due),'next_run_utc':next_run})
                if getattr(claim_cur,'rowcount',0):
                    scheduled=await schedule_agent_task(db,provider_client,task_id,client=client,trigger_source='scheduler',triggered_by='scheduler',advance_next_run_on_finish=False,tg=tg)
                    await app_log('debug','agent_tasks','schedule_agent_task called',{'task_id':task_id,'due_count':len(due),'scheduled':scheduled})
                    if not scheduled:
                        failed=utc_now()
                        await db.execute("UPDATE agent_tasks SET status='failed',error=?,completed_at=?,last_run_utc=?,updated_at=? WHERE id=?",('scheduler could not launch task runner',failed,failed,failed,task_id))
                        await db.commit()
        except Exception as e:
            await db_log_error('agent_tasks','task scheduler failed',e)
            raise
        await asyncio.sleep(poll_interval_s)
async def reset_context_watermarks(db):
    cur=await db.execute('SELECT scope_type,scope_id,MAX(id) FROM messages GROUP BY scope_type,scope_id')
    for scope_type,scope_id,last_id in await cur.fetchall():
        await _upsert(db,'context_state',['scope_type','scope_id'],[scope_type,scope_id],{'last_wake_utc':utc_now(),'rolling_summary':None,'last_message_id':last_id or 0})
async def emergency_stop_runtime(db,seconds,reason):
    await reset_context_watermarks(db)
    task_set=getattr(app.state,'agent_run_tasks',set()) if 'app' in globals() else set()
    for task in list(task_set):
        task.cancel()
    news_task=getattr(app.state,'news_task',None) if 'app' in globals() else None
    if news_task is not None:
        news_task.cancel()
        app.state.news_task=None
    now=utc_now()
    cur=await db.execute("SELECT id,enabled,schedule_minutes FROM agent_tasks WHERE status IN ('running','queued')")
    for row in await cur.fetchall():
        task_id,enabled,schedule_minutes=row
        next_run=None
        if enabled and schedule_minutes:
            next_run=utc_after_seconds(int(seconds)+int(schedule_minutes)*60)
        await db.execute("UPDATE agent_tasks SET status='failed',error=?,completed_at=?,last_run_utc=?,next_run_utc=?,updated_at=? WHERE id=?",(reason,now,now,next_run,now,task_id))
    await db.commit()
async def log_runtime_hold(level,message,detail):
    try:
        await app_log(level,'bot',message,detail,force_console=True)
    except Exception:
        pass
async def request_process_exit(code=0,delay_s=0.25,*,tg:asyncio.TaskGroup):
    exit_func=getattr(app.state,'process_exit',None) if 'app' in globals() else None
    if exit_func is None:
        exit_func=os._exit
    async def later():
        await asyncio.sleep(delay_s)
        exit_func(code)
    tg.create_task(later())
@asynccontextmanager
async def maybe_channel_typing(channel,scope_type=None,scope_id=None,reason='wake'):
    typing=getattr(channel,'typing',None) if channel is not None else None
    trigger_typing=getattr(channel,'trigger_typing',None) if channel is not None else None
    cm=None
    if callable(typing):
        try: cm=typing()
        except Exception: cm=None
    entered=False
    if cm is not None and hasattr(cm,'__aenter__') and hasattr(cm,'__aexit__'):
        try:
            await cm.__aenter__(); entered=True
        except Exception:
            entered=False
    keepalive_stop=asyncio.Event()
    if entered or callable(trigger_typing):
        await app_log('trace','discord','typing indicator started',{'reason':reason,'entered_context':entered,'has_trigger_typing':callable(trigger_typing)},scope_type,scope_id)
        if callable(trigger_typing):
            try:
                await trigger_typing()
            except Exception as e:
                await app_log('debug','discord','typing indicator initial refresh failed',{'error':type(e).__name__,'reason':reason},scope_type,scope_id)
    async def keepalive():
        while not keepalive_stop.is_set():
            try:
                await asyncio.wait_for(keepalive_stop.wait(),timeout=4.0)
                break
            except asyncio.TimeoutError:
                pass
            if callable(trigger_typing):
                try:
                    await trigger_typing()
                    await app_log('trace','discord','typing indicator refreshed',{'reason':reason},scope_type,scope_id)
                except Exception as e:
                    await app_log('debug','discord','typing indicator refresh failed',{'error':type(e).__name__,'reason':reason},scope_type,scope_id)
    try:
        if entered or callable(trigger_typing):
            async with asyncio.TaskGroup() as tg:
                tg.create_task(keepalive())
                try:
                    yield
                finally:
                    keepalive_stop.set()
        else:
            yield
    finally:
        if entered:
            try: await cm.__aexit__(None,None,None)
            except Exception: pass
        if entered or callable(trigger_typing):
            await app_log('trace','discord','typing indicator stopped',{'reason':reason},scope_type,scope_id)
DIRAC_TOOL_DIRECTIVE_RE=re.compile(r'(?m)^DIRAC_TOOL\s+([A-Za-z_][\w.-]*)\s+(\{.*\})\s*$')
def extract_tool_call(call):
    fn=call.get('function',{}) if isinstance(call,dict) else {}
    args=fn.get('arguments',{}) if isinstance(fn,dict) else {}
    if isinstance(args,str):
        try: args=json.loads(args)
        except Exception: args={}
    return (fn.get('name') or (call.get('name') if isinstance(call,dict) else None)), args if isinstance(args,dict) else {}
def extract_tool_directives(text):
    calls=[]
    def repl(match):
        name=match.group(1); raw=match.group(2)
        try: args=json.loads(raw)
        except Exception: args={}
        calls.append({'function':{'name':name,'arguments':args}})
        return ''
    cleaned=DIRAC_TOOL_DIRECTIVE_RE.sub(repl,text or '').strip()
    return cleaned,calls
def tool_schema_from_row(row):
    raw=row.get('schema_json')
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None
def model_response_content_and_calls(resp):
    if isinstance(resp,dict):
        msg_obj=resp.get('message') or {}
        content=msg_obj.get('content','') or resp.get('response','') or resp.get('content','') or ''
        calls=msg_obj.get('tool_calls') or resp.get('tool_calls') or []
        return content,calls
    return str(resp or ''),[]
async def discord_tools_for_scope(db,scope_type,scope_id):
    schemas=[]
    for row in await list_agent_assets(db,'tool',scope_type,scope_id,True,True,True):
        if not row.get('executor_name'):
            continue
        schema=tool_schema_from_row(row)
        if schema:
            schemas.append(schema)
    return schemas
async def active_tool_rows_by_name(db,scope_type,scope_id):
    rows=await list_agent_assets(db,'tool',scope_type,scope_id,True,True,True)
    return {row['name']:row for row in rows}
def public_ip_allowed(ip):
    return bool(getattr(ip,'is_global',False)) and not any((ip.is_private,ip.is_loopback,ip.is_link_local,ip.is_multicast,ip.is_reserved,ip.is_unspecified))
async def validate_public_web_url(url):
    parsed=urlparse(str(url or '').strip())
    if parsed.scheme not in {'http','https'}:
        return None,'unsupported_scheme'
    if not parsed.hostname:
        return None,'missing_hostname'
    host=parsed.hostname.strip().lower()
    if host in {'localhost','0.0.0.0'} or host.endswith('.localhost'):
        return None,'blocked_host'
    port=parsed.port or (443 if parsed.scheme=='https' else 80)
    ips=[]
    try:
        ips=[ipaddress.ip_address(host.strip('[]'))]
    except ValueError:
        try:
            infos=await asyncio.to_thread(socket.getaddrinfo,host,port,type=socket.SOCK_STREAM)
            ips=[ipaddress.ip_address(info[4][0]) for info in infos]
        except Exception:
            return None,'resolve_failed'
    if not ips or any(not public_ip_allowed(ip) for ip in ips):
        return None,'blocked_private_network'
    return parsed.geturl(),None
def clean_fetched_text(content,content_type):
    text=content
    if 'html' in str(content_type or '').lower() or '<html' in text[:500].lower():
        text=re.sub(r'(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>',' ',text)
        text=re.sub(r'(?is)<br\s*/?>','\n',text)
        text=re.sub(r'(?is)</(p|div|li|h[1-6]|tr)>','\n',text)
        text=re.sub(r'(?s)<[^>]+>',' ',text)
    text=html.unescape(text)
    return re.sub(r'[ \t\r\f\v]+',' ',re.sub(r'\n\s*\n+','\n\n',text)).strip()
async def run_web_fetch(url,reason):
    if len(str(reason or '').strip())<6:
        return {'ok':False,'error':'missing_reason'}
    current=str(url or '').strip()
    redirects=0
    headers={'user-agent':f'Dirac/{APP_VERSION} web_fetch','accept':'text/html,text/plain,application/json;q=0.8,*/*;q=0.5'}
    async with httpx.AsyncClient(timeout=WEB_FETCH_TIMEOUT_S,trust_env=False) as client:
        while redirects<=3:
            current,err=await validate_public_web_url(current)
            if err:
                return {'ok':False,'error':err,'url':str(url or '')[:500]}
            try:
                async with client.stream('GET',current,headers=headers,follow_redirects=False) as resp:
                    if resp.status_code in {301,302,303,307,308} and resp.headers.get('location'):
                        current=urljoin(current,resp.headers['location'])
                        redirects+=1
                        continue
                    chunks=[]; total=0; truncated=False
                    async for chunk in resp.aiter_bytes():
                        total+=len(chunk)
                        if total>WEB_FETCH_MAX_BYTES:
                            keep=max(0,len(chunk)-(total-WEB_FETCH_MAX_BYTES))
                            if keep: chunks.append(chunk[:keep])
                            truncated=True
                            break
                        chunks.append(chunk)
                    data=b''.join(chunks)
                    encoding=resp.encoding or 'utf-8'
                    text=data.decode(encoding,errors='replace')
                    cleaned=clean_fetched_text(text,resp.headers.get('content-type',''))
                    if len(cleaned)>WEB_FETCH_TEXT_LIMIT:
                        cleaned=cleaned[:WEB_FETCH_TEXT_LIMIT].rsplit(' ',1)[0]+'\n[trimmed]'
                        truncated=True
                    return {'ok':200 <= resp.status_code < 400,'status_code':resp.status_code,'final_url':str(resp.url),'content_type':resp.headers.get('content-type',''),'bytes_read':len(data),'truncated':truncated,'text':cleaned}
            except Exception as e:
                return {'ok':False,'error':type(e).__name__,'url':current}
    return {'ok':False,'error':'too_many_redirects','url':str(url or '')[:500]}
def tool_call_id(call):
    return call.get('id') if isinstance(call,dict) else None
def tool_call_summary(call,index=0):
    name,args=extract_tool_call(call)
    return {'index':index,'id':tool_call_id(call),'name':name,'args':args}
def tool_log_payload(index,name,args,executor=None,result=None,elapsed_ms=None,error=None):
    payload={'index':index,'tool':name,'executor':executor,'args':args}
    if result is not None:
        payload['result']=result
    if elapsed_ms is not None:
        payload['elapsed_ms']=elapsed_ms
    if error is not None:
        payload['error']=error
    return payload
async def run_discord_tool_calls(db,msg,tool_calls,scope_type,scope_id,author_id,bot_user_id,tool_created_by=None):
    calls=list(tool_calls or [])
    active=await active_tool_rows_by_name(db,scope_type,scope_id)
    await app_log('trace','discord_tool','tool batch start',{'count':len(calls),'parallel_limit':TOOL_CALL_PARALLEL_LIMIT,'tools':[extract_tool_call(call)[0] for call in calls]},scope_type,scope_id)
    started=time.perf_counter()
    semaphore=asyncio.Semaphore(TOOL_CALL_PARALLEL_LIMIT)
    async def run_one(index,call):
        name,args=extract_tool_call(call)
        if name=='silence_user': name='silencer'
        row=active.get(name)
        executor=row.get('executor_name') if row else None
        await app_log('trace','discord_tool','tool call start',tool_log_payload(index,name,args,executor),scope_type,scope_id)
        call_started=time.perf_counter()
        suppress=False
        try:
            if not row:
                result={'tool':name,'ok':False,'error':'tool_not_enabled_or_unknown','needs_model_followup':True,'available_tools':sorted(active.keys())[:40]}
            elif not executor:
                result={'tool':name,'ok':False,'error':'tool_not_executable'}
            elif executor=='react_emoji':
                emoji=str(args.get('emoji') or '\U0001f44d')[:64]
                add=getattr(msg,'add_reaction',None)
                if callable(add):
                    try:
                        await add(emoji)
                        result={'tool':name,'ok':True,'emoji':emoji,'requires_reply':True}
                    except Exception as e:
                        await db_log_error('discord_tool','react_emoji failed',e)
                        result={'tool':name,'ok':False,'error':'reaction_failed'}
                else:
                    result={'tool':name,'ok':False,'error':'message_has_no_add_reaction'}
            elif executor=='silencer':
                reason=str(args.get('reason') or '').strip()
                if len(reason)<12:
                    result={'tool':name,'ok':False,'error':'missing_justification'}
                else:
                    # Ignore model-supplied user identifiers to prevent arbitrary-user silencing;
                    # only the triggering author can be blocked.
                    target=str(author_id)
                    protected=target==str(bot_user_id) or target in root_operator_ids()
                    if protected:
                        result={'tool':name,'ok':False,'error':'protected_user'}
                    else:
                        await _upsert(db,'permissions',['user_id','scope_type','scope_id'],[target,scope_type,scope_id],{'level':'blocked','added_at':utc_now()})
                        suppress=True
                        result={'tool':name,'ok':True,'user_id':target,'scope_type':scope_type,'scope_id':scope_id,'reason':reason}
            elif executor=='current_time':
                result={'tool':name,'ok':True,'needs_model_followup':True,'time':current_time_payload()}
            elif executor=='web_fetch':
                result=await run_web_fetch(args.get('url'),args.get('reason'))
                result.update({'tool':name,'needs_model_followup':True})
                if not result.get('ok'):
                    await db_log_failure('discord_tool','web_fetch failed',{'error':result.get('error'),'url':result.get('url') or args.get('url')})
            elif executor=='web_search':
                query=str(args.get('query') or '').strip()
                if not query:
                    result={'tool':name,'ok':False,'error':'query_required'}
                else:
                    limit=clamp_limit(args.get('limit'),5,8)
                    result=await roxanne_mod.web_search(query,limit)
                    result.update({'tool':name,'ok':not bool(result.get('error')),'needs_model_followup':True})
            elif executor=='memory_search':
                if not args:
                    result=memory_contract.validation_error('memory_search',['No arguments supplied. Provide str_query and/or str_discord_id, plus optional int_limit.'])
                    result.update({'tool':name})
                else:
                    issues=legacy_memory_arg_issues(args)
                    query=str(args.get('str_query') or '').strip() or None
                    discord_id=normalize_memory_discord_id(args.get('str_discord_id')) if args.get('str_discord_id') else None
                    if not query and not discord_id:
                        issues.append('str_query or str_discord_id required: provide search text, one Discord snowflake id, or both.')
                    elif discord_id and not memory_contract.is_discord_id(discord_id):
                        issues.append('str_discord_id invalid: use one Discord snowflake id as digits only.')
                    if issues:
                        result=memory_contract.validation_error('memory_search',issues)
                        result.update({'tool':name})
                    else:
                        limit=clamp_limit(args.get('int_limit'),10,20)
                        rows=await MemoryManager(db).search(discord_id,query,None,limit)
                        result={'tool':name,'ok':True,'needs_model_followup':True,'engine':'MemoryManager','str_query':query,'str_discord_id':discord_id,'rows':rows}
            elif executor in {'memory_add','memory_update','memory_delete'}:
                if not is_root_operator(author_id):
                    result={'tool':name,'ok':False,'error':'root_only'}
                else:
                    if executor=='memory_add':
                        result=await memory_tool_add(db,args,tool_created_by or str(author_id))
                    elif executor=='memory_update':
                        result=await memory_tool_update(db,args,tool_created_by or str(author_id))
                    else:
                        result=await memory_tool_delete(db,args)
                    result.update({'tool':name,'needs_model_followup':True})
            elif executor=='discord_ground':
                result=await discord_ground_tool(db,args,msg,scope_type,scope_id,bot_user_id)
                result.update({'tool':name,'needs_model_followup':True})
            elif executor=='discord_tag':
                result=await discord_identity_tag(db,args.get('id') or args.get('snowflake'),args.get('label'),args.get('kind'),str(author_id))
                result.update({'tool':name,'needs_model_followup':True,'warning':'There is no delete tool for discord_identity_map; calling discord_tag again replaces the label.'})
            elif executor=='dyslexic_helper':
                result=await dyslexic_helper_tool(db,args)
                result.update({'tool':name,'needs_model_followup':True})
            elif executor=='discord_id':
                reason=str(args.get('reason') or '').strip()
                if len(reason)<4:
                    result={'tool':name,'ok':False,'error':'missing_reason'}
                else:
                    identifier=args.get('id') or args.get('user_id') or args.get('channel_id')
                    info=await discord_identity_lookup(db,identifier,msg)
                    mapped=await discord_identity_tags(db,[info.get('id')])
                    result={'tool':name,'ok':True,'needs_model_followup':True,'identity':info,'mapped_label':mapped.get(info.get('id'),{}).get('label')}
            elif executor=='diagnostic_command':
                if not is_root_operator(author_id):
                    result={'tool':name,'ok':False,'error':'root_only'}
                else:
                    result=await run_diagnostic_command(db,args)
                    result.update({'tool':name,'needs_model_followup':True})
            elif executor=='bash':
                if not is_root_operator(author_id):
                    result={'tool':name,'ok':False,'error':'root_only'}
                else:
                    result=await run_bash_command(db,args)
                    result.update({'tool':name,'needs_model_followup':True})
            else:
                result={'tool':name,'ok':False,'error':'unknown_executor'}
        except Exception as e:
            result={'tool':name,'ok':False,'error':type(e).__name__,'needs_model_followup':True}
            await app_log('error','discord_tool','tool call crashed',tool_log_payload(index,name,args,executor,result=result,elapsed_ms=int((time.perf_counter()-call_started)*1000),error=str(e)),scope_type,scope_id)
            return suppress,result
        elapsed_ms=int((time.perf_counter()-call_started)*1000)
        await app_log('trace','discord_tool','tool call result',tool_log_payload(index,name,args,executor,result=result,elapsed_ms=elapsed_ms),scope_type,scope_id)
        return suppress,result
    async def run_limited(index,call):
        async with semaphore:
            return await run_one(index,call)
    pairs=await asyncio.gather(*(run_limited(index,call) for index,call in enumerate(calls)))
    suppress_reply=any(suppress for suppress,_ in pairs)
    results=[result for _,result in pairs]
    if results:
        await broadcast({'type':'discord_tools','data':{'scope_type':scope_type,'scope_id':scope_id,'results':results}})
    await app_log('trace','discord_tool','tool batch complete',{'count':len(results),'elapsed_ms':int((time.perf_counter()-started)*1000),'ok':sum(1 for r in results if r.get('ok')),'errors':[r.get('error') for r in results if not r.get('ok')]},scope_type,scope_id)
    return {'suppress_reply':suppress_reply,'results':results}
def strip_runtime_tool_inventory_messages(messages):
    return [m for m in messages if rem.REM_TOOL_INVENTORY_START not in str(m.get('content') or '')]

async def run_model_with_scoped_tools(db,provider_client,messages,tools,scope_type,scope_id,source,user_id,bot_user_id,msg=None,model=None,params=None,task_id=None,task_run_id=None,max_tool_turns=3,tool_turn_label=None,rem_mode=False,tool_created_by=None):
    """Run a model call, execute any scoped tool calls, and re-enter the model with results."""
    reply=''; suppress_reply=False; all_results=[]; last_resp=None; final_tool_calls=[]
    tool_schemas=tools or None
    total_tool_turns=max(1,int(max_tool_turns))
    label=tool_turn_label or str(source or 'tool')
    finalization_ignored_tool_calls=0
    finalization_failed=False
    latest_result_count=0
    await app_log('trace','ollama','model tool loop start',{'source':source,'user_id':str(user_id),'messages':len(messages),'tools':len(tool_schemas or []),'max_tool_turns':total_tool_turns,'task_id':task_id,'task_run_id':task_run_id},scope_type,scope_id)
    for turn in range(total_tool_turns):
        turn_started=time.perf_counter()
        dynamic_context=tool_turns.render_tool_turn_state(
            label,
            turn+1,
            total_tool_turns,
            available_tool_count=len(tool_schemas or []),
            parallel_limit=TOOL_CALL_PARALLEL_LIMIT,
            previous_tool_results=latest_result_count,
            total_tool_results=len(all_results),
            rem=rem_mode,
        ) if tool_schemas else None
        await app_log('trace','ollama','model turn start',{'source':source,'turn':turn+1,'total_turns':total_tool_turns,'messages':len(messages),'tools_enabled':bool(tool_schemas),'tool_count':len(tool_schemas or [])},scope_type,scope_id)
        try:
            last_resp=await provider_client.chat(messages,tools=tool_schemas,scope_type=scope_type,scope_id=scope_id,source=source,user_id=user_id,model=model,params=params,task_id=task_id,task_run_id=task_run_id,dynamic_context=dynamic_context)
        except Exception as e:
            await app_log('error','ollama','model turn failed',{'source':source,'turn':turn+1,'error':type(e).__name__,'detail':str(e),'elapsed_ms':int((time.perf_counter()-turn_started)*1000)},scope_type,scope_id)
            raise
        reply,tool_calls=model_response_content_and_calls(last_resp)
        reply,directive_calls=extract_tool_directives(reply)
        tool_calls=list(tool_calls or [])+directive_calls
        final_tool_calls=tool_calls
        await app_log('trace','ollama','model turn complete',{'source':source,'turn':turn+1,'elapsed_ms':int((time.perf_counter()-turn_started)*1000),'reply_chars':len(reply or ''),'tool_calls':[tool_call_summary(call,index) for index,call in enumerate(tool_calls)]},scope_type,scope_id)
        if not tool_calls:
            await app_log('trace','ollama','model tool loop complete',{'source':source,'turns':turn+1,'tool_results':len(all_results),'reply_chars':len(reply or '')},scope_type,scope_id)
            return {'reply':reply,'suppress_reply':suppress_reply,'results':all_results,'response':last_resp,'tool_calls':final_tool_calls,'finalization_ignored_tool_calls':0,'finalization_failed':False,'tool_turn_limit':total_tool_turns,'tool_turns_used':turn+1}
        assistant_msg={'role':'assistant','content':reply or ''}
        if tool_calls:
            assistant_msg['tool_calls']=tool_calls
        messages.append(assistant_msg)
        tool_result=await run_discord_tool_calls(db,msg,tool_calls,scope_type,scope_id,user_id,bot_user_id,tool_created_by=tool_created_by)
        suppress_reply=bool(suppress_reply or tool_result.get('suppress_reply'))
        results=tool_result.get('results',[])
        all_results.extend(results)
        latest_result_count=len(results)
        for result in results:
            messages.append({'role':'tool','name':result.get('tool') or 'tool','content':json.dumps(result,ensure_ascii=False)})
        followup_needed=any(r.get('needs_model_followup') or (r.get('requires_reply') and not reply) for r in results)
        if not followup_needed:
            await app_log('trace','ollama','model tool loop complete',{'source':source,'turns':turn+1,'tool_results':len(all_results),'reply_chars':len(reply or ''),'followup_needed':False},scope_type,scope_id)
            return {'reply':reply,'suppress_reply':suppress_reply,'results':all_results,'response':last_resp,'tool_calls':final_tool_calls,'finalization_ignored_tool_calls':0,'finalization_failed':False,'tool_turn_limit':total_tool_turns,'tool_turns_used':turn+1}
    try:
        final_started=time.perf_counter()
        await app_log('trace','ollama','model finalization start',{'source':source,'messages':len(messages),'tool_results':len(all_results)},scope_type,scope_id)
        dynamic_context=tool_turns.render_tool_turn_state(
            label,
            total_tool_turns,
            total_tool_turns,
            latest_tool_results=latest_result_count,
            total_tool_results=len(all_results),
            finalization=True,
            rem=rem_mode,
        ) if tool_schemas else None
        final_messages=strip_runtime_tool_inventory_messages(messages)
        last_resp=await provider_client.chat(final_messages,tools=None,scope_type=scope_type,scope_id=scope_id,source=source,user_id=user_id,model=model,params=params,task_id=task_id,task_run_id=task_run_id,dynamic_context=dynamic_context)
        final_reply,final_calls=model_response_content_and_calls(last_resp)
        final_reply,directive_calls=extract_tool_directives(final_reply)
        final_calls=list(final_calls or [])+directive_calls
        if final_calls:
            finalization_ignored_tool_calls=len(final_calls)
            await app_log('warn','ollama','model requested tools during text-only finalization',{'source':source,'tool_turn_limit':total_tool_turns,'tool_results':len(all_results),'tool_calls':[tool_call_summary(call,index) for index,call in enumerate(final_calls)]},scope_type,scope_id)
        await app_log('trace','ollama','model finalization complete',{'source':source,'elapsed_ms':int((time.perf_counter()-final_started)*1000),'reply_chars':len(final_reply or ''),'ignored_tool_calls':len(final_calls)},scope_type,scope_id)
        if final_reply:
            reply=final_reply
    except Exception as e:
        finalization_failed=True
        await app_log('error','ollama',f'{source} tool finalization failed',{'error':type(e).__name__,'detail':str(e)},scope_type,scope_id)
    await app_log('trace','ollama','model tool loop complete',{'source':source,'turns':total_tool_turns,'tool_results':len(all_results),'reply_chars':len(reply or ''),'finalized':True},scope_type,scope_id)
    return {'reply':reply,'suppress_reply':suppress_reply,'results':all_results,'response':last_resp,'tool_calls':final_tool_calls,'finalization_ignored_tool_calls':finalization_ignored_tool_calls,'finalization_failed':finalization_failed,'tool_turn_limit':total_tool_turns,'tool_turns_used':total_tool_turns}
class CommandHandler:
    def __init__(self,db,provider_client=None,*,tg:asyncio.TaskGroup): self.db=db; self.provider_client=provider_client; self.tg=tg
    def _provider_admin_client(self):
        return self.provider_client if self.provider_client is not None and hasattr(self.provider_client,'list_providers') else provider_client_for_db(self.db)
    async def handle(self,parsed,user_id,scope_type,scope_id,source='discord'):
        c=parsed['command']; a=parsed.get('args',[])
        ultimate_only=c in {'kill','stop','pause','resume'}
        if ultimate_only and not is_ultimate_operator(user_id):
            await log_command(self.db,source,str(user_id),scope_type,scope_id,parsed,False,'ultimate_only')
            return 'ultimate_only'
        root_only=c in {'create','agent','tool','tools','skill','skills','task','tasks','news','provider','providers','scope','scopes'}
        if root_only and not is_root_operator(user_id):
            await log_command(self.db,source,str(user_id),scope_type,scope_id,parsed,False,'root_only')
            return 'root_only'
        ok=True if (root_only or ultimate_only) else await check_permission(self.db,str(user_id),scope_type,scope_id,'admin')
        if not ok:
            await log_command(self.db,source,str(user_id),scope_type,scope_id,parsed,False,'unauthorized')
            return 'unauthorized'
        if c=='kill': result=await self._kill(user_id)
        elif c=='stop': result=await self._stop(a,user_id)
        elif c=='pause': result=await self._pause(a,user_id)
        elif c=='resume': result=await self._resume(user_id)
        elif c=='version': result=await self._version(scope_type,scope_id)
        elif c=='changelog': result=self._changelog()
        elif c=='prompt': result=await self._prompt(a,parsed.get('scope_modifier'),user_id,scope_type,scope_id)
        elif c=='whitelist': result=await self._whitelist(a,parsed.get('scope_modifier'),scope_type,scope_id)
        elif c=='memory': result=await self._memory(a,user_id,scope_type,scope_id)
        elif c=='model': result=await self._model(a,parsed.get('scope_modifier'),scope_type,scope_id)
        elif c=='reasoning': result=await self._reasoning(a,parsed.get('scope_modifier'),scope_type,scope_id)
        elif c=='create': result=await self._create(a,user_id,source,scope_type,scope_id)
        elif c=='agent': result=await self._agent(a)
        elif c in {'tool','tools'}: result=await self._asset('tool',a,parsed.get('scope_modifier'),user_id,source,scope_type,scope_id)
        elif c in {'skill','skills'}: result=await self._asset('skill',a,parsed.get('scope_modifier'),user_id,source,scope_type,scope_id)
        elif c in {'task','tasks'}: result=await self._tasks(a,parsed.get('scope_modifier'),user_id,source,scope_type,scope_id)
        elif c in {'provider','providers'}: result=await self._providers(a)
        elif c in {'scope','scopes'}: result=await self._scope(a,parsed.get('scope_modifier'),scope_type,scope_id)
        elif c=='news': result=await self._news(a,scope_type,scope_id)
        elif c=='status': result=await self._status(scope_type,scope_id)
        elif c=='help': result=await self._help(a,scope_type,scope_id)
        elif c=='clear': result=await self.clear(scope_type,scope_id or '')
        elif c=='compact': result=await self.compact(scope_type,scope_id or '')
        elif c=='summary': result=await self.summary(scope_type,scope_id or '')
        else: result='unknown command'
        accepted=True; reason='ok'
        if result=='unknown command': accepted=False; reason='unknown_command'
        elif result=='bad_args': accepted=False; reason='bad_args'
        await log_command(self.db,source,str(user_id),scope_type,scope_id,parsed,accepted,reason)
        if c=='kill' and accepted and result=='kill requested':
            await request_process_exit(0,tg=self.tg)
        return result
    async def _kill(self,user_id):
        await log_runtime_hold('error','ultimate kill requested',{'user_id':str(user_id),'pid':os.getpid()})
        return 'kill requested'
    async def _stop(self,args,user_id):
        seconds=clamp_hold_seconds(args[0] if args else DEFAULT_STOP_SECONDS,DEFAULT_STOP_SECONDS)
        runtime_control.stop(seconds,started_by=str(user_id))
        await emergency_stop_runtime(self.db,seconds,'cancelled by ultimate stop')
        await log_runtime_hold('warn','ultimate stop engaged',{'user_id':str(user_id),'seconds':seconds,**runtime_metadata_snapshot()})
        return f'stopped for {seconds}s; non-super-admin input, replies, model calls, news, and task queues are held'
    async def _pause(self,args,user_id):
        seconds=clamp_hold_seconds(args[0],DEFAULT_STOP_SECONDS) if args else None
        state=runtime_control.pause(seconds,started_by=str(user_id))
        await log_runtime_hold('warn','ultimate pause engaged',{'user_id':str(user_id),'seconds':seconds,'mode':state.mode})
        if seconds is None:
            return 'paused until !resume; only the super-admin is answered'
        return f'paused for {seconds}s; only the super-admin is answered'
    async def _resume(self,user_id):
        runtime_control.resume()
        await log_runtime_hold('warn','ultimate resume engaged',{'user_id':str(user_id),**runtime_metadata_snapshot()})
        return 'resumed'
    async def _version(self,scope_type,scope_id):
        client=self._provider_admin_client()
        default_model=client.current_model(getattr(app.state,'config',None)) if client else 'unconfigured'
        model=await client.model_for_scope(default_model,scope_type,scope_id) if client else default_model
        return version_report(model=model,scope_type=scope_type,scope_id=scope_id)
    def _changelog(self):
        return 'Dirac changelog\n'+'\n'.join(f'- {version}: {entry}' for version,entry in CHANGELOG)
    async def _prompt(self,args,mod,user_id,scope_type,scope_id):
        tt,tid=_target(scope_type,scope_id,mod)
        if not valid_scope_pair(tt,tid): return 'bad_args'
        if not args: return await system_prompt_for_scope(self.db,scope_type,scope_id or '')
        await set_prompt(self.db,tt,tid,' '.join(args),str(user_id))
        return 'prompt updated'
    async def _whitelist(self,args,mod,scope_type,scope_id):
        if len(args)<2 or args[0] not in {'add','remove','block'}: return 'bad_args'
        tt,tid=_target(scope_type,scope_id,mod); tid=normalize_scope_id(tt,tid); uid=args[1]; level=args[2] if len(args)>2 and args[2] in LEVELS else 'user'
        if not valid_scope_pair(tt,tid): return 'bad_args'
        if is_root_operator(uid) and not (args[0]=='add' and level=='root' and tt=='global' and tid is None):
            return 'protected root'
        if args[0]=='block': level='blocked'
        if args[0]=='remove':
            await self.db.execute('DELETE FROM permissions WHERE user_id=? AND scope_type=? AND ((scope_id IS NULL AND ? IS NULL) OR scope_id=?)',(uid,tt,tid,tid))
            await self.db.commit()
        else:
            await _upsert(self.db,'permissions',['user_id','scope_type','scope_id'],[uid,tt,tid],{'level':level,'added_at':utc_now()})
        return 'permission updated'
    async def _memory(self,args,user_id,scope_type,scope_id):
        mm=MemoryManager(self.db)
        if not args or args[0] in {'help','usage'}:
            return MEMORY_USAGE
        if args[0]=='add':
            discord_id,parts=parse_memory_add_args(args)
            if not discord_id or not memory_contract.is_discord_id(discord_id) or not parts:
                return memory_usage_error('Error: expected !memory add <discord_id|@user|#channel> <annotations> [tags=t1,t2].')
            tags,parts=_memory_tags_arg(parts)
            annotations=' '.join(parts).strip()
            if not annotations:
                return memory_usage_error('Error: memory annotations cannot be empty.')
            mid=await mm.add(discord_id,annotations,tags,str_created_by=str(user_id)); return f'memory {mid} added'
        if args[0] in {'update','edit'}:
            if len(args)<3:
                return memory_usage_error('Error: expected !memory update <#id|id> <annotations> [tags=t1,t2] [confidence=0.8].')
            try:
                memory_id=parse_hash_id(args[1])
                confidence,parts=_memory_confidence_arg(args[2:])
            except ValueError as e:
                return memory_usage_error(f'Error: {e}.')
            tags,parts=_memory_tags_arg(parts)
            annotations=' '.join(parts).strip()
            if not annotations:
                return memory_usage_error('Error: memory annotations cannot be empty.')
            try:
                new_id=await mm.update(memory_id,annotations,tags,confidence,str(user_id))
            except KeyError:
                return f'memory {memory_id} not found'
            return f'memory {memory_id} superseded by {new_id}'
        if args[0] in {'delete','remove'}:
            if len(args)!=2:
                return memory_usage_error('Error: expected !memory delete <#id|id>.')
            try:
                memory_id=parse_hash_id(args[1])
            except ValueError as e:
                return memory_usage_error(f'Error: {e}.')
            result=await memory_tool_delete(self.db,{'int_memory_id':memory_id})
            if not result.get('ok'):
                return f'memory {memory_id} not found'
            return f'memory {memory_id} deleted'
        if args[0] in {'show','list'}:
            if len(args)>=2 and args[1] in {'all','*'}:
                rows=await mm.search(None,None,limit=50)
                return format_memory_rows(rows,'all memories')
            if len(args)==1:
                if scope_id:
                    rows=await mm.search(scope_id,limit=20)
                    return format_memory_rows(rows,f'discord:{scope_id}')
                return memory_usage_error('Error: no current channel scope. Use !memory show <id> or !memory show <discord_id>.')
            if len(args)==2:
                discord_id=normalize_memory_discord_id(args[1])
                if not memory_contract.is_discord_id(discord_id):
                    try:
                        memory_id=parse_hash_id(args[1])
                    except ValueError:
                        return memory_usage_error('Error: expected !memory show <discord_id|@user|#channel> or !memory show <id>.')
                    row=await mm.get(memory_id)
                    return format_memory_rows([row] if row else [],f'memory #{memory_id}')
                rows=await mm.search(discord_id,limit=20)
                return format_memory_rows(rows,f'discord:{discord_id}')
            if len(args)==3 and args[1] in {'user','channel','guild'}:
                discord_id=normalize_memory_discord_id(args[2])
                rows=await mm.search(discord_id,limit=20)
                return format_memory_rows(rows,f'discord:{discord_id}')
            return memory_usage_error('Error: expected !memory show <discord_id|@user|#channel> or !memory show <id>.')
        return memory_usage_error('Error: expected memory action help, add, update, delete, or show.')
    async def _model(self,args,mod,scope_type,scope_id):
        if not args: return 'bad_args'
        tt,tid=_target(scope_type,scope_id,mod)
        if not valid_scope_pair(tt,tid): return 'bad_args'
        await _upsert(self.db,'model_overrides',['scope_type','scope_id'],[tt,tid],{'model':args[0],'updated_at':utc_now()})
        return 'model updated'
    async def _reasoning(self,args,mod,scope_type,scope_id):
        tt,tid=_target(scope_type,scope_id,mod)
        if not valid_scope_pair(tt,tid): return 'bad_args'
        if not args or args[0] in {'show','status'}:
            return f'reasoning={describe_reasoning(await reasoning_for_scope(self.db,tt,tid))} scope={tt}:{tid}'
        mode=args[0].lower()
        aliases={'enable':'on','enabled':'on','true':'on','yes':'on','disable':'off','disabled':'off','false':'off','no':'off','none':'off'}
        mode=aliases.get(mode,mode)
        if mode=='clear':
            await self.db.execute('DELETE FROM reasoning_overrides WHERE scope_type=? AND ((scope_id IS NULL AND ? IS NULL) OR scope_id=?)',(tt,tid,tid))
            await self.db.commit()
            return 'reasoning cleared'
        if mode not in {'on','off','low','medium','high'}: return 'bad_args'
        await _upsert(self.db,'reasoning_overrides',['scope_type','scope_id'],[tt,tid],{'mode':mode,'updated_at':utc_now()})
        return f'reasoning {mode}'
    async def _create(self,args,user_id,source,scope_type,scope_id):
        if not args: return 'bad_args'
        if args[0]=='list': return await self._agent(['list'])
        if args[0]=='show' and len(args)>=2: return await self._agent(['show',args[1]])
        prompt=' '.join(args)
        task_id=await create_agent_task(self.db,'create',prompt,user_id,source,scope_type,scope_id)
        await schedule_agent_task(self.db,self.provider_client,task_id,trigger_source=source,triggered_by=user_id,tg=self.tg)
        return f'agent task {task_id} queued'
    async def _agent(self,args):
        action=args[0] if args else 'show'
        if action in {'help','usage'}:
            return 'Usage:\n!agent\n!agent help\n!agent show\n!agent show <id>\n!agent tools'
        if action=='tools':
            return json.dumps({'installed':local_agent_tools(),'default_backend':'ollama'},indent=2)
        if action=='show' and len(args)>=2:
            cur=await self.db.execute('SELECT * FROM agent_tasks WHERE id=?',(int(args[1]),))
            row=await cur.fetchone()
            if not row: return 'not found'
            keys=[c[0] for c in cur.description]
            return json.dumps(dict(zip(keys,row)),indent=2)
        if action=='list': action='show'
        if action!='show':
            return 'bad_args'
        cur=await self.db.execute('SELECT id,kind,name,status,enabled,schedule_minutes,next_run_utc,run_count,requested_by,source,scope_type,scope_id,backend,created_at,completed_at FROM agent_tasks ORDER BY id DESC LIMIT 10')
        rows=await cur.fetchall(); keys=[c[0] for c in cur.description]
        return json.dumps([dict(zip(keys,r)) for r in rows],indent=2)
    async def _asset(self,asset_type,args,mod,user_id,source,scope_type,scope_id):
        if not args: args=['help']
        action=args[0]
        if action in {'help','usage'}:
            return asset_usage(asset_type)
        if action=='create': action='add'
        if action=='list': action='show'
        if action=='remove':
            return f'Use !{asset_type} disable <id|name> to turn it off, or !{asset_type} delete <id|name> to remove it.'
        if asset_type=='tool' and action=='snapshot':
            if len(args)==1:
                rows=await _dict_rows(await self.db.execute('SELECT version,created_at,created_by,applied_at FROM tool_snapshots ORDER BY id DESC LIMIT 20'))
                if not rows: return 'No tool snapshots recorded.'
                return 'Tool snapshots:\n'+'\n'.join(f"- {r['version']} created={r['created_at']} applied={r.get('applied_at') or '-'} by={r.get('created_by')}" for r in rows)
            if len(args)>=2 and args[1]=='apply':
                version=args[2] if len(args)>=3 else 'latest'
                try:
                    result=await apply_builtin_tool_snapshot(self.db,version,created_by=str(user_id),preserve_state=True)
                except ValueError as e:
                    return str(e)
                return f"tool snapshot {result['version']} applied; restored={result['restored']} inserted={result['inserted']}"
            return 'bad_args'
        if asset_type=='tool' and action=='fix':
            result=await apply_builtin_tool_snapshot(self.db,'latest',created_by=str(user_id),preserve_state=True)
            return f"tool snapshot {result['version']} applied; restored={result['restored']} inserted={result['inserted']}"
        tt,tid=_target(scope_type,scope_id,mod)
        if not valid_scope_pair(tt,tid): return 'bad_args'
        if action=='show' and len(args)==1:
            return format_asset_summary(asset_type,await list_agent_assets(self.db,asset_type,tt,tid,True,True,False),tt,tid)
        if action=='show' and len(args)>=2:
            row=await find_effective_agent_asset(self.db,asset_type,args[1],tt,tid)
            return format_asset_detail(asset_type,row) if row else f'not found for {tt}:{tid or "*"}'
        if action=='edit' and len(args)>=4:
            row=await find_agent_asset(self.db,asset_type,args[1],tt,tid)
            if not row: return f'not found for {tt}:{tid or "*"}'
            field=args[2]; value=' '.join(args[3:]).strip()
            if field=='description':
                if not value: return 'bad_args'
                await self.db.execute('UPDATE agent_assets SET description=?,updated_at=? WHERE id=?',(value,utc_now(),row['id']))
            elif field=='body':
                await self.db.execute('UPDATE agent_assets SET body=?,updated_at=? WHERE id=?',(value or None,utc_now(),row['id']))
            elif field=='schema' and asset_type=='tool':
                try:
                    schema=normalize_tool_schema_json(value,row['name'])
                except ValueError as e:
                    return str(e)
                await self.db.execute('UPDATE agent_assets SET schema_json=?,updated_at=? WHERE id=?',(schema,utc_now(),row['id']))
            elif field in {'executor','executor_name'} and asset_type=='tool':
                try:
                    executor=normalize_executor_name(asset_type,None if value.lower() in {'none','null','-',''} else value)
                except ValueError as e:
                    return str(e)
                await self.db.execute('UPDATE agent_assets SET executor_name=?,updated_at=? WHERE id=?',(executor,utc_now(),row['id']))
                field='executor'
            elif field=='enabled':
                try:
                    enabled=parse_cli_bool(value)
                except ValueError as e:
                    return str(e)
                globally_disabled=0
                if asset_type=='tool' and row['scope_type']=='global':
                    globally_disabled=0 if enabled else 1
                await self.db.execute('UPDATE agent_assets SET enabled=?,globally_disabled=?,updated_at=? WHERE id=?',(int(enabled),globally_disabled,utc_now(),row['id']))
            elif field in {'globally_disabled','global_disabled','disable_everywhere'} and asset_type=='tool':
                try:
                    globally_disabled=parse_cli_bool(value)
                except ValueError as e:
                    return str(e)
                if row['scope_type']!='global':
                    return 'globally_disabled only applies to global tools'
                await self.db.execute('UPDATE agent_assets SET enabled=?,globally_disabled=?,updated_at=? WHERE id=?',(0 if globally_disabled else 1,int(globally_disabled),utc_now(),row['id']))
                field='globally_disabled'
            else:
                return 'bad_args'
            await self.db.commit()
            return f'{asset_type} {row["name"]} {field} updated for {row["scope_type"]}:{row.get("scope_id") or "*"}'
        if action=='delete' and len(args)>=2:
            row=await remove_agent_asset(self.db,asset_type,args[1],tt,tid)
            return f'{asset_type} {args[1]} deleted from {tt}:{tid or "*"}' if row else f'not found for {tt}:{tid or "*"}'
        if action in {'enable','disable'} and len(args)>=2:
            row=await set_agent_asset_enabled(self.db,asset_type,args[1],tt,tid,action=='enable')
            if not row:
                return f'not found for {tt}:{tid or "*"}'
            result=f'{asset_type} {row["name"]} {action}d for {tt}:{tid or "*"}'
            effective=await find_effective_agent_asset(self.db,asset_type,row['name'],tt,tid)
            if action=='enable' and effective and not int(effective.get('enabled') or 0):
                result+=f'; effective state is still disabled because global disable is active. Use !{asset_type} enable {row["name"]} *'
            return result
        if action!='add' or len(args)<3: return 'bad_args'
        name=args[1]; description=' '.join(args[2:])
        try:
            await save_agent_asset(self.db,asset_type,name,description,None,str(user_id),tt,tid,enabled=True)
        except ValueError:
            return 'bad_args'
        task_id=await create_agent_task(self.db,asset_type,f'Design a new {asset_type} named {name}. Description: {description}',user_id,source,tt,tid)
        await schedule_agent_task(self.db,self.provider_client,task_id,trigger_source=source,triggered_by=user_id,tg=self.tg)
        return f'{asset_type} {name} saved for {tt}:{tid or "*"}; agent task {task_id} queued'
    async def _tasks(self,args,mod,user_id,source,scope_type,scope_id):
        action=args[0] if args else 'help'
        if action in {'help','usage'}:
            return task_usage()
        if action=='list': action='show'
        if action=='remove':
            return 'Use !task disable <id|name> to stop a task and keep history, or !task delete <id|name> to permanently remove it.'
        if action=='snapshot':
            rows=await _dict_rows(await self.db.execute('SELECT version,created_at,created_by,applied_at FROM task_snapshots ORDER BY id DESC LIMIT 20'))
            if not rows: return 'No task snapshots recorded.'
            return 'Task snapshots:\n'+'\n'.join(f"- {r['version']} created={r['created_at']} applied={r.get('applied_at') or '-'} by={r.get('created_by')}" for r in rows)
        if action=='fix':
            result=await apply_builtin_task_snapshot(self.db,'latest',created_by=str(user_id),preserve_enabled=True)
            return f"task snapshot {result['version']} applied; restored={result['restored']} inserted={result['inserted']}"
        tt,tid=_target(scope_type,scope_id,mod)
        if not valid_scope_pair(tt,tid): return 'bad_args'
        if action=='show' and len(args)==1:
            return format_task_list(await list_agent_tasks(self.db,tt,tid,True,50),tt,tid)
        if action=='show' and len(args)>=2:
            row=await find_agent_task(self.db,args[1],tt,tid)
            return format_task_row(row,detail=True) if row else 'not found'
        if action=='edit' and len(args)>=4:
            row=await find_agent_task(self.db,args[1],tt,tid)
            if not row: return 'not found'
            field=args[2]; value=' '.join(args[3:]).strip()
            updates={'updated_at':utc_now()}
            if field=='name':
                if not valid_asset_name(value): return 'bad_args'
                updates['name']=value
            elif field=='prompt':
                if not value: return 'bad_args'
                updates['prompt']=value
            elif field in {'schedule','schedule_minutes'}:
                minutes=parse_interval_minutes(value)
                if not minutes: return 'bad_args'
                updates['schedule_minutes']=minutes
                if int(row.get('enabled') or 0):
                    updates['next_run_utc']=utc_after_minutes(minutes)
                field='schedule'
            elif field=='enabled':
                try:
                    enabled=parse_cli_bool(value)
                except ValueError as e:
                    return str(e)
                updates['enabled']=int(enabled)
                updates['next_run_utc']=utc_now() if enabled else None
            elif field=='model':
                updates['model']=value or None
            elif field=='provider_id':
                if value.lower() in {'none','null','-',''}:
                    updates['provider_id']=None
                elif value.isdigit():
                    updates['provider_id']=int(value)
                else:
                    provider=await get_provider(self.db,value)
                    if not provider: return 'not found'
                    updates['provider_id']=provider['id']
            elif field=='runtime_kind':
                if value.lower() in {'none','null','-','default',''}:
                    updates['runtime_kind']='default'
                elif value.lower()=='rem':
                    updates['runtime_kind']='rem'
                else:
                    return 'bad_args'
            else:
                return 'bad_args'
            await self.db.execute('UPDATE agent_tasks SET '+', '.join(f'{k}=?' for k in updates)+' WHERE id=?',tuple(updates.values())+(row['id'],))
            await self.db.commit()
            return f"task {row['id']} {field} updated"
        if action=='run' and len(args)>=2:
            row=await find_agent_task(self.db,args[1],tt,tid)
            if not row: return 'not found'
            await self.db.execute("UPDATE agent_tasks SET status='queued',next_run_utc=?,updated_at=? WHERE id=?",(utc_now(),utc_now(),row['id'])); await self.db.commit()
            await schedule_agent_task(self.db,self.provider_client,row['id'],trigger_source=source,triggered_by=user_id,tg=self.tg)
            return f"task {row['id']} queued"
        if action=='disable' and len(args)>=2:
            row=await find_agent_task(self.db,args[1],tt,tid)
            if not row: return 'not found'
            await self.db.execute('UPDATE agent_tasks SET enabled=0,next_run_utc=NULL,updated_at=? WHERE id=?',(utc_now(),row['id'])); await self.db.commit()
            return f"task {row['id']} disabled"
        if action=='delete' and len(args)>=2:
            row=await find_agent_task(self.db,args[1],tt,tid)
            if not row: return 'not found'
            await self.db.execute('DELETE FROM agent_tasks WHERE id=?',(row['id'],)); await self.db.commit()
            return f"task {row['id']} deleted"
        if action=='enable' and len(args)>=2:
            row=await find_agent_task(self.db,args[1],tt,tid)
            if not row: return 'not found'
            minutes=int(row.get('schedule_minutes') or 0)
            if minutes<=0: return 'bad_args'
            await self.db.execute('UPDATE agent_tasks SET enabled=1,next_run_utc=?,updated_at=? WHERE id=?',(utc_now(),utc_now(),row['id'])); await self.db.commit()
            return f"task {row['id']} enabled"
        if action=='create': action='add'
        if action!='add' or len(args)<5: return 'bad_args'
        name=args[1]
        if args[2]!='every': return 'bad_args'
        minutes=parse_interval_minutes(args[3])
        if not minutes or not valid_asset_name(name): return 'bad_args'
        prompt=' '.join(args[4:])
        task_id=await create_agent_task(self.db,'task',prompt,user_id,source,tt,tid,name=name,enabled=True,schedule_minutes=minutes,next_run_utc=utc_now())
        return f'task {task_id} scheduled every {minutes}m for {tt}:{tid or "*"}'
    async def _providers(self,args):
        action=args[0] if args else 'list'
        client=self._provider_admin_client()
        if action=='list':
            return json.dumps([client.redact_provider(r) for r in await client.list_providers()],indent=2)
        if action=='show' and len(args)>=2:
            row=await client.get_provider(args[1])
            return json.dumps(client.redact_provider(row),indent=2) if row else 'not found'
        if action in {'enable','disable'} and len(args)>=2:
            row=await client.set_provider_enabled(args[1],action=='enable')
            if not row: return 'not found'
            return f"provider {row['name']} {action}d"
        if action=='test' and len(args)>=2:
            row=await client.get_provider(args[1])
            if not row: return 'not found'
            return json.dumps(await client.test_provider(row),indent=2)
        return 'bad_args'
    async def _scope(self,args,mod,scope_type,scope_id):
        action=args[0] if args else 'show'
        tt,tid=_target(scope_type,scope_id,mod)
        tid=normalize_scope_id(tt,tid)
        if not valid_extended_scope_pair(tt,tid): return 'bad_args'
        if action=='show':
            try:
                return json.dumps(await self._provider_admin_client().effective_scope_payload(tt,tid),indent=2)
            except Exception as e:
                return f'provider resolution failed: {e}'
        if action=='provider' and len(args)>=3:
            provider=await self._provider_admin_client().set_scope_provider(tt,tid,args[1],args[2])
            if not provider: return 'not found'
            return f"scope {tt}:{tid or '*'} provider={provider['name']} model={args[2]}"
        if action=='params' and len(args)>=2:
            profile=await self._provider_admin_client().set_scope_params(tt,tid,args[1])
            if not profile: return 'not found'
            return f"scope {tt}:{tid or '*'} params={profile['name']}"
        if action=='reset-provider':
            await self._provider_admin_client().reset_scope_provider(tt,tid)
            return f"scope {tt}:{tid or '*'} provider reset"
        return 'bad_args'
    async def _news(self,args,scope_type,scope_id):
        action=args[0] if args else 'now'
        if action!='now': return 'bad_args'
        cfg=getattr(app.state,'config',None)
        bot_cfg=getattr(cfg,'bot',{}) if cfg is not None else {}
        news_channel_id=bot_cfg.get('news_channel_id',NEWS_CHANNEL_ID) if isinstance(bot_cfg,dict) else NEWS_CHANNEL_ID
        summary=await build_news_summary(self.db,self.provider_client,scope_type,scope_id,store_memory=True,news_channel_id=news_channel_id)
        return summary
    async def _status(self,scope_type,scope_id):
        client=self._provider_admin_client()
        default_model=client.current_model(getattr(app.state,'config',None)) if client else 'unconfigured'
        model=await client.model_for_scope(default_model,scope_type,scope_id) if client else default_model
        reasoning=await client.reasoning_for_scope(scope_type,scope_id) if client else None
        usage=await ollama_usage_snapshot(self.db,scope_type,scope_id)
        cur=await self.db.execute('SELECT COUNT(*) FROM messages WHERE scope_type=? AND scope_id=?',(scope_type,scope_id))
        messages=(await cur.fetchone())[0]
        cur=await self.db.execute('SELECT rolling_summary,last_message_id FROM context_state WHERE scope_type=? AND scope_id=?',(scope_type,scope_id))
        state=await cur.fetchone()
        summary='yes' if state and state[0] else 'no'
        last_id=state[1] if state else None
        return (
            f'uptime_s={int(time.time()-STARTED_AT)}\n'
            f'scope={scope_type}:{scope_id}\n'
            f'model={model}\n'
            f'reasoning={describe_reasoning(reasoning)}\n'
            f'messages_in_scope={messages}\n'
            f'rolling_summary={summary}\n'
            f'last_context_message_id={last_id}\n'
            f'{runtime_hold_line()}\n'
            f"ollama_calls={usage['calls']} prompt_tokens={usage['prompt_tokens']} completion_tokens={usage['completion_tokens']} errors={usage['errors']}\n"
            'reasoning API field=think; use !reasoning off|on|low|medium|high [*|@id].'
        )
    async def _help(self,args,scope_type,scope_id):
        topic=(args[0].lower() if args else 'overview')
        if topic=='overview':
            return compact_help_overview()
        if topic=='all':
            status=await self._status(scope_type,scope_id)
            return admin_help_overview()+'\nRuntime snapshot:\n'+status
        if topic=='config':
            usage=await ollama_usage_snapshot(self.db,scope_type,scope_id)
            return 'Redacted config:\n'+json.dumps(redacted_config_snapshot(),indent=2)+'\n\nScope Ollama usage:\n'+json.dumps(usage,indent=2)
        if topic=='docs':
            if len(args)==1:
                return 'Docs available: '+', '.join(sorted(DOC_SOURCES))+'. Use !help docs <name>.'
            doc=read_doc(args[1],max_chars=3500)
            if doc.get('error'): return json.dumps(doc)
            suffix='\n\n[truncated]' if doc.get('truncated') else ''
            return f"{doc['path']}\n\n{doc['content']}{suffix}"
        if topic in DOC_SOURCES:
            doc=read_doc(topic,max_chars=3500)
            if doc.get('error'): return json.dumps(doc)
            suffix='\n\n[truncated]' if doc.get('truncated') else ''
            return f"{doc['path']}\n\n{doc['content']}{suffix}"
        return admin_help_overview()
    async def clear(self,scope_type,scope_id):
        cur=await self.db.execute('SELECT MAX(id) FROM messages WHERE scope_type=? AND scope_id=?',(scope_type,scope_id)); row=await cur.fetchone()
        await _upsert(self.db,'context_state',['scope_type','scope_id'],[scope_type,scope_id],{'last_wake_utc':utc_now(),'rolling_summary':None,'last_message_id':row[0] or 0})
        return 'cleared'
    async def compact(self,scope_type,scope_id):
        cur=await self.db.execute('SELECT rolling_summary,last_message_id FROM context_state WHERE scope_type=? AND scope_id=?',(scope_type,scope_id)); st=await cur.fetchone()
        existing_summary=context_filters.strip_dirac_fenced_blocks(st[0]) if st and st[0] else None; last_id=int(st[1]) if st and st[1] is not None else 0
        cur=await self.db.execute('SELECT id,author_id,author_name,content FROM messages WHERE scope_type=? AND scope_id=? AND is_command=0 AND id>? ORDER BY id ASC',(scope_type,scope_id,last_id))
        all_rows=await cur.fetchall()
        buf=[]
        for row in all_rows:
            if await is_blocked_user(self.db,row[1],scope_type,scope_id):
                continue
            content=context_filters.strip_dirac_fenced_blocks(row[3])
            if content:
                buf.append((row[0],row[1],row[2],content))
        if not buf: return 'nothing to compact'
        half=max(1,len(buf)//2); compacted=buf[:half]
        text='\n'.join(f'{name}: {content}' for _,_,name,content in compacted); summary='Summary: '+text[:500]
        if self.provider_client:
            try:
                resp=await self.provider_client.chat([{'role':'system','content':'Summarize the following conversation preserving names, decisions, and unresolved questions. Be terse.'},{'role':'user','content':text}],scope_type=scope_type,scope_id=scope_id)
                summary=resp.get('message',{}).get('content') or resp.get('response') or summary
            except Exception: pass
        new_last=int(compacted[-1][0])
        combined=(existing_summary+'\n'+summary) if existing_summary else summary
        await _upsert(self.db,'context_state',['scope_type','scope_id'],[scope_type,scope_id],{'last_wake_utc':utc_now(),'rolling_summary':combined,'last_message_id':new_last})
        return summary
    async def summary(self,scope_type,scope_id):
        ctx=await assemble_context(self.db,scope_type,scope_id); text='\n'.join(m['content'] for m in ctx); summary='Summary: '+text[:500]
        if self.provider_client:
            try:
                resp=await self.provider_client.chat([{'role':'user','content':'Summarize fully:\n'+text}],scope_type=scope_type,scope_id=scope_id); summary=resp.get('message',{}).get('content') or resp.get('response') or summary
            except Exception: pass
        cur=await self.db.execute('SELECT MAX(id) FROM messages WHERE scope_type=? AND scope_id=?',(scope_type,scope_id)); row=await cur.fetchone()
        await _upsert(self.db,'context_state',['scope_type','scope_id'],[scope_type,scope_id],{'last_wake_utc':utc_now(),'rolling_summary':summary,'last_message_id':row[0] or 0})
        return summary
class BotCore:
    def __init__(self,db,provider_client=None,user_id='bot',trigger_on=None,auto_compact_threshold=None,context_window_tokens=4096,*,tg:asyncio.TaskGroup):
        self.db=db; self.provider_client=provider_client; self.user_id=str(user_id); self.commands=CommandHandler(db,provider_client,tg=tg)
        self.trigger_on=set(trigger_on or ('ping','reply')); self.auto_compact_threshold=auto_compact_threshold; self.context_window_tokens=int(context_window_tokens or 4096)
    def scope_for_message(self,msg):
        ch=getattr(msg,'channel',None); g=getattr(msg,'guild',None)
        if g:
            st='guild'; gid=str(getattr(g,'id'))
        elif discord is not None and ch is not None and isinstance(ch,getattr(discord,'GroupChannel',type(None))):
            st='group'; gid=None
        elif ch is not None and (getattr(ch,'type',None)==getattr(getattr(discord,'ChannelType',None),'group',object()) or getattr(ch,'recipients',None)):
            st='group'; gid=None
        else:
            st='dm'; gid=None
        sid=str(getattr(ch,'id',getattr(msg,'channel_id','dm'))); return st,sid,gid
    def _is_reply_to_bot(self,msg):
        ref=getattr(msg,'reference',None)
        if not ref: return False
        target=getattr(ref,'resolved',None) or getattr(ref,'cached_message',None)
        author=getattr(target,'author',None) if target else None
        target_author_id=getattr(author,'id',None) if author else None
        return str(target_author_id)==self.user_id if target_author_id is not None else False
    def was_triggered(self,msg):
        c=getattr(msg,'content','')
        ping=('ping' in self.trigger_on) and (f'<@{self.user_id}>' in c or f'<@!{self.user_id}>' in c or bool(getattr(msg,'triggered_bot',False)))
        reply=('reply' in self.trigger_on) and self._is_reply_to_bot(msg)
        return ping or reply
    def _reply_to_id(self,msg):
        ref=getattr(msg,'reference',None)
        if not ref: return None
        for attr in ('message_id','id'):
            val=getattr(ref,attr,None)
            if val is not None: return str(val)
        target=getattr(ref,'resolved',None) or getattr(ref,'cached_message',None)
        val=getattr(target,'id',None) if target is not None else None
        return str(val) if val is not None else None
    async def _maybe_auto_compact(self,scope_type,scope_id):
        """Estimate the live context size on demand before wake calls; no cache is kept so manual clears/compactions stay authoritative."""
        if not self.auto_compact_threshold: return
        ctx=await assemble_context(self.db,scope_type,scope_id)
        approx_tokens=sum(len(m.get('content','')) for m in ctx)//CHARS_PER_TOKEN_ESTIMATE
        if approx_tokens >= int(self.context_window_tokens * float(self.auto_compact_threshold)):
            await self.commands.compact(scope_type,scope_id)
    async def handle_message(self,msg):
        st,sid,gid=self.scope_for_message(msg); au=getattr(msg,'author',None); aid=str(getattr(au,'id',getattr(msg,'author_id','unknown'))); name=str(getattr(au,'name',getattr(msg,'author_name',aid))); content=str(getattr(msg,'content','')); iscmd=content.strip().startswith('!')
        # Discord clients receive their own messages; ignoring them prevents self-response loops.
        if aid==self.user_id: return None
        ultimate=is_ultimate_operator(aid)
        actual_triggered=self.was_triggered(msg)
        if not runtime_control.should_accept_message(ultimate):
            await app_log('debug','discord','message dropped during ultimate stop',{'message_id':str(getattr(msg,'id','')),'author_id':aid,'is_command':iscmd},st,sid)
            return None
        reply_to_id=self._reply_to_id(msg)
        if await is_blocked_user(self.db,aid,st,sid):
            await self.db.execute('INSERT OR IGNORE INTO messages(discord_msg_id,scope_type,scope_id,guild_id,author_id,author_name,content,is_command,is_authorized,triggered_bot,reply_to_id,timestamp_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(str(getattr(msg,'id',secrets.token_hex(8))),st,sid,gid,aid,name,content,int(iscmd),0,int(actual_triggered),reply_to_id,utc_now())); await self.db.commit()
            if iscmd:
                try: parsed=parse_command(content)
                except ValueError: parsed={'command':'malformed','args':[],'scope_modifier':None}
                await log_command(self.db,'discord',aid,st,sid,parsed,False,'blocked')
            return None
        auth=await check_permission(self.db,aid,st,sid,'admin') if iscmd else True
        answer_allowed=runtime_control.should_answer(ultimate)
        paused_non_ultimate=runtime_control.is_paused() and not ultimate
        triggered=bool(auth and not iscmd and actual_triggered and answer_allowed)
        await self.db.execute('INSERT OR IGNORE INTO messages(discord_msg_id,scope_type,scope_id,guild_id,author_id,author_name,content,is_command,is_authorized,triggered_bot,reply_to_id,timestamp_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(str(getattr(msg,'id',secrets.token_hex(8))),st,sid,gid,aid,name,content,int(iscmd),int(auth),int(actual_triggered),reply_to_id,utc_now())); await self.db.commit()
        await record_memory_event(self.db,'discord_command' if iscmd else 'discord_message',st,sid,'user',content,aid,name,{'message_id':str(getattr(msg,'id','')),'authorized':bool(auth),'triggered_bot':bool(actual_triggered)})
        await broadcast({'type':'message','data':{'scope_type':st,'scope_id':sid,'author_id':aid,'is_command':iscmd}})
        if paused_non_ultimate:
            if iscmd:
                try: parsed=parse_command(content)
                except ValueError: parsed={'command':'malformed','args':[],'scope_modifier':None}
                await log_command(self.db,'discord',aid,st,sid,parsed,False,'paused')
                return None
            if actual_triggered:
                add=getattr(msg,'add_reaction',None)
                if callable(add):
                    try: await add('\U0001f636')
                    except Exception as e: await db_log_error('discord_tool','pause reaction failed',e)
            return 'paused'
        if iscmd:
            try: p=parse_command(content)
            except ValueError:
                p={'command':'malformed','args':[],'scope_modifier':None}
                await log_command(self.db,'discord',aid,st,sid,p,False,'malformed')
                return 'malformed command'
            return await self.commands.handle(p,aid,st,sid,'discord')
        if triggered:
            await app_log('trace','discord','wake response started',{'message_id':str(getattr(msg,'id','')),'author_id':aid,'content_chars':len(content)},st,sid)
            async with maybe_channel_typing(getattr(msg,'channel',None),st,sid,'discord_wake'):
                try:
                    await self._maybe_auto_compact(st,sid)
                    tools=await discord_tools_for_scope(self.db,st,sid)
                    context=await assemble_context(self.db,st,sid,content,trigger_msg=msg,bot_user_id=self.user_id)
                    tool_run=await run_model_with_scoped_tools(self.db,self.provider_client,context,tools,st,sid,'discord',aid,self.user_id,msg=msg,max_tool_turns=DISCORD_TOOL_TURN_LIMIT)
                    if not runtime_control.should_answer(ultimate):
                        return 'held'
                except Exception as e:
                    await db_log_error('ollama','discord wake failed',e)
                    if not runtime_control.should_answer(ultimate):
                        return 'held'
                    detail=str(e)
                    try:
                        detail=(redact_runtime_rows({'detail':detail},await known_secret_values(self.db)) or {}).get('detail',detail)
                    except Exception:
                        pass
                    reply=format_dirac_error(
                        'discord wake model call failed',
                        component='ollama',
                        exception=type(e).__name__,
                        detail=preview_text(detail,500),
                    )
                    await send_discord_reply(msg,reply)
                    await record_memory_event(self.db,'discord_assistant',st,sid,'assistant',reply,self.user_id,'Dirac',{'reply_to':str(getattr(msg,'id','')),'error':type(e).__name__})
                    return reply
            reply=tool_run.get('reply') or ''
            if tool_run.get('suppress_reply'):
                reply=''
            tool_results=tool_run.get('results',[])
            requires_reply=sum(1 for r in tool_results if r.get('requires_reply'))
            needs_model_followup=sum(1 for r in tool_results if r.get('needs_model_followup'))
            if not reply and (requires_reply or needs_model_followup):
                reply=format_dirac_error(
                    'tool completed but model produced no text reply',
                    source='discord',
                    tool_results=len(tool_results),
                    needs_model_followup=needs_model_followup,
                    requires_reply=requires_reply,
                    tool_turns=f"{tool_run.get('tool_turns_used')}/{tool_run.get('tool_turn_limit')}",
                    ignored_finalization_tool_calls=tool_run.get('finalization_ignored_tool_calls') or 0,
                    hint='check bot_logs component=ollama for model finalization details',
                )
            if not runtime_control.should_answer(ultimate):
                return 'held'
            if reply:
                if not await send_discord_reply(msg,reply):
                    return reply
                await record_memory_event(self.db,'discord_assistant',st,sid,'assistant',reply,self.user_id,'Dirac',{'reply_to':str(getattr(msg,'id','')),'tool_results':len(tool_run.get('results',[]))})
            cur=await self.db.execute('SELECT MAX(id) FROM messages WHERE scope_type=? AND scope_id=?',(st,sid)); row=await cur.fetchone()
            await _upsert(self.db,'context_state',['scope_type','scope_id'],[st,sid],{'last_wake_utc':utc_now(),'last_message_id':row[0] or 0})
            await app_log('trace','discord','wake response complete',{'message_id':str(getattr(msg,'id','')),'reply_chars':len(reply or ''),'tool_results':len(tool_run.get('results',[]))},st,sid)
            return reply or 'responded'
        return None

PANEL_HTML = '''
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Dirac Panel</title>
<script src="https://unpkg.com/htmx.org@1.9.12"
        integrity="sha384-ujb1lZYygJmzgSwoxRggbCHcjc0rB2XoQrxeTUQyRjrOnlCoYta87iKBWq3EsdM2"
        crossorigin="anonymous">
</script>
<script defer src="https://unpkg.com/alpinejs@3.14.8/dist/cdn.min.js"
        integrity="sha384-X9kJyAubVxnP0hcA+AMMs21U445qsnqhnUF8EBlEpP3a42Kh/JwWjlv2ZcvGfphb"
        crossorigin="anonymous">
</script>
<style>:root{--bg:#0e0f12;--bg-elev:#15171c;--border:#23262d;--fg:#d7dae0;--fg-dim:#7c828d;--accent:#6ea8fe;--ok:#5ec27b;--warn:#e1b46a;--err:#e16a6a;--mono:ui-monospace,"JetBrains Mono","SF Mono",Menlo,monospace;--sans:system-ui,-apple-system,"Inter",sans-serif}*{box-sizing:border-box}[x-cloak]{display:none!important}body{margin:0;height:100vh;overflow:hidden;background:var(--bg);color:var(--fg);font-family:var(--sans)}.top{height:48px;border-bottom:1px solid var(--border);display:flex;align-items:center;padding:0 14px;gap:14px;background:var(--bg-elev);min-width:0}.top input{width:216px;min-width:140px}.icon-btn{width:34px;height:34px;display:inline-flex;align-items:center;justify-content:center}.layout{display:grid;grid-template-columns:max-content minmax(0,1fr);height:calc(100vh - 48px - 176px);min-height:320px}nav{width:220px;min-width:180px;max-width:340px;resize:horizontal;border-right:1px solid var(--border);padding:12px 10px;background:#101217;overflow:auto}button,input,textarea,select{background:#0c0d10;color:var(--fg);border:1px solid var(--border);padding:8px;font:inherit;max-width:100%}button{cursor:pointer}button:hover{border-color:var(--accent)}nav button{display:block;width:100%;text-align:left;margin-bottom:6px;white-space:normal;line-height:1.2}.active{border-color:var(--accent);color:var(--accent)}main{padding:14px;overflow:auto;min-width:0}.card{border:1px solid var(--border);background:var(--bg-elev);padding:12px;margin-bottom:12px}.modal-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.62);display:flex;align-items:center;justify-content:center;z-index:50}.modal{width:min(920px,94vw);max-height:86vh;overflow:auto;border:1px solid var(--border);background:var(--bg-elev);padding:14px}.modal-head{display:flex;align-items:center;gap:10px;margin-bottom:10px}.modal-head .spacer{flex:1}pre,code,.mono{font-family:var(--mono)}pre{white-space:pre-wrap;word-break:break-word;max-height:58vh;overflow:auto}.live-tail{height:176px;border-top:1px solid var(--border);background:#0b0c0f;color:var(--fg-dim);font-family:var(--mono);display:flex;flex-direction:column}.tail-head{height:36px;display:flex;align-items:center;gap:10px;padding:0 12px;border-bottom:1px solid var(--border);background:#101217}.tail-head strong{color:var(--fg);font-family:var(--sans)}.tail-head .spacer{flex:1}.tail-head button{padding:5px 8px}.tail-body{flex:1;overflow:auto;padding:8px 12px}.tail-line{display:grid;grid-template-columns:92px 86px minmax(0,1fr);gap:10px;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.04);white-space:pre-wrap;overflow-wrap:anywhere}.tail-line .time{color:var(--fg-dim)}.tail-line .type{color:var(--accent)}.tail-line .text{color:var(--fg)}.tail-line.error .type,.tail-line.error .text{color:var(--err)}.tail-empty{padding:18px 0;color:var(--fg-dim)}.debug-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px;margin-bottom:10px}.debug-log{border:1px solid var(--border);background:#0b0c0f;margin-bottom:8px;padding:8px}.debug-log header{display:flex;gap:10px;flex-wrap:wrap;color:var(--fg-dim);margin-bottom:6px}.debug-log.trace{border-color:#59606b}.debug-log.debug{border-color:#44b8d8}.debug-log.info{border-color:#5ec27b}.debug-log.warn{border-color:#e1b46a}.debug-log.error{border-color:#e16a6a}.debug-log.trace header b{color:#a0a6b0}.debug-log.debug header b{color:#44b8d8}.debug-log.info header b{color:#5ec27b}.debug-log.warn header b{color:#e1b46a}.debug-log.error header b{color:#e16a6a}.err{color:var(--err)}.ok{color:var(--ok)}@media(max-width:760px){.top{gap:8px;padding:0 8px}.top input{display:none}.layout{grid-template-columns:1fr;height:calc(100vh - 48px - 176px)}nav{width:auto;max-width:none;resize:none;border-right:0;border-bottom:1px solid var(--border);display:flex;gap:6px;overflow:auto;padding:8px}nav button{min-width:120px;margin:0}main{padding:10px}}</style>
<style>.item{border:1px solid var(--border);background:#101217;padding:10px;margin-bottom:10px}.roxanne-shell{display:grid;grid-template-columns:220px minmax(0,1fr) 300px;gap:12px;height:calc(100vh - 250px);min-height:520px}.roxanne-side,.roxanne-chat,.roxanne-settings{border:1px solid var(--border);background:#101217;min-width:0;overflow:auto}.roxanne-side,.roxanne-settings{padding:10px}.roxanne-chat{display:flex;flex-direction:column}.roxanne-messages{flex:1;overflow:auto;padding:12px}.roxanne-msg{border-bottom:1px solid rgba(255,255,255,.06);padding:9px 0}.roxanne-msg .role{font-size:12px;color:var(--fg-dim);text-transform:uppercase;margin-bottom:4px}.roxanne-msg.operator .role{color:var(--accent)}.roxanne-msg.tool .role{color:var(--warn)}.roxanne-msg .body{white-space:pre-wrap;line-height:1.45;overflow-wrap:anywhere}.roxanne-tool summary{cursor:pointer;color:var(--warn)}.roxanne-tool pre{max-height:220px;overflow:auto;background:#08090c;border:1px solid var(--border);padding:8px;white-space:pre-wrap;overflow-wrap:anywhere}.roxanne-composer{border-top:1px solid var(--border);padding:10px;display:grid;gap:8px}.roxanne-toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.roxanne-thread{width:100%;text-align:left;margin-bottom:6px;overflow:hidden}.roxanne-thread small{display:block;color:var(--fg-dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.roxanne-settings label{display:grid;gap:4px;margin-bottom:8px}.roxanne-memory-row{border-top:1px solid var(--border);padding-top:8px;margin-top:8px}@media(max-width:1100px){.roxanne-shell{grid-template-columns:1fr;height:auto}.roxanne-side,.roxanne-settings{max-height:320px}.roxanne-chat{min-height:520px}}</style>
</head>
<body x-data="panel()">
<div class="top">
<b>Dirac</b>
<span>status: <b class="ok">online</b>
</span>
<span>uptime: <span x-text="stats.uptime_s||0">
</span>s</span>
<input placeholder="scope filter">
<input placeholder="search">
<button class="icon-btn" title="Open config" @click="openConfig()">⚙</button>
<button class="icon-btn" title="Ask Roxanne" @click="openRoxanne()">?</button>
</div>
<div class="layout">
<nav>
<template x-for="t in tabs">
<button :class="tab===t?'active':''" @click="selectTab(t)" x-text="t">
</button>
</template>
</nav>
<main>
<template x-if="tab==='Dashboard'">
<section class="card">
<h2>Dashboard</h2>
<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">
<button @click="loadProviders();load('/api/provider-calls/summary','providerSummary');loadTasks();loadTaskRuns()">Refresh</button>
<button @click="selectTab('Roxanne')">Ask Roxanne</button>
</div>
<pre x-text="pretty({stats,providers:providers.length,providerSummary,tasks:tasks.length,taskRuns:taskRuns.length})"></pre>
</section>
</template>
<template x-if="tab==='Logs'">
<section class="card">
<h2>Logs</h2>
<button @click="load('/api/bot-logs','botLogs')">Refresh</button>
<pre x-text="pretty(botLogs)">
</pre>
</section>
</template>
<template x-if="tab==='Debug'">
<section class="card">
<h2>Debug</h2>
<div class="debug-grid">
<label>Component<select x-model="debugComponent"><option value="">all</option><template x-for="c in logging.components"><option :value="c" x-text="c"></option></template></select></label>
<label>Minimum level<select x-model="debugMinLevel"><template x-for="l in logging.levels"><option :value="l" x-text="l"></option></template></select></label>
<label>Scope type<input x-model="debugScopeType" placeholder="optional"></label>
<label>Scope id<input x-model="debugScopeId" placeholder="optional"></label>
<label class="mono"><input type="checkbox" x-model="debugProviderHttp"> provider HTTP debug</label>
</div>
<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
<button @click="loadLogging();loadDebugLogs()">Refresh</button>
<button @click="saveLogging()">Save logging config</button>
<button @click="debugLogs=[]">Clear view</button>
<span x-text="debugStatus"></span>
</div>
<p class="mono" style="color:var(--fg-dim)">Console hotkeys: + increases verbosity, - reduces verbosity. Provider DEBUG records redacted HTTP requests; TRACE also records redacted responses.</p>
<template x-for="row in debugLogs" :key="row.id || `${row.timestamp_utc}-${row.component}-${row.message}`">
<article class="debug-log" :class="row.level">
<header><b x-text="(row.level||'').toUpperCase()"></b><span x-text="row.component"></span><span x-text="row.timestamp_local || row.timestamp_utc"></span><span x-text="row.timezone || ''"></span><span x-text="row.scope_type?`${row.scope_type}:${row.scope_id||'*'}`:''"></span></header>
<div x-text="row.message"></div>
<pre x-text="debugDetail(row)"></pre>
</article>
</template>
<div class="tail-empty" x-show="debugLogs.length===0">No matching debug rows yet.</div>
</section>
</template>
<template x-if="tab==='Channels'">
<section class="card">
<h2>Channels</h2>
<button @click="load('/api/scopes','scopes')">Load</button>
<pre x-text="pretty(scopes)">
</pre>
</section>
</template>
<template x-if="tab==='Prompts'">
<section class="card">
<h2>Prompts</h2>
<div style="display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap">
<button @click="loadPrompts()">Load prompts</button>
<select x-model="promptScopeType">
<option value="global">global</option>
<option value="dm">dm</option>
<option value="group">group</option>
<option value="guild">guild</option>
</select>
<input x-model="promptScopeId" :disabled="promptScopeType==='global'" placeholder="scope id">
<button @click="newPrompt()">New</button>
<button @click="savePrompt()" x-text="promptSaving?'Saving...':'Save prompt'"></button>
<span x-text="promptStatus"></span>
</div>
<div style="display:grid;grid-template-columns:260px 1fr;gap:12px">
<div>
<template x-for="p in prompts" :key="p.id">
<button style="width:100%;text-align:left;margin-bottom:6px" :class="activePromptId===p.id?'active':''" @click="selectPrompt(p)">
<span x-text="promptLabel(p)"></span>
</button>
</template>
<div class="mono" x-show="prompts.length===0" style="color:var(--fg-dim)">No prompts loaded.</div>
</div>
<div>
<div class="mono" style="margin-bottom:8px;color:var(--fg-dim)" x-text="promptEditorLabel()"></div>
<textarea x-model="promptBody" rows="8" style="width:100%">
</textarea>
</div>
</div>
</section>
</template>
<template x-if="tab==='Perms'">
<section class="card">
<h2>Perms</h2>
<button @click="load('/api/permissions','perms')">Load</button>
<pre x-text="pretty(perms)">
</pre>
</section>
</template>
<template x-if="tab==='Memory'">
<section class="card">
<h2>Memory</h2>
<div style="display:grid;grid-template-columns:minmax(240px,360px) 1fr;gap:12px">
<div>
<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px">
<input x-model="memoryForm.str_discord_id" placeholder="Discord snowflake, @user, or #channel">
<input x-model="memQ" placeholder="query">
<button @click="loadMemory()">Refresh</button>
</div>
<textarea x-model="memoryForm.str_annotations" rows="6" placeholder="memory annotations" style="width:100%;margin-bottom:8px"></textarea>
<input x-model="memoryForm.array_tags" placeholder="tags" style="width:100%;margin-bottom:8px">
<input x-model.number="memoryForm.float_confidence" type="number" min="0" max="1" step="0.05" style="width:90px">
<button @click="saveMemory()" x-text="memoryForm.id?'Update':'Add'"></button>
<button @click="memoryForm={id:null,str_discord_id:'',str_annotations:'',array_tags:'',float_confidence:0.7}">Clear</button>
<h3>Discord Tags</h3>
<input x-model="discordTagForm.snowflake" placeholder="snowflake" style="width:100%;margin-bottom:8px">
<input x-model="discordTagForm.label" placeholder="label" style="width:100%;margin-bottom:8px">
<select x-model="discordTagForm.kind" style="width:100%;margin-bottom:8px"><option value="user">user</option><option value="channel">channel</option><option value="guild">guild</option><option value="unknown">unknown</option></select>
<button @click="saveDiscordTag()">Save tag</button>
<pre x-text="pretty(discordTags)"></pre>
</div>
<div>
<template x-for="m in memories" :key="m.int_memory_id">
<div class="item">
<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><b x-text="`#${m.int_memory_id} discord:${m.str_discord_id}`"></b><span x-text="memoryTagsLabel(m)"></span><button @click="editMemory(m)">Edit</button><button @click="deleteMemory(m.int_memory_id)">Delete</button></div>
<pre x-text="m.str_annotations"></pre>
</div>
</template>
<h3>Short-Term Slice</h3>
<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px">
<select x-model.number="memoryEventsMinutes" @change="loadMemoryEvents()"><option :value="10">10m</option><option :value="30">30m</option><option :value="60">60m</option><option :value="180">180m</option></select>
<button @click="loadMemoryEvents()">Refresh slice</button>
<span class="mono" x-text="memoryEventsStatus"></span>
</div>
<pre x-text="pretty(memoryEvents)"></pre>
</div>
</div>
</section>
</template>
<template x-if="tab==='WebChat'">
<section class="card">
<h2>WebChat</h2>
<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">
<button @click="selectTab('Tools')">Tools</button>
<button @click="selectTab('Skills')">Skills</button>
<button @click="selectTab('Tasks')">Tasks</button>
</div>
<textarea x-model="chat" rows="3" style="width:100%">
</textarea>
<button @click="sendChat()">Send</button>
<pre x-text="pretty(panelChat)">
</pre>
</section>
</template>
<template x-if="tab==='Tools'">
<section class="card">
<h2>Tools</h2>
<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
<select x-model="assetScopeType"><option value="global">global</option><option value="dm">dm</option><option value="group">group</option><option value="guild">guild</option></select>
<input x-model="assetScopeId" :disabled="assetScopeType==='global'" placeholder="scope id">
<button @click="loadAssets('tool')">Load</button>
<button @click="saveAsset('tool')">Save tool</button>
<button @click="restoreToolSnapshot()">Restore snapshot</button>
<span x-text="assetStatus"></span>
</div>
<div style="display:grid;grid-template-columns:minmax(220px,320px) 1fr;gap:12px">
<div>
<input x-model="toolForm.name" placeholder="tool name" style="width:100%;margin-bottom:8px">
<div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:8px">
<label><input type="checkbox" x-model="toolForm.enabled"> enabled</label>
<label><input type="checkbox" x-model="toolForm.globally_disabled"> disable everywhere</label>
</div>
<select x-model="toolForm.executor_name" style="width:100%;margin-bottom:8px">
<option value="">instruction only</option>
<option value="react_emoji">react_emoji</option>
<option value="silencer">silencer</option>
<option value="current_time">current_time</option>
<option value="web_fetch">web_fetch</option>
<option value="web_search">web_search</option>
<option value="memory_search">memory_search</option>
<option value="memory_add">memory_add</option>
<option value="memory_update">memory_update</option>
<option value="memory_delete">memory_delete</option>
<option value="discord_id">discord_id</option>
<option value="discord_ground">discord_ground</option>
<option value="discord_tag">discord_tag</option>
<option value="dyslexic_helper">dyslexic_helper</option>
<option value="bash">bash</option>
</select>
<textarea x-model="toolForm.description" rows="4" placeholder="description" style="width:100%;margin-bottom:8px"></textarea>
<textarea x-model="toolForm.body" rows="5" placeholder="usage/body" style="width:100%"></textarea>
<textarea x-model="toolForm.schema_json" rows="8" placeholder="function schema JSON" style="width:100%;margin-top:8px"></textarea>
</div>
<div>
<template x-for="a in tools" :key="a.id">
<div class="item">
<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
<b x-text="a.name"></b><span class="mono" x-text="`${a.scope_type}:${a.scope_id||'*'}`"></span><span x-text="a.enabled?'enabled':'disabled'"></span><span x-show="a.globally_disabled">disabled everywhere</span><span x-text="a.executor_name?`exec ${a.executor_name}`:''"></span>
<button @click="editAsset('tool',a)">Edit</button>
<button @click="toggleAsset('tool',a)" x-text="a.enabled?'Disable':'Enable'"></button>
<button @click="disableAssetEverywhere(a)">Disable everywhere</button>
<button @click="deleteAsset('tool',a.id)">Delete</button>
</div>
<pre x-text="`${a.description||''}${a.body?'\\n\\n'+a.body:''}`"></pre>
</div>
</template>
</div>
</div>
</section>
</template>
<template x-if="tab==='Skills'">
<section class="card">
<h2>Skills</h2>
<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
<select x-model="assetScopeType"><option value="global">global</option><option value="dm">dm</option><option value="group">group</option><option value="guild">guild</option></select>
<input x-model="assetScopeId" :disabled="assetScopeType==='global'" placeholder="scope id">
<button @click="loadAssets('skill')">Load</button>
<button @click="saveAsset('skill')">Save skill</button>
<span x-text="assetStatus"></span>
</div>
<div style="display:grid;grid-template-columns:minmax(220px,320px) 1fr;gap:12px">
<div>
<input x-model="skillForm.name" placeholder="skill name" style="width:100%;margin-bottom:8px">
<textarea x-model="skillForm.description" rows="4" placeholder="description" style="width:100%;margin-bottom:8px"></textarea>
<textarea x-model="skillForm.body" rows="5" placeholder="workflow/body" style="width:100%"></textarea>
</div>
<div>
<template x-for="a in skills" :key="a.id">
<div class="item">
<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
<b x-text="a.name"></b><span class="mono" x-text="`${a.scope_type}:${a.scope_id||'*'}`"></span><span x-text="a.enabled?'enabled':'disabled'"></span>
<button @click="editAsset('skill',a)">Edit</button>
<button @click="toggleAsset('skill',a)" x-text="a.enabled?'Disable':'Enable'"></button>
<button @click="deleteAsset('skill',a.id)">Delete</button>
</div>
<pre x-text="`${a.description||''}${a.body?'\\n\\n'+a.body:''}`"></pre>
</div>
</template>
</div>
</div>
</section>
</template>
<template x-if="tab==='Tasks'">
<section class="card">
<h2>Tasks</h2>
<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
<select x-model="taskFilterScopeType"><option value="all">all</option><option value="global">global</option><option value="dm">dm</option><option value="group">group</option><option value="guild">guild</option></select>
<input x-model="taskFilterScopeId" :disabled="taskFilterScopeType==='all'||taskFilterScopeType==='global'" placeholder="filter scope id">
<button @click="loadTasks()">Load tasks</button>
<span x-text="tasks.length + ' loaded'"></span>
</div>
<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
<select x-model="taskForm.scope_type"><option value="global">global</option><option value="dm">dm</option><option value="group">group</option><option value="guild">guild</option></select>
<input x-model="taskForm.scope_id" :disabled="taskForm.scope_type==='global'" placeholder="scope id">
<input x-model="taskForm.name" placeholder="task name">
<input x-model.number="taskForm.schedule_minutes" type="number" min="1" style="width:90px">
<input x-model.number="taskForm.provider_id" type="number" placeholder="provider id" style="width:120px">
<input x-model="taskForm.model" placeholder="model">
<select x-model="taskForm.runtime_kind"><option value="default">default runtime</option><option value="rem">REM runtime</option></select>
<button @click="saveTask()" x-text="taskForm.id?'Update task':'Save task'"></button>
<button @click="taskForm={id:null,name:'',prompt:'',schedule_minutes:180,scope_type:'global',scope_id:'',enabled:true,provider_id:null,model:'',runtime_kind:'default'}">Clear</button>
<button @click="restoreTaskSnapshot()">Restore defaults</button>
<span x-text="taskStatus"></span>
</div>
<textarea x-model="taskForm.prompt" rows="4" placeholder="task prompt" style="width:100%;margin-bottom:10px"></textarea>
<template x-for="t in tasks" :key="t.id">
<div class="item">
<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
<b x-text="`${t.id} ${t.name||'(unnamed)'}`"></b><span class="mono" x-text="`${t.scope_type}:${t.scope_id||'*'}`"></span><span x-text="t.enabled?'enabled':'disabled'"></span><span x-text="`every ${t.schedule_minutes||'-'}m`"></span><span x-text="t.status"></span>
<button @click="editTask(t)">Edit</button>
<button @click="runTask(t.id)">Run</button>
<button @click="disableTask(t.id)">Disable</button>
<button @click="deleteTask(t.id)">Delete</button>
</div>
<pre x-text="`${t.prompt||''}\\n\\nlast: ${formatTaskTime(t,'last')} next: ${formatTaskTime(t,'next')} runs: ${t.run_count||0}\\n${t.result||t.error||''}`"></pre>
</div>
</template>
</section>
</template>
<template x-if="tab==='Providers'">
<section class="card">
<h2>Providers</h2>
<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
<button @click="loadProviders()">Load providers</button>
<button @click="saveProvider()">Save provider</button>
<span x-text="providerStatus"></span>
</div>
<div style="display:grid;grid-template-columns:minmax(260px,360px) 1fr;gap:12px">
<div>
<input x-model="providerForm.name" placeholder="name" style="width:100%;margin-bottom:8px">
<select x-model="providerForm.provider_type" style="width:100%;margin-bottom:8px"><option value="ollama">ollama</option><option value="openrouter">openrouter</option><option value="openai_compatible">openai_compatible</option></select>
<input x-model="providerForm.base_url" placeholder="base url" style="width:100%;margin-bottom:8px">
<input x-model="providerForm.default_model" placeholder="default model" style="width:100%;margin-bottom:8px">
<input x-model="providerForm.api_key" type="password" placeholder="api key or leave blank" style="width:100%;margin-bottom:8px">
<input x-model.number="providerForm.timeout_s" type="number" min="1" style="width:100%;margin-bottom:8px">
<label><input type="checkbox" x-model="providerForm.enabled"> enabled</label>
</div>
<div>
<template x-for="p in providers" :key="p.id">
<div class="item">
<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
<b x-text="p.name"></b><span class="mono" x-text="p.provider_type"></span><span x-text="p.enabled?'enabled':'disabled'"></span><span class="mono" x-text="p.api_key_fingerprint||'no key'"></span>
<button @click="editProvider(p)">Edit</button>
<button @click="testProvider(p.id)">Test</button>
<button @click="disableProvider(p.id)">Disable</button>
</div>
<pre x-text="pretty(p)"></pre>
</div>
</template>
</div>
</div>
</section>
</template>
<template x-if="tab==='Provider Calls'">
<section class="card">
<h2>Provider Calls</h2>
<button @click="load('/api/provider-calls/summary','providerSummary');load('/api/provider-calls','providerCalls')">Load</button>
<h3>Summary</h3>
<pre x-text="pretty(providerSummary)"></pre>
<h3>Recent Calls</h3>
<pre x-text="pretty(providerCalls)"></pre>
</section>
</template>
<template x-if="tab==='Bot Entries'">
<section class="card">
<h2>Bot Entries</h2>
<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
<button @click="load('/api/bot-entries','botEntries')">Load</button>
<button @click="saveBotEntry()">Save bot entry</button>
<span x-text="botEntryStatus"></span>
</div>
<input x-model="botEntryForm.name" placeholder="name">
<input x-model="botEntryForm.description" placeholder="description">
<label><input type="checkbox" x-model="botEntryForm.enabled"> enabled</label>
<textarea x-model="botEntryForm.persona" rows="4" style="width:100%;margin-top:8px" placeholder="persona"></textarea>
<template x-for="b in botEntries" :key="b.id"><div class="item"><b x-text="b.name"></b> <span x-text="b.enabled?'enabled':'disabled'"></span> <button @click="editBotEntry(b)">Edit</button><pre x-text="pretty(b)"></pre></div></template>
<pre x-text="pretty(botEntries)"></pre>
</section>
</template>
<template x-if="tab==='Scopes'">
<section class="card">
<h2>Scopes</h2>
<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
<select x-model="scopeForm.scope_type"><option value="global">global</option><option value="guild">guild</option><option value="channel">channel</option><option value="dm">dm</option><option value="group">group</option><option value="user">user</option></select>
<input x-model="scopeForm.scope_id" :disabled="scopeForm.scope_type==='global'" placeholder="scope id">
<input x-model.number="scopeForm.provider_id" type="number" placeholder="provider id">
<input x-model="scopeForm.model" placeholder="model">
<button @click="loadEffectiveScope()">Load effective</button>
<button @click="saveScope()">Save provider/model</button>
<span x-text="scopeStatus"></span>
</div>
<pre x-text="pretty(scopeEffective)"></pre>
</section>
</template>
<template x-if="tab==='Instructions'">
<section class="card">
<h2>Instructions</h2>
<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
<button @click="load('/api/instructions','instructions')">Load</button>
<button @click="saveInstruction()">Save instruction</button>
<span x-text="instructionStatus"></span>
</div>
<input x-model="instructionForm.name" placeholder="name" style="width:220px;margin-bottom:8px">
<select x-model="instructionForm.scope_type"><option value="global">global</option><option value="guild">guild</option><option value="channel">channel</option><option value="dm">dm</option><option value="group">group</option><option value="user">user</option><option value="bot_entry">bot_entry</option><option value="task">task</option><option value="roxanne">roxanne</option></select>
<input x-model="instructionForm.scope_id" :disabled="instructionForm.scope_type==='global'" placeholder="scope id">
<textarea x-model="instructionForm.body" rows="6" style="width:100%;margin-top:8px"></textarea>
<pre x-text="pretty(instructions)"></pre>
</section>
</template>
<template x-if="tab==='Task Runs'">
<section class="card">
<h2>Task Runs</h2>
<button @click="loadTaskRuns()">Load task runs</button>
<pre x-text="pretty(taskRuns)"></pre>
</section>
</template>
<template x-if="tab==='Roxanne'">
<section class="card">
<div class="roxanne-toolbar" style="margin-bottom:10px">
<h2 style="margin:0">Roxanne</h2>
<button @click="newRoxanneThread()">New thread</button>
<button @click="loadRoxanne()">Refresh</button>
<span x-text="roxanneStatus"></span>
</div>
<div class="roxanne-shell">
<aside class="roxanne-side">
<div class="roxanne-toolbar" style="margin-bottom:8px">
<select x-model="roxanneScopeType"><option value="global">global</option><option value="guild">guild</option><option value="channel">channel</option><option value="dm">dm</option><option value="group">group</option><option value="user">user</option></select>
<input x-model="roxanneScopeId" :disabled="roxanneScopeType==='global'" placeholder="scope id">
</div>
<template x-for="s in roxanneSessions" :key="s.id">
<button class="roxanne-thread" :class="roxanneActiveSessionId===s.id?'active':''" @click="loadRoxanneThread(s.id)">
<span x-text="s.title || ('thread '+s.id)"></span>
<small x-text="`${s.active_scope_type||'global'}:${s.active_scope_id||'*'} · ${s.updated_at||s.created_at||''}`"></small>
</button>
</template>
<div class="tail-empty" x-show="roxanneSessions.length===0">No threads yet.</div>
</aside>
<div class="roxanne-chat">
<div class="roxanne-messages">
<template x-for="m in roxanneMessages" :key="m.id">
<article class="roxanne-msg" :class="m.role">
<div class="role" x-text="roxanneRoleLabel(m)"></div>
<template x-if="m.role==='tool'">
<details class="roxanne-tool">
<summary x-text="roxanneToolSummary(m)"></summary>
<pre x-text="prettyRoxanneTool(m.content)"></pre>
</details>
</template>
<template x-if="m.role!=='tool'">
<div class="body" x-text="m.content"></div>
</template>
</article>
</template>
<div class="tail-empty" x-show="roxanneMessages.length===0">Start a thread and ask Roxanne.</div>
</div>
<div class="roxanne-composer">
<textarea x-model="roxanneMessage" rows="4" placeholder="Ask Roxanne to inspect docs, runtime state, memories, providers, logs, or run bounded diagnostics"></textarea>
<div class="roxanne-toolbar">
<button @click="askRoxanne()" :disabled="roxanneBusy" x-text="roxanneBusy?'Thinking...':'Send'"></button>
<button @click="roxanneMessage=''">Clear</button>
</div>
</div>
</div>
<aside class="roxanne-settings">
<h3 style="margin-top:0">Settings</h3>
<label>Provider<select x-model.number="roxanneProfile.provider_id"><option :value="null">auto</option><template x-for="p in providers" :key="p.id"><option :value="p.id" x-text="`${p.name} #${p.id}`"></option></template></select></label>
<label>Model<input x-model="roxanneProfile.model" placeholder="provider default"></label>
<label>Parameters<select x-model.number="roxanneProfile.parameter_profile_id"><option :value="null">none</option><template x-for="p in providerParams" :key="p.id"><option :value="p.id" x-text="p.name"></option></template></select></label>
<label>Reasoning<select x-model="roxanneProfile.reasoning_mode"><option value="inherit">inherit</option><option value="off">off</option><option value="on">on</option><option value="low">low</option><option value="medium">medium</option><option value="high">high</option></select></label>
<label><span><input type="checkbox" x-model="roxanneProfile.tools_enabled"> tools enabled</span></label>
<button @click="saveRoxanneProfile()">Save settings</button>
<h3>Static Memory</h3>
<input x-model="roxanneMemoryForm.title" placeholder="title">
<textarea x-model="roxanneMemoryForm.body" rows="4" placeholder="Roxanne-only memory"></textarea>
<input x-model="roxanneMemoryForm.tags" placeholder="tags">
<button @click="saveRoxanneMemory()">Add memory</button>
<template x-for="m in roxanneMemory" :key="m.id">
<div class="roxanne-memory-row">
<b x-text="m.title || ('memory '+m.id)"></b>
<button @click="deleteRoxanneMemory(m.id)">Delete</button>
<pre x-text="m.body"></pre>
</div>
</template>
<h3>Tools</h3>
<template x-for="t in roxanneTools" :key="t.name"><div class="mono" x-text="`${t.name} (${t.mode})`"></div></template>
</aside>
</div>
</section>
</template>
<template x-if="tab==='Commands'">
<section class="card">
<h2>Commands</h2>
<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
<select x-model="commandScopeType"><option value="global">global</option><option value="dm">dm</option><option value="group">group</option><option value="guild">guild</option></select>
<input x-model="commandScopeId" :disabled="commandScopeType==='global'" placeholder="scope id">
</div>
<input x-model="cmd" placeholder="!status">
<button @click="sendCommand()">Run</button>
<pre x-text="cmdResultText">
</pre>
</section>
</template>
<template x-if="tab==='Config'">
<section class="card">
<h2>Config</h2>
<button @click="load('/api/config','config')">Load redacted</button>
<pre x-text="pretty(config)">
</pre>
</section>
</template>
</main>
</div>
<footer class="live-tail">
<div class="tail-head">
<strong>Live tail</strong>
<span x-text="tail.length + ' events'"></span>
<span class="spacer"></span>
<button @click="tailPaused=!tailPaused" x-text="tailPaused?'Resume':'Pause'"></button>
<button @click="tail=[]">Clear</button>
</div>
<div class="tail-body">
<template x-for="(item,i) in tail" :key="i">
<div class="tail-line" :class="item.level">
<span class="time" x-text="item.time"></span>
<span class="type" x-text="item.type"></span>
<span class="text" x-text="item.text"></span>
</div>
</template>
<div class="tail-empty" x-show="tail.length===0">No live events yet.</div>
</div>
</footer>
<script>
function panel(){return{
tabs:['Dashboard','Providers','Provider Calls','Bot Entries','Scopes','Instructions','Logs','Debug','Channels','Prompts','Perms','Memory','WebChat','Tools','Skills','Tasks','Task Runs','Commands','Config','Roxanne'],
tab:'Dashboard',stats:{},botLogs:[],scopes:[],perms:[],memories:[],memoryEvents:[],memoryEventsMinutes:60,memoryEventsStatus:'',memoryEventsTimer:null,discordTags:[],memoryForm:{id:null,str_discord_id:'',str_annotations:'',array_tags:'',float_confidence:0.7},discordTagForm:{snowflake:'',label:'',kind:'user'},panelChat:[],config:{},tail:[],tailPaused:false,prompts:[],activePromptId:null,promptScopeType:'global',promptScopeId:'',promptBody:'',promptStatus:'',promptSaving:false,memQ:'',chat:'',cmd:'!status',commandScopeType:'global',commandScopeId:'',cmdResult:null,cmdResultText:'',tools:[],skills:[],tasks:[],assetScopeType:'global',assetScopeId:'',assetStatus:'',toolForm:{id:null,name:'',description:'',body:'',schema_json:'',executor_name:'',enabled:true,globally_disabled:false},skillForm:{id:null,name:'',description:'',body:'',enabled:true},taskFilterScopeType:'all',taskFilterScopeId:'',taskForm:{id:null,name:'',prompt:'',schedule_minutes:180,scope_type:'global',scope_id:'',enabled:true,provider_id:null,model:'',runtime_kind:'default'},taskStatus:'',providers:[],providerParams:[],providerCalls:[],providerSummary:[],providerStatus:'',providerForm:{id:null,name:'',provider_type:'ollama',base_url:'https://ollama.com',default_model:'llama3.2',api_key:'',timeout_s:120,enabled:true},botEntries:[],botEntryForm:{id:null,name:'dirac',description:'',enabled:true,persona:''},botEntryStatus:'',scopeForm:{scope_type:'global',scope_id:'',provider_id:null,model:''},scopeEffective:{},scopeStatus:'',instructions:[],instructionForm:{name:'default',scope_type:'global',scope_id:'',body:''},instructionStatus:'',taskRuns:[],logging:{levels:['trace','debug','info','warn','error'],components:[],config:{}},debugLogs:[],debugComponent:'provider',debugMinLevel:'debug',debugScopeType:'',debugScopeId:'',debugProviderHttp:false,debugStatus:'',levelRank:{trace:0,debug:1,info:2,warn:3,error:4},roxanneProfile:{},roxanneSessions:[],roxanneMessages:[],roxanneTools:[],roxanneMemory:[],roxanneMemoryForm:{title:'',body:'',tags:''},roxanneActiveSessionId:null,roxanneMessage:'',roxanneAnswer:null,roxanneBusy:false,roxanneStatus:'',roxanneScopeType:'global',roxanneScopeId:'',
async init(){try{let r=await fetch('/api/stats');if(r.status===401)location='/login';this.stats=await r.json();this.addTail({type:'stat',data:this.stats});await this.loadLogging();await this.loadTab(this.tab);let ws=new WebSocket((location.protocol==='https:'?'wss':'ws')+'://'+location.host+'/ws');ws.onmessage=e=>this.addTail(e.data)}catch(e){location='/login'}},
async load(u,k){let r=await fetch(u);if(r.status===401)location='/login';this[k]=await r.json()},
async selectTab(t){this.stopMemoryEventsRefresh();this.tab=t;await this.loadTab(t);if(t==='Memory')this.startMemoryEventsRefresh()},
memoryQuery(){let q=new URLSearchParams({limit:'100'});if(this.memQ)q.set('str_query',this.memQ);let f=this.memoryForm||{};if(f.str_discord_id)q.set('str_discord_id',f.str_discord_id);return '/api/memories?'+q.toString()},
async loadMemoryEvents(){let minutes=Number(this.memoryEventsMinutes||60);await this.load(`/api/memory-events?minutes=${minutes}&limit=200`,'memoryEvents');this.memoryEventsStatus=`Showing ${this.memoryEvents.length} events from last ${minutes} minutes. Updated ${new Date().toLocaleTimeString()}`},
startMemoryEventsRefresh(){this.stopMemoryEventsRefresh();this.memoryEventsTimer=setInterval(()=>{if(this.tab==='Memory')this.loadMemoryEvents();else this.stopMemoryEventsRefresh()},15000)},
stopMemoryEventsRefresh(){if(this.memoryEventsTimer){clearInterval(this.memoryEventsTimer);this.memoryEventsTimer=null}},
async loadMemory(){await this.load(this.memoryQuery(),'memories');await this.loadMemoryEvents();await this.load('/api/discord-identity-map','discordTags')},
memoryTagsLabel(m){let tags=m&&m.array_tags;if(Array.isArray(tags))return tags.join(', ')||'-';if(typeof tags==='string'){try{let parsed=JSON.parse(tags);if(Array.isArray(parsed))return parsed.join(', ')||'-'}catch(e){}return tags||'-'}return'-'},
editMemory(m){this.memoryForm={id:m.int_memory_id,str_discord_id:m.str_discord_id||'',str_annotations:m.str_annotations||'',array_tags:this.memoryTagsLabel(m)==='-'?'':this.memoryTagsLabel(m),float_confidence:m.float_confidence||0.7}},
async saveMemory(){let f=this.memoryForm;let payload={str_discord_id:f.str_discord_id,str_annotations:f.str_annotations,array_tags:f.array_tags||null,float_confidence:Number(f.float_confidence||0.7)};let r=await fetch(f.id?`/api/memories/${f.id}`:'/api/memories',{method:f.id?'PUT':'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});if(r.status===401)location='/login';if(r.ok)this.memoryForm={id:null,str_discord_id:'',str_annotations:'',array_tags:'',float_confidence:0.7};await this.loadMemory()},
async deleteMemory(id){let r=await fetch(`/api/memories/${id}`,{method:'DELETE'});if(r.status===401)location='/login';await this.loadMemory()},
async saveDiscordTag(){let f=this.discordTagForm;let r=await fetch('/api/discord-identity-map',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({snowflake:f.snowflake,label:f.label,kind:f.kind})});if(r.status===401)location='/login';if(r.ok)this.discordTagForm={snowflake:'',label:'',kind:'user'};await this.load('/api/discord-identity-map','discordTags')},
async loadTab(t){try{if(t==='Dashboard'){await this.loadProviders();await this.load('/api/provider-calls/summary','providerSummary');await this.loadTasks();await this.loadTaskRuns()}else if(t==='Providers'){await this.loadProviders()}else if(t==='Provider Calls'){await this.load('/api/provider-calls/summary','providerSummary');await this.load('/api/provider-calls','providerCalls')}else if(t==='Bot Entries'){await this.load('/api/bot-entries','botEntries')}else if(t==='Scopes'){await this.loadEffectiveScope()}else if(t==='Instructions'){await this.load('/api/instructions','instructions')}else if(t==='Logs'){await this.load('/api/bot-logs','botLogs')}else if(t==='Debug'){await this.loadLogging();await this.loadDebugLogs()}else if(t==='Channels'){await this.load('/api/scopes','scopes')}else if(t==='Prompts'){await this.loadPrompts()}else if(t==='Perms'){await this.load('/api/permissions','perms')}else if(t==='Memory'){await this.loadMemory()}else if(t==='Tools'){await this.loadAssets('tool')}else if(t==='Skills'){await this.loadAssets('skill')}else if(t==='Tasks'){await this.loadTasks()}else if(t==='Task Runs'){await this.loadTaskRuns()}else if(t==='Config'){await this.load('/api/config','config')}else if(t==='Roxanne'){await this.loadRoxanne()}}catch(e){this.addTail({type:'log',data:{level:'error',component:'panel',message:`${t} load failed: ${e}`}})}},
async openRoxanne(){await this.selectTab('Roxanne')},
async loadLogging(){let r=await fetch('/api/logging');if(r.status===401)location='/login';this.logging=await r.json();let cfg=this.logging.config||{};this.debugProviderHttp=!!cfg.provider_http_debug;if(cfg.console_level)this.debugMinLevel=cfg.console_level;return this.logging},
debugQuery(){let q=new URLSearchParams({min_level:this.debugMinLevel||'debug',limit:'200'});if(this.debugComponent)q.set('component',this.debugComponent);if(this.debugScopeType)q.set('scope_type',this.debugScopeType);if(this.debugScopeId)q.set('scope_id',this.debugScopeId);return '/api/bot-logs?'+q.toString()},
localizeLogRow(row){if(row&&!row.timestamp_local&&row.timestamp_utc){row.timestamp_local=new Date(row.timestamp_utc).toLocaleString('sv-SE',{timeZone:'Europe/Madrid'})+' Europe/Madrid'}return row},
formatTaskTime(t,kind){let local=t&&t[`${kind}_run_local`];let utc=t&&t[`${kind}_run_utc`];if(local)return local+' Europe/Madrid';if(!utc)return'-';return new Date(utc).toLocaleString('sv-SE',{timeZone:'Europe/Madrid'})+' Europe/Madrid'},
async loadDebugLogs(){let r=await fetch(this.debugQuery());if(r.status===401)location='/login';this.debugLogs=(await r.json()).map(row=>this.localizeLogRow(row));return this.debugLogs},
async saveLogging(){let cfg={...(this.logging.config||{})};cfg.console_level=this.debugMinLevel||'info';cfg.provider_http_debug=!!this.debugProviderHttp;cfg.component_levels={...(cfg.component_levels||{})};if(this.debugComponent)cfg.component_levels[this.debugComponent]=this.debugMinLevel||cfg.console_level;let r=await fetch('/api/logging',{method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify(cfg)});if(r.status===401)location='/login';let data=await r.json();this.debugStatus=r.ok?'Saved':'Save failed';if(data.config){this.logging.config=data.config;this.debugProviderHttp=!!data.config.provider_http_debug;}await this.loadDebugLogs()},
debugMatches(d){if(!d)return false;let lvl=this.levelRank[d.level||'info']??2;let min=this.levelRank[this.debugMinLevel||'debug']??1;if(lvl<min)return false;if(this.debugComponent&&d.component!==this.debugComponent)return false;if(this.debugScopeType&&d.scope_type!==this.debugScopeType)return false;if(this.debugScopeId&&(d.scope_id||'')!==this.debugScopeId)return false;return true},
debugDetail(row){let d=row&&row.detail!==undefined?row.detail:row&&row.detail_json;if(d===undefined||d===null||d==='')return'';if(typeof d==='string'){try{return this.pretty(JSON.parse(d))}catch(e){return d}}return this.pretty(d)},
async openConfig(){await this.selectTab('Config')},
async loadPrompts(){let r=await fetch('/api/prompts');if(r.status===401)location='/login';this.prompts=await r.json();if(this.prompts.length&&!this.activePromptId)this.selectPrompt(this.prompts[0]);return this.prompts},
promptLabel(p){return `${p.scope_type}:${p.scope_id||'*'} · ${(p.body||'').slice(0,42)}`},
promptEditorLabel(){return `Editing ${this.promptScopeType}:${this.promptScopeType==='global'?'*':(this.promptScopeId||'(scope id required)')}`},
selectPrompt(p){this.activePromptId=p.id;this.promptScopeType=p.scope_type;this.promptScopeId=p.scope_id||'';this.promptBody=p.body||'';this.promptStatus=`Loaded ${this.promptLabel(p)}`},
newPrompt(){this.activePromptId=null;this.promptScopeType='global';this.promptScopeId='';this.promptBody='';this.promptStatus='New global prompt'},
async savePrompt(){this.promptSaving=true;this.promptStatus='Saving...';let payload={scope_type:this.promptScopeType,scope_id:this.promptScopeType==='global'?null:this.promptScopeId,body:this.promptBody};let r=await fetch('/api/prompts',{method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});if(r.status===401)location='/login';if(!r.ok){this.promptStatus='Save failed';this.promptSaving=false;return}await this.loadPrompts();let match=this.prompts.find(p=>p.scope_type===payload.scope_type&&(p.scope_id||'')===(payload.scope_id||''));if(match)this.selectPrompt(match);this.promptStatus='Saved';this.promptSaving=false;this.addTail({type:'command',data:{command:'save prompt',accepted:true,reason:'ok'}})},
async sendChat(){let r=await fetch('/api/panel-chat',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({message:this.chat})});this.panelChat=await r.json()},
scopeIdFor(t,id){return (t==='global'||t==='all')?null:(id||null)},
scopeQuery(t,id){let sid=this.scopeIdFor(t,id);return sid?`&scope_id=${encodeURIComponent(sid)}`:''},
async sendCommand(){let r=await fetch('/api/command',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({scope_type:this.commandScopeType,scope_id:this.scopeIdFor(this.commandScopeType,this.commandScopeId),command:this.cmd,args:''})});if(r.status===401)location='/login';this.cmdResult=await r.json();this.cmdResultText=this.formatCommandResult(this.cmdResult)},
assetScopeReady(){return this.assetScopeType==='global'||!!this.assetScopeId},
async loadAssets(kind){if(!this.assetScopeReady()){this.assetStatus=`${this.assetScopeType} scope id required`;if(kind==='tool')this.tools=[];else this.skills=[];return []}let u=`/api/assets?asset_type=${kind}&scope_type=${this.assetScopeType}${this.scopeQuery(this.assetScopeType,this.assetScopeId)}`;let r=await fetch(u);if(r.status===401)location='/login';if(!r.ok){this.assetStatus=`Load failed ${r.status}`;if(kind==='tool')this.tools=[];else this.skills=[];return []}let data=await r.json();if(kind==='tool')this.tools=data;else this.skills=data;this.assetStatus='';return data},
editAsset(kind,a){let form=kind==='tool'?this.toolForm:this.skillForm;form.id=a.id;form.name=a.name||'';form.description=a.description||'';form.body=a.body||'';form.enabled=!!a.enabled;if(kind==='tool'){form.schema_json=a.schema_json||'';form.executor_name=a.executor_name||'';form.globally_disabled=!!a.globally_disabled}this.assetScopeType=a.scope_type||'global';this.assetScopeId=a.scope_id||'';this.assetStatus=`Editing ${a.name}`},
async saveAsset(kind){if(!this.assetScopeReady()){this.assetStatus=`${this.assetScopeType} scope id required`;return}let form=kind==='tool'?this.toolForm:this.skillForm;let payload={asset_type:kind,name:form.name,description:form.description,body:form.body||null,scope_type:this.assetScopeType,scope_id:this.scopeIdFor(this.assetScopeType,this.assetScopeId),enabled:form.enabled!==false};if(kind==='tool'){payload.schema_json=form.schema_json||null;payload.executor_name=form.executor_name||null;payload.globally_disabled=!!form.globally_disabled}let r;if(form.id){let patch={description:payload.description,body:payload.body,enabled:payload.enabled};if(kind==='tool'){patch.schema_json=payload.schema_json;patch.executor_name=payload.executor_name;patch.globally_disabled=payload.globally_disabled}r=await fetch(`/api/assets/${form.id}`,{method:'PATCH',headers:{'content-type':'application/json'},body:JSON.stringify(patch)})}else{r=await fetch('/api/assets',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)})}if(r.status===401)location='/login';this.assetStatus=r.ok?'Saved':'Save failed';await this.loadAssets(kind);if(r.ok){form.id=null;}},
async toggleAsset(kind,a){let r=await fetch(`/api/assets/${a.id}`,{method:'PATCH',headers:{'content-type':'application/json'},body:JSON.stringify({enabled:!a.enabled})});if(r.status===401)location='/login';await this.loadAssets(kind)},
async disableAssetEverywhere(a){let r=await fetch(`/api/assets/${a.id}`,{method:'PATCH',headers:{'content-type':'application/json'},body:JSON.stringify({enabled:false,globally_disabled:true})});if(r.status===401)location='/login';this.assetStatus=r.ok?'Disabled everywhere':'Disable failed';await this.loadAssets('tool')},
async restoreToolSnapshot(){let r=await fetch('/api/assets/snapshot/apply',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({version:'latest'})});if(r.status===401)location='/login';this.assetStatus=r.ok?'Snapshot restored':'Snapshot failed';await this.loadAssets('tool')},
async deleteAsset(kind,id){let r=await fetch(`/api/assets/${id}`,{method:'DELETE'});if(r.status===401)location='/login';this.assetStatus=r.ok?'Deleted':'Delete failed';await this.loadAssets(kind)},
async loadTasks(){let u='/api/tasks';if(this.taskFilterScopeType!=='all'){u+=`?scope_type=${this.taskFilterScopeType}&scope_id=${encodeURIComponent(this.scopeIdFor(this.taskFilterScopeType,this.taskFilterScopeId)||'')}`}let r=await fetch(u);if(r.status===401)location='/login';this.tasks=await r.json();return this.tasks},
editTask(t){this.taskForm={id:t.id,name:t.name||'',prompt:t.prompt||'',schedule_minutes:t.schedule_minutes||10,scope_type:t.scope_type||'global',scope_id:t.scope_id||'',enabled:!!t.enabled,provider_id:t.provider_id||null,model:t.model||'',runtime_kind:t.runtime_kind||'default'};this.taskStatus=`Editing ${t.name||t.id}`},
async saveTask(){let payload={...this.taskForm,scope_id:this.scopeIdFor(this.taskForm.scope_type,this.taskForm.scope_id)};let id=payload.id;delete payload.id;let r=await fetch(id?`/api/tasks/${id}`:'/api/tasks',{method:id?'PATCH':'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});if(r.status===401)location='/login';this.taskStatus=r.ok?'Saved':'Save failed';if(r.ok)this.taskForm.id=null;await this.loadTasks()},
async restoreTaskSnapshot(){let r=await fetch('/api/tasks/snapshot/apply',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({version:'latest'})});if(r.status===401)location='/login';this.taskStatus=r.ok?'Defaults restored':'Restore failed';await this.loadTasks()},
async runTask(id){let r=await fetch(`/api/tasks/${id}/run`,{method:'POST'});if(r.status===401)location='/login';await this.loadTasks()},
async disableTask(id){let r=await fetch(`/api/tasks/${id}/disable`,{method:'POST'});if(r.status===401)location='/login';await this.loadTasks()},
async deleteTask(id){let r=await fetch(`/api/tasks/${id}`,{method:'DELETE'});if(r.status===401)location='/login';await this.loadTasks()},
async loadProviders(){let r=await fetch('/api/providers');if(r.status===401)location='/login';this.providers=await r.json();return this.providers},
editProvider(p){this.providerForm={id:p.id,name:p.name||'',provider_type:p.provider_type||'ollama',base_url:p.base_url||'',default_model:p.default_model||'',api_key:'',timeout_s:p.timeout_s||120,enabled:!!p.enabled};this.providerStatus=`Editing ${p.name}`},
async saveProvider(){let payload={...this.providerForm};let id=payload.id;delete payload.id;if(!payload.api_key)delete payload.api_key;let r=await fetch(id?`/api/providers/${id}`:'/api/providers',{method:id?'PATCH':'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});if(r.status===401)location='/login';this.providerStatus=r.ok?'Saved':'Save failed';await this.loadProviders()},
async testProvider(id){let r=await fetch(`/api/providers/${id}/test`,{method:'POST'});if(r.status===401)location='/login';this.providerStatus=JSON.stringify(await r.json())},
async disableProvider(id){let r=await fetch(`/api/providers/${id}`,{method:'DELETE'});if(r.status===401)location='/login';await this.loadProviders()},
editBotEntry(b){this.botEntryForm={id:b.id,name:b.name||'',description:b.description||'',enabled:!!b.enabled,persona:b.persona||''};this.botEntryStatus=`Editing ${b.name}`},
async saveBotEntry(){let payload={...this.botEntryForm};let id=payload.id;delete payload.id;let r=await fetch(id?`/api/bot-entries/${id}`:'/api/bot-entries',{method:id?'PATCH':'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});if(r.status===401)location='/login';this.botEntryStatus=r.ok?'Saved':'Save failed';await this.load('/api/bot-entries','botEntries')},
async loadEffectiveScope(){let sid=this.scopeIdFor(this.scopeForm.scope_type,this.scopeForm.scope_id);let u=`/api/scopes/effective?scope_type=${this.scopeForm.scope_type}`+(sid?`&scope_id=${encodeURIComponent(sid)}`:'');let r=await fetch(u);if(r.status===401)location='/login';this.scopeEffective=await r.json()},
async saveScope(){let sid=this.scopeIdFor(this.scopeForm.scope_type,this.scopeForm.scope_id)||'*';let payload={provider_id:this.scopeForm.provider_id||null,model:this.scopeForm.model||null};let r=await fetch(`/api/scopes/${this.scopeForm.scope_type}/${encodeURIComponent(sid)}`,{method:'PATCH',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});if(r.status===401)location='/login';this.scopeStatus=r.ok?'Saved':'Save failed';await this.loadEffectiveScope()},
async saveInstruction(){let payload={...this.instructionForm,scope_id:this.scopeIdFor(this.instructionForm.scope_type,this.instructionForm.scope_id)};let r=await fetch('/api/instructions',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});if(r.status===401)location='/login';this.instructionStatus=r.ok?'Saved':'Save failed';await this.load('/api/instructions','instructions')},
async loadTaskRuns(){let r=await fetch('/api/task-runs');if(r.status===401)location='/login';this.taskRuns=await r.json();return this.taskRuns},
async loadProviderParams(){let r=await fetch('/api/provider-parameters');if(r.status===401)location='/login';this.providerParams=await r.json();return this.providerParams},
async loadRoxanne(){await this.loadProviders();await this.loadProviderParams();await this.load('/api/roxanne/profile','roxanneProfile');await this.load('/api/roxanne/sessions','roxanneSessions');await this.load('/api/roxanne/tools','roxanneTools');await this.load('/api/roxanne/memory','roxanneMemory');if(!this.roxanneActiveSessionId&&this.roxanneSessions.length){await this.loadRoxanneThread(this.roxanneSessions[0].id)}},
async loadRoxanneThread(id){this.roxanneActiveSessionId=id;await this.load(`/api/roxanne/sessions/${id}/messages`,'roxanneMessages')},
async newRoxanneThread(){let payload={title:'New Roxanne thread',active_scope_type:this.roxanneScopeType,active_scope_id:this.scopeIdFor(this.roxanneScopeType,this.roxanneScopeId)};let r=await fetch('/api/roxanne/sessions',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});if(r.status===401)location='/login';let data=await r.json();if(r.ok){this.roxanneActiveSessionId=data.id;this.roxanneMessages=[];await this.load('/api/roxanne/sessions','roxanneSessions');this.roxanneStatus='Thread created'}else this.roxanneStatus='Thread failed'},
nullableId(v){if(v===null||v===undefined||v===''||v==='null'||Number.isNaN(v))return null;let n=Number(v);return Number.isFinite(n)?n:null},
nullableText(v){let s=(v??'').toString().trim();return s?s:null},
async saveRoxanneProfile(){let p=this.roxanneProfile||{};let payload={provider_id:this.nullableId(p.provider_id),model:this.nullableText(p.model),parameter_profile_id:this.nullableId(p.parameter_profile_id),reasoning_mode:p.reasoning_mode||'inherit',tools_enabled:p.tools_enabled!==false,system_prompt:this.nullableText(p.system_prompt)};let r=await fetch('/api/roxanne/profile',{method:'PATCH',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});if(r.status===401)location='/login';this.roxanneStatus=r.ok?'Settings saved':'Settings failed';await this.load('/api/roxanne/profile','roxanneProfile')},
async saveRoxanneMemory(){let body=(this.roxanneMemoryForm.body||'').trim();if(!body){this.roxanneStatus='Memory body required';return}let r=await fetch('/api/roxanne/memory',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({...this.roxanneMemoryForm,body})});if(r.status===401)location='/login';this.roxanneStatus=r.ok?'Memory added':'Memory failed';if(r.ok)this.roxanneMemoryForm={title:'',body:'',tags:''};await this.load('/api/roxanne/memory','roxanneMemory')},
async deleteRoxanneMemory(id){let r=await fetch(`/api/roxanne/memory/${id}`,{method:'DELETE'});if(r.status===401)location='/login';this.roxanneStatus=r.ok?'Memory deleted':'Delete failed';await this.load('/api/roxanne/memory','roxanneMemory')},
async askRoxanne(){let text=(this.roxanneMessage||'').trim();if(!text)return;this.roxanneBusy=true;this.roxanneStatus='Thinking...';let payload={message:text,active_scope_type:this.roxanneScopeType,active_scope_id:this.scopeIdFor(this.roxanneScopeType,this.roxanneScopeId),session_id:this.roxanneActiveSessionId};let r=await fetch('/api/roxanne/ask',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});if(r.status===401)location='/login';this.roxanneAnswer=await r.json();this.roxanneStatus=r.ok?'Answered':'Ask failed';if(r.ok){this.roxanneActiveSessionId=this.roxanneAnswer.session_id;this.roxanneMessage='';await this.loadRoxanneThread(this.roxanneActiveSessionId);await this.load('/api/roxanne/sessions','roxanneSessions')}this.roxanneBusy=false},
roxanneRoleLabel(m){if(m.role==='operator')return'operator';if(m.role==='tool')return'tool result';return m.role||'message'},
roxanneToolSummary(m){let meta={};try{meta=JSON.parse(m.tool_calls_json||'{}')}catch(e){}let name=meta.name||'tool';let text=String(m.content||'');try{let data=JSON.parse(text);if(data&&data.ok===false&&data.error)return `${name}: ${data.error}`;if(data&&data.ok===true)return `${name}: ok`;if(Array.isArray(data))return `${name}: ${data.length} rows`}catch(e){}return `${name}: ${text.length} chars`},
prettyRoxanneTool(v){try{return JSON.stringify(JSON.parse(v),null,2)}catch(e){return String(v||'')}},
pretty(v){return JSON.stringify(v,null,2).replace(/\\\\r\\\\n/g,'\\n').replace(/\\\\n/g,'\\n')},
formatCommandResult(v){if(!v)return'';if(typeof v.result==='string')return v.result;if(typeof v.detail==='string')return v.detail;return this.pretty(v)},
addTail(raw){let ev=raw;try{if(typeof raw==='string')ev=JSON.parse(raw)}catch(e){ev={type:'raw',data:{text:String(raw)}}}if(ev&&ev.type==='bot_log'&&this.debugMatches(ev.data)){this.debugLogs=[this.localizeLogRow(ev.data),...this.debugLogs].slice(0,200)}if(this.tailPaused)return;let item=this.formatEvent(ev);this.tail.push(item);this.tail=this.tail.slice(-80)},
formatEvent(ev){let d=ev&&ev.data?ev.data:{};let type=(ev&&ev.type)||'event';let level=d.level||'';let text='';if(type==='message')text=`${d.scope_type||''}:${d.scope_id||''} author=${d.author_id||''} command=${!!d.is_command}`;else if(type==='ollama')text=`${d.scope_type||''}:${d.scope_id||''} model=${d.model||''} ${d.error?'error='+d.error:'ok'}`;else if(type==='command')text=`${d.source||'panel'} !${d.command||''} accepted=${d.accepted!==false} ${d.reason||''}`;else if(type==='bot_log'||type==='log')text=`${d.component||''} ${d.message||''}`;else if(type==='stat')text=`uptime=${d.uptime_s||0}s messages=${d.messages||0} model=${d.model||''}`;else text=typeof d.text==='string'?d.text:JSON.stringify(d);return{time:new Date().toLocaleTimeString(),type,level:level==='error'?'error':'',text}}
}}</script>
</body>
</html>
'''
LOGIN_HTML = '''
<!doctype html>
<html>
<body style="background:#0e0f12;color:#d7dae0;font-family:system-ui">
<form method="post" action="/login">
<h1>Dirac login</h1>
<input type="password" name="token" autofocus>
<button>Login</button>
</form>
</body>
</html>
'''
app=FastAPI(title='Dirac Panel'); app.state.db=None; app.state.provider_client=None; app.state.ollama=None; app.state.config=None; app.state.ws_clients=set(); app.state.auth_token=PANEL_AUTH_TOKEN; app.state.agent_run_tasks=set(); app.state.process_exit=None; app.state.news_task=None; app.state.runtime_task_group=None; app.state.runtime_logger=None

def make_legacy_provider_client(db,cfg=None):
    cfg=cfg if cfg is not None else getattr(app.state,'config',None)
    ollama_cfg=getattr(cfg,'ollama',{}) if cfg is not None else {}
    return LegacyProviderClient(
        db,
        ollama_cfg.get('endpoint','https://ollama.com') if isinstance(ollama_cfg,dict) else 'https://ollama.com',
        ollama_cfg.get('api_key','') if isinstance(ollama_cfg,dict) else '',
        ollama_cfg.get('default_model','llama3.2') if isinstance(ollama_cfg,dict) else 'llama3.2',
        ollama_cfg.get('request_timeout_s',120.0) if isinstance(ollama_cfg,dict) else 120.0,
        redacted_secret=REDACTED_SECRET,
        utc_now=utc_now,
        app_log=app_log,
        current_logging_config=current_logging_config,
        broadcast=broadcast,
        inject_runtime_request_context=inject_runtime_request_context,
        list_agent_assets=list_agent_assets,
        prompt_scope_types=PROMPT_SCOPE_TYPES,
        valid_asset_name=valid_asset_name,
        upsert=_upsert,
    )
def make_provider_client(db,cfg=None):
    mode=os.environ.get('DIRAC_PROVIDER_CLIENT','legacy').strip().lower()
    if mode == 'openai':
        return OpenAIProviderClient(os.environ.get('DIRAC_OPENAI_CONFIG') or 'openai.toml')
    if mode == 'sim':
        return SimProviderClient()
    return make_legacy_provider_client(db,cfg)
def provider_client_for_db(db=None):
    db=db if db is not None else getattr(app.state,'db',None)
    client=getattr(app.state,'provider_client',None)
    if client is not None and (db is None or getattr(client,'db',db) is db):
        return client
    previous=client
    client=make_provider_client(db)
    app.state.provider_client=client
    current_ollama=getattr(app.state,'ollama',None)
    if current_ollama is None or current_ollama is previous:
        app.state.ollama=client
    return client
async def list_service_providers(db,enabled_only=False):
    return await provider_client_for_db(db).list_providers(enabled_only)
async def get_provider(db,token):
    return await provider_client_for_db(db).get_provider(token)
def redact_provider(row):
    return provider_client_for_db().redact_provider(row)
async def sync_legacy_ollama_provider(db,cfg):
    return await provider_client_for_db(db).sync_config(cfg)
async def resolve_provider_binding(db,scope_type='panel',scope_id=None,user_id=None,task_id=None,bot_entry_id=None,roxanne_profile_id=None,model=None,params=None):
    return await provider_client_for_db(db).resolve_binding(scope_type,scope_id,user_id=user_id,task_id=task_id,bot_entry_id=bot_entry_id,roxanne_profile_id=roxanne_profile_id,model=model,params=params)
async def reasoning_for_scope(db,scope_type,scope_id):
    return await provider_client_for_db(db).reasoning_for_scope(scope_type,scope_id)
async def test_provider_connection(db,provider):
    return await provider_client_for_db(db).test_provider(provider)
def active_config_path():
    return getattr(app.state,'config_path',CONFIG_PATH)
def runtime_logger():
    logger=getattr(app.state,'runtime_logger',None)
    if logger is None:
        logger=dirac_logging.RuntimeLogger(
            get_db=lambda: getattr(app.state,'db',None),
            get_config=lambda: getattr(app.state,'config',None),
            set_config=lambda cfg: setattr(app.state,'config',cfg),
            persist_config=persist_runtime_config,
            broadcast=broadcast,
            known_secret_values=known_secret_values,
            redact_runtime_rows=redact_runtime_rows,
            utc_now=utc_now,
            madrid_now=madrid_now,
            madrid_from_utc=madrid_from_utc,
            local_timezone_name=LOCAL_TIMEZONE_NAME,
        )
        app.state.runtime_logger=logger
    return logger
async def get_db():
    if app.state.db is None:
        app.state.db=await aiosqlite.connect(':memory:'); await bootstrap_db(app.state.db)
    return app.state.db
async def db_log_error(component, message, exc):
    await db_log_failure(component,message,{'error':type(exc).__name__,'detail':str(exc),'traceback':traceback.format_exc()})
async def db_log_failure(component,message,detail):
    await app_log('error',component,message,detail)
async def app_log(level,component,message,detail=None,scope_type=None,scope_id=None,force_console=False):
    await runtime_logger().app_log(level,component,message,detail,scope_type,scope_id,force_console)
def discord_message_chunks(text,limit=DISCORD_MESSAGE_LIMIT):
    message_text=str(text)
    if len(message_text)<=limit:
        return [message_text]
    fenced=re.match(r'^```([^\n`]*)\n(.*)\n```$',message_text,re.S)
    if fenced:
        language=fenced.group(1)
        body=fenced.group(2)
        wrapper_open=f'```{language}\n'; wrapper_close='\n```'
        body_limit=max(100,limit-len(wrapper_open)-len(wrapper_close))
        return [wrapper_open+chunk+wrapper_close for chunk in split_discord_text(body,body_limit)]
    return split_discord_text(message_text,min(limit,DISCORD_SAFE_MESSAGE_LIMIT))
def split_discord_text(text,limit=DISCORD_SAFE_MESSAGE_LIMIT):
    remaining=str(text)
    chunks=[]
    while remaining:
        if len(remaining)<=limit:
            chunks.append(remaining); break
        cut=remaining.rfind('\n',0,limit+1)
        if cut < max(1,int(limit*0.45)):
            cut=remaining.rfind(' ',0,limit+1)
        if cut < max(1,int(limit*0.25)):
            cut=limit
        chunk=remaining[:cut].rstrip()
        if not chunk:
            chunk=remaining[:limit]
            cut=limit
        chunks.append(chunk)
        remaining=remaining[cut:].lstrip('\n ')
    return chunks
def format_discord_command_response(text):
    return context_filters.format_dirac_block(text)
def format_dirac_error(message,**fields):
    lines=[f'ERROR: {message}']
    for key,value in fields.items():
        if value is None:
            continue
        lines.append(f'{key}={value}')
    return context_filters.format_dirac_block('\n'.join(lines))
async def send_discord_text(send,text):
    if not callable(send):
        await db_log_error('discord','discord reply send failed',RuntimeError('message channel has no callable send'))
        return False
    for chunk in discord_message_chunks(text):
        try:
            await send(chunk)
        except Exception as e:
            await db_log_error('discord','discord reply send failed',e)
            return False
    return True
async def send_discord_reply(message,text):
    reply=getattr(message,'reply',None)
    if callable(reply):
        try:
            for chunk in discord_message_chunks(text):
                try:
                    await reply(chunk,mention_author=False)
                except TypeError:
                    await reply(chunk)
            return True
        except Exception as e:
            await db_log_error('discord','discord message reply failed; falling back to channel send',e)
    ch=getattr(message,'channel',None)
    return await send_discord_text(getattr(ch,'send',None),text)
def normalize_news_text(text):
    return news_mod.normalize_news_text(text)
def tech_news_limit(limit):
    return news_mod.tech_news_limit(limit)
def is_acceptable_tech_news(title):
    return news_mod.is_acceptable_tech_news(title)
def add_tech_news_item(items,title,link,source,limit):
    if len(items)>=limit: return True
    item=news_mod.news_item(title,link,source,'grounding')
    if not item: return False
    key=news_mod.normalize_news_key(item['title'])
    if key in {i.get('key') for i in items}: return False
    items.append({'title':item['title'],'link':item['url'],'url':item['url'],'source':item['source'],'source_kind':item['source_kind'],'published_at_utc':item['published_at_utc'],'date_status':item['date_status'],'key':key})
    return len(items)>=limit
async def fetch_artificial_analysis_articles(client,limit):
    return await news_mod.fetch_artificial_analysis_articles(client,limit)
async def fetch_known_news(limit=news_mod.KNOWN_NEWS_LIMIT):
    return await news_mod.fetch_known_news(limit)
async def fetch_exploratory_news(limit=news_mod.EXPLORATORY_NEWS_LIMIT,fetcher=None):
    return await news_mod.fetch_exploratory_news(limit,fetcher=fetcher or run_web_fetch)
async def fetch_ai_tech_news(limit=TECH_NEWS_MAX_ITEMS):
    return await news_mod.fetch_ai_tech_news(limit)
async def fetch_international_news(limit=TECH_NEWS_MAX_ITEMS):
    return await fetch_ai_tech_news(limit)
async def build_news_summary(db,ollama,scope_type='scheduler',scope_id=None,store_memory=True,news_channel_id=None):
    known_items=await fetch_known_news(news_mod.KNOWN_NEWS_LIMIT*3)
    exploratory_items=await fetch_exploratory_news(news_mod.EXPLORATORY_NEWS_LIMIT,fetcher=run_web_fetch)
    all_items=list(known_items or [])+list(exploratory_items or [])
    if not all_items:
        try:
            await app_log('warn','news','news fetch returned no items',{'sources':['Artificial Analysis']+[s for s,_ in AI_TECH_NEWS_FEEDS],'exploratory_queries':news_mod.EXPLORATORY_NEWS_QUERIES})
        except Exception:
            pass
        return 'No AI/model news feed items could be fetched right now.'
    for item in all_items:
        try:
            await news_mod.upsert_news_item(db,item)
        except Exception as e:
            await app_log('debug','news','news item persistence skipped',{'error':type(e).__name__,'title':item.get('title'),'url':item.get('url') or item.get('link')})
    candidates=await news_mod.select_news_candidates(db,known_items,exploratory_items)
    previous_items=await news_mod.recent_posted_news(db,30)
    payload=news_mod.build_news_prompt_payload(db,candidates,previous_items)
    summary=payload['fallback']
    if ollama is not None:
        try:
            resp=await ollama.chat([
                {'role':'system','content':'Summarize AI/model news for a Discord channel using the supplied grounding and exploratory candidates. Do not repeat recently posted items unless no fresh alternatives exist. Include dates when available and write "date unknown" when unavailable. Keep source links visible. Stay under 1800 characters.'},
                {'role':'user','content':payload['prompt']},
            ],scope_type='news',scope_id=scope_id,source='news')
            summary=(resp.get('message') or {}).get('content','') if isinstance(resp,dict) else ''
            summary=summary or payload['fallback']
        except Exception:
            summary=payload['fallback']
    if payload.get('repeating') and 'No fresh unseen items found' not in summary:
        summary='No fresh unseen items found; repeating latest known sources.\n'+summary
    if len(summary)>1800:
        summary=summary[:1750].rsplit('\n',1)[0]+'\n\n[trimmed for Discord]'
    selected_items=payload.get('items') or []
    if selected_items:
        try:
            await news_mod.mark_news_items_posted(db,selected_items)
        except Exception as e:
            await app_log('warn','news','news posted-state update failed',{'error':type(e).__name__})
    if store_memory:
        try:
            note=news_mod.memory_note_for_summary(summary,selected_items)
            await MemoryManager(db).add(str(news_channel_id or NEWS_CHANNEL_ID),note[:MAX_MEMORY_NOTE_LENGTH],['news','ai','tech'],0.8,'bot')
        except Exception:
            pass
    return summary
async def discord_channel_for_id(client,channel_id):
    channel=None
    getter=getattr(client,'get_channel',None)
    if callable(getter):
        try: channel=getter(int(channel_id))
        except Exception: channel=getter(str(channel_id))
    if channel is None:
        fetcher=getattr(client,'fetch_channel',None)
        if callable(fetcher):
            try: channel=await fetcher(int(channel_id))
            except Exception: channel=None
    return channel
async def news_scheduler(client,db,ollama,cfg):
    bot_cfg=cfg.bot if hasattr(cfg,'bot') else {}
    channel_id=str(bot_cfg.get('news_channel_id',NEWS_CHANNEL_ID))
    quick_interval=max(5,int(bot_cfg.get('news_summary_interval_minutes',180)))
    memory_interval=max(5,int(bot_cfg.get('news_memory_interval_minutes',420)))
    nickname=str(getattr(getattr(client,'user',None),'name',None) or getattr(getattr(client,'user',None),'display_name',None) or 'Dirac')
    channel=await discord_channel_for_id(client,channel_id)
    if channel is None:
        await db_log_failure('news','news channel not found',{'channel_id':channel_id})
        return
    while runtime_control.background_suspended():
        await asyncio.sleep(5)
    await app_log('info','news','news scheduler ready',{'channel_id':channel_id,**app_build_info()})
    await send_discord_text(getattr(channel,'send',None),startup_discord_banner(nickname))
    summary=await build_news_summary(db,ollama,'guild',channel_id,store_memory=True,news_channel_id=channel_id)
    await send_discord_text(getattr(channel,'send',None),summary)
    last_memory=time.time()
    while True:
        await asyncio.sleep(quick_interval*60)
        if runtime_control.background_suspended():
            continue
        now=time.time()
        store_memory=(now-last_memory)>=memory_interval*60
        summary=await build_news_summary(db,ollama,'guild',channel_id,store_memory=store_memory,news_channel_id=channel_id)
        if store_memory: last_memory=now
        await send_discord_text(getattr(channel,'send',None),summary)
async def require_auth(session: str|None=Cookie(default=None)):
    if not session or session!=app.state.auth_token: raise HTTPException(status_code=401,detail='unauthorized')
    return True
@app.get('/login',response_class=HTMLResponse)
async def login_form(): return LOGIN_HTML
@app.post('/login')
async def login(request:Request):
    form=await request.form()
    if form.get('token')!=app.state.auth_token: return JSONResponse({'detail':'unauthorized'},status_code=401)
    r=RedirectResponse('/',status_code=303); r.set_cookie('session', app.state.auth_token, httponly=True, samesite='lax', secure=request.url.scheme == 'https'); return r
@app.get('/',response_class=HTMLResponse)
async def index(session: str|None=Cookie(default=None)):
    if not session or session!=app.state.auth_token:
        return RedirectResponse('/login',status_code=303)
    return PANEL_HTML
def current_ollama_model():
    ollama=app.state.ollama
    if ollama is not None:
        model=getattr(ollama,'model',None) or getattr(ollama,'default_model',None)
        if model: return model
    config=app.state.config
    if isinstance(config,dict):
        ollama_cfg=config.get('ollama')
        if isinstance(ollama_cfg,dict):
            model=ollama_cfg.get('default_model')
            if model: return model
    elif config is not None:
        ollama_cfg=getattr(config,'ollama',None)
        if isinstance(ollama_cfg,dict):
            model=ollama_cfg.get('default_model')
        else:
            model=getattr(ollama_cfg,'default_model',None)
        if model: return model
    return 'llama3.2'
@app.get('/api/stats')
async def api_stats(_=Depends(require_auth),db=Depends(get_db)):
    cur=await db.execute('SELECT COUNT(*) FROM messages'); return {'uptime_s':int(time.time()-STARTED_AT),'messages':(await cur.fetchone())[0],'model':current_ollama_model(),'version':APP_VERSION}
async def rows(cur):
    data=await cur.fetchall(); return [dict(zip([c[0] for c in cur.description],r)) for r in data]
@app.get('/api/messages')
async def api_messages(scope_type=None,scope_id=None,q=None,since=None,limit:int=Query(50,ge=1,le=500),_=Depends(require_auth),db=Depends(get_db)):
    params=[]
    if q: sql='SELECT m.* FROM messages m JOIN messages_fts f ON f.rowid=m.id WHERE messages_fts MATCH ?'; params.append(quote_fts5_query(q))
    else: sql='SELECT * FROM messages WHERE 1=1'
    if scope_type: sql+=' AND scope_type=?'; params.append(scope_type)
    if scope_id: sql+=(' AND m.scope_id=?' if q else ' AND scope_id=?'); params.append(scope_id)
    if since: sql+=' AND timestamp_utc>=?'; params.append(since)
    sql+=' ORDER BY id DESC LIMIT ?'; params.append(limit)
    try: return await rows(await db.execute(sql,tuple(params)))
    except aiosqlite.Error: raise HTTPException(status_code=400,detail='invalid search query')
@app.get('/api/ollama-log')
async def api_ollama_log(scope_id=None,limit:int=Query(50,ge=1,le=500),_=Depends(require_auth),db=Depends(get_db)):
    sql='SELECT * FROM ollama_log WHERE 1=1'; p=[]
    if scope_id: sql+=' AND scope_id=?'; p.append(scope_id)
    sql+=' ORDER BY id DESC LIMIT ?'; p.append(limit); return await rows(await db.execute(sql,tuple(p)))
@app.get('/api/bot-logs')
async def api_bot_logs(level=None,min_level=None,component=None,scope_type=None,scope_id=None,limit:int=Query(50,ge=1,le=500),_=Depends(require_auth),db=Depends(get_db)):
    sql='SELECT * FROM bot_logs WHERE 1=1'; p=[]
    if level: sql+=' AND level=?'; p.append(level)
    if min_level:
        threshold=dirac_logging.LOG_LEVEL_ORDER.get(dirac_logging.normalize_log_level(min_level),dirac_logging.LOG_LEVEL_ORDER['info'])
        allowed=[name for name,idx in dirac_logging.LOG_LEVEL_ORDER.items() if idx>=threshold]
        sql+=' AND level IN ('+','.join('?'*len(allowed))+')'; p.extend(allowed)
    if component: sql+=' AND component=?'; p.append(component)
    if scope_type: sql+=' AND scope_type=?'; p.append(scope_type)
    if scope_id: sql+=' AND scope_id=?'; p.append(scope_id)
    sql+=' ORDER BY id DESC LIMIT ?'; p.append(limit)
    out=await rows(await db.execute(sql,tuple(p)))
    for row in out:
        row['timestamp_local']=madrid_from_utc(row.get('timestamp_utc'))
        row['timezone']=LOCAL_TIMEZONE_NAME
    return out
class LoggingConfigIn(BaseModel):
    console_level:Literal['trace','debug','info','warn','error']='info'
    component_levels:dict[str,Literal['trace','debug','info','warn','error']]=Field(default_factory=dict)
    provider_http_debug:bool=False
@app.get('/api/logging')
async def api_logging(_=Depends(require_auth)):
    cfg=current_logging_config()
    return {'levels':list(dirac_logging.LOG_LEVELS),'components':list(dirac_logging.DEFAULT_LOG_COMPONENTS),'config':cfg}
@app.put('/api/logging')
async def api_put_logging(data:LoggingConfigIn,_=Depends(require_auth)):
    cfg=await set_runtime_logging_config(data.model_dump())
    await app_log('info','panel','logging configuration updated',cfg)
    return {'ok':True,'config':cfg}
@app.get('/api/commands-log')
async def api_commands_log(limit:int=Query(50,ge=1,le=500),_=Depends(require_auth),db=Depends(get_db)): return await rows(await db.execute('SELECT * FROM commands_log ORDER BY id DESC LIMIT ?',(limit,)))
@app.get('/api/scopes')
async def api_scopes(_=Depends(require_auth),db=Depends(get_db)): return await rows(await db.execute('SELECT scope_type,scope_id,MAX(timestamp_utc) last_activity,COUNT(*) message_count FROM messages GROUP BY scope_type,scope_id ORDER BY last_activity DESC'))
@app.get('/api/prompts')
async def api_prompts(_=Depends(require_auth),db=Depends(get_db)): return await rows(await db.execute('SELECT * FROM prompts ORDER BY id DESC'))
class PromptIn(BaseModel): scope_type:Literal['global','dm','group','guild']; scope_id:str|None=None; body:str=Field(max_length=MAX_PROMPT_LENGTH)
@app.put('/api/prompts')
async def api_put_prompts(data:PromptIn,_=Depends(require_auth),db=Depends(get_db)):
    sid=normalize_scope_id(data.scope_type,data.scope_id)
    if not valid_scope_pair(data.scope_type,sid): raise HTTPException(status_code=400,detail='invalid scope/scope_id combination')
    await set_prompt(db,data.scope_type,sid,data.body,'panel')
    return {'ok':True}
@app.get('/api/permissions')
async def api_permissions(_=Depends(require_auth),db=Depends(get_db)): return await rows(await db.execute('SELECT * FROM permissions ORDER BY id DESC'))
class PermIn(BaseModel): user_id:str; scope_type:Literal['global','dm','group','guild']='global'; scope_id:str|None=None; level:Literal['root','admin','user','blocked']='user'
@app.post('/api/permissions')
async def api_post_permissions(data:PermIn,_=Depends(require_auth),db=Depends(get_db)):
    sid=normalize_scope_id(data.scope_type,data.scope_id)
    if not valid_scope_pair(data.scope_type,sid): raise HTTPException(status_code=400,detail='invalid scope/scope_id combination')
    if is_root_operator(data.user_id) and (data.level!='root' or data.scope_type!='global' or sid is not None):
        raise HTTPException(status_code=400,detail='root permission is protected')
    await _upsert(db,'permissions',['user_id','scope_type','scope_id'],[data.user_id,data.scope_type,sid],{'level':data.level,'added_at':utc_now()})
    return {'ok':True}
@app.delete('/api/permissions/{perm_id}')
async def api_delete_permissions(perm_id:int,_=Depends(require_auth),db=Depends(get_db)):
    cur=await db.execute('SELECT user_id,level FROM permissions WHERE id=?',(perm_id,))
    row=await cur.fetchone()
    if not row: raise HTTPException(status_code=404,detail='permission not found')
    if is_root_operator(row[0]) or row[1]=='root': raise HTTPException(status_code=400,detail='root permission is protected')
    await db.execute('DELETE FROM permissions WHERE id=?',(perm_id,)); await db.commit(); return {'ok':True}
@app.get('/api/memories')
async def api_memories(str_discord_id=None,str_query=None,pending:bool|None=None,limit:int=Query(50,ge=1,le=500),_=Depends(require_auth),db=Depends(get_db)): return await MemoryManager(db).search(str_discord_id,str_query,pending,limit)
class MemoryIn(BaseModel):
    str_discord_id:str
    str_annotations:str=Field(max_length=MAX_MEMORY_NOTE_LENGTH)
    array_tags:list[str]|str|None=Field(default=None)
    float_confidence:float=Field(default=0.7,ge=0.0,le=1.0)
@app.post('/api/memories')
async def api_post_memories(data:MemoryIn,_=Depends(require_auth),db=Depends(get_db)):
    try:
        return {'int_memory_id':await MemoryManager(db).add(data.str_discord_id,data.str_annotations,data.array_tags,data.float_confidence,'operator')}
    except ValueError as e:
        raise HTTPException(status_code=422,detail=str(e))
@app.put('/api/memories/{memory_id}')
async def api_put_memories(memory_id:int,data:MemoryIn,_=Depends(require_auth),db=Depends(get_db)):
    try:
        return {'int_memory_id':await MemoryManager(db).update(memory_id,data.str_annotations,data.array_tags,data.float_confidence,'operator')}
    except KeyError:
        raise HTTPException(status_code=404,detail='memory not found')
    except ValueError as e:
        raise HTTPException(status_code=422,detail=str(e))
@app.delete('/api/memories/{memory_id}')
async def api_delete_memories(memory_id:int,_=Depends(require_auth),db=Depends(get_db)): await MemoryManager(db).delete(memory_id); return {'ok':True}
@app.post('/api/memories/{memory_id}/approve')
async def api_approve_memory(memory_id:int,_=Depends(require_auth),db=Depends(get_db)): await MemoryManager(db).approve(memory_id); return {'ok':True}
@app.get('/api/memory-events')
async def api_memory_events(minutes:int=Query(10,ge=1,le=1440),limit:int=Query(100,ge=1,le=500),_=Depends(require_auth),db=Depends(get_db)):
    return await recent_memory_events(db,minutes,limit)
class DiscordTagIn(BaseModel):
    snowflake:str=Field(min_length=1,max_length=64)
    label:str=Field(min_length=1,max_length=255)
    kind:Literal['user','channel','guild','unknown']|None='unknown'
@app.get('/api/discord-identity-map')
async def api_discord_identity_map(limit:int=Query(200,ge=1,le=500),_=Depends(require_auth),db=Depends(get_db)):
    return await rows(await db.execute('SELECT snowflake,label,kind,source,created_at,updated_at FROM discord_identity_map ORDER BY updated_at DESC LIMIT ?',(limit,)))
@app.post('/api/discord-identity-map')
async def api_post_discord_identity_map(data:DiscordTagIn,_=Depends(require_auth),db=Depends(get_db)):
    result=await discord_identity_tag(db,data.snowflake,data.label,data.kind,'panel')
    if not result.get('ok'):
        raise HTTPException(status_code=400,detail=result.get('error'))
    return result
class AssetIn(BaseModel):
    model_config=ConfigDict(populate_by_name=True)
    asset_type:Literal['tool','skill']
    name:str=Field(min_length=1,max_length=64)
    description:str=Field(min_length=1,max_length=MAX_ASSET_DESCRIPTION_LENGTH)
    body:str|None=Field(default=None,max_length=MAX_ASSET_BODY_LENGTH)
    tool_schema_json:Any|None=Field(default=None,alias='schema_json')
    executor_name:str|None=Field(default=None,max_length=64)
    globally_disabled:bool=False
    scope_type:Literal['global','dm','group','guild']='global'
    scope_id:str|None=None
    enabled:bool=True
class AssetPatchIn(BaseModel):
    model_config=ConfigDict(populate_by_name=True)
    description:str|None=Field(default=None,min_length=1,max_length=MAX_ASSET_DESCRIPTION_LENGTH)
    body:str|None=Field(default=None,max_length=MAX_ASSET_BODY_LENGTH)
    tool_schema_json:Any|None=Field(default=None,alias='schema_json')
    executor_name:str|None=Field(default=None,max_length=64)
    globally_disabled:bool|None=None
    enabled:bool|None=None
class ToolSnapshotApplyIn(BaseModel):
    version:str|None='latest'
@app.get('/api/assets')
async def api_assets(asset_type:Literal['tool','skill']='tool',scope_type:Literal['global','dm','group','guild']='global',scope_id:str|None=None,effective:bool=False,enabled_only:bool=False,_=Depends(require_auth),db=Depends(get_db)):
    sid=normalize_scope_id(scope_type,scope_id)
    if not valid_scope_pair(scope_type,sid): raise HTTPException(status_code=400,detail='invalid scope/scope_id combination')
    return await list_agent_assets(db,asset_type,scope_type,sid,True,effective,enabled_only)
@app.post('/api/assets')
async def api_post_assets(data:AssetIn,_=Depends(require_auth),db=Depends(get_db)):
    sid=normalize_scope_id(data.scope_type,data.scope_id)
    if not valid_scope_pair(data.scope_type,sid) or not valid_asset_name(data.name): raise HTTPException(status_code=400,detail='invalid asset or scope')
    try:
        aid=await save_agent_asset(db,data.asset_type,data.name,data.description,data.body,'panel',data.scope_type,sid,data.enabled,schema_json=data.tool_schema_json,executor_name=data.executor_name,globally_disabled=data.globally_disabled)
    except ValueError as e:
        raise HTTPException(status_code=400,detail=str(e))
    return {'id':aid,'ok':True}
@app.post('/api/assets/snapshot/apply')
async def api_apply_tool_snapshot(data:ToolSnapshotApplyIn,_=Depends(require_auth),db=Depends(get_db)):
    try:
        return await apply_builtin_tool_snapshot(db,data.version or 'latest',created_by='panel',preserve_state=True)
    except ValueError as e:
        raise HTTPException(status_code=404,detail=str(e))
@app.patch('/api/assets/{asset_id}')
async def api_patch_assets(asset_id:int,data:AssetPatchIn,_=Depends(require_auth),db=Depends(get_db)):
    cur=await db.execute('SELECT asset_type,name,scope_type,description,body,enabled,schema_json,executor_name,globally_disabled FROM agent_assets WHERE id=?',(asset_id,))
    row=await cur.fetchone()
    if not row: raise HTTPException(status_code=404,detail='asset not found')
    asset_type,name,scope_type=row[0],row[1],row[2]
    description=data.description if data.description is not None else row[3]
    body=data.body if data.body is not None else row[4]
    enabled=row[5] if data.enabled is None else int(data.enabled)
    try:
        schema_json=row[6] if data.tool_schema_json is None else normalize_tool_schema_json(data.tool_schema_json,name)
        executor_name=row[7] if data.executor_name is None else normalize_executor_name(asset_type,data.executor_name)
    except ValueError as e:
        raise HTTPException(status_code=400,detail=str(e))
    if data.globally_disabled is None:
        globally_disabled=int(row[8] or 0)
        if data.enabled is not None and asset_type=='tool' and scope_type=='global':
            globally_disabled=0 if data.enabled else 1
    else:
        globally_disabled=int(bool(data.globally_disabled)) if asset_type=='tool' and scope_type=='global' else 0
        if data.globally_disabled:
            enabled=0
    await db.execute('UPDATE agent_assets SET description=?,body=?,enabled=?,schema_json=?,executor_name=?,globally_disabled=?,updated_at=? WHERE id=?',(description,body,enabled,schema_json,executor_name,globally_disabled,utc_now(),asset_id)); await db.commit()
    return {'ok':True}
@app.delete('/api/assets/{asset_id}')
async def api_delete_assets(asset_id:int,_=Depends(require_auth),db=Depends(get_db)):
    cur=await db.execute('SELECT id FROM agent_assets WHERE id=?',(asset_id,))
    row=await cur.fetchone()
    if not row: raise HTTPException(status_code=404,detail='asset not found')
    await db.execute('DELETE FROM agent_assets WHERE id=?',(asset_id,))
    await db.commit(); return {'ok':True}
class InstructionIn(BaseModel):
    name:str=Field(min_length=1,max_length=100)
    scope_type:Literal['global','guild','channel','dm','group','user','bot_entry','task','roxanne']='global'
    scope_id:str|None=None
    body:str=Field(min_length=1,max_length=MAX_PROMPT_LENGTH)
@app.get('/api/instructions')
async def api_instructions(scope_type:str|None=None,scope_id:str|None=None,_=Depends(require_auth),db=Depends(get_db)):
    sql='SELECT * FROM instructions WHERE 1=1'; p=[]
    if scope_type: sql+=' AND scope_type=?'; p.append(scope_type)
    if scope_id: sql+=' AND scope_id=?'; p.append(scope_id)
    sql+=' ORDER BY id DESC'
    return await rows(await db.execute(sql,tuple(p)))
@app.post('/api/instructions')
async def api_post_instruction(data:InstructionIn,_=Depends(require_auth),db=Depends(get_db)):
    sid=normalize_scope_id(data.scope_type,data.scope_id)
    if data.scope_type in EXTENDED_SCOPE_TYPES and not valid_extended_scope_pair(data.scope_type,sid):
        raise HTTPException(status_code=400,detail='invalid scope/scope_id combination')
    now=utc_now()
    await _upsert(db,'instructions',['scope_type','scope_id','name'],[data.scope_type,sid,data.name],{'body':data.body,'created_by':'panel','created_at':now,'updated_at':now})
    return {'ok':True}
@app.patch('/api/instructions/{instruction_id}')
async def api_patch_instruction(instruction_id:int,data:InstructionIn,_=Depends(require_auth),db=Depends(get_db)):
    cur=await db.execute('SELECT id FROM instructions WHERE id=?',(instruction_id,))
    if not await cur.fetchone(): raise HTTPException(status_code=404,detail='instruction not found')
    sid=normalize_scope_id(data.scope_type,data.scope_id)
    await db.execute('UPDATE instructions SET name=?,scope_type=?,scope_id=?,body=?,updated_at=? WHERE id=?',(data.name,data.scope_type,sid,data.body,utc_now(),instruction_id))
    await db.commit()
    return {'ok':True}
@app.delete('/api/instructions/{instruction_id}')
async def api_delete_instruction(instruction_id:int,_=Depends(require_auth),db=Depends(get_db)):
    await db.execute('DELETE FROM instructions WHERE id=?',(instruction_id,)); await db.commit(); return {'ok':True}
class ProviderIn(BaseModel):
    name:str=Field(min_length=1,max_length=64)
    provider_type:Literal['ollama','openrouter','openai_compatible']='ollama'
    base_url:str=Field(min_length=1,max_length=500)
    default_model:str=Field(min_length=1,max_length=200)
    api_key:str|None=Field(default=None,max_length=1000)
    enabled:bool=True
    timeout_s:float=Field(default=120.0,gt=0,le=600)
    supports_tools:bool|None=None
    supports_reasoning:bool|None=None
    supports_temperature:bool|None=None
    supports_streaming:bool|None=None
class ProviderPatchIn(BaseModel):
    name:str|None=Field(default=None,min_length=1,max_length=64)
    provider_type:Literal['ollama','openrouter','openai_compatible']|None=None
    base_url:str|None=Field(default=None,min_length=1,max_length=500)
    default_model:str|None=Field(default=None,min_length=1,max_length=200)
    api_key:str|None=Field(default=None,max_length=1000)
    enabled:bool|None=None
    timeout_s:float|None=Field(default=None,gt=0,le=600)
    supports_tools:bool|None=None
    supports_reasoning:bool|None=None
    supports_temperature:bool|None=None
    supports_streaming:bool|None=None
@app.get('/api/providers')
async def api_providers(_=Depends(require_auth),db=Depends(get_db)):
    client=provider_client_for_db(db)
    return [client.redact_provider(r) for r in await client.list_providers()]
@app.post('/api/providers')
async def api_post_provider(data:ProviderIn,_=Depends(require_auth),db=Depends(get_db)):
    try:
        return await provider_client_for_db(db).create_provider(data)
    except ValueError as e:
        raise HTTPException(status_code=400,detail=str(e))
@app.get('/api/providers/{provider_id}')
async def api_provider(provider_id:int,_=Depends(require_auth),db=Depends(get_db)):
    client=provider_client_for_db(db)
    row=await client.get_provider(provider_id)
    if not row: raise HTTPException(status_code=404,detail='provider not found')
    return client.redact_provider(row)
@app.patch('/api/providers/{provider_id}')
async def api_patch_provider(provider_id:int,data:ProviderPatchIn,_=Depends(require_auth),db=Depends(get_db)):
    try:
        result=await provider_client_for_db(db).patch_provider(provider_id,data)
    except ValueError as e:
        raise HTTPException(status_code=400,detail=str(e))
    if not result: raise HTTPException(status_code=404,detail='provider not found')
    return result
@app.delete('/api/providers/{provider_id}')
async def api_delete_provider(provider_id:int,_=Depends(require_auth),db=Depends(get_db)):
    result=await provider_client_for_db(db).disable_provider(provider_id)
    if not result: raise HTTPException(status_code=404,detail='provider not found')
    return result
@app.post('/api/providers/{provider_id}/test')
async def api_test_provider(provider_id:int,_=Depends(require_auth),db=Depends(get_db)):
    client=provider_client_for_db(db)
    provider=await client.get_provider(provider_id)
    if not provider: raise HTTPException(status_code=404,detail='provider not found')
    result=await client.test_provider(provider)
    if not result['ok']: await db_log_failure('provider','provider test failed',{'provider_id':provider_id,'error':result.get('error')})
    return result
class ProviderModelIn(BaseModel):
    model:str=Field(min_length=1,max_length=200)
    display_name:str|None=Field(default=None,max_length=200)
    enabled:bool=True
    context_window_tokens:int|None=Field(default=None,ge=1,le=10000000)
    supports_tools:bool|None=None
    supports_reasoning:bool|None=None
    supports_vision:bool|None=None
    supports_json:bool|None=None
@app.get('/api/providers/{provider_id}/models')
async def api_provider_models(provider_id:int,_=Depends(require_auth),db=Depends(get_db)):
    return await provider_client_for_db(db).list_provider_models(provider_id)
@app.post('/api/providers/{provider_id}/models')
async def api_post_provider_model(provider_id:int,data:ProviderModelIn,_=Depends(require_auth),db=Depends(get_db)):
    result=await provider_client_for_db(db).upsert_provider_model(provider_id,data)
    if not result: raise HTTPException(status_code=404,detail='provider not found')
    return result
@app.get('/api/provider-calls/summary')
async def api_provider_calls_summary(_=Depends(require_auth),db=Depends(get_db)):
    return await provider_client_for_db(db).provider_call_summary()
@app.get('/api/provider-calls')
async def api_provider_calls(provider_id:int|None=None,scope_type:str|None=None,scope_id:str|None=None,source:str|None=None,errors_only:bool=False,limit:int=Query(50,ge=1,le=500),_=Depends(require_auth),db=Depends(get_db)):
    return await provider_client_for_db(db).provider_calls(provider_id,scope_type,scope_id,source,errors_only,limit)
class ScopeProfileIn(BaseModel):
    display_name:str|None=Field(default=None,max_length=200)
    enabled:bool=True
    provider_id:int|None=None
    model:str|None=Field(default=None,max_length=200)
    parameter_profile_id:int|None=None
    instructions_id:int|None=None
    memory_enabled:bool=True
    tools_enabled:bool=True
    skills_enabled:bool=True
    tasks_enabled:bool=True
async def effective_scope_payload(db,scope_type,scope_id,user_id=None):
    return await provider_client_for_db(db).effective_scope_payload(scope_type,normalize_scope_id(scope_type,scope_id),user_id)
@app.get('/api/scopes/effective')
async def api_scope_effective(scope_type:Literal['global','guild','channel','dm','group','user']='global',scope_id:str|None=None,user_id:str|None=None,_=Depends(require_auth),db=Depends(get_db)):
    if not valid_extended_scope_pair(scope_type,scope_id): raise HTTPException(status_code=400,detail='invalid scope/scope_id combination')
    return await effective_scope_payload(db,scope_type,scope_id,user_id)
@app.patch('/api/scopes/{scope_type}/{scope_id}')
async def api_patch_scope(scope_type:str,scope_id:str,data:ScopeProfileIn,_=Depends(require_auth),db=Depends(get_db)):
    sid=normalize_scope_id(scope_type,scope_id)
    if not valid_extended_scope_pair(scope_type,sid): raise HTTPException(status_code=400,detail='invalid scope/scope_id combination')
    now=utc_now()
    await _upsert(db,'scope_profiles',['scope_type','scope_id'],[scope_type,sid],{'display_name':data.display_name,'enabled':int(data.enabled),'provider_id':data.provider_id,'model':data.model,'parameter_profile_id':data.parameter_profile_id,'instructions_id':data.instructions_id,'memory_enabled':int(data.memory_enabled),'tools_enabled':int(data.tools_enabled),'skills_enabled':int(data.skills_enabled),'tasks_enabled':int(data.tasks_enabled),'updated_at':now,'created_at':now})
    return {'ok':True}
@app.get('/api/scopes/{scope_type}/{scope_id}/provider-resolution')
async def api_scope_provider_resolution(scope_type:str,scope_id:str,_=Depends(require_auth),db=Depends(get_db)):
    return await effective_scope_payload(db,scope_type,scope_id)
@app.get('/api/scopes/{scope_type}/{scope_id}/capabilities')
async def api_scope_capabilities(scope_type:str,scope_id:str,_=Depends(require_auth),db=Depends(get_db)):
    sid=normalize_scope_id(scope_type,scope_id)
    return await rows(await db.execute('SELECT cb.*, aa.asset_type, aa.name, aa.description FROM capability_bindings cb JOIN agent_assets aa ON aa.id=cb.asset_id WHERE cb.scope_type=? AND ((cb.scope_id IS NULL AND ? IS NULL) OR cb.scope_id=?) ORDER BY aa.asset_type, aa.name',(scope_type,sid,sid)))
class CapabilityBindingIn(BaseModel):
    enabled:bool
    reason:str|None=Field(default=None,max_length=500)
@app.put('/api/scopes/{scope_type}/{scope_id}/capabilities/{asset_id}')
async def api_put_scope_capability(scope_type:str,scope_id:str,asset_id:int,data:CapabilityBindingIn,_=Depends(require_auth),db=Depends(get_db)):
    sid=normalize_scope_id(scope_type,scope_id)
    if not valid_extended_scope_pair(scope_type,sid): raise HTTPException(status_code=400,detail='invalid scope/scope_id combination')
    cur=await db.execute('SELECT id FROM agent_assets WHERE id=?',(asset_id,))
    if not await cur.fetchone(): raise HTTPException(status_code=404,detail='asset not found')
    now=utc_now()
    await _upsert(db,'capability_bindings',['asset_id','scope_type','scope_id'],[asset_id,scope_type,sid],{'enabled':int(data.enabled),'reason':data.reason,'created_by':'panel','created_at':now,'updated_at':now})
    return {'ok':True}
class BotEntryIn(BaseModel):
    name:str=Field(min_length=1,max_length=64)
    description:str|None=Field(default=None,max_length=500)
    enabled:bool=True
    persona:str|None=Field(default=None,max_length=4000)
@app.get('/api/bot-entries')
async def api_bot_entries(_=Depends(require_auth),db=Depends(get_db)):
    return await rows(await db.execute('SELECT * FROM bot_entries ORDER BY enabled DESC, name'))
@app.post('/api/bot-entries')
async def api_post_bot_entry(data:BotEntryIn,_=Depends(require_auth),db=Depends(get_db)):
    if not valid_asset_name(data.name): raise HTTPException(status_code=400,detail='invalid bot entry name')
    now=utc_now()
    cur=await db.execute('INSERT INTO bot_entries(name,description,enabled,persona,default_scope_type,default_scope_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',(data.name,data.description,int(data.enabled),data.persona,'global',None,now,now))
    await db.commit(); return {'id':int(cur.lastrowid),'ok':True}
@app.patch('/api/bot-entries/{entry_id}')
async def api_patch_bot_entry(entry_id:int,data:BotEntryIn,_=Depends(require_auth),db=Depends(get_db)):
    cur=await db.execute('SELECT id FROM bot_entries WHERE id=?',(entry_id,))
    if not await cur.fetchone(): raise HTTPException(status_code=404,detail='bot entry not found')
    await db.execute('UPDATE bot_entries SET name=?,description=?,enabled=?,persona=?,updated_at=? WHERE id=?',(data.name,data.description,int(data.enabled),data.persona,utc_now(),entry_id)); await db.commit()
    return {'ok':True}
@app.delete('/api/bot-entries/{entry_id}')
async def api_delete_bot_entry(entry_id:int,_=Depends(require_auth),db=Depends(get_db)):
    await db.execute('UPDATE bot_entries SET enabled=0,updated_at=? WHERE id=?',(utc_now(),entry_id)); await db.commit(); return {'ok':True}
@app.get('/api/bot-entries/{entry_id}/bindings')
async def api_bot_entry_bindings(entry_id:int,_=Depends(require_auth),db=Depends(get_db)):
    return await rows(await db.execute('SELECT * FROM bot_entry_bindings WHERE bot_entry_id=? ORDER BY priority DESC,id DESC',(entry_id,)))
class BotEntryBindingIn(BaseModel):
    scope_type:Literal['global','guild','channel','dm','group','user']='global'
    scope_id:str|None=None
    provider_id:int|None=None
    model:str|None=Field(default=None,max_length=200)
    parameter_profile_id:int|None=None
    instructions_id:int|None=None
    enabled:bool=True
    priority:int=0
@app.put('/api/bot-entries/{entry_id}/bindings')
async def api_put_bot_entry_binding(entry_id:int,data:BotEntryBindingIn,_=Depends(require_auth),db=Depends(get_db)):
    sid=normalize_scope_id(data.scope_type,data.scope_id)
    if not valid_extended_scope_pair(data.scope_type,sid): raise HTTPException(status_code=400,detail='invalid scope/scope_id combination')
    now=utc_now()
    await _upsert(db,'bot_entry_bindings',['bot_entry_id','scope_type','scope_id'],[entry_id,data.scope_type,sid],{'provider_id':data.provider_id,'model':data.model,'parameter_profile_id':data.parameter_profile_id,'instructions_id':data.instructions_id,'enabled':int(data.enabled),'priority':data.priority,'created_at':now,'updated_at':now})
    return {'ok':True}
@app.get('/api/task-runs')
async def api_task_runs(task_id:int|None=None,status:str|None=None,provider_id:int|None=None,scope_type:str|None=None,scope_id:str|None=None,limit:int=Query(50,ge=1,le=500),_=Depends(require_auth),db=Depends(get_db)):
    sql='SELECT * FROM agent_task_runs WHERE 1=1'; p=[]
    if task_id is not None: sql+=' AND task_id=?'; p.append(task_id)
    if status: sql+=' AND run_status=?'; p.append(status)
    if provider_id is not None: sql+=' AND provider_id=?'; p.append(provider_id)
    if scope_type: sql+=' AND scope_type=?'; p.append(scope_type)
    if scope_id: sql+=' AND scope_id=?'; p.append(scope_id)
    sql+=' ORDER BY id DESC LIMIT ?'; p.append(limit)
    return await rows(await db.execute(sql,tuple(p)))
@app.get('/api/task-runs/{run_id}')
async def api_task_run(run_id:int,_=Depends(require_auth),db=Depends(get_db)):
    data=await rows(await db.execute('SELECT * FROM agent_task_runs WHERE id=?',(run_id,)))
    if not data: raise HTTPException(status_code=404,detail='task run not found')
    return data[0]
@app.get('/api/tasks/{task_id}/runs')
async def api_task_runs_for_task(task_id:int,_=Depends(require_auth),db=Depends(get_db)):
    return await rows(await db.execute('SELECT * FROM agent_task_runs WHERE task_id=? ORDER BY id DESC',(task_id,)))
class TaskIn(BaseModel):
    name:str=Field(min_length=1,max_length=64)
    prompt:str=Field(min_length=1,max_length=MAX_TASK_PROMPT_LENGTH)
    schedule_minutes:int=Field(ge=1,le=10080)
    scope_type:Literal['global','dm','group','guild']='global'
    scope_id:str|None=None
    enabled:bool=True
    max_runs:int|None=Field(default=None,ge=1,le=1000000)
    provider_id:int|None=None
    model:str|None=Field(default=None,max_length=200)
    parameter_profile_id:int|None=None
    runtime_kind:Literal['default','rem']|None='default'
class TaskPatchIn(BaseModel):
    name:str|None=Field(default=None,min_length=1,max_length=64)
    prompt:str|None=Field(default=None,min_length=1,max_length=MAX_TASK_PROMPT_LENGTH)
    schedule_minutes:int|None=Field(default=None,ge=1,le=10080)
    enabled:bool|None=None
    max_runs:int|None=Field(default=None,ge=1,le=1000000)
    provider_id:int|None=None
    model:str|None=Field(default=None,max_length=200)
    parameter_profile_id:int|None=None
    runtime_kind:Literal['default','rem']|None=None
class TaskSnapshotApplyIn(BaseModel):
    version:str|None='latest'
@app.get('/api/tasks')
async def api_tasks(scope_type:str='all',scope_id:str|None=None,recurring_only:bool=True,_=Depends(require_auth),db=Depends(get_db)):
    if scope_type=='all':
        return await list_agent_tasks(db,None,None,recurring_only,100)
    if scope_type not in PROMPT_SCOPE_TYPES or not valid_scope_pair(scope_type,scope_id):
        raise HTTPException(status_code=400,detail='invalid scope/scope_id combination')
    return await list_agent_tasks(db,scope_type,scope_id,recurring_only,100)
@app.post('/api/tasks')
async def api_post_tasks(data:TaskIn,_=Depends(require_auth),db=Depends(get_db)):
    if not valid_scope_pair(data.scope_type,data.scope_id) or not valid_asset_name(data.name): raise HTTPException(status_code=400,detail='invalid task or scope')
    task_id=await create_agent_task(db,'task',data.prompt,'panel','panel',data.scope_type,data.scope_id,name=data.name,enabled=data.enabled,schedule_minutes=data.schedule_minutes,next_run_utc=utc_now() if data.enabled else None,max_runs=data.max_runs,provider_id=data.provider_id,model=data.model,parameter_profile_id=data.parameter_profile_id,runtime_kind=data.runtime_kind or 'default')
    if data.enabled: await schedule_agent_task(db,getattr(app.state,'ollama',None),task_id,trigger_source='panel',triggered_by='panel',tg=app.state.runtime_task_group)
    return {'id':task_id,'ok':True}
@app.post('/api/tasks/snapshot/apply')
async def api_apply_task_snapshot(data:TaskSnapshotApplyIn,_=Depends(require_auth),db=Depends(get_db)):
    try:
        result=await apply_builtin_task_snapshot(db,data.version or 'latest',created_by='panel',preserve_enabled=True)
        return {'ok':True,**result}
    except ValueError as e:
        raise HTTPException(status_code=404,detail=str(e))
@app.patch('/api/tasks/{task_id}')
async def api_patch_tasks(task_id:int,data:TaskPatchIn,_=Depends(require_auth),db=Depends(get_db)):
    cur=await db.execute('SELECT * FROM agent_tasks WHERE id=?',(task_id,))
    row=await cur.fetchone()
    if not row: raise HTTPException(status_code=404,detail='task not found')
    current=dict(zip([c[0] for c in cur.description],row))
    fields=data.model_dump(exclude_unset=True)
    if 'name' in fields and not valid_asset_name(fields['name']):
        raise HTTPException(status_code=400,detail='invalid task name')
    if 'runtime_kind' in fields and not fields['runtime_kind']:
        fields['runtime_kind']='default'
    if 'enabled' in fields:
        fields['enabled']=int(bool(fields['enabled']))
        fields['next_run_utc']=utc_now() if fields['enabled'] else None
    elif fields.get('schedule_minutes') and int(current.get('enabled') or 0):
        fields['next_run_utc']=utc_after_minutes(fields['schedule_minutes'])
    fields['updated_at']=utc_now()
    await db.execute('UPDATE agent_tasks SET '+', '.join(f'{k}=?' for k in fields)+' WHERE id=?',tuple(fields.values())+(task_id,))
    await db.commit()
    return {'ok':True}
@app.delete('/api/tasks/{task_id}')
async def api_delete_tasks(task_id:int,_=Depends(require_auth),db=Depends(get_db)):
    cur=await db.execute('SELECT id FROM agent_tasks WHERE id=?',(task_id,))
    if not await cur.fetchone(): raise HTTPException(status_code=404,detail='task not found')
    await db.execute('DELETE FROM agent_tasks WHERE id=?',(task_id,)); await db.commit()
    return {'ok':True}
@app.post('/api/tasks/{task_id}/disable')
async def api_disable_task(task_id:int,_=Depends(require_auth),db=Depends(get_db)):
    cur=await db.execute('SELECT id FROM agent_tasks WHERE id=?',(task_id,))
    if not await cur.fetchone(): raise HTTPException(status_code=404,detail='task not found')
    await db.execute('UPDATE agent_tasks SET enabled=0,next_run_utc=NULL,updated_at=? WHERE id=?',(utc_now(),task_id)); await db.commit()
    return {'ok':True}
@app.post('/api/tasks/{task_id}/run')
async def api_run_task(task_id:int,_=Depends(require_auth),db=Depends(get_db)):
    cur=await db.execute('SELECT id FROM agent_tasks WHERE id=?',(task_id,))
    if not await cur.fetchone(): raise HTTPException(status_code=404,detail='task not found')
    await db.execute("UPDATE agent_tasks SET status='queued',next_run_utc=?,updated_at=? WHERE id=?",(utc_now(),utc_now(),task_id)); await db.commit()
    await schedule_agent_task(db,getattr(app.state,'ollama',None),task_id,trigger_source='panel',triggered_by='panel',tg=app.state.runtime_task_group)
    return {'ok':True}
@app.get('/api/panel-chat')
async def api_panel_chat(_=Depends(require_auth),db=Depends(get_db)): return await rows(await db.execute('SELECT * FROM panel_chat ORDER BY id ASC'))
class ChatIn(BaseModel): message:str=Field(max_length=MAX_PANEL_CHAT_LENGTH)
def _panel_chat_client(request:Request):
    state=request.app.state
    for name in ('ollama_client','ollama','client'):
        client=getattr(state,name,None)
        if client and hasattr(client,'chat'):
            return client
    raise HTTPException(status_code=503,detail='Ollama client is not configured')
def _panel_chat_messages(chat_rows:list[dict[str,Any]])->list[dict[str,str]]:
    messages=[{'role':'system','content':tool_turns.TOOL_TURN_STATE_PLACEHOLDER+'\n\nYou are Dirac panel admin chat. Help the operator understand and operate this local bot. Use available tools when asked about persisted messages, memories, logs, current time, or current documentation. Never reveal secrets; configuration values such as tokens and API keys must stay redacted.\n\n'+current_time_context_note()}]
    for row in chat_rows:
        role='user' if row.get('role')=='operator' else 'assistant'
        content=(row.get('content') or '').strip()
        if content:
            messages.append({'role':role,'content':content})
    return messages
def _panel_chat_response_parts(result:Any)->tuple[str,str|None]:
    tool_calls_json=None
    if isinstance(result,str):
        return result,None
    if isinstance(result,dict):
        message=result.get('message')
        if isinstance(message,dict):
            content=(message.get('content') or '').strip()
            tool_calls=message.get('tool_calls')
            if tool_calls is not None:
                tool_calls_json=json.dumps(tool_calls)
            return content,tool_calls_json
        content=(result.get('content') or result.get('response') or '').strip()
        tool_calls=result.get('tool_calls')
        if tool_calls is not None:
            tool_calls_json=json.dumps(tool_calls)
        return content,tool_calls_json
    message=getattr(result,'message',None)
    if message is not None:
        if isinstance(message,dict):
            content=(message.get('content') or '').strip()
            tool_calls=message.get('tool_calls')
        else:
            content=(getattr(message,'content','') or '').strip()
            tool_calls=getattr(message,'tool_calls',None)
        if tool_calls is not None:
            if isinstance(tool_calls,str):
                tool_calls_json=tool_calls
            else:
                tool_calls_json=json.dumps(tool_calls)
        return content,tool_calls_json
    content=(getattr(result,'content','') or getattr(result,'response','') or '').strip()
    tool_calls=getattr(result,'tool_calls',None)
    if tool_calls is not None:
        if isinstance(tool_calls,str):
            tool_calls_json=tool_calls
        else:
            tool_calls_json=json.dumps(tool_calls)
    return content,tool_calls_json
async def run_diagnostic_command(db,args):
    raw=args.get('command') or args.get('cmd') or ''
    argv=args.get('argv')
    if argv is not None:
        if not isinstance(argv,list) or not all(isinstance(item,str) for item in argv):
            return {'ok':False,'error':'invalid_argv'}
        parts=argv
    else:
        try:
            parts=shlex.split(str(raw))
        except ValueError as e:
            return {'ok':False,'error':'invalid_command','detail':str(e)}
    if not parts:
        return {'ok':False,'error':'command_required'}
    executable=parts[0]
    if executable not in DIAGNOSTIC_ALLOWED_COMMANDS:
        return {'ok':False,'error':'command_not_allowed','allowed':sorted(DIAGNOSTIC_ALLOWED_COMMANDS)}
    if executable=='git' and len(parts)>1 and parts[1] not in {'status','diff','log','show'}:
        return {'ok':False,'error':'git_subcommand_not_allowed','allowed':['status','diff','log','show']}
    try:
        timeout=max(1.0,min(float(args.get('timeout_s') or DIAGNOSTIC_COMMAND_TIMEOUT_S),DIAGNOSTIC_COMMAND_TIMEOUT_S))
    except (TypeError,ValueError):
        timeout=DIAGNOSTIC_COMMAND_TIMEOUT_S
    try:
        proc=await asyncio.to_thread(
            subprocess.run,
            parts,
            cwd=str(REPO_DIR),
            text=True,
            capture_output=True,
            timeout=timeout,
            env={**os.environ,'PYTHONUNBUFFERED':'1'},
        )
        stdout=proc.stdout or ''
        stderr=proc.stderr or ''
        secrets=await known_secret_values(db)
        return {
            'ok':proc.returncode==0,
            'returncode':proc.returncode,
            'cwd':str(REPO_DIR),
            'argv':parts,
            'stdout':redact_known_secrets(stdout[:DIAGNOSTIC_COMMAND_OUTPUT_LIMIT],secrets),
            'stderr':redact_known_secrets(stderr[:DIAGNOSTIC_COMMAND_OUTPUT_LIMIT],secrets),
            'truncated':len(stdout)>DIAGNOSTIC_COMMAND_OUTPUT_LIMIT or len(stderr)>DIAGNOSTIC_COMMAND_OUTPUT_LIMIT,
        }
    except subprocess.TimeoutExpired:
        return {'ok':False,'error':'timeout','timeout_s':timeout,'argv':parts}
    except FileNotFoundError:
        return {'ok':False,'error':'executable_not_found','argv':parts}
async def run_bash_command(db,args):
    command=str(args.get('command') or args.get('cmd') or '').strip()
    if not command:
        return {'ok':False,'error':'command_required'}
    try:
        timeout=max(1.0,min(float(args.get('timeout_s') or BASH_COMMAND_TIMEOUT_S),BASH_COMMAND_TIMEOUT_S))
    except (TypeError,ValueError):
        timeout=BASH_COMMAND_TIMEOUT_S
    cwd_arg=str(args.get('cwd') or REPO_DIR).strip()
    cwd=Path(cwd_arg).expanduser()
    if not cwd.is_absolute():
        cwd=(REPO_DIR / cwd).resolve()
    try:
        proc=await asyncio.to_thread(
            subprocess.run,
            command,
            cwd=str(cwd),
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout,
            executable='/bin/bash',
            env={**os.environ,'PYTHONUNBUFFERED':'1'},
        )
        stdout=proc.stdout or ''
        stderr=proc.stderr or ''
        secrets=await known_secret_values(db)
        return {
            'ok':proc.returncode==0,
            'returncode':proc.returncode,
            'cwd':str(cwd),
            'command':command,
            'stdout':redact_known_secrets(stdout[:BASH_COMMAND_OUTPUT_LIMIT],secrets),
            'stderr':redact_known_secrets(stderr[:BASH_COMMAND_OUTPUT_LIMIT],secrets),
            'truncated':len(stdout)>BASH_COMMAND_OUTPUT_LIMIT or len(stderr)>BASH_COMMAND_OUTPUT_LIMIT,
        }
    except subprocess.TimeoutExpired:
        return {'ok':False,'error':'timeout','timeout_s':timeout,'command':command}
    except FileNotFoundError:
        return {'ok':False,'error':'bash_not_found','command':command}
PANEL_TOOLS=[
    {'type':'function','function':{'name':'messages_search','description':'Search persisted Discord messages visible to the panel','parameters':{'type':'object','properties':{'q':{'type':'string'},'scope_type':{'type':'string'},'scope_id':{'type':'string'},'limit':{'type':'integer'}},'required':['q']}}},
    memory_contract.memory_tool_schema('memory_search'),
    memory_contract.memory_tool_schema('memory_add'),
    memory_contract.memory_tool_schema('memory_update'),
    memory_contract.memory_tool_schema('memory_delete'),
    memory_contract.memory_tool_schema('memory_edit'),
    memory_contract.memory_tool_schema('memory_remove'),
    {'type':'function','function':{'name':'discord_ground','description':'Bulk-resolve Discord snowflakes and persistent identity tags.','parameters':{'type':'object','properties':{'ids':{'type':'array','items':{'type':'string'}},'text':{'type':'string'},'reason':{'type':'string'}}}}},
    {'type':'function','function':{'name':'discord_tag','description':'Add or replace the stable label for one Discord snowflake.','parameters':{'type':'object','properties':{'id':{'type':'string'},'snowflake':{'type':'string'},'label':{'type':'string'},'kind':{'type':'string'}},'required':['label']}}},
    {'type':'function','function':{'name':'dyslexic_helper','description':'Replace ugly Discord mentions/snowflakes in text with mapped labels.','parameters':{'type':'object','properties':{'text':{'type':'string'},'ids':{'type':'array','items':{'type':'string'}}},'required':['text']}}},
    {'type':'function','function':{'name':'web_search','description':'Search the public web for current troubleshooting context.','parameters':{'type':'object','properties':{'query':{'type':'string'},'limit':{'type':'integer'}},'required':['query']}}},
    {'type':'function','function':{'name':'bash','description':'Run a Bash command for the authenticated panel operator. Use doctor.py for SQLite, memory, tool, config, and online diagnostics when possible.','parameters':{'type':'object','properties':{'command':{'type':'string'},'cwd':{'type':'string'},'timeout_s':{'type':'number'}},'required':['command']}}},
    {'type':'function','function':{'name':'diagnostic_command','description':'Run a bounded repo-local diagnostic command for the panel operator. Allowed commands include rg, ls, sed, cat, wc, git status/diff/log/show, python, and sqlite3.','parameters':{'type':'object','properties':{'command':{'type':'string'},'argv':{'type':'array','items':{'type':'string'}},'timeout_s':{'type':'number'}}}}},
    {'type':'function','function':{'name':'list_bot_logs','description':'List recent bot log rows','parameters':{'type':'object','properties':{'level':{'type':'string'},'component':{'type':'string'},'limit':{'type':'integer'}}}}},
    {'type':'function','function':{'name':'read_docs','description':'Read current Dirac documentation by name. Available names include admin, usage, readme, agents.','parameters':{'type':'object','properties':{'name':{'type':'string'},'limit':{'type':'integer'}}, 'required':['name']}}},
    {'type':'function','function':{'name':'current_time','description':'Return the current date and time in Europe/Madrid and UTC.','parameters':{'type':'object','properties':{}}}},
]
def _tool_args(call):
    """Extract tool name/arguments; malformed tool arguments become empty args so panel chat can continue safely."""
    return extract_tool_call(call)
async def _run_panel_tool(db,name,args):
    """Execute a panel-chat tool call and return JSON-serializable results."""
    limit=clamp_limit(args.get('int_limit') or args.get('limit'))
    if name=='messages_search':
        p=[like_pattern(args.get('q',''))]
        sql="SELECT * FROM messages WHERE content LIKE ? ESCAPE '\\'"
        if args.get('scope_type'): sql+=' AND scope_type=?'; p.append(args['scope_type'])
        if args.get('scope_id'): sql+=' AND scope_id=?'; p.append(str(args['scope_id']))
        sql+=' ORDER BY id DESC LIMIT ?'; p.append(limit); return await rows(await db.execute(sql,tuple(p)))
    if name=='memory_search':
        return await MemoryManager(db).search(args.get('str_discord_id'),args.get('str_query'),None,limit)
    if name=='memory_add':
        return await memory_tool_add(db,args,'panel_tool')
    if name in {'memory_update','memory_edit'}:
        return await memory_tool_update(db,args,'panel_tool')
    if name in {'memory_delete','memory_remove'}:
        return await memory_tool_delete(db,args)
    if name=='discord_ground':
        return await discord_ground_tool(db,args,scope_type='panel',scope_id=None,bot_user_id='panel')
    if name=='discord_tag':
        return await discord_identity_tag(db,args.get('id') or args.get('snowflake'),args.get('label'),args.get('kind'),'panel_tool')
    if name=='dyslexic_helper':
        return await dyslexic_helper_tool(db,args)
    if name=='web_search':
        return await roxanne_mod.web_search(args.get('query'),limit)
    if name=='diagnostic_command':
        return await run_diagnostic_command(db,args)
    if name=='bash':
        return await run_bash_command(db,args)
    if name=='list_bot_logs':
        p=[]; sql='SELECT * FROM bot_logs WHERE 1=1'
        if args.get('level'): sql+=' AND level=?'; p.append(args['level'])
        if args.get('component'): sql+=' AND component=?'; p.append(args['component'])
        sql+=' ORDER BY id DESC LIMIT ?'; p.append(limit); return await rows(await db.execute(sql,tuple(p)))
    if name=='read_docs':
        return read_doc(args.get('name', None),max_chars=limit*100)
    if name=='current_time':
        return current_time_payload()
    return {'error':'unknown tool'}
@app.post('/api/panel-chat')
async def api_post_panel_chat(data:ChatIn,request:Request,_=Depends(require_auth),db=Depends(get_db)):
    message=data.message.strip()
    if not message:
        raise HTTPException(status_code=400,detail='message is required')
    await db.execute('INSERT INTO panel_chat(role,content,tool_calls_json,timestamp_utc) VALUES (?,?,?,?)',('operator',message,None,utc_now()))
    await db.commit()
    await record_memory_event(db,'panel_operator','panel',None,'operator',message,'panel','panel',{})
    chat_rows=await rows(await db.execute('SELECT * FROM panel_chat ORDER BY id ASC'))
    client=_panel_chat_client(request)
    messages=_panel_chat_messages(chat_rows)
    assistant_content=''; tool_calls_json=None
    latest_tool_count=0
    total_tool_count=0
    for turn in range(PANEL_TOOL_TURN_LIMIT):
        try:
            dynamic_context=tool_turns.render_tool_turn_state('PANEL',turn+1,PANEL_TOOL_TURN_LIMIT,available_tool_count=len(PANEL_TOOLS),batch_limit=PANEL_TOOL_BATCH_LIMIT,previous_tool_results=latest_tool_count,total_tool_results=total_tool_count)
            try:
                result=await client.chat(messages,tools=PANEL_TOOLS,scope_type='panel',scope_id=None,dynamic_context=dynamic_context)
            except TypeError:
                prepared=tool_turns.prepare_messages_for_tool_turn(messages,dynamic_context)
                result=await client.chat(prepared,tools=PANEL_TOOLS,scope_type='panel',scope_id=None)
        except Exception as e:
            await db_log_error('ollama','panel chat failed',e)
            raise HTTPException(status_code=502,detail='Ollama chat failed')
        assistant_content,tool_calls_json=_panel_chat_response_parts(result)
        tool_calls=json.loads(tool_calls_json) if tool_calls_json else []
        if not tool_calls:
            break
        messages.append({'role':'assistant','content':assistant_content or '', 'tool_calls':tool_calls})
        limited_calls=tool_calls[:PANEL_TOOL_BATCH_LIMIT]
        for call in limited_calls:
            name,args=_tool_args(call)
            tool_result=await _run_panel_tool(db,name,args)
            messages.append({'role':'tool','content':json.dumps(tool_result,ensure_ascii=False), 'name':name or 'tool'})
        latest_tool_count=len(limited_calls)
        total_tool_count+=latest_tool_count
    else:
        try:
            dynamic_context=tool_turns.render_tool_turn_state('PANEL',PANEL_TOOL_TURN_LIMIT,PANEL_TOOL_TURN_LIMIT,latest_tool_results=latest_tool_count,total_tool_results=total_tool_count,finalization=True)
            try:
                result=await client.chat(messages,tools=None,scope_type='panel',scope_id=None,dynamic_context=dynamic_context)
            except TypeError:
                prepared=tool_turns.prepare_messages_for_tool_turn(messages,dynamic_context)
                result=await client.chat(prepared,tools=None,scope_type='panel',scope_id=None)
            assistant_content,tool_calls_json=_panel_chat_response_parts(result)
            if tool_calls_json:
                try:
                    logged_tool_calls=json.loads(tool_calls_json)
                except Exception:
                    logged_tool_calls=tool_calls_json
                await app_log('warn','ollama','panel chat requested tools during text-only finalization',{'tool_calls':logged_tool_calls},'panel',None)
                if not assistant_content:
                    assistant_content=format_dirac_error('panel chat cut short after text-only finalization requested more tools',component='panel')
                tool_calls_json=None
        except Exception as e:
            await db_log_error('ollama','panel chat finalization failed',e)
    if not assistant_content and tool_calls_json is None:
        raise HTTPException(status_code=502,detail='Ollama chat returned no assistant content')
    await db.execute('INSERT INTO panel_chat(role,content,tool_calls_json,timestamp_utc) VALUES (?,?,?,?)',('assistant',assistant_content,tool_calls_json,utc_now()))
    await db.commit()
    await record_memory_event(db,'panel_assistant','panel',None,'assistant',assistant_content,'panel','Dirac panel',{'tool_calls':bool(tool_calls_json)})
    return await rows(await db.execute('SELECT * FROM panel_chat ORDER BY id ASC'))
class CommandIn(BaseModel): scope_type:Literal['global','dm','group','guild']='global'; scope_id:str|None=None; command:str; args:str=''; user_id:str='panel'
@app.post('/api/command')
async def api_command(data:CommandIn,_=Depends(require_auth),db=Depends(get_db)):
    if not valid_scope_pair(data.scope_type,data.scope_id): raise HTTPException(status_code=400,detail='invalid scope/scope_id combination')
    text=data.command if data.command.startswith('!') else '!'+data.command
    if data.args: text+=' '+data.args
    try: parsed=parse_command(text)
    except ValueError:
        await log_command(db,'panel','panel',data.scope_type,data.scope_id,{'command':data.command,'args':[data.args]},False,'malformed')
        raise HTTPException(status_code=400,detail='malformed command')
    await _upsert(db,'permissions',['user_id','scope_type','scope_id'],['panel','global',None],{'level':'root','added_at':utc_now()})
    return {'result':await CommandHandler(db,getattr(app.state,'ollama',None),tg=app.state.runtime_task_group).handle(parsed,'panel',data.scope_type,data.scope_id,'panel')}
async def known_secret_values(db):
    values=set()
    cfg=getattr(app.state,'config',None)
    if cfg is not None:
        data=config_to_dict(cfg)
        for section,key in (('ollama','api_key'),('discord','token'),('panel','auth_token')):
            value=data.get(section,{}).get(key)
            if value and value != REDACTED_SECRET and len(str(value)) >= 4:
                values.add(str(value))
    try:
        cur=await db.execute("SELECT api_key FROM service_providers WHERE api_key IS NOT NULL AND api_key!=''")
        for (value,) in await cur.fetchall():
            if value and len(str(value)) >= 4:
                values.add(str(value))
    except Exception:
        pass
    return values
def redact_known_secrets(value,secrets):
    if isinstance(value,dict):
        return {k:redact_known_secrets(v,secrets) for k,v in value.items()}
    if isinstance(value,list):
        return [redact_known_secrets(v,secrets) for v in value]
    if not isinstance(value,str):
        return value
    text=value
    for secret in sorted(secrets,key=len,reverse=True):
        text=text.replace(secret,REDACTED_SECRET)
    text=re.sub(r'(?i)(authorization"\s*:\s*")Bearer\s+[^"]+',r'\1Bearer '+REDACTED_SECRET,text)
    text=re.sub(r'(?i)((api[_-]?key|token|auth[_-]?token)["\']?\s*[:=]\s*["\']?)[^"\'\s,}]+',r'\1'+REDACTED_SECRET,text)
    return text
def redact_runtime_rows(data,secrets):
    return redact_known_secrets(data,secrets)
async def roxanne_table_counts(db):
    out={}
    for table in ('messages','bot_logs','commands_log','provider_calls','agent_tasks','agent_task_runs','memories','panel_chat','roxanne_sessions','roxanne_memory'):
        try:
            cur=await db.execute(f'SELECT COUNT(*) FROM {table}')
            out[table]=(await cur.fetchone())[0]
        except Exception as e:
            out[table]=f'error:{type(e).__name__}'
    return out
async def roxanne_recent_runtime(db,secrets,limit=20):
    lim=clamp_limit(limit,20,50)
    sections={}
    query_map={
        'recent_bot_logs':('SELECT id,level,component,message,substr(detail_json,1,2000) detail_json,timestamp_utc FROM bot_logs ORDER BY id DESC LIMIT ?',()),
        'recent_commands':('SELECT id,source,user_id,scope_type,scope_id,command,args,accepted,reason,timestamp_utc FROM commands_log ORDER BY id DESC LIMIT ?',()),
        'recent_provider_calls':('SELECT id,provider_name,provider_type,model,scope_type,scope_id,source,task_id,task_run_id,substr(request_json,1,3000) request_json_preview,substr(response_json,1,3000) response_json_preview,sent_params_json,ignored_params_json,prompt_tokens,completion_tokens,total_tokens,latency_ms,error,timestamp_utc FROM provider_calls ORDER BY id DESC LIMIT ?',()),
        'recent_task_runs':('SELECT id,task_id,run_status,trigger_source,triggered_by,scope_type,scope_id,provider_name,provider_type,model,params_json,substr(prompt,1,1500) prompt_preview,substr(result,1,2000) result_preview,error,prompt_tokens,completion_tokens,latency_ms,started_at,completed_at,created_at FROM agent_task_runs ORDER BY id DESC LIMIT ?',()),
        'recent_messages':('SELECT id,discord_msg_id,scope_type,scope_id,guild_id,author_id,author_name,substr(content,1,1600) content_preview,is_command,is_authorized,triggered_bot,reply_to_id,timestamp_utc FROM messages ORDER BY id DESC LIMIT ?',()),
    }
    for name,(sql,params) in query_map.items():
        try:
            sections[name]=await rows(await db.execute(sql,tuple(params)+(lim,)))
        except Exception as e:
            sections[name]=[{'error':type(e).__name__,'detail':str(e)}]
    return redact_runtime_rows(sections,secrets)
async def get_roxanne_profile(db):
    cur=await db.execute("SELECT * FROM roxanne_profiles WHERE name='default' ORDER BY id LIMIT 1")
    row=await cur.fetchone()
    if not row:
        await ensure_default_records(db)
        cur=await db.execute("SELECT * FROM roxanne_profiles WHERE name='default' ORDER BY id LIMIT 1")
        row=await cur.fetchone()
    return dict(zip([c[0] for c in cur.description],row)) if row else None
async def roxanne_runtime_context(db,scope_type=None,scope_id=None):
    secrets=await known_secret_values(db)
    docs=[]
    for name in ('admin','usage','readme','agents','help','ui'):
        doc=read_doc(name,max_chars=2400)
        if not doc.get('error'):
            docs.append(f"[doc:{name} path={doc['path']}]\n{doc['content']}")
    providers=[redact_provider(r) for r in await list_service_providers(db)]
    tasks=await list_agent_tasks(db,None,None,False,15)
    runtime=await roxanne_recent_runtime(db,secrets,25)
    counts=await roxanne_table_counts(db)
    try:
        provider_summary=await rows(await db.execute("SELECT provider_name,provider_type,model,COUNT(*) calls,SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) errors FROM provider_calls GROUP BY provider_name,provider_type,model ORDER BY calls DESC LIMIT 10"))
    except Exception:
        provider_summary=[]
    static_memory=await roxanne_mod.static_memory_context(db)
    effective=None
    if scope_type and valid_extended_scope_pair(scope_type,normalize_scope_id(scope_type,scope_id)):
        try:
            effective=await effective_scope_payload(db,scope_type,scope_id)
        except Exception as e:
            effective={'error':str(e)}
    return (
        'Roxanne live operator operations context. This snapshot is regenerated for every ask. '
        'It contains recent DB-backed logs and runtime state for direct troubleshooting. '
        'Roxanne can edit Dirac persisted memories and run Bash only through panel-authorized tools. '
        'Known secrets are redacted before injection.\n\n'
        'Current time:\n'+json.dumps(current_time_payload(),indent=2)+'\n\n'
        'Runtime metadata:\n'+json.dumps(redact_runtime_rows(runtime_metadata_snapshot(),secrets),indent=2)+'\n\n'
        'SQLite table counts:\n'+json.dumps(counts,indent=2)+'\n\n'
        'Roxanne static memory:\n'+static_memory+'\n\n'
        'Available Roxanne tools:\n'+json.dumps([t['function']['name'] for t in roxanne_mod.ROXANNE_TOOLS],indent=2)+'\n\n'
        'Documentation excerpts:\n'+'\n\n'.join(docs)+'\n\n'
        'Redacted config:\n'+json.dumps(redact_runtime_rows(redacted_config_snapshot(),secrets),indent=2)+'\n\n'
        'Providers:\n'+json.dumps(providers,indent=2)+'\n\n'
        'Provider call summary:\n'+json.dumps(provider_summary,indent=2)+'\n\n'
        'Recent tasks:\n'+json.dumps(tasks,indent=2)+'\n\n'
        'Recent live DB rows:\n'+json.dumps(runtime,indent=2)+'\n\n'
        'Selected effective scope:\n'+json.dumps(redact_runtime_rows(effective,secrets),indent=2)
    )
RoxanneProfilePatchIn=roxanne_mod.RoxanneProfilePatchIn
RoxanneSessionIn=roxanne_mod.RoxanneSessionIn
RoxanneAskIn=roxanne_mod.RoxanneAskIn
RoxanneMemoryIn=roxanne_mod.RoxanneMemoryIn
RoxanneMemoryPatchIn=roxanne_mod.RoxanneMemoryPatchIn
async def roxanne_memory_search(db,str_discord_id,str_query,limit):
    return await MemoryManager(db).search(str_discord_id,str_query,None,limit)
def roxanne_deps(db):
    return roxanne_mod.RoxanneDeps(
        utc_now=utc_now,
        preview_text=preview_text,
        normalize_scope_id=normalize_scope_id,
        valid_extended_scope_pair=valid_extended_scope_pair,
        provider_params_for_profile=provider_params_for_profile,
        runtime_context=roxanne_runtime_context,
        response_parts=_panel_chat_response_parts,
        tool_args=_tool_args,
        read_doc=read_doc,
        current_time_payload=current_time_payload,
        redacted_config_snapshot=redacted_config_snapshot,
        list_service_providers=list_service_providers,
        redact_provider=redact_provider,
        effective_scope_payload=effective_scope_payload,
        memory_search=lambda str_discord_id,str_query,limit: roxanne_memory_search(db,str_discord_id,str_query,limit),
        memory_add=lambda args: memory_tool_add(db,args,'roxanne'),
        memory_update=lambda args: memory_tool_update(db,args,'roxanne'),
        memory_delete=lambda args: memory_tool_delete(db,args),
        rows=rows,
        clamp_limit=clamp_limit,
        like_pattern=like_pattern,
        web_fetch=run_web_fetch,
        diagnostic_command=lambda args: run_diagnostic_command(db,args),
        bash=lambda args: run_bash_command(db,args),
        db_log_error=db_log_error,
    )
@app.get('/api/roxanne/profile')
async def api_roxanne_profile(_=Depends(require_auth),db=Depends(get_db)):
    profile=await get_roxanne_profile(db)
    if not profile: raise HTTPException(status_code=404,detail='roxanne profile not found')
    provider=await get_provider(db,profile.get('provider_id')) if profile.get('provider_id') else None
    profile['provider']=redact_provider(provider)
    return profile
@app.patch('/api/roxanne/profile')
async def api_patch_roxanne_profile(data:RoxanneProfilePatchIn,_=Depends(require_auth),db=Depends(get_db)):
    profile=await get_roxanne_profile(db)
    if not profile: raise HTTPException(status_code=404,detail='roxanne profile not found')
    fields=data.model_dump(exclude_unset=True)
    if fields.get('system_prompt') is None:
        fields.pop('system_prompt',None)
    if not fields: return {'ok':True}
    if fields.get('provider_id') is not None and not await get_provider(db,fields['provider_id']):
        raise HTTPException(status_code=404,detail='provider not found')
    if fields.get('parameter_profile_id') is not None:
        cur=await db.execute('SELECT id FROM provider_parameters WHERE id=?',(int(fields['parameter_profile_id']),))
        if not await cur.fetchone(): raise HTTPException(status_code=404,detail='parameter profile not found')
    if 'tools_enabled' in fields:
        fields['tools_enabled']=int(bool(fields['tools_enabled']))
    fields['updated_at']=utc_now()
    await db.execute('UPDATE roxanne_profiles SET '+', '.join(f'{k}=?' for k in fields)+' WHERE id=?',tuple(fields.values())+(profile['id'],))
    await db.commit()
    return {'ok':True}
@app.get('/api/roxanne/sessions')
async def api_roxanne_sessions(_=Depends(require_auth),db=Depends(get_db)):
    return await rows(await db.execute('SELECT * FROM roxanne_sessions ORDER BY id DESC LIMIT 50'))
@app.post('/api/roxanne/sessions')
async def api_post_roxanne_session(data:RoxanneSessionIn,_=Depends(require_auth),db=Depends(get_db)):
    st=data.active_scope_type or 'global'; sid=normalize_scope_id(st,data.active_scope_id)
    if not valid_extended_scope_pair(st,sid): raise HTTPException(status_code=400,detail='invalid scope/scope_id combination')
    now=utc_now()
    cur=await db.execute('INSERT INTO roxanne_sessions(title,active_scope_type,active_scope_id,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?)',(data.title,st,sid,'panel',now,now))
    await db.commit()
    return {'id':int(cur.lastrowid),'ok':True}
@app.get('/api/roxanne/sessions/{session_id}/messages')
async def api_roxanne_session_messages(session_id:int,_=Depends(require_auth),db=Depends(get_db)):
    return await rows(await db.execute('SELECT * FROM roxanne_messages WHERE session_id=? ORDER BY id ASC',(session_id,)))
async def roxanne_ask(db,client,message,session_id=None,active_scope_type='global',active_scope_id=None):
    profile=await get_roxanne_profile(db)
    if not profile: raise HTTPException(status_code=404,detail='roxanne profile not found')
    try:
        result=await roxanne_mod.ask(db,client,message,profile,session_id,active_scope_type,active_scope_id,roxanne_deps(db))
        if 'Roxanne provider produced no text reply' in str(result.get('message') or ''):
            await app_log('warn','roxanne','empty provider reply',{'session_id':result.get('session_id'),'profile_id':profile.get('id'),'provider_id':profile.get('provider_id'),'model':profile.get('model'),'reasoning_mode':profile.get('reasoning_mode'),'tools_enabled':profile.get('tools_enabled')},'roxanne',str(result.get('session_id') or ''))
        await record_memory_event(db,'roxanne_operator',active_scope_type,active_scope_id,'operator',message,'panel','panel',{'session_id':result.get('session_id')})
        await record_memory_event(db,'roxanne_assistant',active_scope_type,active_scope_id,'assistant',result.get('message') or '','roxanne','Roxanne',{'session_id':result.get('session_id')})
        return result
    except ValueError as e:
        raise HTTPException(status_code=400,detail=str(e))
    except LookupError:
        raise HTTPException(status_code=404,detail='roxanne session not found')
@app.post('/api/roxanne/sessions/{session_id}/messages')
async def api_post_roxanne_message(session_id:int,data:ChatIn,request:Request,_=Depends(require_auth),db=Depends(get_db)):
    client=_panel_chat_client(request)
    return await roxanne_ask(db,client,data.message,session_id=session_id)
@app.post('/api/roxanne/ask')
async def api_roxanne_ask(data:RoxanneAskIn,request:Request,_=Depends(require_auth),db=Depends(get_db)):
    return await roxanne_ask(db,_panel_chat_client(request),data.message,data.session_id,data.active_scope_type,data.active_scope_id)
@app.get('/api/roxanne/tools')
async def api_roxanne_tools(_=Depends(require_auth)):
    write_tools={'memory_add','memory_update','memory_delete','diagnostic_command','bash'}
    return [{'name':t['function']['name'],'mode':'operator_write' if t['function']['name'] in write_tools else 'read_only','description':t['function'].get('description',''),'schema':t} for t in roxanne_mod.ROXANNE_TOOLS]
@app.get('/api/roxanne/memory')
async def api_roxanne_memory(_=Depends(require_auth),db=Depends(get_db)):
    return await roxanne_mod.list_memory(db)
@app.post('/api/roxanne/memory')
async def api_post_roxanne_memory(data:RoxanneMemoryIn,_=Depends(require_auth),db=Depends(get_db)):
    return await roxanne_mod.create_memory(db,data,utc_now())
@app.patch('/api/roxanne/memory/{memory_id}')
async def api_patch_roxanne_memory(memory_id:int,data:RoxanneMemoryPatchIn,_=Depends(require_auth),db=Depends(get_db)):
    result=await roxanne_mod.patch_memory(db,memory_id,data,utc_now())
    if result is None: raise HTTPException(status_code=404,detail='roxanne memory not found')
    return result
@app.delete('/api/roxanne/memory/{memory_id}')
async def api_delete_roxanne_memory(memory_id:int,_=Depends(require_auth),db=Depends(get_db)):
    if not await roxanne_mod.delete_memory(db,memory_id): raise HTTPException(status_code=404,detail='roxanne memory not found')
    return {'ok':True}
@app.get('/api/provider-parameters')
async def api_provider_parameters(_=Depends(require_auth),db=Depends(get_db)):
    return await rows(await db.execute('SELECT id,name,description,params_json,created_at,updated_at FROM provider_parameters ORDER BY name'))
@app.get('/api/config')
async def api_config(_=Depends(require_auth)):
    if app.state.config:
        c=app.state.config; return {'ollama':{**c.ollama,'api_key':REDACTED_SECRET},'discord':{**c.discord,'token':REDACTED_SECRET},'panel':{**c.panel,'auth_token':REDACTED_SECRET},'bot':c.bot,'logging':dirac_logging.normalize_logging_config(c.logging)}
    return {'ollama':{'api_key':REDACTED_SECRET},'discord':{'token':REDACTED_SECRET},'panel':{'auth_token':REDACTED_SECRET},'bot':{},'logging':default_logging_config()}
class StrictBaseModel(BaseModel):
    """Base for config update models that raise validation errors for unknown fields before writing config.toml."""
    model_config=ConfigDict(extra='forbid')

class OllamaConfigUpdate(StrictBaseModel):
    endpoint:str|None=Field(default=None,min_length=1,max_length=500)
    api_key:str|None=Field(default=None,max_length=500)
    default_model:str|None=Field(default=None,min_length=1,max_length=200)
    request_timeout_s:float|None=Field(default=None,gt=0,le=600)
class DiscordConfigUpdate(StrictBaseModel):
    token:str|None=Field(default=None,max_length=500)
    i_understand_selfbot_risk:bool|None=None
class PanelConfigUpdate(StrictBaseModel):
    host:str|None=Field(default=None,min_length=1,max_length=255)
    port:int|None=Field(default=None,ge=1,le=65535)
    auth_token:str|None=Field(default=None,min_length=1,max_length=500)
class BotConfigUpdate(StrictBaseModel):
    trigger_on:list[Literal['ping','reply']]|None=None
    auto_compact_threshold:float|None=Field(default=None,gt=0,le=1)
    proactive_memory_enabled:bool|None=None
    proactive_memory_interval_minutes:int|None=Field(default=None,ge=1,le=10080)
    context_window_tokens:int|None=Field(default=None,ge=256,le=1000000)
    command_prefix:str|None=Field(default=None,min_length=1,max_length=5)
    root_operator_ids:list[str]|None=None
    news_enabled:bool|None=None
    news_channel_id:str|None=Field(default=None,min_length=1,max_length=64)
    news_summary_interval_minutes:int|None=Field(default=None,ge=5,le=10080)
    news_memory_interval_minutes:int|None=Field(default=None,ge=5,le=10080)
    @field_validator('trigger_on')
    @classmethod
    def validate_trigger_on(cls,trigger_list):
        if trigger_list is None: return trigger_list
        if not trigger_list: raise ValueError('trigger_on must not be empty')
        if len(set(trigger_list))!=len(trigger_list): raise ValueError('trigger_on must not contain duplicates')
        return trigger_list
class LoggingConfigUpdate(StrictBaseModel):
    console_level:Literal['trace','debug','info','warn','error']|None=None
    component_levels:dict[str,Literal['trace','debug','info','warn','error']]|None=None
    provider_http_debug:bool|None=None
class ConfigUpdateIn(StrictBaseModel):
    ollama:OllamaConfigUpdate|None=None
    discord:DiscordConfigUpdate|None=None
    panel:PanelConfigUpdate|None=None
    bot:BotConfigUpdate|None=None
    logging:LoggingConfigUpdate|None=None
def _merge_config_update(current,data:ConfigUpdateIn):
    updates=data.model_dump(exclude_none=True)
    for section,incoming in updates.items():
        current.setdefault(section,{})
        for key,value in incoming.items():
            if key in {'api_key','token','auth_token'} and value==REDACTED_SECRET: continue
            current[section][key]=value
    return current
@app.put('/api/config')
async def api_put_config(data:ConfigUpdateIn,_=Depends(require_auth),db=Depends(get_db)):
    current=config_to_dict(app.state.config) if app.state.config else {'ollama':{},'discord':{},'panel':{},'bot':{}}
    current=_merge_config_update(current,data)
    config_path=active_config_path()
    if config_path.exists():
        filename_timestamp=format_timestamp_for_filename()
        backup=config_path.with_suffix(f'{config_path.suffix}.{filename_timestamp}.bak')
        shutil.copy2(config_path,backup)
    config_path.write_text(dump_config_toml(current),encoding='utf-8')
    app.state.config=config_from_dict(current); app.state.auth_token=app.state.config.panel.get('auth_token',app.state.auth_token)
    await sync_legacy_ollama_provider(db,app.state.config)
    previous=getattr(app.state,'provider_client',None)
    app.state.provider_client=None
    if getattr(app.state,'ollama',None) is previous:
        app.state.ollama=None
    provider_client_for_db(db)
    return {'ok':True,'restart_required':True}
@app.post('/api/config/test-ollama')
async def api_test_ollama(_=Depends(require_auth)):
    cfg=app.state.config; endpoint=(cfg.ollama.get('endpoint','https://ollama.com') if cfg else 'https://ollama.com').rstrip('/')
    api_key=cfg.ollama.get('api_key','') if cfg else ''
    headers={'Authorization':f'Bearer {api_key}'} if api_key else {}
    try:
        if current_logging_config().get('provider_http_debug') or log_is_enabled('debug','provider', current_logging_config()):
            await app_log('debug','provider',f'HTTP GET {endpoint}/api/tags',{'method':'GET','url':f'{endpoint}/api/tags','headers':headers,'source':'config-test'})
        async with httpx.AsyncClient(timeout=10.0,headers=headers) as client:
            r=await client.get(f'{endpoint}/api/tags')
        if current_logging_config().get('provider_http_debug') or log_is_enabled('debug','provider', current_logging_config()):
            await app_log('debug','provider',f'HTTP response {r.status_code} {endpoint}/api/tags',{'status_code':r.status_code,'text':r.text,'source':'config-test'})
        elif log_is_enabled('trace','provider', current_logging_config()):
            await app_log('trace','provider',f'HTTP response {r.status_code} {endpoint}/api/tags',{'status_code':r.status_code,'text':r.text,'source':'config-test'})
        if r.status_code!=200:
            await db_log_failure('panel','test-ollama failed',{'status_code':r.status_code})
        return {'ok':r.status_code==200,'status_code':r.status_code}
    except Exception as e:
        await db_log_error('panel','test-ollama failed',e)
        return {'ok':False,'error':'connection_failed'}
@app.post('/api/config/test-discord')
async def api_test_discord(_=Depends(require_auth)):
    cfg=app.state.config; token=(cfg.discord.get('token','') if cfg else '') or ''
    if not token: return {'ok':False,'error':'no token configured'}
    if discord is None: return {'ok':False,'error':'discord.py-self not installed'}
    try:
        headers={'Authorization':token}
        if log_is_enabled('debug','discord', current_logging_config()):
            await app_log('debug','discord','HTTP GET https://discord.com/api/v9/users/@me',{'method':'GET','url':'https://discord.com/api/v9/users/@me','headers':headers,'source':'config-test'})
        async with httpx.AsyncClient(timeout=10.0,headers=headers) as client:
            r=await client.get('https://discord.com/api/v9/users/@me')
        if log_is_enabled('debug','discord', current_logging_config()):
            await app_log('debug','discord','HTTP response from Discord user test',{'status_code':r.status_code,'text':r.text,'source':'config-test'})
        elif log_is_enabled('trace','discord', current_logging_config()):
            await app_log('trace','discord','HTTP response from Discord user test',{'status_code':r.status_code,'text':r.text,'source':'config-test'})
        if r.status_code!=200:
            await db_log_failure('panel','test-discord failed',{'status_code':r.status_code})
        return {'ok':r.status_code==200,'status_code':r.status_code}
    except Exception as e:
        await db_log_error('panel','test-discord failed',e)
        return {'ok':False,'error':'connection_failed'}
@app.websocket('/ws')
async def websocket_endpoint(ws:WebSocket):
    if ws.cookies.get('session')!=app.state.auth_token: await ws.close(code=1008); return
    await ws.accept(); app.state.ws_clients.add(ws)
    try:
        await ws.send_json({'type':'stat','data':{'uptime_s':int(time.time()-STARTED_AT)}})
        while True: await ws.receive_text()
    except WebSocketDisconnect: pass
    finally: app.state.ws_clients.discard(ws)
async def broadcast(event):
    for ws in list(app.state.ws_clients):
        try: await ws.send_json(event)
        except Exception: app.state.ws_clients.discard(ws)
def create_discord_client(cfg, db, tg:asyncio.TaskGroup):
    client_kwargs={}
    intents_cls=getattr(discord,'Intents',None)
    if intents_cls is not None:
        intents=intents_cls.default()
        if hasattr(intents,'message_content'): intents.message_content=True
        client_kwargs['intents']=intents
    client=discord.Client(**client_kwargs)
    prefix=cfg.bot.get('command_prefix','!')
    bot_core=BotCore(db,provider_client_for_db(db),str(cfg.discord.get('user_id','') or 'bot'),cfg.bot.get('trigger_on',('ping','reply')),cfg.bot.get('auto_compact_threshold'),cfg.bot.get('context_window_tokens',4096),tg=tg)

    @client.event
    async def on_ready():
        user=getattr(client,'user',None)
        uid=getattr(user,'id',None)
        if uid is not None: bot_core.user_id=str(uid)
        await app_log('info','discord','discord client ready',{'user_id':str(uid) if uid is not None else None,'user':str(user) if user is not None else None})
        if cfg.bot.get('news_enabled',False) and getattr(app.state,'news_task',None) is None:
            app.state.news_task=tg.create_task(news_scheduler(client,db,provider_client_for_db(db),cfg))

    @client.event
    async def on_message(message):
        scope_type,scope_id,_=bot_core.scope_for_message(message)
        await app_log('debug','discord','message received',{'message_id':str(getattr(message,'id','')),'author_id':str(getattr(getattr(message,'author',None),'id','')),'triggered_bot':bool(getattr(message,'triggered_bot',False))},scope_type,scope_id)
        result=await bot_core.handle_message(message)
        content=getattr(message,'content',None) or ''
        if not content.startswith(prefix): return
        if result not in (None,''):
            rendered=format_discord_command_response(result)
            await send_discord_reply(message,rendered)
            await record_memory_event(db,'discord_command_response',scope_type,scope_id,'assistant',rendered,str(getattr(getattr(client,'user',None),'id','bot')),'Dirac',{'reply_to':str(getattr(message,'id',''))})
    return client
async def main():
    import uvicorn
    cfg=load_config(CONFIG_PATH); app.state.config=cfg; app.state.auth_token=cfg.panel.get('auth_token',PANEL_AUTH_TOKEN)
    if apply_cli_logging_overrides(cfg):
        app.state.config=cfg; persist_runtime_config()
    async with asyncio.TaskGroup() as db_tg:
        writer=await DbWriter(path=DB_PATH).start(db_tg); db=RuntimeDb(writer)
        app.state.db=db; app.state.db_writer=writer
        try:
            await sync_legacy_ollama_provider(db,cfg)
            app.state.ollama=provider_client_for_db(db)
            if discord is None: raise RuntimeError('discord.py-self is required to start the Discord self-bot')
            token=cfg.discord.get('token','')
            if not token: raise RuntimeError('Missing Discord token in configuration')
            async with asyncio.TaskGroup() as runtime_tg:
                app.state.runtime_task_group=runtime_tg
                app.state.console_key_stop=start_console_key_listener(asyncio.get_running_loop(), lambda: adjust_console_logging(-1), lambda: adjust_console_logging(1), lambda e: app_log('warn','bot','console key listener stopped',{'error':type(e).__name__}))
                await app_log('info','bot','Dirac starting',{**app_build_info(),'pid':os.getpid(),'console_level':current_logging_config().get('console_level'),'provider_http_debug':current_logging_config().get('provider_http_debug'),'console_hotkeys':'+ increases verbosity, - reduces verbosity'},force_console=True)
                server=uvicorn.Server(uvicorn.Config(app,host=cfg.panel.get('host','127.0.0.1'),port=int(cfg.panel.get('port',8765)),log_level='warning',access_log=False))
                client=create_discord_client(cfg,db,runtime_tg)
                try:
                    await reconcile_orphan_agent_tasks(db)
                except Exception as e:
                    await db_log_error('agent_tasks','startup orphan reconcile failed',e)
                app.state.agent_task_scheduler_task=runtime_tg.create_task(agent_task_scheduler(db,app.state.ollama,client=client,tg=runtime_tg))
                try:
                    await asyncio.gather(server.serve(),client.start(token))
                finally:
                    stop=getattr(app.state,'console_key_stop',None)
                    if stop is not None: stop.set()
                    for task_name in ('news_task','agent_task_scheduler_task'):
                        task=getattr(app.state,task_name,None)
                        if task is not None:
                            task.cancel()
                    try: await client.close()
                    except Exception: pass
                    app.state.runtime_task_group=None
        finally:
            await writer.close()
if __name__=='__main__':
    if not handle_cli_info():
        asyncio.run(main())
