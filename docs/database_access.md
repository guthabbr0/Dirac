# Database Access Contract

This document is the contract for direct SQLite access from Dirac-adjacent tools, including future external repos. Read it before changing schema, migrations, writer behavior, `doctor.py`, or cross-process database access.

## Runtime Location

The default runtime DB is:

```text
/home/codexy/Desktop/workspaces/dirac-config/bot.sqlite
```

`DIRAC_CONFIG_DIR` can override the runtime directory. `python doctor.py paths` prints the effective config and DB paths.

## SQLite WAL Behavior

Dirac keeps SQLite in WAL mode. WAL supports many concurrent readers and one writer at a time. SQLite serializes writers through file locks, so data integrity is fine for light direct read/write use, but write contention can still produce `database is locked` if a process holds a transaction too long or does not set a busy timeout.

The in-process `RuntimeDb` writer queue only coordinates writes inside the Dirac process. External direct writes bypass that queue and do not emit Dirac WebSocket broadcasts or in-memory UI refresh events.

## External Connection Settings

External Python tools should open the same DB with a timeout, foreign keys, WAL, and busy timeout:

```python
import sqlite3

DB_PATH = "/home/codexy/Desktop/workspaces/dirac-config/bot.sqlite"

conn = sqlite3.connect(DB_PATH, timeout=10.0)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys=ON")
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=10000")

with conn:
    conn.execute(
        "INSERT INTO memories(str_discord_id,str_annotations,array_tags,float_confidence,str_created_utc,str_created_by) VALUES (?,?,?,?,?,?)",
        (
            "1506438075977568266",
            "debug note",
            '["debug"]',
            0.8,
            "2026-05-29T00:00:00Z",
            "external:my-tool",
        ),
    )
```

Keep transactions short. Do not hold a transaction open while calling a model, waiting on the network, prompting an operator, or scanning large result sets.

## Safe Direct Writes

Direct external writes are acceptable for low-contention maintenance and append-style workflows when the table contract is followed:

- `memories`
- `memory_events`
- `discord_identity_map`
- Read-heavy diagnostics
- Append-only audit or diagnostic rows where the schema is already understood

Use ISO-8601 UTC timestamps. Store `array_tags` as valid JSON array text. Never write secrets into logs, memory, command rows, or model-facing context tables.

## Use Caution

Direct writes require extra care for state that Dirac expects to own or immediately reflect in memory/UI:

- `permissions`
- `agent_assets`
- `tool_snapshots`
- `agent_tasks`
- Provider configuration tables
- Any table where the runtime should broadcast an immediate WebSocket update
- Any state where an in-process scheduler, provider router, or permission check may already have cached assumptions

For those tables, prefer Dirac commands, the panel API, or `doctor.py` unless the runtime is stopped or the repair is deliberate and audited.

## Migrations

Do not run schema migrations from two processes at once. Do not run an external migration while Dirac is running.

Use the controlled path:

```bash
python doctor.py db upgrade --yes
```

That path creates a backup, runs the repo bootstrap/migration code, and stamps `schema_meta.schema_tag` with the current source schema tag.
