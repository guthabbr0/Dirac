#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import sys
import tomllib
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from dirac import memory_contract


REPO_DIR = Path(__file__).resolve().parent
DEFAULT_RUNTIME_DIR_CANDIDATES = (
    REPO_DIR.parent / "dirac-config",
    Path.home() / "Desktop" / "workspaces" / "dirac-config",
)
REDACTED = "***"
SECRET_KEYS = ("token", "api_key", "auth_token", "authorization", "password", "secret")
WRITABLE_TABLES = {
    "memories",
    "agent_assets",
    "tool_snapshots",
    "service_providers",
    "provider_models",
    "provider_parameters",
    "model_overrides",
    "reasoning_overrides",
    "prompts",
    "instructions",
    "permissions",
    "agent_tasks",
    "news_items",
    "roxanne_memory",
    "roxanne_profiles",
}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def runtime_dir() -> Path:
    configured = os.environ.get("DIRAC_CONFIG_DIR")
    if configured:
        return Path(configured).expanduser()
    for candidate in DEFAULT_RUNTIME_DIR_CANDIDATES:
        if candidate.exists():
            return candidate
    return REPO_DIR


def default_db_path() -> Path:
    return runtime_dir() / "bot.sqlite"


def default_config_path() -> Path:
    return runtime_dir() / "config.toml"


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def ident(name: str) -> str:
    if not str(name).replace("_", "").isalnum():
        raise SystemExit(f"invalid identifier: {name}")
    return str(name)


