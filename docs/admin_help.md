# Dirac Admin Help

This file is the operator-facing capability map that Dirac can expose through `!help docs admin` and the panel chat `read_docs` tool.

## Fast Mental Model

Dirac is four surfaces sharing one SQLite audit database:

- Discord self-bot listener and responder.
- Provider-aware model bridge for Ollama Cloud, OpenRouter, and OpenAI-compatible APIs.
- Local FastAPI panel at `http://127.0.0.1:8765`.
- Roxanne, the WebUI assistant for explaining the panel and redacted runtime state.

Discord commands are deterministic code paths. They are never sent to the LLM. Unauthorized commands stop at the permission filter and are excluded from model context. Deterministic command replies and hardcoded fallback errors are wrapped in `` ```dirac `` fenced blocks so operators can distinguish code-origin output from model prose.

## Admin Commands

- `!help [all|config|docs|docs <name>]`: show compact help, full capabilities, redacted config, and docs.
- `!version`: show the running Dirac version and capability families.
- `!changelog`: show recent local implementation changes.
- `!kill`: ultimate-only process kill for the protected super-admin user; it is parsed before any LLM path and cannot be granted through permission rows.
- `!stop [seconds]`: ultimate-only cooldown, default 60 seconds. Non-super-admin input is dropped and replies, model calls, news, and task queues are suspended.
- `!pause [seconds]`: ultimate-only mute. Non-super-admin messages are still collected, but replies/model calls are suppressed until the timer expires or `!resume`.
- `!resume`: ultimate-only lift for an active pause/stop hold.
- `!status`: show runtime, active scope, model, context state, and known Ollama usage.
- `!prompt '<body>' [*|@id]`: set the active prompt for this scope, global scope, or a specific scope.
- `!compact`: summarize the older half of context.
- `!summary`: summarize the full current working context.
- `!clear`: clear active context state for this scope without deleting audit history.
- `!whitelist add|remove|block <user_id> [root|admin|user] [*|@id]`: manage permissions.
- `!memory` or `!memory help`: show memory command usage.
- `!memory add <discord_id|@user|#channel> <annotations> [tags=t1,t2] [confidence=0.8]`: add memory for one normalized Discord snowflake id.
- `!memory update <#id|id> <annotations> [tags=t1,t2] [confidence=0.8]`: supersede an active memory row.
- `!memory delete <#id|id>`: delete a memory row and its superseded chain.
- `!memory show all`, `!memory show <discord_id|@user|#channel>`, or `!memory show <#id|id>`: list memory. With no arguments, Discord commands default to the current channel scope. Mention IDs are normalized before storage and lookup.
- `!model <model_name> [*|@id]`: set a model override.
- `!reasoning show|clear|on|off|low|medium|high [*|@id]`: control the Ollama `/api/chat` `think` field.
- `!create <task>`: root-only sub-agent task creation. Results are persisted in `agent_tasks`.
- `!agent help|show [id]|tools`: root-only inspection for sub-agent tasks and installed CLIs.
- `!tool help|add|show [#id|name]|edit <#id|name> description|body|schema|executor|enabled|globally_disabled <value>|enable <#id|name>|disable <#id|name>|delete <#id|name>|snapshot|snapshot apply [version]|fix [*|@id]`: root-only scoped tool management.
- `!skill help|add|show [#id|name]|edit <#id|name> description|body|enabled <value>|enable <#id|name>|disable <#id|name>|delete <#id|name> [*|@id]`: root-only scoped skill management.
- `!task add <name> every <5m|2h|1d> <prompt> [*|@id]`: root-only recurring task creation.
- `!task help|show [id|name]|edit <id|name> name|prompt|schedule|enabled|model|provider_id|runtime_kind <value>|run <id|name>|enable <id|name>|disable <id|name>|delete <id|name>|fix`: root-only recurring task inspection and control.
- `!providers list|show <name|id>|test <name|id>|enable <name|id>|disable <name|id>`: root-only provider visibility and tests.
- `!scope show|provider <provider> <model>|params <profile>|reset-provider [*|@id]`: root-only effective scope and provider assignment control.
- `!news now`: root-only immediate AI/model/benchmark news fetch, summary, and memory write using known-source grounding plus exploratory web search.

## Panel Capabilities

