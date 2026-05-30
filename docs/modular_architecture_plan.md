# Dirac Experimental Modular Architecture And Provider Control Revamp

## Summary

Revamp the earlier modular architecture plan to account for the new upstream state and the larger product direction:

- Keep the repo on the current `experimental` branch.
- Keep this plan current as modules land.
- Split `bot.py` into a modular design with separate API, Discord bot, worker, and frontend surfaces.
- Replace the single Ollama-only model path with a provider registry supporting Ollama Cloud, OpenRouter, and future OpenAI-compatible providers.
- Add a powerful WebUI with dedicated Providers, Scopes, Bot Entries, Capabilities, Tasks, Runs, Logs, and Roxanne assistant surfaces.
- Allow DM/channel/user/guild scoped behavior: provider/model/parameters, instructions, tools, skills, task behavior, and capability toggles.
- Preserve shared memory across providers and bot entries.
- Add full task provenance: who created a task, which scope triggered it, which provider/model/parameters executed it, when it ran, what it used, and what it produced.
- Add Roxanne as a visible threaded WebUI assistant connected to a configurable provider/model, with access to project docs, redacted runtime state, and UI guidance tools.

The guiding architecture is a **modular local application**, not microservices. We split code and process entrypoints, but keep one repository, one SQLite database, and predictable local operation.

## Important Current Repo State

Observed current branch:

```text
experimental
tracking origin/experimental
```

Observed latest commit:

```text
01def66 Apply review fixes for scoped tasks and silencer safety (#6)
```

Observed repo files:

```text
bot.py
README.md
USAGE.md
AGENTS.md
config.example.toml
requirements.txt
pytest.ini
docs/admin_help.md
tests/
```

Observed current architecture:

- `bot.py` is still the launch surface and should keep shrinking as modules land.
- It includes DB schema, migrations, commands, permissions, memory, context, Ollama client, tasks, news, Discord client, FastAPI routes, WebSocket, and embedded `PANEL_HTML`.
- Existing provider/model behavior is centered around `OllamaClient`.
- Existing scoped model overrides are stored in `model_overrides`.
- Existing reasoning overrides are stored in `reasoning_overrides`.
- Existing tools/skills/tasks are scoped.
- Existing task visibility and scoped task safety fixes are present upstream.
- Existing WebUI is embedded Alpine/HTML in `bot.py`.

## Execution Rule

This plan is already saved in `docs/modular_architecture_plan.md`. Implementation changes may update docs and runtime code together when an operational fix is urgent, but each change must keep tests green and preserve the invariants below.

## Non-Negotiable Invariants

These remain mandatory during the architecture migration:

1. Unauthorized Discord commands never reach the LLM.
2. Authorized commands are deterministic and excluded from assembled LLM context.
3. Blocked users are excluded from context.
4. Runtime DB writes go through the writer queue.
5. Secrets are never logged and never returned unredacted.
6. All timestamps are ISO-8601 UTC.
7. Panel/API auth remains required.
8. Shared memory remains provider-agnostic.
9. Tasks must record provider/model/parameters used at execution time.
10. Provider configuration must show visibility without exposing secret values.
11. Scoped overrides must be deterministic and inspectable.
12. Migration must be phased; do not attempt the whole rewrite in one change.

## Product Goals

### Provider Visibility

Add a first-class Providers area in the WebUI that shows:

- Provider name.
- Provider type.
- Base URL.
- Enabled/disabled state.
- Default model.
- Redacted API key fingerprint.
- Last successful test time.
- Last failure time and bounded error.
- Recent calls.
- Token usage when available.
- Latency.
- Error rate.
- Which scopes/bot entries currently use the provider.

Important: “which API key is being used” means show an operator-safe identity such as:

```text
key label: ollama-main
key fingerprint: sha256:ab12cd34...7890
secret display: ***abcd
```

Never show the full API key.

### Multiple Providers

Support at least these provider types:

```text
ollama
openrouter
openai_compatible
```

Ollama Cloud and OpenRouter must be configurable from WebUI.

Provider examples:

```text
Ollama Cloud:
  provider_type = ollama
  base_url = https://ollama.com
  auth_scheme = bearer
  chat_format = ollama_chat

OpenRouter:
  provider_type = openrouter
  base_url = https://openrouter.ai/api/v1
  auth_scheme = bearer
  chat_format = openai_chat_completions

Custom OpenAI-compatible:
  provider_type = openai_compatible
  base_url = operator supplied
  auth_scheme = bearer
  chat_format = openai_chat_completions
```

### Scoped Provider Assignment

Allow provider/model/parameter assignment by:

```text
global default
guild
channel
dm
user
bot entry
task
Roxanne
```

Effective behavior must be computed by deterministic precedence.

Recommended precedence, highest first:

```text
task explicit provider binding
message user override
channel override
dm override
guild override
bot entry default
global default
```

For Discord channel messages, scope resolution should consider:

```text
user_id
channel_id
guild_id
bot_entry_id
global
```

For DMs:

```text
user_id
dm scope_id
bot_entry_id
global
```

For panel/Roxanne:

```text
roxanne profile
operator panel default
global
```

### Provider Parameters

Provider parameters must support:

