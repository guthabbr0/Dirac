# Dirac Usage Guide

## Risk Notice
Dirac uses `discord.py-self` to automate a Discord user account. This is not covered by Discord's ToS and may result in account limitation.

The bot refuses to start unless `discord.i_understand_selfbot_risk = true` is set in runtime `config.toml`.

## Fastest Local Start
```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
mkdir -p /home/codexy/Desktop/workspaces/dirac-config
cp config.example.toml /home/codexy/Desktop/workspaces/dirac-config/config.toml
chmod 600 /home/codexy/Desktop/workspaces/dirac-config/config.toml
.venv/bin/pytest
.venv/bin/python bot.py
```

On this machine the runtime config/state directory is `/home/codexy/Desktop/workspaces/dirac-config`, so the live files are `/home/codexy/Desktop/workspaces/dirac-config/config.toml` and `/home/codexy/Desktop/workspaces/dirac-config/bot.sqlite`. Set `DIRAC_CONFIG_DIR` to override that path.

## Where To Put Secrets
Edit `/home/codexy/Desktop/workspaces/dirac-config/config.toml`. This file is local-only and must not be committed.

Use this shape:

```toml
[ollama]
endpoint = "https://ollama.com"
api_key = "PASTE_OLLAMA_API_KEY_HERE"
default_model = "llama3.2"
request_timeout_s = 120.0

[discord]
token = "PASTE_DISCORD_USER_TOKEN_HERE"
i_understand_selfbot_risk = true

[panel]
host = "127.0.0.1"
port = 8765
auth_token = "PASTE_LONG_RANDOM_PANEL_PASSWORD_HERE"

[bot]
trigger_on = ["ping", "reply"]
auto_compact_threshold = 0.80
proactive_memory_enabled = false
proactive_memory_interval_minutes = 60
context_window_tokens = 4096
root_operator_ids = ["1482143139828596916"]
news_enabled = false
news_channel_id = "1506027063512141896"
news_summary_interval_minutes = 180
news_memory_interval_minutes = 420

[logging]
console_level = "info"
component_levels = { "provider" = "info", "discord" = "info", "bot" = "info" }
provider_http_debug = false
```

Generate a strong panel token with:

```bash
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(32))"
```

The key fields are:

- `ollama.api_key`: your Ollama API key.
- `discord.token`: your Discord user token.
- `discord.i_understand_selfbot_risk`: must be `true`.
- `panel.auth_token`: the password used to log in to the local panel.

Never paste these values into Discord, panel chat, issue comments, or logs.

## Run Tests
Run the full suite before startup and before declaring changes done:

```bash
.venv/bin/pytest
```

The current suite covers command parsing and handling, permission filtering, database bootstrap and writer behavior, context assembly, memory management, and panel API routes.
It also covers provider registry bootstrapping, provider routing/logging, scoped task behavior, task APIs, and Roxanne API routes.

## Start The App
Start Dirac from the repo root:

```bash
.venv/bin/python bot.py
```

To confirm exactly which build a folder will run without starting Discord:

```bash
.venv/bin/python bot.py --version
```

To start with more verbose logs and persist that choice into runtime `config.toml`:

```bash
.venv/bin/python bot.py --log-level debug --component-log provider=debug --provider-http-debug
```

While the bot is running in an interactive terminal, press `+` to increase console verbosity or `-` to reduce it. The new level is persisted in `[logging]`. Console logs are colorized and printed in `Europe/Madrid`; database timestamps stay ISO-8601 UTC. JSON detail payloads are pretty-printed only in the terminal; stored `bot_logs.detail_json` stays compact JSON.

Then open:

```text
http://127.0.0.1:8765
```

Log in with the value from `panel.auth_token`.

## Verify Connections
For first run, prefer the panel UI:

- Open the Config tab.
- Use the Test Ollama button.
- Use the Test Discord button.

The direct API endpoints are:

- `POST /api/config/test-ollama`
- `POST /api/config/test-discord`

If either test fails, fix `config.toml` first and restart if needed.

## Configure Providers
Dirac seeds a provider named `ollama-default` from `[ollama]` in `config.toml`. Use the panel Providers tab to add additional providers:

- `ollama`: Ollama Cloud or compatible `/api/chat`.
- `openrouter`: OpenRouter `/chat/completions`.
- `openai_compatible`: generic OpenAI-compatible `/chat/completions`.

Provider API keys are local secrets. The panel shows only whether a key exists, its SHA-256 fingerprint, and the last four characters.

Use the Scopes tab to bind a DM, channel, guild, user, or global default to a provider/model. Use Provider Calls and Task Runs to see which provider/model/parameters were used.

