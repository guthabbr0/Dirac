# Dirac

To start `discord.i_understand_selfbot_risk = true` is set in runtime `config.toml`.

## What it does
Dirac is a Discord self-bot, provider-aware model bridge, and FastAPI control panel currently launched through `bot.py`. It supports the legacy Ollama Cloud config plus first-class provider rows for Ollama, OpenRouter, and OpenAI-compatible APIs. It persists observed Discord messages, deterministic command attempts, model I/O, task runs, operator chat, short-term memory events, editable memories, Discord identity tags, and logs into SQLite with FTS search.

The bot wakes only when pinged or replied to. Commands beginning with `!` are parsed before any LLM logic; unauthorized commands are logged and stopped, and authorized commands are executed by code rather than sent to Ollama. Emergency controls `!kill`, `!stop [seconds]`, `!pause [seconds]`, and `!resume` are ultimate-only for the protected super-admin user and cannot be granted through normal permission rows.

The web panel is a dark developer cockpit for providers, scoped model routing, bot entries, instructions, logs, channels, prompts, permissions, memories, private webchat, tools, skills, tasks, task runs, commands, Roxanne, and redacted configuration. Roxanne now has a dedicated threaded chat surface with provider/model/reasoning settings, static Roxanne-only memory, memory repair tools, Bash, and docs/runtime/web tools.

Roxanne receives fresh runtime context on each ask, including redacted config, provider calls, bot logs, command logs, recent messages, task runs, selected scope state, and process metadata.

For human command syntax, start with [HELP.md](HELP.md). `USAGE.md` has workflow examples, `docs/admin_help.md` is the longer admin map exposed through `!help docs admin`, `docs/doctor.md` covers the low-level `doctor.py` repair console, `docs/memory_contract.md` is the canonical persisted-memory contract, and `docs/database_access.md` covers direct SQLite access from external tools.

## Quick start
```bash
pip install -r requirements.txt
mkdir -p /home/codexy/Desktop/workspaces/dirac-config
cp config.example.toml /home/codexy/Desktop/workspaces/dirac-config/config.toml
# edit dirac-config/config.toml, set secrets and i_understand_selfbot_risk = true
python bot.py
# open http://127.0.0.1:8765
```

## Guides
- Human setup and operations: `USAGE.md`
- Agent grounding and contribution rules: `AGENTS.md`
- Admin help exposed to the bot and panel chat: `docs/admin_help.md`
- Persisted memory contract: `docs/memory_contract.md`
- SQLite/external DB access contract: `docs/database_access.md`
- Low-level repair console: `docs/doctor.md`

## Configuration reference
- `ollama.endpoint`: Ollama API base URL.
- `ollama.api_key`: bearer token for Ollama.
- `ollama.default_model`: default model name.
- `ollama.request_timeout_s`: HTTP timeout in seconds.
- `discord.token`: Discord user token.
- `discord.i_understand_selfbot_risk`: must be `true` to run.
- `panel.host`: FastAPI bind host.
- `panel.port`: FastAPI bind port.
- `panel.auth_token`: shared panel password/session token.
- `bot.trigger_on`: wake modes, normally `ping` and `reply`.
- `bot.auto_compact_threshold`: ratio of token budget before compacting.
- `bot.proactive_memory_enabled`: reserved for future periodic memory proposals; keep disabled.
- `bot.proactive_memory_interval_minutes`: reserved proposal interval.
- `bot.context_window_tokens`: approximate context budget.
- `bot.root_operator_ids`: Discord user IDs allowed to use root-only commands.
- `bot.news_enabled`: start the background AI/model-news scheduler. Default is `false`; use `!news now` for manual updates.
- `bot.news_channel_id`: channel that receives startup greeting and news summaries.
- `bot.news_summary_interval_minutes`: interval for quick AI/model news summaries.
- `bot.news_memory_interval_minutes`: interval for saving consolidated AI/model news summaries to memory.
- `logging.console_level`: persisted console verbosity, one of `trace`, `debug`, `info`, `warn`, or `error`.
- `logging.component_levels`: per-component overrides such as `{ "provider" = "debug", "discord" = "info" }`.
- `logging.provider_http_debug`: record redacted provider HTTP request details; `trace` also records redacted response previews.

Provider rows are initialized from `[ollama]` as `ollama-default`. Add OpenRouter or OpenAI-compatible providers in the panel Providers tab; API keys are stored locally and displayed only as redacted presence, fingerprint, and last-four identity.

Runtime logging can also be adjusted at startup with `--log-level debug`, `--component-log provider=debug`, and `--provider-http-debug`. Use `python bot.py --version` to print the app version, release timestamp, Git commit, branch, code directory, runtime directory, and SQLite path without starting Discord. In an interactive terminal, press `+` to increase console verbosity or `-` to reduce it; the level is persisted. Console logs are colorized and shown in `Europe/Madrid`; persisted DB timestamps remain ISO-8601 UTC. At `trace`, Discord wake responses log model turns, tool call inputs/results, elapsed time, typing indicator refreshes, and error detail payloads with full redacted message/tool bodies up to the trace console cap. Console JSON is pretty-printed for humans; stored `bot_logs.detail_json` remains compact machine-readable JSON.