```text
temperature
top_p
top_k
max_tokens
presence_penalty
frequency_penalty
reasoning mode
reasoning effort
timeout seconds
tool use enabled
streaming enabled
response format
seed
custom provider options JSON
```

Not every provider supports every option. The system must:

- Store the full desired parameter set.
- Translate only supported fields per provider.
- Log which fields were sent.
- Log which fields were ignored because unsupported.
- Show unsupported fields in WebUI with warnings.

### Shared Instructions And Memory

System prompt and instructions remain shared unless scoped overrides exist.

Memory remains shared across providers:

- A channel memory is visible whether the channel uses Ollama or OpenRouter.
- A user memory is visible across DMs/channels/providers.
- A bot entry can include memory filters but must not create provider-specific memory silos by default.

### Tools And Skills Toggles

Tools and skills need scoped toggles:

```text
global enabled/disabled
guild enabled/disabled
channel enabled/disabled
dm enabled/disabled
user enabled/disabled
bot entry enabled/disabled
task enabled/disabled
```

Capability resolution must be explicit and visible.

For each tool/skill, WebUI must show:

```text
name
description
source: builtin/operator/generated
enabled globally
effective status in selected scope
why enabled or disabled
last used
used by which provider/model
failure count
```

### Task Visibility And Provenance

Tasks must show:

```text
task id
name
kind
status
enabled
schedule
scope
created by
created from source: discord/panel/scheduler/roxanne
assigned provider binding
effective provider at last run
effective model at last run
effective parameters at last run
effective instructions at last run
effective tools/skills at last run
next run
last run
run count
last result
last error
run history
```

Each run must be separate from the task definition.

Add task run history:

```text
agent_task_runs
```

A recurring task row describes intent and schedule. A task run row records what actually happened.

### Powerful WebUI

The WebUI should become the main operating surface, not a debugging afterthought.

Required tabs/pages:

```text
Dashboard
Providers
Provider Calls
Bot Entries
Scopes
Instructions
Memory
Tools
Skills
Tasks
Task Runs
Messages
Commands
Logs
Config
Roxanne
```

The WebUI must support:

- Filtering by guild/channel/DM/user.
- Viewing effective configuration for a scope.
- Editing provider/model/parameters for a scope.
- Toggling tools/skills per scope.
- Creating and editing tasks.
- Viewing task run history.
- Testing provider calls.
- Seeing token/latency/error stats.
- Asking Roxanne for help anywhere.

### Roxanne

Add Roxanne as a visible threaded WebUI assistant.

Roxanne is not the Discord bot. Roxanne is a panel-side assistant persona.

Roxanne requirements:

- Opens as a first-class panel tab from any WebUI page.
- Has a persistent conversation history.
- Uses a configurable provider/model/parameter profile.
- Has access to project documentation.
- Has access to redacted runtime state.
- Can answer “how do I use this UI?” questions.
- Can suggest configuration changes.
- Can draft changes but must not apply destructive changes without explicit operator action.
- Must never reveal secrets.
- Must cite which local docs/runtime state it used when possible.
- Can deep-link or point to relevant tabs.
- Can inspect current selected scope context.
- Can explain why a provider/model/tool/task is effective for a selected scope.

Roxanne default provider behavior:

```text
Use roxanne provider binding if configured.
Else use panel default provider binding.
Else use global default provider binding.
```

Roxanne default model should not be hardcoded to Ollama. It must be operator-configurable.

## Revised Target Repository Layout

```text
dirac/
  README.md
  USAGE.md
  AGENTS.md
  config.example.toml
  requirements.txt
  pytest.ini
  bot.py                         # launch surface during extraction
  docs/
    admin_help.md
    modular_architecture_plan.md
    architecture/
      providers.md
      scopes.md
      tasks.md
      roxanne.md
      frontend.md
      migrations.md

  src/
    dirac/
      __init__.py
      version.py
      constants.py
      timeutil.py
      models.py

      config.py
      secrets.py
      docs.py
      logging.py
      events.py

      db.py
      schema.py
      migrations.py

      providers/
        __init__.py
        base.py
        registry.py
        routing.py
        ollama.py
        openrouter.py
        openai_compatible.py
        parameters.py
        usage.py

      permissions.py
      prompts.py
      instructions.py
      memory.py
      context.py

      capabilities/
        __init__.py
        assets.py
        tools.py
        skills.py
        resolver.py

      tasks/
        __init__.py
        service.py
        scheduler.py
        runs.py
        formatting.py

      commands.py
      news.py
      roxanne.py
      discord_tools.py

  apps/
    api/
      __init__.py
      main.py
      deps.py
      routes/
        auth.py
        bootstrap.py
        dashboard.py
        providers.py
        provider_calls.py
        bot_entries.py
        scopes.py
        instructions.py
        prompts.py
        memory.py
        tools.py
        skills.py
        tasks.py
        task_runs.py
        messages.py
        commands.py
        logs.py
        config.py
        roxanne.py
        websocket.py

    bot/
      __init__.py
      main.py
      discord_client.py
      bot_core.py
      delivery.py

    worker/
      __init__.py
      main.py
      scheduler.py
      outbox.py

  web/
    package.json
    index.html
    src/
      main.tsx
      api/
      components/
      pages/
      modals/
        RoxanneModal.tsx
      state/
      styles/
```