## Debug Logging
Use the panel Debug tab for live scoped logs. It can filter by component, level, `scope_type`, and `scope_id`.

Useful components:

- `provider`: provider routing and redacted HTTP requests/responses.
- `discord`: Discord connection and message receive diagnostics.
- `bot`: process lifecycle and console-level changes.
- `panel`: panel API activity and connection tests.

Levels, from most verbose to least verbose, are `trace`, `debug`, `info`, `warn`, and `error`.

Provider HTTP logging is controlled by `logging.provider_http_debug` or by setting the `provider` component to `debug`. Request and response headers/bodies are written to the Debug tab and console with known tokens/API keys redacted before they are written to the console, database, WebSocket, or Roxanne context.

At `trace`, the `discord`, `ollama`, and `discord_tool` components show the live wake lifecycle: typing indicator start/refresh/stop, model turn start/finish, requested tool calls, tool inputs/results, elapsed milliseconds, and model finalization. Discord wake replies can use up to five tool follow-up turns before a text-only finalization call; recurring and REM tasks can use four. Each model turn receives an explicit `[[ TOOL ROUND N/TOTAL ]]` budget banner, and the final text-only call receives a critical no-tools reminder. Tool-round banners are generated only at provider-call time, so stale round markers are not retained in the reusable transcript. Console detail values are trimmed after pretty rendering so long prompts, fetched pages, and command output stay readable.

## Code-Origin Output And Context Hygiene
Deterministic Discord command replies and hardcoded fallback errors are wrapped in `` ```dirac `` fenced blocks. That fence means "Dirac code produced this", not "the model inferred this." Raw `messages`, `memory_events`, command logs, bot logs, and Roxanne audit tools still show those blocks for troubleshooting.

Normal Discord model context, rolling summaries, compaction input, and REM short-term slices strip only exact `dirac` fences. Other code blocks such as `bash`, `json`, `text`, or `bash dirac eats it` remain visible. If a user pastes a `dirac` block in the current turn, the current trigger remains visible for that turn; the filter is for later context pollution.

## Time And Date Access
Dirac injects the current date/time into the system context for Discord wake responses, panel chat, recurring tasks, and Roxanne. The injected clock includes `Europe/Madrid`, UTC, weekday, and offset.

### Roxanne

Use the panel Roxanne tab for operator troubleshooting. Roxanne is separate from Discord memories: she has her own static memory table, threaded chat sessions, selectable provider/model/parameter profile, a reasoning mode selector, and a visible tools list. Her tools can read local docs, inspect redacted runtime state, search/add/edit/delete Dirac memories, search messages/logs, fetch one safe public URL, perform a bounded public web search, and run Bash through the authenticated panel path. If she says docs or runtime state are unavailable while the tools are enabled, that is a bug.

The built-in `current_time` tool is enabled by default. When the model needs a fresh clock during a response, it can call that tool and receive current `Europe/Madrid` and UTC timestamps.

## Bootstrap Permissions
Discord commands are admin-only. The panel can bootstrap the first admin permission.

From the panel Commands tab, run:

```text
!whitelist add YOUR_DISCORD_USER_ID admin *
```

After that, Discord-side commands from that user can work globally unless a scoped `blocked` permission overrides the global admin row.

To see the current command and capability map from Discord, run:

```text
!help all
```

For the concise human command reference, read `HELP.md`.

To verify the running build and latest local changes, run:

```text
!version
!changelog
```

Emergency controls are reserved for the protected super-admin user only:

```text
!kill
!stop [seconds]
!pause [seconds]
!resume
```

`!stop` drops non-super-admin input and suspends replies, model calls, news, and task queues for the cooldown, defaulting to 60 seconds. `!pause` keeps collecting messages but suppresses non-super-admin replies/model calls until its timer expires or `!resume` is sent.

To manage memories, use explicit targets or let `show` default to the current Discord channel:

```text
!memory
!memory add USER_ID likes concise answers tags=preference
!memory add CHANNEL_ID ongoing provider debugging tags=project
!memory add <@USER_ID> likes concise answers
!memory add <#CHANNEL_ID> ongoing provider debugging
!memory update #20 replacement note tags=debug confidence=0.9
!memory delete #20
!memory show
!memory show all
!memory show USER_ID
!memory show CHANNEL_ID
```

To inspect redacted runtime configuration and known Ollama usage, run:

```text
!help config
```

To control Ollama reasoning/thinking for the current scope, run one of:

```text
!reasoning off
!reasoning on
!reasoning low
!reasoning medium
!reasoning high
!reasoning show
!reasoning clear
```

Use `*` to apply globally:

```text
!reasoning off *
```

`clear` removes Dirac's override and lets the model/API default apply again.

To read the bundled admin help doc, run:

```text
!help docs admin
```

Root-only commands are available to Discord user `1482143139828596916` and the local panel operator:

```text
!create investigate this bug and propose a fix
!agent show
!agent show 1
!agent tools
!tool show
!tool add sample_tool describe what this tool should do
!tool edit web_fetch body Fetch public pages only and always reply with a summary
!tool edit sample_tool executor web_fetch
!tool disable sample_tool
!tool disable silencer *
!tool enable silencer *
!tool snapshot
!tool fix
!tool delete sample_tool
!skill show
!skill add sample_skill describe the workflow
!task add daily_digest every 6h summarize useful channel activity
!task show
!task show daily_digest
!task edit daily_digest prompt summarize useful channel activity and memory drift
!task run daily_digest
!task disable daily_digest
!task delete daily_digest
!task fix
!providers list
!providers show ollama-default
!scope show
!scope provider ollama-default llama3.2
!scope params default-balanced
!scope reset-provider
!news now
```

Use `*` for global tools, skills, or tasks and `@SCOPE_ID` to target a specific current scope type. Tool and skill lists are ordered by name and show stable `#id` values; use `#8` or `silencer`, not the visual row position. The built-in global tools are `react_emoji`, `silencer`, `current_time`, `web_fetch`, `web_search`, `memory_search`, `memory_add`, `memory_update`, `memory_edit`, `memory_delete`, `memory_remove`, `discord_id`, `discord_ground`, `discord_tag`, `dyslexic_helper`, and `bash`. Built-in tool definitions are stored in SQLite from `docs/builtin_tools_snapshot.json`; edit them from the panel or Discord, and use `!tool fix` to restore the built-in snapshot without re-enabling a globally disabled tool. `!tool disable <name> *` disables that tool everywhere until `!tool enable <name> *`.

