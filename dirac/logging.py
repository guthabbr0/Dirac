from __future__ import annotations

import asyncio
import json
import os
import select
import sys
import threading
import termios
import tty
from typing import Any, Callable


LOG_LEVELS = ('trace', 'debug', 'info', 'warn', 'error')
LOG_LEVEL_ORDER = {name: i for i, name in enumerate(LOG_LEVELS)}
DEFAULT_LOG_COMPONENTS = ('bot', 'provider', 'discord', 'discord_tool', 'ollama', 'panel', 'agent_tasks', 'news', 'roxanne', 'rem', 'db')
CONSOLE_DETAIL_LIMIT = 20000
CONSOLE_TRACE_DETAIL_LIMIT = 500000
CONSOLE_DETAIL_VALUE_LIMIT = 100


CONSOLE_JSON_VIEW_DEFAULTS = {
    'fold_json': False,
    'show_system': True,
    'show_user': True,
    'show_tool': True,
    'show_assistant': True,
    'show_tools': True,
    'show_tool_calls': True,
}
CONSOLE_JSON_VIEW_KEY_FLAGS = {
    'f': 'fold_json',
    's': 'show_system',
    'u': 'show_user',
    't': 'show_tool',
    'a': 'show_assistant',
    'T': 'show_tools',
    'c': 'show_tool_calls',
}
CONSOLE_JSON_VIEW_KEY_LABELS = {
    'f': 'JSON folding',
    's': 'system message content',
    'u': 'user message content',
    't': 'tool message content',
    'a': 'assistant message content',
    'T': 'tools array',
    'c': 'tool_calls array',
}
CONSOLE_JSON_VIEW_ROLE_FLAGS = {
    'system': 'show_system',
    'user': 'show_user',
    'tool': 'show_tool',
    'assistant': 'show_assistant',
}
_CONSOLE_JSON_VIEW = dict(CONSOLE_JSON_VIEW_DEFAULTS)
_CONSOLE_JSON_VIEW_LOCK = threading.Lock()


class _ConsoleRawJson:
    __slots__ = ('text',)

    def __init__(self, text):
        self.text = str(text)


def default_logging_config():
    return {'console_level': 'info', 'component_levels': {}, 'provider_http_debug': False}


def normalize_log_level(level, default='info'):
    value = str(level or default).lower()
    return value if value in LOG_LEVEL_ORDER else default


def parse_component_log_override(value):
    text = str(value or '')
    if '=' not in text:
        return None
    component, level = text.split('=', 1)
    component = component.strip()
    level = normalize_log_level(level.strip(), None)
    if not component or level is None:
        return None
    return component, level


def normalize_logging_config(data=None):
    incoming = dict(data or {})
    cfg = default_logging_config()
    cfg['console_level'] = normalize_log_level(incoming.get('console_level'), cfg['console_level'])
    raw_components = incoming.get('component_levels') or {}
    if isinstance(raw_components, str):
        parsed = {}
        try:
            maybe = json.loads(raw_components)
            if isinstance(maybe, dict):
                parsed = maybe
        except Exception:
            for part in raw_components.split(','):
                item = parse_component_log_override(part)
                if item:
                    parsed[item[0]] = item[1]
        raw_components = parsed
    if not isinstance(raw_components, dict):
        raw_components = {}
    cfg['component_levels'] = {str(k): normalize_log_level(v, cfg['console_level']) for k, v in raw_components.items() if str(k)}
    cfg['provider_http_debug'] = bool(incoming.get('provider_http_debug', False))
    return cfg


def log_threshold_for(component, config):
    cfg = normalize_logging_config(config)
    return normalize_log_level(cfg.get('component_levels', {}).get(str(component), cfg.get('console_level', 'info')))


def log_is_enabled(level, component, config):
    return LOG_LEVEL_ORDER[normalize_log_level(level)] >= LOG_LEVEL_ORDER[log_threshold_for(component, config)]