## Data Model Plan

### Provider Tables

Add `service_providers`:

```sql
CREATE TABLE IF NOT EXISTS service_providers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    provider_type TEXT NOT NULL CHECK (provider_type IN ('ollama','openrouter','openai_compatible')),
    base_url TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    default_model TEXT NOT NULL,
    api_key TEXT,
    api_key_fingerprint TEXT,
    api_key_last4 TEXT,
    auth_scheme TEXT NOT NULL DEFAULT 'bearer',
    headers_json TEXT,
    supports_tools INTEGER NOT NULL DEFAULT 0,
    supports_reasoning INTEGER NOT NULL DEFAULT 0,
    supports_temperature INTEGER NOT NULL DEFAULT 1,
    supports_streaming INTEGER NOT NULL DEFAULT 0,
    timeout_s REAL NOT NULL DEFAULT 120.0,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    last_test_at TEXT,
    last_test_ok INTEGER,
    last_error TEXT
);
```

Initial secret handling:

- Store API keys in `config.toml` or encrypted DB field.
- For the first experimental implementation, use DB storage with local encryption deferred only if no secret library is available.
- Always store `api_key_fingerprint` and `api_key_last4`.
- Always redact the actual key in API responses.

No new crypto dependency in the first pass. If encryption is not implemented yet, document that local DB contains provider secrets and must remain ignored/private like `config.toml`.

Add `provider_models`:

```sql
CREATE TABLE IF NOT EXISTS provider_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id INTEGER NOT NULL REFERENCES service_providers(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    display_name TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    context_window_tokens INTEGER,
    supports_tools INTEGER,
    supports_reasoning INTEGER,
    supports_vision INTEGER,
    supports_json INTEGER,
    input_cost_per_million REAL,
    output_cost_per_million REAL,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    UNIQUE(provider_id, model)
);
```

Add `provider_parameters`:

```sql
CREATE TABLE IF NOT EXISTS provider_parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    params_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
```

### Bot Entry Tables

Add `bot_entries`:

```sql
CREATE TABLE IF NOT EXISTS bot_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    persona TEXT,
    default_scope_type TEXT NOT NULL DEFAULT 'global',
    default_scope_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
```

Default row:

```text
name = dirac
description = Primary Discord self-bot entry
enabled = 1
```

Add `bot_entry_bindings`:

```sql
CREATE TABLE IF NOT EXISTS bot_entry_bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_entry_id INTEGER NOT NULL REFERENCES bot_entries(id) ON DELETE CASCADE,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('global','guild','channel','dm','user')),
    scope_id TEXT,
    provider_id INTEGER REFERENCES service_providers(id),
    model TEXT,
    parameter_profile_id INTEGER REFERENCES provider_parameters(id),
    instructions_id INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    UNIQUE(bot_entry_id, scope_type, scope_id)
);
```

### Scope Configuration Tables

Add `scope_profiles`:

```sql
CREATE TABLE IF NOT EXISTS scope_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('global','guild','channel','dm','user')),
    scope_id TEXT,
    display_name TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    provider_id INTEGER REFERENCES service_providers(id),
    model TEXT,
    parameter_profile_id INTEGER REFERENCES provider_parameters(id),
    instructions_id INTEGER,
    memory_enabled INTEGER NOT NULL DEFAULT 1,
    tools_enabled INTEGER NOT NULL DEFAULT 1,
    skills_enabled INTEGER NOT NULL DEFAULT 1,
    tasks_enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    UNIQUE(scope_type, scope_id)
);
```

Add `instructions`:

```sql
CREATE TABLE IF NOT EXISTS instructions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('global','guild','channel','dm','user','bot_entry','task','roxanne')),
    scope_id TEXT,
    body TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    UNIQUE(scope_type, scope_id, name)
);
```

Existing `prompts` can be migrated into `instructions` or kept as compatibility. Recommended:

- Keep `prompts` for backward compatibility in early phases.
- Introduce `instructions`.
- Effective instruction assembly reads both, with `instructions` taking precedence.
- Later migrate `prompts` rows into `instructions`.

### Capability Toggle Tables

Add `capability_bindings`:

```sql
CREATE TABLE IF NOT EXISTS capability_bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL REFERENCES agent_assets(id) ON DELETE CASCADE,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('global','guild','channel','dm','user','bot_entry','task')),
    scope_id TEXT,
    enabled INTEGER NOT NULL,
    reason TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    UNIQUE(asset_id, scope_type, scope_id)
);
```

This separates the asset definition from per-scope enable/disable state.

Existing `agent_assets.enabled` remains the global/default enabled flag during migration.

### Task Run Provenance Tables

Keep `agent_tasks` but add columns:

```sql
ALTER TABLE agent_tasks ADD COLUMN bot_entry_id INTEGER;
ALTER TABLE agent_tasks ADD COLUMN provider_id INTEGER;
ALTER TABLE agent_tasks ADD COLUMN model TEXT;
ALTER TABLE agent_tasks ADD COLUMN parameter_profile_id INTEGER;
ALTER TABLE agent_tasks ADD COLUMN created_by_display TEXT;
ALTER TABLE agent_tasks ADD COLUMN target_scope_type TEXT;
ALTER TABLE agent_tasks ADD COLUMN target_scope_id TEXT;
```