Keep the panel bound to `127.0.0.1` unless it is behind a TLS-terminating reverse proxy with its own access controls. The panel uses a reusable cookie token, so exposing it over plaintext HTTP can leak operator credentials.

## Command reference
| Command | Args | Effect |
|---|---|---|
| `!version` | — | Show running Dirac version and enabled capability families |
| `!changelog` | — | Show recent local implementation changes |
| `!kill` | — | Ultimate-only: terminate the Python process without restart handling |
| `!stop` | `[N seconds]` | Ultimate-only: drop non-super-admin input and suspend replies/model calls/news/tasks for a cooldown, default 60 seconds |
| `!pause` | `[N seconds]` | Ultimate-only: keep collecting non-super-admin messages but suppress replies/model calls until the timer expires or `!resume` |
| `!resume` | — | Ultimate-only: clear an active pause/stop hold |
| `!prompt` | `'<body>' [*|@id]` | Set/show system prompt |
| `!compact` | — | Summarize older half of context |
| `!summary` | — | Summarize full working buffer |
| `!clear` | — | Reset context state for scope |
| `!whitelist` | `add|remove <user_id> [root\|admin\|user] [*|@id]` | Manage permissions |
| `!memory` | `help`, `add <discord_id\|@user\|#channel> <annotations>`, `update <#id\|id> <annotations>`, `delete <#id\|id>`, `show ...` | Manage memories |
| `!model` | `<model_name> [*|@id]` | Store model override as scoped config memory |
| `!reasoning` | `show|clear|on|off|low|medium|high [*|@id]` | Control Ollama `think` reasoning for a scope |
| `!create` | `<task>` | Root-only sub-agent task creation |
| `!agent` | `help`, `show [id]`, `tools` | Root-only sub-agent task and tool inspection |
| `!tool` / `!skill` | `help`, `add`, `show [#id\|name]`, `edit`, `enable`, `disable`, `delete ... [*|@id]`; tools also support `snapshot` and `fix` | Root-only scoped tool and skill management; lists are ordered by name and use stable `#id` values |
| `!task` | `help`, `add <name> every <5m\|2h\|1d> <prompt> [*|@id]`, `show [id\|name]`, `edit`, `run`, `enable`, `disable`, `delete`, `fix` | Root-only recurring task management |
| `!providers` | `list|show|test|enable|disable <name\|id>` | Root-only provider inspection and tests |
| `!scope` | `show\|provider <provider> <model>\|params <profile>\|reset-provider [*|@id]` | Root-only effective scope/provider control |
| `!news` | `now` | Root-only manual AI/model news fetch/summarize/memorize using known-source grounding plus exploratory web search |
| `!status` | — | Show uptime/model/context/token status |
| `!help` | `[all|config|docs|docs <name>]` | Show compact help, full admin help, redacted config, runtime status, and docs |

## Permission model
Permissions can be global or scoped to `dm`, `group`, or `guild` scope IDs. `root` is protected and cannot be blocked; `admin` includes `user`; `blocked` denies non-root access even if another row grants access. The Discord root operator is `1482143139828596916`.

## Database
The default runtime directory is `/home/codexy/Desktop/workspaces/dirac-config` when that directory exists, or `DIRAC_CONFIG_DIR` when set. Its `bot.sqlite` contains messages with FTS5, prompts, permissions, service providers, provider calls, bot entries, instructions, task runs, command logs, Ollama compatibility logs, bot logs, context state, memories, short-term `memory_events`, durable `news_items`, Discord identity tags, editable tools/skills, tool and task snapshots, Roxanne sessions, and panel chat. The base schema lives in `docs/schema.sql`; `bot.py` still owns migrations and runtime bootstrap. `schema_meta.schema_tag` records the source schema tag: a newer DB tag makes the runtime refuse to touch the database, while an older/missing tag warns and continues best-effort until `python doctor.py db upgrade --yes` stamps the current tag. See `docs/memory_contract.md` before touching memory columns or tools, and `docs/database_access.md` before building another process that reads or writes the same DB.

Use `python doctor.py paths`, `python doctor.py db status`, `python doctor.py memory list --str-discord-id DISCORD_ID --limit 20`, `python doctor.py tools list`, and `python doctor.py sql "SELECT ..."` for low-level runtime inspection and repair. Destructive `doctor.py` operations create timestamped backups and require explicit confirmation where appropriate. See `docs/doctor.md`.

## Panel screenshots
The control panel renders a dark dashboard with Providers, Provider Calls, Bot Entries, Scopes, Instructions, Logs, Debug, Channels, Prompts, Permissions, Memory, WebChat, Tools, Skills, Tasks, Task Runs, Commands, Config, and Roxanne tabs. The Memory tab can search/edit/delete persisted memories, review an auto-refreshing short-term event slice that defaults to the last 60 minutes, and maintain Discord identity tags. The Tasks tab can edit tasks and restore the built-in REM task snapshot. The Roxanne tab is a compact threaded assistant workspace with a thread list, chat transcript, provider/model/reasoning controls, Roxanne-only static memory, and visible tool inventory. The Debug tab filters live bot logs by component, level, and scope, including redacted provider HTTP requests and responses when enabled. Screenshots are not yet committed to this repository.