def redact(value):
    if isinstance(value, dict):
        return {k: (REDACTED if any(s in k.lower() for s in SECRET_KEYS) and v else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def emit(value, *, raw: bool = False) -> None:
    if raw:
        print(value)
    else:
        print(json.dumps(redact(value), indent=2, ensure_ascii=False, default=str))


def backup(path: Path) -> Path:
    backup_path = path.with_suffix(path.suffix + f".doctor-{utc_stamp()}.bak")
    shutil.copy2(path, backup_path)
    return backup_path


def parse_value(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        lowered = text.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered in {"none", "null"}:
            return None
        return text


def normalize_memory_discord_id(value: str) -> str:
    discord_id = memory_contract.normalize_discord_id(value)
    if not memory_contract.is_discord_id(discord_id):
        raise SystemExit("str_discord_id must be one Discord snowflake id as digits, or a Discord user/channel mention")
    return discord_id


def normalize_memory_array_tags(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    tags, error = memory_contract.parse_tags(value)
    if error:
        raise SystemExit(error)
    return json.dumps(tags or [], ensure_ascii=False)


def is_readonly_sql(sql: str) -> bool:
    first = sql.strip().split(None, 1)[0].lower() if sql.strip() else ""
    return first in {"select", "pragma", "with", "explain"}


def command_paths(args) -> None:
    emit({"repo_dir": REPO_DIR, "runtime_dir": runtime_dir(), "db_path": args.db, "config_path": args.config})


def command_tables(args) -> None:
    with connect(args.db) as conn:
        rows = conn.execute("SELECT name,type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name").fetchall()
    emit([dict(row) for row in rows])


def command_schema(args) -> None:
    with connect(args.db) as conn:
        rows = conn.execute(f"PRAGMA table_info({ident(args.table)})").fetchall()
    emit([dict(row) for row in rows])


def db_status(args) -> None:
    import bot

    with connect(args.db) as conn:
        has_meta = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'").fetchone() is not None
        row = conn.execute("SELECT value FROM schema_meta WHERE key=?", (bot.DB_SCHEMA_META_KEY,)).fetchone() if has_meta else None
    db_tag = row["value"] if row else None
    cmp = bot.compare_version_tags(db_tag, bot.DB_SCHEMA_TAG) if db_tag else -1
    emit({
        "ok": cmp <= 0,
        "db_path": args.db,
        "db_schema_tag": db_tag or "missing",
        "code_schema_tag": bot.DB_SCHEMA_TAG,
        "state": "newer_than_code" if cmp > 0 else ("current" if cmp == 0 else "older_than_code"),
        "upgrade": "python doctor.py db upgrade --yes",
    })


def db_upgrade(args) -> None:
    if not args.yes:
        raise SystemExit("refusing DB upgrade without --yes")
    import aiosqlite
    import bot

    backup_path = backup(args.db) if args.db.exists() else None

    async def upgrade() -> None:
        async with aiosqlite.connect(args.db) as conn:
            await bot.bootstrap_db(conn, upgrade_schema_tag=True)

    asyncio.run(upgrade())
    emit({"ok": True, "db_path": args.db, "schema_tag": bot.DB_SCHEMA_TAG, "backup": backup_path})


def command_sql(args) -> None:
    sql = args.sql
    readonly = is_readonly_sql(sql)
    if not readonly and not (args.write and args.yes):
        raise SystemExit("refusing write SQL without --write --yes")
    if not readonly:
        backup_path = backup(args.db)
    else:
        backup_path = None
    with connect(args.db) as conn:
        cur = conn.execute(sql)
        if readonly:
            rows = [dict(row) for row in cur.fetchall()]
            emit(rows)
        else:
            conn.commit()
            emit({"ok": True, "rowcount": cur.rowcount, "backup": backup_path})


def command_dump(args) -> None:
    table = ident(args.table)
    order_col = "int_memory_id" if table == "memories" else "id"
    with connect(args.db) as conn:
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY {order_col} DESC LIMIT ?", (args.limit,)).fetchall()
    emit([dict(row) for row in rows])


def command_delete_row(args) -> None:
    if args.table not in WRITABLE_TABLES:
        raise SystemExit(f"refusing delete from {args.table}; allowed: {', '.join(sorted(WRITABLE_TABLES))}")
    if not args.yes:
        raise SystemExit("refusing delete without --yes")
    backup_path = backup(args.db)
    with connect(args.db) as conn:
        cur = conn.execute(f"DELETE FROM {ident(args.table)} WHERE id=?", (args.id,))
        conn.commit()
    emit({"ok": True, "table": args.table, "id": args.id, "rowcount": cur.rowcount, "backup": backup_path})


def memory_list(args) -> None:
    clauses = ["int_superseded_by IS NULL"]
    params = []
    if args.str_discord_id:
        clauses.append("str_discord_id=?")
        params.append(normalize_memory_discord_id(args.str_discord_id))
    if args.query:
        clauses.append("str_annotations LIKE ?")
        params.append(f"%{args.query}%")
    params.append(args.limit)
    with connect(args.db) as conn:
        rows = conn.execute(
            f"SELECT * FROM memories WHERE {' AND '.join(clauses)} ORDER BY int_memory_id DESC LIMIT ?",
            tuple(params),
        ).fetchall()
    emit([dict(row) for row in rows])


def memory_add(args) -> None:
    backup_path = backup(args.db)
    discord_id = normalize_memory_discord_id(args.str_discord_id)
    with connect(args.db) as conn:
        cur = conn.execute(
            "INSERT INTO memories(str_discord_id,str_annotations,array_tags,float_confidence,str_created_utc,str_created_by) VALUES (?,?,?,?,?,?)",
            (discord_id, args.str_annotations, normalize_memory_array_tags(args.array_tags), args.float_confidence, datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), args.created_by),
        )
        conn.commit()
    emit({"ok": True, "int_memory_id": cur.lastrowid, "backup": backup_path})


def memory_update(args) -> None:
    backup_path = backup(args.db)
    with connect(args.db) as conn:
        row = conn.execute("SELECT * FROM memories WHERE int_memory_id=?", (args.int_memory_id,)).fetchone()
        if row is None:
            raise SystemExit(f"memory {args.int_memory_id} not found")
        cur = conn.execute(
            "INSERT INTO memories(str_discord_id,str_annotations,array_tags,float_confidence,str_created_utc,str_created_by) VALUES (?,?,?,?,?,?)",
            (
                row["str_discord_id"],
                args.str_annotations,
                normalize_memory_array_tags(args.array_tags) if args.array_tags is not None else row["array_tags"],
                args.float_confidence if args.float_confidence is not None else row["float_confidence"],
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                args.created_by,
            ),
        )
        new_id = cur.lastrowid
        conn.execute("UPDATE memories SET int_superseded_by=? WHERE int_memory_id=?", (new_id, args.int_memory_id))
        conn.commit()
    emit({"ok": True, "int_memory_id": new_id, "int_superseded_memory_id": args.int_memory_id, "backup": backup_path})


def memory_delete(args) -> None:
    backup_path = backup(args.db)
    with connect(args.db) as conn:
        if conn.execute("SELECT int_memory_id FROM memories WHERE int_memory_id=?", (args.int_memory_id,)).fetchone() is None:
            raise SystemExit(f"memory {args.int_memory_id} not found")
        ids = [row["int_memory_id"] for row in conn.execute(
            "WITH RECURSIVE chain(int_memory_id) AS (SELECT ? UNION ALL SELECT m.int_memory_id FROM memories m JOIN chain c ON m.int_superseded_by=c.int_memory_id) SELECT int_memory_id FROM chain",
            (args.int_memory_id,),
        ).fetchall()]
        if not ids:
            raise SystemExit(f"memory {args.int_memory_id} not found")
        conn.executemany("DELETE FROM memories WHERE int_memory_id=?", [(item,) for item in reversed(ids)])
        conn.commit()
    emit({"ok": True, "deleted": ids, "backup": backup_path})


def config_show(args) -> None:
    if not args.config.exists():
        raise SystemExit(f"config not found: {args.config}")
    data = tomllib.loads(args.config.read_text(encoding="utf-8"))
    emit(data)


def toml_literal(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return '""'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_literal(item) for item in value) + "]"
    return json.dumps(str(value))


def config_set(args) -> None:
    if "." not in args.key:
        raise SystemExit("key must be section.name, for example bot.news_enabled")
    if not args.yes:
        raise SystemExit("refusing config write without --yes")
    section, key = args.key.split(".", 1)
    value = toml_literal(parse_value(args.value))
    text = args.config.read_text(encoding="utf-8") if args.config.exists() else ""
    backup_path = backup(args.config) if args.config.exists() else None
    lines = text.splitlines()
    out = []
    current = None
    found_section = False
    wrote = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if current == section and not wrote:
                out.append(f"{key} = {value}")
                wrote = True
            current = stripped.strip("[]")
            if current == section:
                found_section = True
        if current == section and stripped.startswith(f"{key} "):
            out.append(f"{key} = {value}")
            wrote = True
            continue
        out.append(line)
    if not found_section:
        if out and out[-1].strip():
            out.append("")
        out.append(f"[{section}]")
        out.append(f"{key} = {value}")
    elif not wrote:
        out.append(f"{key} = {value}")
    args.config.write_text("\n".join(out) + "\n", encoding="utf-8")
    emit({"ok": True, "key": args.key, "value": parse_value(args.value), "backup": backup_path})


def tools_list(args) -> None:
    with connect(args.db) as conn:
        rows = conn.execute(
            "SELECT id,name,enabled,globally_disabled,scope_type,scope_id,executor_name,is_builtin FROM agent_assets WHERE asset_type='tool' ORDER BY name,scope_type,id"
        ).fetchall()
    emit([dict(row) for row in rows])


def tools_set(args) -> None:
    backup_path = backup(args.db)
    enabled = 1 if args.action == "enable" else 0
    with connect(args.db) as conn:
        cur = conn.execute(
            "UPDATE agent_assets SET enabled=?, globally_disabled=CASE WHEN scope_type='global' THEN ? ELSE globally_disabled END, updated_at=? WHERE asset_type='tool' AND name=?",
            (enabled, 0 if enabled else 1, datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), args.name),
        )
        conn.commit()
    emit({"ok": True, "name": args.name, "action": args.action, "rowcount": cur.rowcount, "backup": backup_path})


def web_fetch(args) -> None:
    req = urllib.request.Request(args.url, headers={"User-Agent": "Dirac doctor.py"})
    with urllib.request.urlopen(req, timeout=args.timeout) as resp:
        data = resp.read(args.bytes)
        emit({
            "ok": 200 <= resp.status < 400,
            "status": resp.status,
            "url": resp.geturl(),
            "content_type": resp.headers.get("content-type"),
            "bytes": len(data),
            "text": data.decode(resp.headers.get_content_charset() or "utf-8", errors="replace"),
        })


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dirac doctor: low-level runtime, SQLite, memory, config, tool, and online diagnostics.")
    parser.add_argument("--db", type=Path, default=default_db_path())
    parser.add_argument("--config", type=Path, default=default_config_path())
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("paths").set_defaults(func=command_paths)
    sub.add_parser("tables").set_defaults(func=command_tables)
    schema = sub.add_parser("schema")
    schema.add_argument("table")
    schema.set_defaults(func=command_schema)
    sql = sub.add_parser("sql")
    sql.add_argument("sql")
    sql.add_argument("--write", action="store_true")
    sql.add_argument("--yes", action="store_true")
    sql.set_defaults(func=command_sql)
    dump = sub.add_parser("dump")
    dump.add_argument("table")
    dump.add_argument("--limit", type=int, default=50)
    dump.set_defaults(func=command_dump)
    delete_row = sub.add_parser("delete-row")
    delete_row.add_argument("table")
    delete_row.add_argument("id", type=int)
    delete_row.add_argument("--yes", action="store_true")
    delete_row.set_defaults(func=command_delete_row)

    db = sub.add_parser("db")
    db_sub = db.add_subparsers(dest="db_command", required=True)
    db_sub.add_parser("status").set_defaults(func=db_status)
    db_upgrade_parser = db_sub.add_parser("upgrade")
    db_upgrade_parser.add_argument("--yes", action="store_true")
    db_upgrade_parser.set_defaults(func=db_upgrade)

    mem = sub.add_parser("memory")
    mem_sub = mem.add_subparsers(dest="memory_command", required=True)
    mem_list = mem_sub.add_parser("list")
    mem_list.add_argument("--str-discord-id")
    mem_list.add_argument("--query")
    mem_list.add_argument("--limit", type=int, default=50)
    mem_list.set_defaults(func=memory_list)
    mem_add = mem_sub.add_parser("add")
    mem_add.add_argument("str_discord_id")
    mem_add.add_argument("str_annotations")
    mem_add.add_argument("--array-tags")
    mem_add.add_argument("--float-confidence", type=float, default=0.7)
    mem_add.add_argument("--created-by", default="doctor.py")
    mem_add.set_defaults(func=memory_add)
    mem_update = mem_sub.add_parser("update")
    mem_update.add_argument("int_memory_id", type=int)
    mem_update.add_argument("str_annotations")
    mem_update.add_argument("--array-tags")
    mem_update.add_argument("--float-confidence", type=float)
    mem_update.add_argument("--created-by", default="doctor.py")
    mem_update.set_defaults(func=memory_update)
    mem_delete = mem_sub.add_parser("delete")
    mem_delete.add_argument("int_memory_id", type=int)
    mem_delete.set_defaults(func=memory_delete)

    config = sub.add_parser("config")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser("show").set_defaults(func=config_show)
    config_set_parser = config_sub.add_parser("set")
    config_set_parser.add_argument("key")
    config_set_parser.add_argument("value")
    config_set_parser.add_argument("--yes", action="store_true")
    config_set_parser.set_defaults(func=config_set)

    tools = sub.add_parser("tools")
    tools_sub = tools.add_subparsers(dest="tools_command", required=True)
    tools_sub.add_parser("list").set_defaults(func=tools_list)
    for action in ("enable", "disable"):
        p = tools_sub.add_parser(action)
        p.add_argument("name")
        p.set_defaults(func=tools_set, action=action)

    web = sub.add_parser("web-fetch")
    web.add_argument("url")
    web.add_argument("--timeout", type=float, default=8.0)
    web.add_argument("--bytes", type=int, default=12000)
    web.set_defaults(func=web_fetch)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except sqlite3.Error as exc:
        print(f"sqlite error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"os error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