Add `agent_task_runs`:

```sql
CREATE TABLE IF NOT EXISTS agent_task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES agent_tasks(id) ON DELETE CASCADE,
    run_status TEXT NOT NULL CHECK (run_status IN ('queued','running','completed','failed','cancelled')),
    trigger_source TEXT NOT NULL CHECK (trigger_source IN ('scheduler','discord','panel','roxanne','manual')),
    triggered_by TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    scope_id TEXT,
    provider_id INTEGER REFERENCES service_providers(id),
    provider_name TEXT,
    provider_type TEXT,
    model TEXT,
    params_json TEXT,
    instructions_preview TEXT,
    tools_json TEXT,
    skills_json TEXT,
    prompt TEXT NOT NULL,
    result TEXT,
    error TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    latency_ms INTEGER,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL
);
```

Add `outbound_messages`:

```sql
CREATE TABLE IF NOT EXISTS outbound_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL CHECK (source_type IN ('task','news','command','roxanne','manual')),
    source_id INTEGER,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('dm','group','guild','channel')),
    scope_id TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued','sent','failed')) DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    sent_at TEXT
);
```

### Provider Call Logging

Replace or extend `ollama_log`.

Recommended migration:

Keep `ollama_log` as compatibility, add `provider_calls`.

```sql
CREATE TABLE IF NOT EXISTS provider_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id INTEGER REFERENCES service_providers(id),
    provider_name TEXT NOT NULL,
    provider_type TEXT NOT NULL,
    model TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    scope_id TEXT,
    bot_entry_id INTEGER,
    task_id INTEGER,
    task_run_id INTEGER,
    source TEXT NOT NULL CHECK (source IN ('discord','panel','task','news','roxanne','test')),
    request_json TEXT NOT NULL,
    response_json TEXT,
    sent_params_json TEXT,
    ignored_params_json TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    latency_ms INTEGER,
    error TEXT,
    timestamp_utc TEXT NOT NULL
);
```

Compatibility:

- `OllamaClient` writes to `provider_calls`.
- During early migration, optionally mirror Ollama calls into `ollama_log` until UI/tests move.

### Roxanne Tables

Add `roxanne_profiles`:

```sql
CREATE TABLE IF NOT EXISTS roxanne_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    provider_id INTEGER REFERENCES service_providers(id),
    model TEXT,
    parameter_profile_id INTEGER REFERENCES provider_parameters(id),
    system_prompt TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
```

Default profile:

```text
name = default
system_prompt = You are Roxanne, Dirac's WebUI assistant. Help the operator understand and configure Dirac. Use docs and redacted runtime state. Never reveal secrets.
```

Add `roxanne_sessions`:

```sql
CREATE TABLE IF NOT EXISTS roxanne_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    active_scope_type TEXT,
    active_scope_id TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
```

Add `roxanne_messages`:

```sql
CREATE TABLE IF NOT EXISTS roxanne_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES roxanne_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('operator','assistant','system','tool')),
    content TEXT NOT NULL,
    tool_calls_json TEXT,
    provider_call_id INTEGER REFERENCES provider_calls(id),
    timestamp_utc TEXT NOT NULL
);
```

## Provider Routing Logic

Create `src/dirac/providers/routing.py`.

Core function:

```python
async def resolve_provider_binding(
    db,
    *,
    bot_entry_id: int | None,
    source: str,
    scope_type: str,
    scope_id: str | None,
    user_id: str | None = None,
    task_id: int | None = None,
    roxanne_profile_id: int | None = None,
) -> ProviderBinding:
    ...
```

Return model:

```python
class ProviderBinding(BaseModel):
    provider_id: int
    provider_name: str
    provider_type: str
    base_url: str
    api_key_secret_ref: str | None
    api_key_fingerprint: str | None
    model: str
    params: dict[str, Any]
    source_chain: list[str]
    warnings: list[str]
```

Resolution order for Discord channel:

```text
task explicit provider if task_id present
user scope profile
channel scope profile
guild scope profile
bot entry binding
global scope profile
first enabled provider fallback
```

Resolution order for DM:

```text
task explicit provider if task_id present
user scope profile
dm scope profile
bot entry binding
global scope profile
first enabled provider fallback
```

Resolution order for Roxanne:

```text
roxanne profile
panel/operator scope profile
global scope profile
first enabled provider fallback
```

If no provider is available:

- Do not call LLM.
- Return clear operator-visible error.
- Log `provider_resolution_failed`.
- For Discord wake, send bounded fallback: `No model provider is configured for this scope yet.`

## Provider Adapter Interfaces

Create `src/dirac/providers/base.py`.

```python
class ProviderAdapter(Protocol):
    provider_type: str

    async def chat(
        self,
        *,
        provider: ServiceProvider,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        params: dict[str, Any],
        scope_type: str,
        scope_id: str | None,
        source: str,
    ) -> ProviderResponse:
        ...

    async def test(self, provider: ServiceProvider, model: str | None = None) -> ProviderTestResult:
        ...
```

Provider response:

```python
class ProviderResponse(BaseModel):
    content: str
    raw: dict[str, Any]
    tool_calls: list[dict[str, Any]] = []
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int
    sent_params: dict[str, Any]
    ignored_params: dict[str, Any]
```

