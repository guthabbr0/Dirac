# Dirac WebUI Guidelines

This document is the grounding spec for Dirac's operator interface. The UI is a separate product surface with stable API contracts even while the launch path remains `bot.py`.

## Interface Principles

- The WebUI is the primary operating surface, not a raw JSON debug page.
- Selecting a tab must load the data needed for that tab automatically.
- Buttons named `Load` may exist as refresh actions, but a tab must not be empty until the operator clicks one.
- Global scope must never send `scope_id=` to APIs. Omit `scope_id` or send `null`.
- Backend APIs must also normalize `scope_id=""` for global scope because browsers and hand-written URLs often produce it.
- Side navigation must be readable, scrollable, and resizable on desktop.
- Layouts must not require the operator to resize the browser to discover hidden content.
- Every panel route must return bounded, useful errors and preserve auth checks.
- Secrets must never appear in panel JSON, Debug logs, WebSocket events, Roxanne context, or console output.
- Root permissions are protected. The Discord root operator ID is `1482143139828596916`.

## Page Loading Contract

Each tab owns a default data load:

- Dashboard: stats, providers, provider summary, tasks, task runs.
- Providers: provider list.
- Provider Calls: summary and recent calls.
- Bot Entries: entry list.
- Scopes: effective selected scope.
- Instructions: instruction list.
- Logs: recent bot logs.
- Debug: logging config and filtered bot logs.
- Channels: discovered scopes.
- Prompts: prompt list and selected prompt.
- Perms: permissions list.
- Memory: persisted memory list/editor, recent short-term memory events, and Discord identity tag list/editor.
- Tools: tool list for selected scope.
- Skills: skill list for selected scope.
- Tasks: task list/editor for selected filter plus built-in snapshot restore.
- Task Runs: task run list.
- Commands: command surface state.
- Config: redacted config.
- Roxanne: profile, provider parameters, sessions, selected thread messages, tools, and Roxanne-only static memory.

When adding a tab, update `loadTab()` in `PANEL_HTML` and add a panel API test that proves the tab marker and route are present.

## Scope Semantics

Canonical scope pairs:

- `global`: `scope_id` is `null` or omitted.
- `dm`, `group`, `guild`: `scope_id` is a non-empty string.
- Extended provider scopes may also include `channel` and `user`.

Frontend helpers must use a single scope serializer. Backend routes must normalize incoming empty strings with `normalize_scope_id()` before validating or writing rows.

## Permission Rules

- `root` is above `admin`, `user`, and `blocked`.
- `ROOT_OPERATOR_ID` and `panel` are root operators.
- Root operators cannot be blocked by the silencer tool or permission rows.
- Root permission rows cannot be deleted from the panel API.
- A permission reset must preserve root rows and remove untrusted scoped blocks.

## WebUI/API Edge Cases To Test

Every WebUI change should run tests for:

- Global scope with omitted `scope_id`.
- Global scope with `scope_id=`.
- Scoped route with missing `scope_id` returns a 400.
- Auth-required route returns 401 without the session cookie.
- Root permission cannot be deleted.
- Panel HTML contains the tab and auto-load method for new surfaces.
- Memory APIs expose authenticated routes for persisted memories, short-term events, and Discord identity tags.
- Task APIs expose authenticated edit and snapshot-restore routes.
- Roxanne quick-open action selects the Roxanne tab and loads the full threaded assistant workspace. Do not reintroduce a hidden modal for Roxanne.

## Future Extraction Direction

When the repo moves beyond the embedded panel, keep a modular boundary:

- `apps/api`: FastAPI routes and auth.
- `web`: frontend application.
- `src/dirac`: business logic, permissions, providers, tasks, memory.

During extraction, keep API contracts and UI behavior explicit in tests so the panel remains operable.