- Dashboard: quick health, provider, task, and run summary.
- Providers: list, add, edit, disable, and test model providers with redacted key identity.
- Provider Calls: inspect model call latency, token usage, ignored parameters, and failures.
- Bot Entries: inspect configured bot entry personas.
- Scopes: view effective provider/model/parameters/tools/skills and set scoped provider/model overrides.
- Instructions: store structured operator instructions for scopes and future migration away from raw prompts.
- Logs: inspect bot logs.
- Debug: tune persisted log levels, filter live scoped logs by component and scope, and inspect redacted provider HTTP traffic.
- Channels: list seen scopes.
- Prompts: edit global prompt.
- Perms: inspect permission rows.
- Memory: search/edit/delete persisted memory rows, inspect recent short-term memory events, and maintain deterministic Discord identity tags.
- WebChat: talk to the private panel assistant.
- Tools: add, edit, enable, disable, globally disable, restore snapshots, or delete scoped tools.
- Skills: add, edit, enable, disable, or delete scoped skills.
- Tasks: add, edit, run, disable, delete, and restore recurring scoped tasks. The task list defaults to all scopes and can be filtered by scope.
- Task Runs: inspect provider/model/parameter provenance for task executions.
- Commands: issue deterministic commands as `source='panel'`.
- Config: view redacted config and use connection tests.
- Roxanne: use a threaded WebUI assistant with selectable provider/model/reasoning settings, Roxanne-only static memory, docs/runtime tools, memory/message/log search, and safe public web fetch/search.
- Live tail: see WebSocket events in a readable bottom drawer.

## Root-Only Agent Surface

Only Discord user `1482143139828596916` and the local panel operator can use root-only commands. The emergency runtime controls are stricter: only Discord user `1482143139828596916` can use `!kill`, `!stop`, `!pause`, and `!resume`.

The root operator has a protected global `root` permission row. Root operators cannot be blocked by scoped permission rows or by the silencer tool.

The root-only surface deliberately does not expose arbitrary shell execution to Discord. Task outputs and task runs are persisted and auditable.

## Providers And Scoped Routing

`ollama-default` is seeded from `[ollama]` in runtime `config.toml` for compatibility. Additional providers can be added through the panel Providers tab. Supported provider types are `ollama`, `openrouter`, and `openai_compatible`.

Provider API keys are stored locally and shown only by redacted identity: presence, fingerprint, and last four characters. Full secrets are never returned by APIs, `!help config`, Roxanne context, or panel JSON.

Effective provider resolution checks task overrides, Roxanne profile, user scope, active scope, bot entry binding, global scope, then the first enabled provider. Scoped model and reasoning overrides remain compatible with `!model` and `!reasoning`.

Task runs are recorded in `agent_task_runs` with trigger source, triggered by, scope, provider, model, parameters, prompt, result/error, token counts when available, and timestamps.

## Roxanne

Roxanne is a panel-side assistant, not the Discord bot. She runs through `dirac/roxanne.py`, and the launch path keeps moving behavior into repo-local modules. On every ask, Dirac injects a fresh runtime snapshot into her context: local docs, Roxanne-only static memory, redacted config, provider registry state, provider call logs, bot logs, command logs, recent messages, task definitions, task run history, selected effective scope, table counts, and process metadata.

She should use that snapshot and her tools proactively for troubleshooting and should not claim she cannot access docs, logs, runtime state, memory, provider calls, or task runs when those sources are available. Her dedicated tools can read docs, inspect redacted config/providers/effective scope, search/add/edit/delete persisted memories, search messages/logs, use `web_fetch`, run public `web_search`, run Bash through the authenticated panel path, and read current time. She can explain how to use the WebUI and run `python doctor.py ...` through Bash for SQLite, memory, tool, config, and online diagnostics. She must still avoid exposing full Discord tokens, panel auth tokens, provider API keys, bearer headers, or other secrets.

`doctor.py` is the low-level command-line repair tool. Use it for direct runtime inspection and repair when the WebUI or model tool layer is confused:

```bash
python doctor.py paths
python doctor.py db status
python doctor.py db upgrade --yes
python doctor.py memory list --str-discord-id CHANNEL_ID --limit 20
python doctor.py sql "SELECT id,name,enabled,globally_disabled FROM agent_assets WHERE asset_type='tool'"
python doctor.py config set bot.news_enabled false --yes
python doctor.py web-fetch https://example.com
```

See `docs/doctor.md` for the full command list.

## Tools, Skills, And Tasks