Adapters:

```text
OllamaAdapter:
  endpoint: /api/chat
  model field: model
  messages field: messages
  tools field: tools when supported
  reasoning maps to think

OpenRouterAdapter:
  endpoint: /chat/completions
  model field: model
  messages field: messages
  tools field: tools when supported
  extra headers:
    HTTP-Referer optional
    X-Title optional
  reasoning maps to provider-specific extra_body when supported, else ignored

OpenAICompatibleAdapter:
  endpoint: /chat/completions
  model field: model
  messages field: messages
```

The existing `OllamaClient.chat()` becomes either:

- A thin compatibility wrapper around `ProviderService.chat()`, or
- Removed after command/context tests migrate.

Recommended transitional class:

```python
class OllamaClient:
    async def chat(...):
        return await ProviderService(...).chat_with_legacy_ollama_default(...)
```

## Configuration Plan

### Current Config Compatibility

Current config:

```toml
[ollama]
endpoint = "https://ollama.com"
api_key = "..."
default_model = "llama3.2"
request_timeout_s = 120.0
```

Must still work.

Migration behavior:

- On startup, if `service_providers` has no rows, create one provider from `[ollama]`.
- Provider name: `ollama-default`.
- Provider type: `ollama`.
- Base URL: `ollama.endpoint`.
- Default model: `ollama.default_model`.
- API key: `ollama.api_key`.
- Timeout: `ollama.request_timeout_s`.

### New Config Format

Support optional config sections:

```toml
[providers.ollama_default]
name = "ollama-default"
type = "ollama"
base_url = "https://ollama.com"
api_key = "..."
default_model = "kimi-k2.6"
enabled = true
timeout_s = 120.0

[providers.openrouter_main]
name = "openrouter-main"
type = "openrouter"
base_url = "https://openrouter.ai/api/v1"
api_key = "..."
default_model = "anthropic/claude-sonnet-4.5"
enabled = true
timeout_s = 120.0

[provider_parameters.default_balanced]
temperature = 0.4
top_p = 0.9
max_tokens = 1600
reasoning = "medium"

[roxanne]
provider = "ollama-default"
model = "kimi-k2.6"
parameter_profile = "default_balanced"
```

WebUI can write providers to DB first. Config import/export can come later.

## API Plan

### Provider APIs

Add:

```text
GET    /api/providers
POST   /api/providers
GET    /api/providers/{provider_id}
PATCH  /api/providers/{provider_id}
DELETE /api/providers/{provider_id}
POST   /api/providers/{provider_id}/test
GET    /api/providers/{provider_id}/models
POST   /api/providers/{provider_id}/models
GET    /api/provider-calls
GET    /api/provider-calls/summary
```

Provider response redaction:

```json
{
  "id": 1,
  "name": "ollama-default",
  "provider_type": "ollama",
  "base_url": "https://ollama.com",
  "enabled": true,
  "default_model": "kimi-k2.6",
  "api_key_present": true,
  "api_key_last4": "abcd",
  "api_key_fingerprint": "sha256:12ab...",
  "last_test_ok": true
}
```

### Scope APIs

Add:

```text
GET   /api/scopes/effective?scope_type=channel&scope_id=...
PATCH /api/scopes/{scope_type}/{scope_id}
GET   /api/scopes/{scope_type}/{scope_id}/capabilities
PUT   /api/scopes/{scope_type}/{scope_id}/capabilities/{asset_id}
GET   /api/scopes/{scope_type}/{scope_id}/provider-resolution
```

Effective scope response:

```json
{
  "scope": {"scope_type": "channel", "scope_id": "1506027063512141896"},
  "provider": {
    "id": 1,
    "name": "ollama-default",
    "model": "kimi-k2.6",
    "resolved_from": "channel"
  },
  "parameters": {
    "temperature": 0.4,
    "reasoning": "medium"
  },
  "instructions": {
    "resolved_from": "channel",
    "preview": "..."
  },
  "tools": [],
  "skills": [],
  "memory_enabled": true
}
```

### Bot Entry APIs

Add:

```text
GET    /api/bot-entries
POST   /api/bot-entries
GET    /api/bot-entries/{id}
PATCH  /api/bot-entries/{id}
DELETE /api/bot-entries/{id}
GET    /api/bot-entries/{id}/bindings
PUT    /api/bot-entries/{id}/bindings
```

### Task Run APIs

Add:

```text
GET /api/task-runs
GET /api/task-runs/{run_id}
GET /api/tasks/{task_id}/runs
POST /api/tasks/{task_id}/run
```

Task run listing filters:

```text
task_id
status
provider_id
model
scope_type
scope_id
trigger_source
triggered_by
created_after
created_before
```

### Roxanne APIs

Add:

```text
GET    /api/roxanne/profile
PATCH  /api/roxanne/profile
GET    /api/roxanne/sessions
POST   /api/roxanne/sessions
GET    /api/roxanne/sessions/{session_id}/messages
POST   /api/roxanne/sessions/{session_id}/messages
POST   /api/roxanne/ask
GET    /api/roxanne/tools
```

Roxanne tools:

```text
read_docs
search_docs
get_current_page_help
get_redacted_config
get_providers
get_provider_calls_summary
get_effective_scope
get_tasks
get_task_runs
get_recent_logs
draft_provider_config
draft_scope_change
```

Roxanne tools must be read-only except draft tools. Draft tools return proposed JSON patches, not applied changes.

## WebUI Plan

### Dashboard

Purpose:

- Show service health.
- Show current active providers.
- Show Discord status.
- Show worker status.
- Show task queue health.
- Show recent provider errors.
- Show recent task failures.

Widgets:

```text
API online
Discord connected
Worker heartbeat
Configured providers count
Enabled providers count
Provider error rate
Calls last hour
Tokens last hour
Tasks due
Tasks failed
Outbox queued/failed
```

### Providers Tab

Sections:

1. Provider list.
2. Provider editor.
3. Model list.
4. Parameter profiles.
5. Test panel.
6. Usage summary.
7. Scope usage map.

Actions:

```text
Add provider
Disable provider
Edit provider
Rotate API key
Test provider
Add model
Disable model
Create parameter profile
Assign as global default
View recent calls
```

### Provider Calls Tab

Columns:

```text
time
source
scope
provider
model
latency
prompt tokens
completion tokens
error
task run id
```

Filters:

```text
provider
model
source
scope
errors only
time range
```

### Bot Entries Tab

Purpose:

Manage personas/entrypoints.

Default row:

```text
Dirac
```

Fields:

```text
name
description
enabled
persona
default provider
default model
default parameters
default instructions
```

### Scopes Tab

Purpose:

Powerful DM/channel/user/guild control.

Scope selector:

```text
global
guild
channel
dm
user
```

Scope panel shows:

```text
enabled
provider
model
parameters
instructions
tools
skills
memory
tasks
effective resolution chain
```

Actions:

```text
Set provider/model
Set parameter profile
Edit instructions
Toggle memory
Toggle tools
Toggle skills
Toggle tasks
Reset override
Copy from another scope
Preview effective context
```

### Instructions Tab

Purpose:

Replace scattered prompt editing with structured instructions.

Fields:

```text
name
scope
body
updated by
updated at
```

Features:

```text
diff history
preview effective instructions
restore previous version
```

### Memory Tab

Keep current memory features, add:

```text
scope-aware filters
provider call references
Roxanne explanation
memory usage preview for selected scope
```

### Tools Tab

Keep existing tool management, add:

```text
effective toggles per scope
last-used metadata
provider compatibility warnings
tool schema preview
```

### Skills Tab

Keep existing skill management, add:

```text
effective toggles per scope
last-used metadata
scope availability matrix
```

### Tasks Tab

Upgrade from current list/editor.

Sections:

```text
Task list
Task editor
Schedule editor
Provider assignment
Scope assignment
Capability toggles
Run now button
Run history drawer
```

Fields:

```text
name
prompt
scope
schedule
enabled
max runs
provider override
model override
parameter profile
tools allowed
skills allowed
instructions override
```

### Task Runs Tab

Purpose:

Detailed execution audit.

Columns:

```text
run id
task
status
trigger source
triggered by
scope
provider
model
started
completed
latency
tokens
error
```

Run detail drawer:

```text
prompt
effective instructions
params
tools
skills
provider request
provider response
result
outbound message status
```

### Roxanne Modal

Global button:

```text
Ask Roxanne
```

Available everywhere.

Modal layout:

```text
left: conversation
right: context card
bottom: suggested actions
```

Context card shows:

```text
current page
selected scope
selected provider
active docs source
Roxanne provider/model
```

Roxanne can answer:

```text
How do I assign this channel to OpenRouter?
Why did this task use Ollama?
Which provider is Dirac using here?
How do I disable the silencer in this DM?
What failed in the last task run?
What does reasoning medium do for this provider?
Show me docs for tasks.
Suggest a safer config for this channel.
```

Roxanne cannot:

```text
Reveal full API keys
Bypass auth
Run shell commands
Delete tasks/providers without explicit UI confirmation
Silently mutate config
```

## Migration Phases

### Phase 0: Save The Plan

Files:

```text
docs/modular_architecture_plan.md
```

Actions:

1. Save this plan exactly.
2. Commit docs only.
3. Push to upstream for review.

Acceptance:

```bash
git status --short
```

Only the plan file is staged/committed.

### Phase 1: Provider Data Model And Compatibility Seeding

Goal:

Add provider tables while preserving existing Ollama config behavior.

Changes:

- Add `service_providers`.
- Add `provider_models`.
- Add `provider_parameters`.
- Add `provider_calls`.
- Add startup seeding from `[ollama]` if no provider exists.
- Keep existing `ollama_log`.
- Keep existing `OllamaClient`.

Tests:

- Fresh DB has provider tables.
- Existing config creates `ollama-default`.
- Provider API key is fingerprinted/redacted.
- No full secret appears in API output or logs.

Acceptance:

```bash
.venv/bin/pytest tests/test_db.py tests/test_panel_api.py
```

### Phase 2: Provider Service Abstraction

Goal:

Route all LLM calls through provider abstraction.

Changes:

- Add `ProviderService`.
- Add `OllamaAdapter`.
- Add `OpenRouterAdapter`.
- Add `OpenAICompatibleAdapter`.
- Make existing `OllamaClient.chat()` call `ProviderService` internally.
- Log to `provider_calls`.