Tool behavior notes:

- `react_emoji` can add a reaction, but Dirac must still send a text reply. If the model only asks for the emoji, Dirac performs a follow-up model turn for the reply.
- `silencer` requires a reason, only blocks the triggering author, and can never block root operators such as `1482143139828596916`.
- `web_fetch` fetches only public HTTP/HTTPS URLs, blocks local/private/metadata networks, sends no cookies or secrets, and returns cleaned text for a follow-up answer.
- `web_search` runs a bounded public search and returns results for a follow-up answer.
- `memory_search` searches persisted memories through `MemoryManager`/SQLite FTS and explains that access path in its tool result.
- `memory_add`, `memory_update`/`memory_edit`, and `memory_delete`/`memory_remove` let Dirac repair persisted memories from tool calls, but Discord execution is restricted to the protected root operator.
- `discord_id` and `discord_ground` resolve Discord snowflake IDs to trusted JSON for known users, channels, guilds, nicknames, and the protected `.normal.man.` superuser identity when available.
- `discord_tag` stores one deterministic 255-character label for one snowflake in `discord_identity_map`; calling it again replaces the label, and there is intentionally no delete tool.
- `dyslexic_helper` replaces known ugly Discord refs in arbitrary text with those deterministic labels and returns missing IDs that should be tagged.
- `bash` runs `/bin/bash` for the root operator on Discord and for Roxanne through the authenticated panel path. Prefer `python doctor.py ...` for SQLite, memory, config, tool, and online diagnostics.

`doctor.py` is the command-line repair console for the same runtime files:

```bash
python doctor.py paths
python doctor.py memory list --str-discord-id CHANNEL_ID --limit 20
python doctor.py memory add CHANNEL_ID "debug note" --array-tags debug
python doctor.py sql "SELECT id,name,enabled FROM agent_assets WHERE asset_type='tool'"
python doctor.py sql "SELECT title,source,last_posted_utc FROM news_items ORDER BY last_seen_utc DESC LIMIT 10"
python doctor.py config set bot.news_enabled false --yes
python doctor.py web-fetch https://example.com
```

See `docs/doctor.md` for the full operator workflow.

`!task show` shows the visible recurring tasks for the current scope, including status, run count, last run, next run, prompt preview, and last result/error preview. Last/next task times are shown in `Europe/Madrid`; the stored `last_run_utc` and `next_run_utc` fields remain UTC. Task state is included in the model context, so a direct mention like `<@BOT_USER_ID> did you run your tasks?` should be answered from the persisted task table.