## Time And Model Awareness
Dirac injects the current `Europe/Madrid` and UTC date/time into the system context for Discord wake responses, panel chat, tasks, and Roxanne. Immediately before every provider request, Dirac also injects trusted runtime request context with the exact model tag being sent in the API body, plus provider name/type and fresh time metadata; prompts may use `{{DIRAC_RUNTIME_CONTEXT}}` or `{{DIRAC_REQUEST_MODEL}}` to place that note explicitly. The built-in `current_time` tool is enabled by default so the model can refresh the exact date/time during a response. Built-in Discord tools are seeded from `docs/builtin_tools_snapshot.json` into SQLite; `react_emoji`, `silencer`, `current_time`, `web_fetch`, `web_search`, `memory_search`, `memory_add`, `memory_update`, `memory_edit`, `memory_delete`, `memory_remove`, `discord_id`, `discord_ground`, `discord_tag`, `dyslexic_helper`, and `bash` descriptions, bodies, schemas, executors, and enabled state can be edited, disabled, deleted, or restored with `!tool fix`. Memory write/delete and Bash execution are root-operator only from Discord; Roxanne reaches Bash through the authenticated panel path.

## Memory And REM
Visible inbound and outbound bot interactions are copied into `memory_events` as short-term memory without model reasoning text. Deterministic code-origin Discord output is wrapped as `` ```dirac `` fenced blocks; raw rows stay visible in SQLite, audit views, and Roxanne, but those blocks are stripped from normal model context, rolling summaries, compaction input, and REM short-term slices. The default `rem_dream` recurring task is seeded from `docs/builtin_tasks_snapshot.json` into `agent_tasks` with `runtime_kind=rem`, runs every 10 minutes while the bot process is alive, and receives the latest filtered short-term slice as its own scheduled context. Operators can edit, disable, delete, retarget it, or change `runtime_kind` to `default` like any other task; `!task fix` restores the snapshot without forcing disabled tasks back on. The in-process scheduler wakes every 30 seconds, picks one random due enabled task regardless of its previous status, advances its next run before launch, and lets failures or long-running attempts retry on their next interval.

## News
Manual `!news now` keeps the trusted Artificial Analysis, Hugging Face Blog, and arXiv `cs.AI`/`cs.LG`/`cs.CL` grounding sources, then adds exploratory public web-search candidates for current model, agent, benchmark, coding-agent, and open-source release status. Candidate URLs, titles, sources, dates, first/last seen times, posted counts, and last posted times are stored in `news_items`, so recent posted items are skipped when fresh alternatives exist. Summaries include dates when available or `date unknown`; if no unseen item is available, Dirac says it is repeating known sources instead of presenting repeats as fresh.

Model tool use now runs in a bounded follow-up loop: Dirac lets the model request tools, executes supported tools in code, returns structured results or errors, and calls the model again with explicit `[[ TOOL ROUND N/TOTAL ]]` budget banners. Those banners are rendered ephemerally immediately before each provider request and are not retained in the reusable prompt transcript. Discord wake replies allow up to five tool follow-up turns before a loud text-only finalization reminder; scheduled and REM task runs allow four tool follow-up turns. Tool batches are executed concurrently with a bounded parallel limit, and the prompt explicitly tells the model to batch independent I/O work such as web fetch/search, memory repair, and diagnostics instead of spending turns serially. The memory tools go through `MemoryManager` and SQLite FTS/row APIs; the model never receives raw SQL access. Discord identity grounding is injected as trusted JSON before chat context, and `discord_tag`/`dyslexic_helper` provide deterministic labels for ugly snowflake-heavy text.

If a REM run exhausts its tool-round budget and still requests tools during the text-only finalization call, Dirac records an explicit `[DIRAC_RUNTIME_GENERATED_TASK_WARNING]` result instead of inventing a successful `DONE`. That warning remains visible as runtime-origin task state so later REM runs and operator tools can tell the previous assimilation attempt was cut short.

## Tests
Run `pytest tests/ -v`. CI can add `pytest --cov=bot --cov-fail-under=80`.

## Roadmap / known limitations
- No message edit handling yet.
- No attachment handling yet.
- Single operator only.
- Prompt changes are audited in `prompt_history`, but the panel has no diff UI yet.
- The old proactive-memory config flags are still reserved; the active memory organizer is the editable `rem_dream` task.
- The news scheduler is disabled by default because manual `!news now` is less noisy during active development.
- Scheduled task output is persisted in `agent_tasks`; Discord-scoped tasks run by the background scheduler also post their result to the scoped channel. Task last/next displays are shown in `Europe/Madrid`, while persisted `next_run_utc` and `last_run_utc` stay UTC. `disable` stops a task and keeps its row; `delete` permanently removes it.

## License
MIT