Tools and skills are scoped like prompts: global, DM, group, or guild. Scoped entries override global entries by name. `disable` on a scoped copy turns off that tool/skill for that scope while leaving the global default intact. `!tool disable <name> *` globally disables a tool everywhere until `!tool enable <name> *`. Disabled tools and skills are never included in model context; disabled tools are not exposed to Discord model calls and rejected if requested through a directive.

Tool and skill command lists use stable database `#id` values and are ordered by name. They do not expose a separate row index. If a scoped row is enabled but the global row is `globally_disabled`, the list and detail views show the effective state as disabled and point the operator to `!tool enable <name> *`.

Built-in tools are seeded from `docs/builtin_tools_snapshot.json` into SQLite and recorded in `tool_snapshots`. Operators can edit their descriptions, bodies, schemas, executors, and enabled state from Discord or the panel. `delete` removes the DB row even for built-ins; `!tool fix` restores the latest built-in snapshot while preserving current enabled/global-disable state for rows that still exist.

Built-in tools:

- `react_emoji`: allows Dirac to add one emoji reaction to the message that woke it, but Dirac must still send a text reply.
- `silencer`: allows Dirac to block the triggering author in the current scope only with a required reason. It ignores arbitrary model-supplied user IDs and can never block root operators, panel, or Dirac's own user.
- `current_time`: allows Dirac to read the current date/time in `Europe/Madrid` and UTC.
- `web_fetch`: fetches one public HTTP/HTTPS URL, blocks local/private/metadata networks, sends no cookies or secrets, and returns cleaned text for a required follow-up answer.
- `web_search`: performs a bounded public web search and returns results for a required follow-up answer.
- `memory_search`: searches persisted memories through `MemoryManager`/SQLite FTS and returns matching rows plus an access-path explanation for a required follow-up answer.
- `memory_add`, `memory_update`/`memory_edit`, and `memory_delete`/`memory_remove`: root-only Discord tools for repairing persisted memory rows.
- `discord_id` and `discord_ground`: resolve Discord snowflake IDs to known users, channels, guilds, nicknames, and trusted JSON identity grounding.
- `discord_tag`: stores or replaces one deterministic label for one Discord snowflake in `discord_identity_map`; there is intentionally no delete tool for this map.
- `dyslexic_helper`: rewrites ugly Discord refs in arbitrary text with stored identity labels and reports missing IDs.
- `bash`: runs `/bin/bash` with captured/redacted output. Discord execution is root-operator only; Roxanne receives it only through panel authentication.

The active tools and skills are inserted into the model context for the current scope. Supported Discord tools are also passed as Ollama tool schemas during wake responses. Dirac lets the model request tools, executes each batch concurrently with a bounded parallel limit, appends structured tool results or errors in call order, and calls the model again with an explicit `[[ TOOL ROUND N/TOTAL ]]` budget banner. Discord wake replies allow up to five tool follow-up turns before a critical text-only finalization reminder; recurring and REM tasks allow four. The banners tell the model to batch independent tool calls in one round instead of spending the budget serially, and they are rendered ephemerally immediately before each provider request rather than retained in the reusable prompt transcript. Dirac also injects the current `Europe/Madrid` and UTC time into the system context on every wake/task/panel/Roxanne call, so the model can answer time-sensitive questions without guessing. Immediately before each provider request, Dirac injects trusted runtime request context with the exact model tag in the outgoing API body, provider name/type, and fresh time metadata; prompts can place that note with `{{DIRAC_RUNTIME_CONTEXT}}` or only the model tag with `{{DIRAC_REQUEST_MODEL}}`.

Recurring tasks live in `agent_tasks` with `enabled`, `schedule_minutes`, `next_run_utc`, `last_run_utc`, `run_count`, `result`, and `error`. `!task show` is human-readable and includes last/next run time in `Europe/Madrid` plus previews of the prompt and last result/error. `!task show <id|name>` shows the longer detail. The persisted task timestamp columns remain UTC.

Built-in task definitions are seeded from `docs/builtin_tasks_snapshot.json` into SQLite and recorded in `task_snapshots`. The default `rem_dream` task is ordinary editable DB state with `runtime_kind=rem`: it wakes every 10 minutes when enabled, receives the latest short-term `memory_events` slice, can use the normal memory/search/Discord-grounding tools for up to four follow-up turns, and then returns to sleep. Dirac renders the live REM round as `[[ REM TOOL ROUND N/TOTAL ]]` for the current provider call only; if the model exhausts the budget and still asks for tools during text-only finalization, Dirac records `[DIRAC_RUNTIME_GENERATED_TASK_WARNING]` rather than pretending the model produced `DONE`. Change `runtime_kind` to `default` to make it an ordinary task. `!task fix` restores the snapshot while preserving disabled state.