def summarize_log_value(value, max_string=CONSOLE_DETAIL_VALUE_LIMIT, max_items=20, max_depth=4):
    if max_depth <= 0:
        return '...'
    if isinstance(value, str):
        return value if len(value) <= max_string else value[:max_string] + f'... [trimmed {len(value) - max_string} chars]'
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        out = {}
        for idx, (key, item) in enumerate(value.items()):
            if idx >= max_items:
                out['...'] = f'trimmed {len(value) - max_items} keys'
                break
            out[str(key)] = summarize_log_value(item, max_string, max_items, max_depth - 1)
        return out
    if isinstance(value, (list, tuple, set)):
        seq = list(value)
        out = [summarize_log_value(item, max_string, max_items, max_depth - 1) for item in seq[:max_items]]
        if len(seq) > max_items:
            out.append(f'... trimmed {len(seq) - max_items} items')
        return out
    return summarize_log_value(str(value), max_string, max_items, max_depth - 1)


def console_json_view_state():
    with _CONSOLE_JSON_VIEW_LOCK:
        return dict(_CONSOLE_JSON_VIEW)


def console_json_view_hint():
    return '+ increases verbosity, - reduces verbosity, f folds JSON, s/u/t/a toggle system/user/tool/assistant content, T toggles tools, c toggles tool_calls'


def console_json_view_status(snapshot=None):
    state = dict(CONSOLE_JSON_VIEW_DEFAULTS)
    state.update(snapshot or console_json_view_state())
    return (
        f"json={'folded' if state.get('fold_json') else 'pretty'}, "
        f"system={'shown' if state.get('show_system') else 'redacted'}, "
        f"user={'shown' if state.get('show_user') else 'redacted'}, "
        f"tool={'shown' if state.get('show_tool') else 'redacted'}, "
        f"assistant={'shown' if state.get('show_assistant') else 'redacted'}, "
        f"tools={'shown' if state.get('show_tools') else 'redacted'}, "
        f"tool_calls={'shown' if state.get('show_tool_calls') else 'redacted'}"
    )


def toggle_console_json_view(key):
    flag = CONSOLE_JSON_VIEW_KEY_FLAGS.get(key)
    if flag is None:
        return None
    with _CONSOLE_JSON_VIEW_LOCK:
        _CONSOLE_JSON_VIEW[flag] = not bool(_CONSOLE_JSON_VIEW.get(flag, CONSOLE_JSON_VIEW_DEFAULTS.get(flag, True)))
        return dict(_CONSOLE_JSON_VIEW)


def console_json_view_status_line(key, snapshot=None):
    label = CONSOLE_JSON_VIEW_KEY_LABELS.get(key, key)
    return f"[console json] {label} toggled: {console_json_view_status(snapshot)}"


def _json_scalar_text(value, ensure_ascii=False, default=str):
    try:
        return json.dumps(value, ensure_ascii=ensure_ascii, default=default)
    except Exception:
        try:
            replacement = default(value) if callable(default) else str(value)
        except Exception:
            replacement = str(value)
        try:
            return json.dumps(replacement, ensure_ascii=ensure_ascii, default=str)
        except Exception:
            return json.dumps(str(replacement), ensure_ascii=ensure_ascii)


def _json_key_text(key, ensure_ascii=False):
    try:
        return json.dumps(str(key), ensure_ascii=ensure_ascii)
    except Exception:
        return json.dumps(str(key), ensure_ascii=False)


def _compact_jsonish(value, ensure_ascii=False, default=str):
    if isinstance(value, _ConsoleRawJson):
        return value.text
    if isinstance(value, dict):
        return '{' + ','.join(f'{_json_key_text(key, ensure_ascii)}:{_compact_jsonish(item, ensure_ascii, default)}' for key, item in value.items()) + '}'
    if isinstance(value, (list, tuple, set)):
        return '[' + ','.join(_compact_jsonish(item, ensure_ascii, default) for item in value) + ']'
    return _json_scalar_text(value, ensure_ascii, default)