Use `!task edit <id|name> name|prompt|schedule|enabled|model|provider_id|runtime_kind <value>` to change a recurring task from Discord or edit it in the panel Tasks tab. `runtime_kind=rem` is what injects the short-term memory slice; `runtime_kind=default` runs an ordinary task. Use `!task disable <id|name>` to stop a task while keeping its run history. Use `!task delete <id|name>` to permanently remove the task row. Use `!task fix` to restore tasks from `docs/builtin_tasks_snapshot.json`.

The default `rem_dream` task is ordinary editable DB state seeded from `docs/builtin_tasks_snapshot.json`. It wakes every 10 minutes when enabled, receives the filtered short-term memory slice from `memory_events`, and can use the normal memory/search/Discord-grounding tools for up to four tool follow-up turns before going back to sleep. Dirac renders the current `[[ REM TOOL ROUND N/TOTAL ]]` banner ephemerally for the active provider call, encourages batching independent memory/search edits in one round, and records `[DIRAC_RUNTIME_GENERATED_TASK_WARNING]` instead of a fake `DONE` if the model keeps asking for tools after the final text-only reminder.

Recurring tasks are process-local scheduling, not durable cron. While Dirac is alive, the scheduler wakes every 30 seconds, randomly picks one due enabled task regardless of whether the previous stored status is `queued`, `running`, `failed`, or `completed`, advances that task's next run first, and launches the inference work in the background. Failures and long-running attempts do not disable the task; the next interval can try again.

Discord wake tool batches run concurrently with a bounded parallel limit. Dirac waits for the whole batch before calling the model again, preserving the model's tool/result turn order while avoiding avoidable I/O serialization. Panel chat and Roxanne also receive per-call round banners and batch guidance; those surfaces process up to eight requested tool calls from a single assistant reply. The panel Memory tab auto-refreshes only its short-term slice while open, defaults to 60 minutes, and keeps manual refresh for persisted memories and Discord tags.

In the panel Tasks tab, the list filter defaults to `all`, so web loading should show global, DM, group, and guild tasks together. Use the filter controls to narrow to one scope.

Background news is disabled by default. Use `!news now` for a manual AI/model/benchmark summary. It keeps Artificial Analysis, Hugging Face Blog, and arXiv `cs.AI`/`cs.LG`/`cs.CL` as known-source grounding, then explores current public web-search results for model releases, agent frameworks, coding-agent status, and benchmarks. Candidate URLs, titles, sources, dates, first/last seen times, posted counts, and last-posted times are stored in `news_items`, so recent items are skipped when fresh alternatives exist. Summaries include dates when available or `date unknown`; if no unseen item exists, Dirac says it is repeating known sources. If `bot.news_enabled = true`, startup posts a build banner to `bot.news_channel_id` and then posts the latest summary; later summaries run every `bot.news_summary_interval_minutes` and consolidated summaries are stored to memory every `bot.news_memory_interval_minutes`.

Use the Roxanne tab when you need help navigating or troubleshooting the WebUI. Roxanne receives a fresh runtime snapshot on every ask: local docs, redacted config, provider summaries and recent calls, bot logs, command logs, recent messages, tasks, task runs, table counts, process metadata, and selected scope context. She can search/add/update/delete Dirac memories and run Bash through the authenticated panel tool path. She cannot reveal full secrets, but she can confirm secret presence, fingerprints, and last-four previews.

## First Discord Smoke Test
Start in a DM or an accessible channel.

Mention the self-bot account directly:

```text
<@BOT_USER_ID> hello
```

You can also reply to a previous bot message once one exists.

Confirm that Dirac responds, then check the panel logs and messages views to confirm the message, wake event, and Ollama call were persisted.

## Operational Notes
- Keep the panel bound to `127.0.0.1` for fast local mode.
- Do not expose the panel over plain HTTP.
- `/home/codexy/Desktop/workspaces/dirac-config/bot.sqlite` is the local SQLite database.
- `/home/codexy/Desktop/workspaces/dirac-config/config.toml` contains secrets and should remain local-only.
- Panel config writes may create `config.toml.*.bak` backups that also contain secrets.

Back up the database with:

```bash
sqlite3 /home/codexy/Desktop/workspaces/dirac-config/bot.sqlite ".backup bot.backup.sqlite"
```

## Troubleshooting
- PEP 668 or externally managed Python: use `.venv` as shown above.
- Startup refuses the risk flag: set `discord.i_understand_selfbot_risk = true`.
- Panel returns 401: log in with `panel.auth_token`.
- Discord test returns 401: the Discord token is invalid, expired, or copied incorrectly.
- Ollama test fails: check `ollama.endpoint`, `ollama.api_key`, and `ollama.default_model`.
- Port conflict: change `panel.port` in `config.toml`.
- Commands are ignored: whitelist your Discord user as admin from the panel.
- Never paste secrets into Discord or panel chat.