The in-process scheduler wakes every 30 seconds while the bot is alive. On each tick, it lists due enabled recurring tasks regardless of previous stored status, randomly picks one, advances `next_run_utc` before launch, and executes it through the same Ollama-backed task runner. Scheduled Discord-scoped task results are sent back to the scoped channel when the background scheduler runs them.

Active task state is inserted into wake-response context, so Dirac can answer questions like "did you run your tasks?" from persisted task state instead of guessing.

`edit` changes stored task fields. `disable` is non-destructive: it sets `enabled=0` and clears `next_run_utc`, leaving history and the last result visible. `delete` is destructive: it removes the `agent_tasks` row permanently.

## News Scheduler

The news scheduler is disabled by default. Use `!news now` for a manual AI/model/benchmark summary. If `bot.news_enabled = true`, Dirac posts a startup build banner to the configured `bot.news_channel_id`, then immediately posts the latest AI/model/benchmark summary. The banner includes the app version, release timestamp, Git commit, branch, dirty state, and code directory. Later summaries run on the configured interval and consolidated summaries are written to that channel's memory.

News state is durable in `news_items`: URL, title, source, grounding/exploratory kind, published date when available, first/last seen timestamps, last-posted timestamp, posted count, and metadata. Known-source grounding stays Artificial Analysis, Hugging Face Blog, and arXiv `cs.AI`, `cs.LG`, and `cs.CL`. Each run also explores a deterministic set of current model/agent/benchmark/coding-agent/open-source release searches, fetches promising public URLs through the same safe public-fetch rules, extracts dates when possible, and prefers candidates from the last 14 days. Recent posted URLs are skipped when fresh alternatives exist; if no unseen item exists, Dirac explicitly says it is repeating known sources.

## Visibility And Limits

Admins can inspect redacted configuration, command logs, model call logs, message history, memory, prompts, and context state through commands and panel APIs.

Secrets stay hidden. Discord tokens, Ollama API keys, and panel auth tokens are never shown by `!help config`, panel config, or model tools.

The Debug tab and console logs use the same persisted `[logging]` configuration. Levels are `trace`, `debug`, `info`, `warn`, and `error`. Component overrides can target `provider`, `discord`, `discord_tool`, `ollama`, `bot`, `panel`, `agent_tasks`, `news`, `roxanne`, and database-related logs. Provider DEBUG records redacted HTTP request and response method, URL, headers, JSON body, status, and response body. Wake TRACE records typing indicator lifecycle, model turn lifecycle, tool call inputs/results, elapsed time, and failures. Known API keys, bearer headers, Discord tokens, and panel tokens are masked before logs are stored or streamed. At `trace`, console detail prints full redacted message/tool payloads up to the trace cap so crashes include the useful arguments and error strings. Terminal JSON is indented for humans, while stored SQLite `detail_json` stays compact and parseable.

`schema_meta.schema_tag` records the source schema tag in SQLite. If the DB tag is newer than the running code, Dirac refuses to bootstrap that DB. If the DB tag is missing or older, Dirac warns and continues best-effort; run `python doctor.py db upgrade --yes` after reviewing/backing up the DB to apply the current schema path and stamp the tag.

At startup, `python bot.py --log-level debug --component-log provider=debug --provider-http-debug` enables provider request/response visibility. Use `python bot.py --version` to print the exact build and runtime directory without starting Discord. In an interactive console, `+` increases verbosity and `-` reduces it; the selected level is saved back to runtime `config.toml`. Console logs are colorized and printed in `Europe/Madrid`; SQLite audit timestamps remain UTC.

Reasoning is controlled with the Ollama `/api/chat` `think` field. `!reasoning off` sends `false`, `!reasoning on` sends `true`, and `!reasoning low|medium|high` sends that level string. `!reasoning clear` removes Dirac's override and lets the API/model default apply.

Token usage is recorded when the Ollama response includes token counts. Some providers or failures may leave token counts at zero or null.

## Known Not-Yet-Implemented Areas

- Message edit handling.
- Attachment ingestion.
- Multi-operator accounts.
- Full prompt history diff UI.
- Full provider model discovery/import UI.
