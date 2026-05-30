# Dirac Memory Contract

This document is the canonical map for persisted Dirac memories. Read it before changing `!memory`, `MemoryManager`, memory tools, the panel Memory API, Roxanne memory tools, REM memory writes, or memory schema migrations.

## Canonical Columns

The `memories` table stores one durable memory against one Discord snowflake id. The current columns are:

- `int_memory_id`: primary key.
- `str_discord_id`: Discord user, channel, or guild snowflake as digits only. Mentions may be accepted by callers but must be normalized before storage.
- `str_annotations`: durable memory text.
- `array_tags`: JSON array text containing short string tags, or `NULL`.
- `float_confidence`: number from `0.0` to `1.0`.
- `str_created_utc`: ISO-8601 UTC timestamp.
- `str_created_by`: provenance string such as `operator`, `tool:<name>`, or `task:<name>:run:<id>`.
- `int_superseded_by`: replacement memory id, or `NULL` for active rows.

SQLite FTS indexes `str_annotations`, `array_tags`, and `str_discord_id` through `memories_fts` with `content_rowid='int_memory_id'`.

The obsolete persisted-memory names are not part of the public contract: the old split target fields, the old note/tag/confidence names, and raw row id for memory tools. Tool calls using those names must return `invalid_arguments` with obsolete-argument guidance through `legacy_memory_arg_issues()`.

## MemoryManager

All runtime memory writes should keep using `MemoryManager` as the validation and normalization chokepoint:

```python
await MemoryManager(db).add(
    str_discord_id,
    str_annotations,
    array_tags=None,
    float_confidence=0.7,
    str_created_by="operator",
)

await MemoryManager(db).search(
    str_discord_id=None,
    query=None,
    pending=None,
    limit=10,
)

await MemoryManager(db).update(
    int_memory_id,
    str_annotations,
    array_tags=None,
    float_confidence=0.7,
    str_created_by="operator",
)

await MemoryManager(db).delete(int_memory_id)
```

Search and mutation results expose canonical row keys, including `int_memory_id`.

## Discord Commands

Operators may pass a raw snowflake, a user mention, or a channel mention. The command parser normalizes that into `str_discord_id`.

```text
!memory add <discord_id|@user|#channel> <annotations> [tags=t1,t2] [confidence=0.8]
!memory update <#id|id> <annotations> [tags=t1,t2] [confidence=0.8]
!memory delete <#id|id>
!memory show
!memory show all
!memory show <discord_id|@user|#channel>
!memory show <#id|id>
```

`!memory show` defaults to the current Discord channel scope. `!memory update` supersedes the old row; `!memory delete` removes the current row and its superseded chain.

## Panel API

The panel Memory tab uses canonical field names:

```text
GET /api/memories?str_query=TEXT&str_discord_id=DISCORD_ID&limit=50
POST /api/memories
PUT /api/memories/{memory_id}
DELETE /api/memories/{memory_id}
```

`POST` and `PUT` bodies use:

```json
{
  "str_discord_id": "1506438075977568266",
  "str_annotations": "debug note",
  "array_tags": ["debug"],
  "float_confidence": 0.8
}
```

Responses use `int_memory_id` for the row id.

## Tool Schemas

Built-in memory tools are seeded from `dirac.memory_contract` into `docs/builtin_tools_snapshot.json` and SQLite `tool_snapshots`.

- `memory_search`: `str_query`, `str_discord_id`, `int_limit`.
- `memory_add`: `str_discord_id`, `str_annotations`, `array_tags`, `float_confidence`.
- `memory_update` and `memory_edit`: `int_memory_id`, `str_annotations`, `array_tags`, `float_confidence`.
- `memory_delete` and `memory_remove`: `int_memory_id`.

`array_tags` must be an array of strings. `float_confidence` must be between `0.0` and `1.0`. Discord-side memory write/delete tools remain root-operator-only at runtime.

## Doctor CLI

Use `doctor.py` when the panel or Discord surface is unavailable:

```bash
python doctor.py memory list --str-discord-id 1506438075977568266 --query debug --limit 20
python doctor.py memory add 1506438075977568266 "debug note" --array-tags debug --float-confidence 0.8
python doctor.py memory update 20 "replacement note" --array-tags debug,repair --float-confidence 0.9
python doctor.py memory delete 20
```

`doctor.py memory list` prints canonical row keys. `python doctor.py dump memories` orders by `int_memory_id`.

## REM And Roxanne

REM memory writes should identify their provenance with `str_created_by='task:<name>:run:<id>'` when a task run id is available. Short-term visible traffic belongs in `memory_events`; durable conclusions belong in `memories`.

Roxanne also has a separate `roxanne_memory` table. Its `tags` column is Roxanne-only static memory metadata and is not the same field as `memories.array_tags`.
