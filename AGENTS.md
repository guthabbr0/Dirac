# AGENTS.md — instructions for coding agents working on this repo

## Ground rules
- Keep current behavior operable through `bot.py` while extracting behavior into repo-local modules.
- Prefer repo-local module boundaries when extracting code, following `docs/modular_architecture_plan.md`.
- Move behavior out of `bot.py` when a coherent module boundary exists; keep the panel usable throughout any frontend extraction.
- ISO-8601 UTC for all timestamps. Decimal dot, space digit grouping.
- Never weaken the permission filter.
- Add or update tests for every change. Run `pytest` before declaring done.
- Update README.md and AGENTS.md when behavior changes.

## Architecture pointers
- Read `docs/admin_help.md` before changing admin-facing capabilities.
- Read `docs/ui_guidelines.md` before changing the WebUI or panel APIs.
- Read `docs/memory_contract.md` before changing persisted memories, memory tools, `!memory`, panel memory APIs, Roxanne memory tools, or REM memory writes.
- Read `docs/database_access.md` before changing schema, writer behavior, doctor DB repair, or external SQLite access.
- Read `docs/doctor.md` before changing `doctor.py`.
- Schema changes require an update to `docs/schema.sql`, a migration block at the top of `bootstrap_db()`, a `doctor.py db upgrade --yes` path, and a test in `test_db.py`. Keep `DB_SCHEMA_TAG` aligned to `APP_VERSION`; doctor reports this as the code schema tag.
- New commands: parser + handler + permission check + test in `test_commands.py` + entry in `!help`.
- New panel routes: handler + auth check + test in `test_panel_api.py` + frontend wiring.

## Fast grounding workflow
- Read `README.md`.
- Read `USAGE.md`.
- Read `docs/admin_help.md`.
- Read `docs/ui_guidelines.md`.
- Inspect `bot.py` with targeted search before editing.
- Run `.venv/bin/pytest` before declaring done.

## Code map
- Config/runtime state: `RUNTIME_DIR`, `CONFIG_PATH`, `DB_PATH`, `load_config`, `Config`, `config_to_dict`, panel config routes. Runtime files default to `/home/codexy/Desktop/workspaces/dirac-config` when that directory exists, or `DIRAC_CONFIG_DIR` when set.
- DB/schema: `docs/schema.sql`, `docs/database_access.md`, `SCHEMA_SQL`, `bootstrap_db`, `DbWriter`, `RuntimeDb`.
- Permissions: `_permission_level`, `check_permission`, `is_blocked_user`.
- Commands: `parse_command`, `CommandHandler`.
- Context/memory: `assemble_context`, `system_prompt_for_scope`, compaction methods, `memory_events`, `discord_identity_map`, `dirac/memory_contract.py`, `docs/memory_contract.md`, `dirac/context_filters.py`, `dirac/rem.py`.
- Ollama: `OllamaClient.chat`.
- Providers: `service_providers`, `provider_models`, `provider_parameters`, `provider_calls`, `resolve_provider_binding`, `provider_chat_payload`.
- Logging/debug: `dirac/logging.py`, `RuntimeLogger`, `LOG_LEVELS`, `current_logging_config`, `app_log`, `/api/logging`, `/api/bot-logs`, Debug tab in `PANEL_HTML`.
- Discord: `BotCore`, `create_discord_client`.
- Panel: `PANEL_HTML`, FastAPI routes, WebSocket broadcast.
- Module ownership: follow `docs/modular_architecture_plan.md`; keep `bot.py` as the launch surface during extraction.
- WebUI rules: `docs/ui_guidelines.md`; tab selection must auto-load data through `loadTab()`.
- Roxanne: `dirac/roxanne.py`, `roxanne_profiles`, `roxanne_sessions`, `roxanne_messages`, `roxanne_memory`, `roxanne_runtime_context`, `/api/roxanne/*`.
- News: `dirac/news.py`, `news_items`, `!news now`, `build_news_summary`.
- Admin docs/help: `docs/admin_help.md`, `read_doc`, `admin_help_overview`, `CommandHandler._help`.