Tests:

- Existing Ollama tests still pass.
- OpenRouter request body is correctly shaped.
- Unsupported params are logged as ignored.
- Reasoning maps correctly for Ollama `think`.
- Provider failures produce bounded user-visible error.

Acceptance:

```bash
.venv/bin/pytest tests/test_permissions.py tests/test_commands.py
```

### Phase 3: Scoped Provider Routing

Goal:

Allow provider/model/params by global/guild/channel/DM/user/bot entry.

Changes:

- Add `scope_profiles`.
- Add `bot_entries`.
- Add `bot_entry_bindings`.
- Add provider resolution service.
- Keep `model_overrides` and `reasoning_overrides` as compatibility input.
- New effective config API.

Tests:

- Channel override wins over guild/global.
- User override wins over channel.
- Task explicit provider wins over scope.
- No provider gives safe failure.
- Existing `!model` and `!reasoning` commands still work.

Acceptance:

```bash
.venv/bin/pytest tests/test_context.py tests/test_permissions.py tests/test_commands.py
```

### Phase 4: Capability Resolver

Goal:

Make tools/skills toggles powerful and visible.

Changes:

- Add `capability_bindings`.
- Add effective capability resolver.
- Existing `agent_assets.enabled` remains global default.
- Add API for toggles.
- Add WebUI-ready effective capability payloads.

Tests:

- Global enabled tool can be disabled in a channel.
- Channel disabled tool does not reach model tools.
- User override can disable tool for abusive user.
- Built-in tools remain protected from unsafe model-supplied args.

Acceptance:

```bash
.venv/bin/pytest tests/test_permissions.py tests/test_context.py
```

### Phase 5: Task Run History And Provider-Aware Tasks

Goal:

Make tasks auditable and provider-aware.

Changes:

- Add `agent_task_runs`.
- Add task provider/model/parameter fields.
- `run_agent_task` creates a task run row.
- Effective provider/model/params are snapshotted per run.
- Task result references provider call.
- Task list shows last effective provider/model.
- Add task run API.

Tests:

- Running a task creates `agent_task_runs`.
- Task run records provider/model/params.
- Failed provider call records failed run.
- Scoped task uses channel provider if task has no explicit provider.
- Task explicit provider overrides channel.

Acceptance:

```bash
.venv/bin/pytest tests/test_commands.py tests/test_panel_api.py
```

### Phase 6: Outbox And Worker Split

Goal:

Separate scheduled work from Discord delivery.

Changes:

- Add `outbound_messages`.
- Worker runs due tasks and writes outbound rows.
- Discord bot process sends queued outbound messages.
- Existing combined mode can still run both loops during transition.

Tests:

- Worker task writes outbound message.
- Discord delivery marks outbound sent.
- Missing channel marks failed.
- Worker failure does not crash scheduler.

Acceptance:

```bash
.venv/bin/pytest tests/test_db.py tests/test_commands.py
```

### Phase 7: Modular Python Package Extraction

Goal:

Move code out of `bot.py` while preserving behavior.

Create:

```text
src/dirac/
apps/api/
apps/bot/
apps/worker/
```

Extract in this order:

1. Constants/time/version.
2. Config/docs/logging.
3. DB/schema/migrations.
4. Providers.
5. Permissions/memory/context.
6. Capabilities.
7. Tasks.
8. Commands.
9. Discord client.
10. FastAPI app.
11. Worker.

Keep `bot.py` as the launch surface while moving behavior into modules.

Tests:

- Existing tests pass after each extraction.
- Import tests cover new modules.

Acceptance:

```bash
.venv/bin/pytest
```

### Phase 8: Provider And Scope WebUI In Current Embedded Panel

Goal:

Expose new provider/scope power before full frontend extraction.

Because frontend extraction is large, first add minimal embedded panel tabs:

```text
Providers
Scopes
Task Runs
Roxanne
```

This is temporary but gives immediate operator value.

Tests:

- `/` contains Providers, Scopes, Task Runs, Roxanne.
- Provider CRUD routes are auth-protected.
- Scope effective route works.
- Roxanne routes are auth-protected.

Acceptance:

```bash
.venv/bin/pytest tests/test_panel_api.py
```

### Phase 9: Roxanne Backend

Goal:

Add Roxanne assistant service and API.

Changes:

- Add Roxanne tables.
- Add Roxanne profile.
- Add docs tools.
- Add redacted runtime-state tools.
- Add provider-bound Roxanne chat.
- Store sessions/messages.
- Roxanne can draft but not apply config changes.

Tests:

- Roxanne uses configured provider.
- Roxanne can read docs.
- Roxanne redacts secrets.
- Roxanne records provider call.
- Roxanne draft action does not mutate config.

Acceptance:

```bash
.venv/bin/pytest tests/test_panel_api.py
```

### Phase 10: Real Frontend

Goal:

Replace embedded panel with powerful WebUI.

Stack:

```text
Vite + React + TypeScript
```

Create:

```text
web/
```

Pages:

```text
Dashboard
Providers
Provider Calls
Bot Entries
Scopes
Instructions
Memory
Tools
Skills
Tasks
Task Runs
Messages
Commands
Logs
Config
```

