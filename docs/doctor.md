# Dirac Doctor

`doctor.py` is the low-level operator console for Dirac runtime repair. It works directly against the runtime SQLite database and `config.toml`, so it is useful when the WebUI, Roxanne, or Discord command surface is confused.

Default paths match `bot.py`:

```bash
python doctor.py paths
python doctor.py db status
python doctor.py tables
python doctor.py schema memories
```

Use `--db` and `--config` to point at alternate files.

## DB Schema Tag

Dirac stores the source schema tag in `schema_meta`. Runtime bootstrap refuses a DB tagged newer than the running code so older code cannot corrupt newer state. Older or missing tags warn and continue best-effort.

```bash
python doctor.py db status
python doctor.py db upgrade --yes
```

`db upgrade --yes` creates a backup when the DB exists, runs the repo bootstrap/migration path, and stamps the current source schema tag.

## Memory Repair

```bash
python doctor.py memory list --str-discord-id 1506438075977568266 --query debug --limit 20
python doctor.py memory add 1506438075977568266 "debug note" --array-tags debug --float-confidence 0.8
python doctor.py memory update 20 "replacement note" --array-tags debug,repair --float-confidence 0.9
python doctor.py memory delete 20
```

Memory commands use the canonical persisted-memory names: `str_discord_id`, `str_annotations`, `array_tags`, `float_confidence`, and `int_memory_id`. The Discord id must be one 15-22 digit snowflake; user and channel mentions are normalized before storage. `--array-tags` accepts comma-separated tags or JSON array text.

Writes create `*.doctor-<UTC>.bak` backups before changing the database. `memory update` follows Dirac's normal supersession model; `memory delete` removes the selected memory and the superseded chain beneath it. `memory list` and `dump memories` output canonical row keys.

## SQL And Tables

Read-only SQL runs without flags:

```bash
python doctor.py sql "SELECT int_memory_id,str_discord_id,str_annotations,array_tags FROM memories ORDER BY int_memory_id DESC LIMIT 10"
python doctor.py sql "SELECT title,source,source_kind,last_seen_utc,last_posted_utc,posted_count FROM news_items ORDER BY last_seen_utc DESC LIMIT 10"
python doctor.py dump memories --limit 30
python doctor.py dump agent_assets --limit 30
```

Write SQL requires both `--write` and `--yes`:

```bash
python doctor.py sql "UPDATE agent_assets SET enabled=1 WHERE name='bash'" --write --yes
python doctor.py delete-row news_items 4 --yes
python doctor.py delete-row roxanne_memory 4 --yes
```

## Config And Online Checks

```bash
python doctor.py config show
python doctor.py config set bot.news_enabled false --yes
python doctor.py tools list
python doctor.py tools enable bash
python doctor.py web-fetch https://example.com --bytes 2000
```

Config output redacts obvious secrets. Config writes preserve the existing file shape where possible and create a backup first.

`doctor.py` opens SQLite with `timeout=10.0`, `PRAGMA foreign_keys=ON`, and `PRAGMA busy_timeout=10000` so it can coexist with a running WAL-mode Dirac process for short repair operations. Use `docs/database_access.md` before building any other external writer.

## Roxanne And Bash

Roxanne has an authenticated panel-only `bash` tool. Dirac has a Discord `bash` tool, but runtime execution is root-operator only. Prefer asking either assistant to run `python doctor.py ...` for state repair because it gives consistent JSON output and creates backups before destructive writes.