def _pretty_jsonish(value, ensure_ascii=False, default=str, indent=2, level=0):
    if isinstance(value, _ConsoleRawJson):
        return value.text
    try:
        indent_size = int(indent)
    except Exception:
        indent_size = 2
    if indent_size <= 0:
        return _compact_jsonish(value, ensure_ascii, default)
    pad = ' ' * (indent_size * level)
    child_pad = ' ' * (indent_size * (level + 1))
    if isinstance(value, dict):
        if not value:
            return '{}'
        lines = ['{']
        items = list(value.items())
        for idx, (key, item) in enumerate(items):
            rendered = _pretty_jsonish(item, ensure_ascii, default, indent_size, level + 1)
            suffix = ',' if idx < len(items) - 1 else ''
            lines.append(f'{child_pad}{_json_key_text(key, ensure_ascii)}: {rendered}{suffix}')
        lines.append(f'{pad}' + '}')
        return '\n'.join(lines)
    if isinstance(value, (list, tuple, set)):
        seq = list(value)
        if not seq:
            return '[]'
        lines = ['[']
        for idx, item in enumerate(seq):
            rendered = _pretty_jsonish(item, ensure_ascii, default, indent_size, level + 1)
            suffix = ',' if idx < len(seq) - 1 else ''
            lines.append(f'{child_pad}{rendered}{suffix}')
        lines.append(f'{pad}]')
        return '\n'.join(lines)
    return _json_scalar_text(value, ensure_ascii, default)


def _redact_console_json_value(value, flags, ensure_ascii=False, default=str):
    if isinstance(value, dict):
        role = str(value.get('role', '')).lower() if 'role' in value else ''
        role_flag = CONSOLE_JSON_VIEW_ROLE_FLAGS.get(role)
        if role_flag and not flags.get(role_flag, True):
            redacted = {}
            has_content = False
            for key, item in value.items():
                key_text = str(key)
                if key_text == 'content':
                    redacted[key] = '...'
                    has_content = True
                else:
                    redacted[key] = _redact_console_json_value(item, flags, ensure_ascii, default)
            if not has_content:
                redacted['content'] = '...'
            return _ConsoleRawJson(_compact_jsonish(redacted, ensure_ascii, default))

        out = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text == 'tools' and isinstance(item, (list, tuple)):
                out[key] = _redact_console_json_value(item, flags, ensure_ascii, default) if flags.get('show_tools', True) else _ConsoleRawJson('[...]')
            elif key_text == 'tool_calls' and isinstance(item, (list, tuple)):
                out[key] = _redact_console_json_value(item, flags, ensure_ascii, default) if flags.get('show_tool_calls', True) else _ConsoleRawJson('[...]')
            else:
                out[key] = _redact_console_json_value(item, flags, ensure_ascii, default)
        return out

    if isinstance(value, (list, tuple)):
        return [_redact_console_json_value(item, flags, ensure_ascii, default) for item in value]

    if isinstance(value, set):
        return [_redact_console_json_value(item, flags, ensure_ascii, default) for item in value]

    return value


def wonderful_magic_prettifier(value, ensure_ascii=False, default=str, indent=2):
    try:
        flags = console_json_view_state()
        prepared = _redact_console_json_value(value, flags, ensure_ascii, default)
        if flags.get('fold_json', False):
            return _compact_jsonish(prepared, ensure_ascii, default)
        return _pretty_jsonish(prepared, ensure_ascii, default, indent)
    except Exception:
        try:
            return json.dumps(value, ensure_ascii=ensure_ascii, default=default, indent=indent)
        except Exception:
            return str(value)


def console_detail_text(component, level, detail, config):
    if detail is None:
        return ''
    threshold = log_threshold_for(component, config)
    row_level = normalize_log_level(level)
    if threshold == 'trace':
        value = detail
        limit = CONSOLE_TRACE_DETAIL_LIMIT
    elif row_level in {'trace', 'debug'}:
        value = summarize_log_value(detail)
        limit = CONSOLE_DETAIL_LIMIT
    else:
        return ''
    try:
        text = wonderful_magic_prettifier(value, ensure_ascii=False, default=str, indent=2)
    except Exception:
        text = str(value)
    if limit and len(text) > limit:
        text = text[:limit] + f'\n[console detail trimmed {len(text) - limit} chars]'
    return '\n' + text


