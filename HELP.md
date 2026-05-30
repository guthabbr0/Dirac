# Dirac Human Command Help

This is the concise operator-facing command reference. `README.md` explains setup, `USAGE.md` walks through common workflows, and `docs/admin_help.md` is the longer admin capability map exposed through `!help docs admin`.

## Command Output

Discord command replies are sent in `` ```dirac `` code blocks and split safely before Discord's 2 000 character message limit. That fence marks deterministic code-origin output, not model prose. Long output is split on line or word boundaries where possible, so follow-up chunks continue cleanly.

## Canonical Verbs

Dirac keeps one advertised verb for each action:

- `show`: list items when no id/name is provided; show one item when an id/name is provided.
- `disable`: turn something off without deleting history or the row.
- `delete`: permanently remove a row where deletion is supported. Built-in tools are disabled rather than physically removed so they do not silently reappear as active on restart.
- `enable`: turn a disabled item back on.
- `add`: create a new item.
- `edit`: change an existing row in place when the surface supports it.
- `fix`: restore a bundled known-good snapshot while preserving disable state where supported.

Older aliases may be accepted for compatibility, but they are not the documented operator path.

## General Commands

```text
!help
!help all
!help config
!help docs
!help docs <name>
!kill
!stop [seconds]
!pause [seconds]
!resume
!version
!changelog
!status
```

`!help` is intentionally compact. Use `!help all` for the full admin overview and runtime snapshot.

`!kill`, `!stop`, `!pause`, and `!resume` are ultimate-only emergency controls for the protected super-admin user. They are parsed before any model call and cannot be granted through ordinary permissions.

## Prompts And Memory

```text
!prompt
!prompt <body> [*|@id]
!clear
!compact
!summary

!memory
!memory help
!memory add <discord_id|@user|#channel> <annotations> [tags=t1,t2] [confidence=0.8]
!memory update <#id|id> <annotations> [tags=t1,t2] [confidence=0.8]
!memory delete <#id|id>
!memory show
!memory show all
!memory show <#id|id>
!memory show <discord_id|@user|#channel>
```

`!memory show` defaults to the current Discord channel scope. `!memory show all` lists recent active memories. Mention and raw snowflake targets normalize to one `str_discord_id`. Memory rows are shown by `int_memory_id`; `!memory update` supersedes the old row, and `!memory delete` removes the current row plus the superseded chain.

For low-level repair outside Discord, use `python doctor.py paths`, `python doctor.py memory list --str-discord-id DISCORD_ID --limit 20`, `python doctor.py tools list`, and `python doctor.py sql "SELECT ..."`.

## Permissions

```text
!whitelist add <user_id> [root|admin|user] [*|@id]
!whitelist remove <user_id> [*|@id]
!whitelist block <user_id> [*|@id]
```

Unauthorized commands never reach the model.

## Tools And Skills

```text
!tool
!tool help
!tool add <name> <description> [*|@id]
!tool show [#id|name] [*|@id]
!tool edit <#id|name> description|body|schema|executor|enabled|globally_disabled <value> [*|@id]
!tool enable <#id|name> [*|@id]
!tool disable <#id|name> [*|@id]
!tool delete <#id|name> [*|@id]
!tool snapshot
!tool snapshot apply [version]
!tool fix

!skill
!skill help
!skill add <name> <description> [*|@id]
!skill show [#id|name] [*|@id]
!skill edit <#id|name> description|body|enabled <value> [*|@id]
!skill enable <#id|name> [*|@id]
!skill disable <#id|name> [*|@id]
!skill delete <#id|name> [*|@id]
```

Tool and skill lists are ordered by name and show only stable `#id` values, not row indexes. Use `#8` or `silencer`, never the visual row position. Disabled tools and skills are not shown in model context. Disabled tools are not exposed as callable Discord tools and tool directives for disabled tools are rejected. `!tool disable <name> *` disables a global tool everywhere until `!tool enable <name> *`. `!tool fix` restores built-in tool definitions from the DB snapshot while preserving disable state.

## Tasks

```text
!task
!task help
!task add <name> every <5m|2h|1d> <prompt> [*|@id]
!task show [id|name] [*|@id]
!task edit <id|name> name|prompt|schedule|enabled|model|provider_id|runtime_kind <value> [*|@id]
!task run <id|name> [*|@id]
!task enable <id|name> [*|@id]
!task disable <id|name> [*|@id]
!task delete <id|name> [*|@id]
!task fix
```

`disable` stops future runs and keeps history. `delete` removes the task row. `fix` restores the built-in task snapshot from `docs/builtin_tasks_snapshot.json`, including the editable `rem_dream` memory organizer.

Discord wake replies allow up to five tool follow-up turns. Scheduled/default tasks and REM tasks allow four tool follow-up turns before the text-only finalization path.

## Providers And Scopes

```text
!provider list
!provider show <name|id>
!provider test <name|id>
!provider enable <name|id>
!provider disable <name|id>

!scope show [*|@id]
!scope provider <provider> <model> [*|@id]
!scope params <profile> [*|@id]
!scope reset-provider [*|@id]
```

Provider secrets are never shown unredacted.

## News

```text
!news now
```

`!news now` is root-only. It summarizes AI/model/benchmark status from trusted known-source grounding plus exploratory public web search, stores candidate state in `news_items`, and skips recent repeats when fresh alternatives exist.