Modal:

```text
RoxanneModal
```

FastAPI serves `web/dist` when built. Embedded panel remains fallback until parity.

Tests:

- API contract tests remain backend authority.
- Optional frontend tests can be added once Node tooling is accepted.

Acceptance:

- Manual WebUI smoke test passes.
- Providers can be added/tested.
- Channel can be assigned to OpenRouter.
- Another channel can remain on Ollama.
- Roxanne answers UI usage questions.
- Task run page shows provider/model/provenance.

### Phase 11: Docs Update And Legacy Cleanup

Update:

```text
README.md
USAGE.md
AGENTS.md
docs/admin_help.md
docs/architecture/providers.md
docs/architecture/scopes.md
docs/architecture/tasks.md
docs/architecture/roxanne.md
```

Key docs changes:

- Remove “single Python script” as future instruction.
- Document provider setup.
- Document OpenRouter setup.
- Document scoped provider assignment.
- Document Roxanne.
- Document task run provenance.
- Document local multi-process development.

Acceptance:

- Docs no longer contradict modular architecture.
- AGENTS.md maps module ownership.
- USAGE.md includes provider setup and WebUI walkthrough.

## Commands To Add Or Update

### Provider Commands

Add root-only commands for parity with WebUI:

```text
!providers list
!providers show <name|id>
!providers test <name|id>
!providers enable <name|id>
!providers disable <name|id>
```

Do not add provider secret creation through Discord in the first pass. API keys should be entered through local WebUI/config only.

### Scope Commands

Add root-only inspection commands:

```text
!scope show [*|@id]
!scope provider <provider_name> <model> [*|@id]
!scope params <profile_name> [*|@id]
!scope reset-provider [*|@id]
```

### Task Commands

Extend:

```text
!tasks show <id|name>
```

Must include:

```text
provider
model
last run provider
last run model
last run status
last run id
```

Add:

```text
!tasks runs <id|name>
```

### Roxanne Commands

No Discord command required initially.

Roxanne is WebUI-first.

## Testing Matrix

### Provider Tests

- Ollama request body includes `think` for reasoning.
- OpenRouter request body uses `/chat/completions` format.
- OpenAI-compatible request body uses generic chat completions.
- Temperature/top_p/max_tokens map correctly.
- Unsupported params are ignored and logged.
- API key is never returned.
- Key fingerprint remains stable for same key.

### Routing Tests

- Global provider fallback works.
- Guild override works.
- Channel override beats guild.
- User override beats channel.
- Task override beats all.
- Roxanne profile beats panel/global.
- Disabled provider is skipped or errors clearly.
- Missing model errors clearly.

### Capability Tests

- Global tool enabled appears in scope.
- Scoped disable hides global tool.
- Scoped enable restores local tool.
- User disable overrides channel enable.
- Tool use disabled for provider without tool support.

### Task Tests

- Task run records provider/model/params.
- Task run records triggered_by/source.
- Recurring task run advances schedule.
- Manual run records panel/manual trigger.
- Failed provider call records failed run.
- Run history API filters by provider/model/status.

### Roxanne Tests

- Roxanne reads docs.
- Roxanne sees redacted providers.
- Roxanne can explain effective scope config.
- Roxanne stores conversation.
- Roxanne does not mutate config through draft tools.
- Roxanne never exposes full secrets.

### WebUI API Tests

- Provider CRUD auth.
- Scope effective auth.
- Task run API auth.
- Roxanne API auth.
- 401 behavior unchanged.
- Redaction behavior unchanged.

## Acceptance Criteria For The Full Experiment

The experiment is successful when:

1. Operator can configure Ollama Cloud and OpenRouter in WebUI.
2. Operator can see which redacted key/fingerprint is used by each provider.
3. Operator can assign one channel to Ollama and another to OpenRouter.
4. Operator can configure model/temperature/reasoning per scope.
5. Memory remains shared across providers.
6. Tools/skills can be toggled by scope.
7. Tasks record run history with provider/model/params/provenance.
8. Task assigned to a channel uses that channel’s effective provider unless task overrides it.
9. Roxanne can answer how to use the WebUI using local docs and redacted runtime state.
10. Unauthorized commands still never reach the model.
11. Existing tests pass.
12. New provider/scope/task/Roxanne tests pass.
13. Docs explain the new architecture clearly.

## Explicit Assumptions And Defaults

- Current branch `experimental` is the correct branch.
- Plan file path is `docs/modular_architecture_plan.md`.
- Provider keys are redacted everywhere.
- API key identity is shown by label, fingerprint, and last four characters only.
- Ollama Cloud remains supported through compatibility config.
- OpenRouter is first non-Ollama provider.
- OpenAI-compatible is the generic future provider path.
- Memory is shared by default.
- Provider assignment precedence is task, user, channel/DM, guild, bot entry, global.
- Roxanne is WebUI-only at first.
- Roxanne can draft changes but cannot apply destructive changes silently.
- Frontend target is Vite + React + TypeScript.
- SQLite remains the database.
- No Redis/Celery/Postgres in the first experimental provider revamp.
- `bot.py` remains the launch surface during migration.
- Operationally urgent fixes may pair docs and runtime code in one change when tests cover the behavior.