def console_log_line(level, component, message, detail=None, scope_type=None, scope_id=None, *, config=None, local_timezone_name='Europe/Madrid', madrid_now=None):
    scope = f' scope={scope_type}:{scope_id}' if scope_type or scope_id else ''
    level = normalize_log_level(level)
    now = madrid_now() if callable(madrid_now) else ''
    prefix = f'[{now} {local_timezone_name}] {level.upper()} {component}{scope} {message}'
    detail_text = console_detail_text(component, level, detail, config or default_logging_config())
    line = prefix + detail_text
    colors = {'trace': '\033[90m', 'debug': '\033[36m', 'info': '\033[32m', 'warn': '\033[33m', 'error': '\033[31m'}
    if getattr(sys.stdout, 'isatty', lambda: False)() and not os.environ.get('NO_COLOR') and os.environ.get('TERM', '') != 'dumb':
        line = colors.get(level, '') + line + '\033[0m'
    print(line, flush=True)


def apply_cli_logging_overrides(cfg, argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    logging_cfg = normalize_logging_config(cfg.logging)
    changed = False
    i = 0
    while i < len(args):
        arg = args[i]
        value = None
        if arg in {'--log-level', '--console-log-level'} and i + 1 < len(args):
            value = args[i + 1]
            i += 1
        elif arg.startswith('--log-level='):
            value = arg.split('=', 1)[1]
        elif arg.startswith('--console-log-level='):
            value = arg.split('=', 1)[1]
        if value is not None:
            logging_cfg['console_level'] = normalize_log_level(value, logging_cfg['console_level'])
            changed = True
            i += 1
            continue
        comp_value = None
        if arg in {'--component-log', '--log-component'} and i + 1 < len(args):
            comp_value = args[i + 1]
            i += 1
        elif arg.startswith('--component-log='):
            comp_value = arg.split('=', 1)[1]
        elif arg.startswith('--log-component='):
            comp_value = arg.split('=', 1)[1]
        if comp_value is not None:
            parsed = parse_component_log_override(comp_value)
            if parsed:
                component, comp_level = parsed
                logging_cfg.setdefault('component_levels', {})[component] = comp_level
                changed = True
            i += 1
            continue
        if arg == '--provider-http-debug':
            logging_cfg['provider_http_debug'] = True
            changed = True
        elif arg == '--no-provider-http-debug':
            logging_cfg['provider_http_debug'] = False
            changed = True
        i += 1
    if changed:
        cfg.logging = normalize_logging_config(logging_cfg)
    return changed


def start_console_key_listener(loop, decrease_callback: Callable[[], Any], increase_callback: Callable[[], Any], error_callback: Callable[[Exception], Any] | None = None, json_view_callback: Callable[[str, dict[str, bool], str], Any] | None = None):
    if not getattr(sys.stdin, 'isatty', lambda: False)():
        return None
    stop = threading.Event()

    def worker():
        fd = sys.stdin.fileno()
        old_settings = None
        try:
            old_settings = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            while not stop.is_set():
                readable, _, _ = select.select([sys.stdin], [], [], 0.25)
                if not readable:
                    continue
                ch = sys.stdin.read(1)
                if ch == '+':
                    asyncio.run_coroutine_threadsafe(decrease_callback(), loop)
                elif ch == '-':
                    asyncio.run_coroutine_threadsafe(increase_callback(), loop)
                elif ch in CONSOLE_JSON_VIEW_KEY_FLAGS:
                    snapshot = toggle_console_json_view(ch)
                    if snapshot is None:
                        continue
                    status_line = console_json_view_status_line(ch, snapshot)
                    if json_view_callback is not None:
                        try:
                            asyncio.run_coroutine_threadsafe(json_view_callback(ch, snapshot, status_line), loop)
                        except Exception:
                            print(status_line, flush=True)
                    else:
                        print(status_line, flush=True)
        except Exception as e:
            if error_callback is not None:
                try:
                    asyncio.run_coroutine_threadsafe(error_callback(e), loop)
                except Exception:
                    pass
        finally:
            if old_settings is not None:
                try:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                except Exception:
                    pass

    thread = threading.Thread(target=worker, name='dirac-console-keys', daemon=True)
    thread.start()
    return stop


class RuntimeLogger:
    def __init__(
        self,
        *,
        get_db,
        get_config,
        set_config,
        persist_config,
        broadcast,
        known_secret_values,
        redact_runtime_rows,
        utc_now,
        madrid_now,
        madrid_from_utc,
        local_timezone_name='Europe/Madrid',
    ):
        self.get_db = get_db
        self.get_config = get_config
        self.set_config = set_config
        self.persist_config = persist_config
        self.broadcast = broadcast
        self.known_secret_values = known_secret_values
        self.redact_runtime_rows = redact_runtime_rows
        self.utc_now = utc_now
        self.madrid_now = madrid_now
        self.madrid_from_utc = madrid_from_utc
        self.local_timezone_name = local_timezone_name

    def current_config(self):
        cfg = self.get_config()
        return normalize_logging_config(getattr(cfg, 'logging', {}) if cfg is not None else {})

    def log_is_enabled(self, level, component):
        return log_is_enabled(level, component, self.current_config())

    def console_log_line(self, level, component, message, detail=None, scope_type=None, scope_id=None):
        return console_log_line(
            level,
            component,
            message,
            detail,
            scope_type,
            scope_id,
            config=self.current_config(),
            local_timezone_name=self.local_timezone_name,
            madrid_now=self.madrid_now,
        )

    async def set_runtime_logging_config(self, logging_cfg):
        cfg = self.get_config()
        if cfg is not None:
            cfg.logging = normalize_logging_config(logging_cfg)
            self.set_config(cfg)
        self.persist_config()
        return self.current_config()

    async def adjust_console_logging(self, delta, app_log):
        cfg = self.current_config()
        current = normalize_log_level(cfg.get('console_level', 'info'))
        idx = LOG_LEVEL_ORDER[current]
        idx = max(0, min(len(LOG_LEVELS) - 1, idx + delta))
        cfg['console_level'] = LOG_LEVELS[idx]
        await self.set_runtime_logging_config(cfg)
        await app_log('info', 'bot', f"console log level set to {cfg['console_level']}", {'hint': console_json_view_hint()}, force_console=True)
        return cfg

    async def app_log(self, level, component, message, detail=None, scope_type=None, scope_id=None, force_console=False):
        db = self.get_db()
        level = normalize_log_level(level)
        safe_detail = detail
        if db is not None:
            try:
                safe_detail = self.redact_runtime_rows(detail, await self.known_secret_values(db))
            except Exception:
                safe_detail = detail
        if force_console or self.log_is_enabled(level, component):
            self.console_log_line(level, component, message, safe_detail, scope_type, scope_id)
        if db is None:
            return
        try:
            timestamp_utc = self.utc_now()
            await db.execute(
                'INSERT INTO bot_logs(level,component,message,detail_json,scope_type,scope_id,timestamp_utc) VALUES (?,?,?,?,?,?,?)',
                (level, component, message, json.dumps(safe_detail), scope_type, scope_id, timestamp_utc),
            )
            await db.commit()
            await self.broadcast({
                'type': 'bot_log',
                'data': {
                    'level': level,
                    'component': component,
                    'message': message,
                    'detail': safe_detail,
                    'scope_type': scope_type,
                    'scope_id': scope_id,
                    'timestamp_utc': timestamp_utc,
                    'timestamp_local': self.madrid_from_utc(timestamp_utc),
                    'timezone': self.local_timezone_name,
                },
            })
        except Exception:
            pass