## Critical invariants
- Unauthorized commands never reach the LLM.
- Commands are excluded from assembled context.
- Exact `` ```dirac `` fenced command/code output is excluded from model-facing historical context, compaction, summaries, and REM slices; raw SQLite audit rows and Roxanne views remain unfiltered.
- Blocked users are excluded from context.
- Runtime DB writes go through the writer queue.
- Persisted Dirac memories use the canonical `int_memory_id`, `str_discord_id`, `str_annotations`, `array_tags`, `float_confidence`, `str_created_utc`, `str_created_by`, and `int_superseded_by` contract.
- Secrets are redacted in API responses and never logged.
- All timestamps are ISO-8601 UTC.
- Provider API keys are never exposed unredacted; use fingerprints/last-four only.
- Task executions that call the model should create provider-call and task-run provenance when possible.
- Console/debug UI may render `Europe/Madrid` local time, but persisted DB columns named `timestamp_utc` remain UTC.

## Change recipes
- New command: parser, handler, permission check, `!help`, tests.
- Reasoning control: keep `!reasoning` mapped to Ollama `/api/chat` `think`; test request-body wiring.
- Root-only commands: keep `!create`, `!agent`, `!tool`/`!tools`, `!skill`/`!skills`, `!task`/`!tasks`, `!providers`, `!scope`, and `!news` restricted to `ROOT_OPERATOR_ID` or panel.
- Ultimate-only commands: keep `!kill`, `!stop`, `!pause`, and `!resume` restricted to `ROOT_OPERATOR_ID` only; panel and ordinary root permission rows must not bypass this.
- Version surface: update `APP_VERSION`, append a new `CHANGELOG` entry, `!version`, and `!changelog` when behavior changes. Never rewrite an existing version tag with a different description or add duplicate entries for the same tag.
- Providers/scopes: preserve compatibility with `[ollama]`, `model_overrides`, and `reasoning_overrides`; new provider rows must stay redacted in API responses.
- Logging/debug: keep request details redacted, route operator-visible rows through `app_log`/`RuntimeLogger`, keep console JSON pretty-printed, keep DB `detail_json` compact, and preserve persisted `[logging]` updates from the Debug tab, CLI flags, and console `+`/`-` hotkeys.
- Tool/debug visibility: keep Discord wake/tool/model trace logs useful and bounded; at `trace`, console detail should show full redacted message/tool payloads up to the trace cap, while structured DB/WebSocket log rows remain redacted.
- Time/model awareness: keep `current_time_context_note()` injected into model-facing system context, keep the built-in `current_time` tool enabled unless explicitly scoped off by the operator, and keep `OllamaClient.chat()` injecting trusted runtime request context with the exact outgoing model tag before provider calls.
- Model/tool loop: Discord wake replies allow up to five tool follow-up turns before text-only finalization; scheduled and REM task runs allow four tool follow-up turns unless that operator-facing budget is intentionally changed and documented. Keep the explicit `[[ TOOL ROUND N/TOTAL ]]` banners, batch-tool guidance, and final text-only no-tools reminder in sync with the real budget. Tool-round state is rendered ephemerally at provider-call time through `{{DIRAC_TOOL_TURN_STATE}}`; do not persist rendered round banners in reusable message transcripts.
- WebUI changes: preserve auto-loading tabs, global scope serialization without `scope_id=`, resizable/readable nav, and API tests for empty global scope edge cases.
- Roxanne: keep her WebUI-only and operator-oriented; she receives fresh runtime rows and Roxanne-only static memory for troubleshooting, can edit Dirac memories and run Bash through authenticated panel tools, but never expose full secrets through docs/runtime/tool context. Her implementation lives in `dirac/roxanne.py`; keep `bot.py` as the launcher and route host.
- Tools/skills/tasks: preserve scope semantics; global rows apply everywhere unless scoped rows override by name. Built-in tool metadata comes from `docs/builtin_tools_snapshot.json` and SQLite `tool_snapshots`; built-in task metadata comes from `docs/builtin_tasks_snapshot.json` and SQLite `task_snapshots`. Built-in tool rows can be hard-deleted by operators and restored with `!tool fix`; keep executable names stable and use `!tool fix`/`!task fix` snapshot restore rather than re-hardcoding tool or task bodies in Python.
- Command list output: use stable `#id` values or names for follow-up commands; do not show a separate display index that can be mistaken for an id.
- Command/code-origin output: deterministic Discord command output and hardcoded fallback errors must use `` ```dirac `` fences. Model prose should remain unfenced unless the model intentionally writes a code block.
- Tool safety: `silencer` must require justification and never affect root operators, `react_emoji` must still produce a text reply, `web_fetch` must remain public-web-only with local/private/metadata networks blocked, Discord identity tags must not expose a delete tool, and Discord `bash` plus memory write/delete tools must remain root-operator-only at runtime.
- Task visibility: keep scheduled task state in assembled context and keep `!task show` human-readable with `Europe/Madrid` last/next run and result/error previews.
- REM memory: keep `rem_dream` editable/deletable DB state seeded from `docs/builtin_tasks_snapshot.json`; `runtime_kind=rem` is the editable switch that injects short-term memory events, and `!task fix` is the restore path. Short-term visible traffic goes to `memory_events`, not model reasoning. Never synthesize a successful REM `DONE`; if the runtime cuts a REM run short after the tool budget, persist an explicit runtime-origin warning so later REM runs can distinguish code fallback from model-authored output.
- Task deletion: `disable` is non-destructive; `delete` is the hard-delete path and must remain root-only/audited through command logs.
- Panel task list: default web/API task loading should include all scopes; scope-specific filters are for narrowing only.
- Task scheduler: keep it process-local and cron-like; every 30 seconds pick one random due enabled task regardless of stored status, advance `next_run_utc` before launch, and let failed or long-running attempts retry on their next interval.
- News scheduler: keep it disabled by default; if explicitly enabled, avoid blocking startup and keep fetch/summarize/send failures logged, not fatal. `!news now` should use known-source grounding plus exploratory web search, persist candidates in `news_items`, skip recently posted URLs when fresh alternatives exist, and include dates or `date unknown`.
- New panel route: auth dependency, API test, frontend wiring.
- Schema change: migration/bootstrap change and `test_db.py`.
- Ollama behavior: route through `OllamaClient.chat`.
- Frontend change: keep panel API contracts tested and the WebUI operable while frontend code moves to a clearer module boundary.

## Bring-up checklist for agents
- Ensure runtime `config.toml` exists in `/home/codexy/Desktop/workspaces/dirac-config` and remains ignored by git.
- Install deps in `.venv`.
- Run tests.
- Start app.
- Verify panel login.
- Verify Ollama/Discord test buttons.
- Bootstrap admin permission from panel.

## Conventions
- All DB writes go through the writer queue in runtime paths. Tests may use direct in-memory connections for setup.
- External direct SQLite writers must follow `docs/database_access.md`; they bypass the in-process writer queue and WebSocket broadcasts.
- All LLM calls go through `OllamaClient.chat()`. Never construct httpx requests inline.
- All operator-visible log lines go to `bot_logs` and should be broadcast via the WebSocket pub/sub when available.
- Provider HTTP DEBUG/TRACE logs may include full request/response shapes but must redact headers and known secrets before console, DB, WebSocket, or Roxanne exposure.
- Context assembly: only true instructions/capabilities belong in `system`; remembered facts, task state, and rolling summaries should stay as user-role context notes.
- Context filters: strip only exact `dirac` fenced blocks from model-facing history and REM; preserve `bash`, `json`, `text`, and non-exact languages such as `bash dirac eats it`.

## How to run
- Install: `pip install -r requirements.txt`
- Configure: copy `config.example.toml` to `/home/codexy/Desktop/workspaces/dirac-config/config.toml` and fill in.
- Run: `python bot.py`
- Test: `pytest`
- Lint: project doesn't enforce a linter, but match existing style.

## What NOT to do
- Don't add dependencies. The list in requirements.txt is closed.
- Don't add a build step for the frontend.
- Don't bypass the permission filter for convenience.
- Don't log secrets (token, API key) anywhere — they must be masked in API responses and never written to bot_logs.
