from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import httpx

from dirac import tool_turns
from dirac.logging import log_is_enabled
from dirac.providers.base import BaseProviderClient


PROVIDER_PARAM_KEYS = {
    'temperature',
    'top_p',
    'top_k',
    'max_tokens',
    'presence_penalty',
    'frequency_penalty',
    'reasoning',
    'reasoning_effort',
    'timeout_s',
    'tools_enabled',
    'streaming',
    'response_format',
    'seed',
}


async def _dict_rows(cur):
    data = await cur.fetchall()
    return [dict(zip([c[0] for c in cur.description], r)) for r in data]


def _dict_from_row(cur, row):
    return dict(zip([c[0] for c in cur.description], row)) if row else None


def normalize_scope_id(scope_type, scope_id):
    return None if scope_id in (None, '', '*') else str(scope_id)


def api_key_identity(secret):
    value = str(secret or '')
    if not value:
        return None, None
    return 'sha256:' + hashlib.sha256(value.encode('utf-8')).hexdigest(), value[-4:]


def provider_defaults_for_type(provider_type):
    if provider_type == 'ollama':
        return {'supports_tools': 1, 'supports_reasoning': 1, 'supports_temperature': 1, 'supports_streaming': 0, 'auth_scheme': 'bearer'}
    if provider_type == 'openrouter':
        return {'supports_tools': 1, 'supports_reasoning': 1, 'supports_temperature': 1, 'supports_streaming': 1, 'auth_scheme': 'bearer'}
    return {'supports_tools': 1, 'supports_reasoning': 0, 'supports_temperature': 1, 'supports_streaming': 1, 'auth_scheme': 'bearer'}


def reasoning_to_think(mode):
    if mode == 'on':
        return True
    if mode == 'off':
        return False
    if mode in {'low', 'medium', 'high'}:
        return mode
    return None


def token_counts_from_ollama_response(resp):
    if not isinstance(resp, dict):
        return None, None
    usage = resp.get('usage') if isinstance(resp.get('usage'), dict) else {}
    prompt = resp.get('prompt_eval_count', resp.get('prompt_tokens', usage.get('prompt_tokens')))
    completion = resp.get('eval_count', resp.get('completion_tokens', usage.get('completion_tokens')))
    return prompt, completion


def provider_chat_payload(provider, messages, tools, model, params):
    provider_type = provider.get('provider_type')
    sent = {}
    ignored = {}
    if provider_type == 'ollama':
        body = {'model': model, 'messages': messages, 'stream': False}
        if tools and int(provider.get('supports_tools') or 0):
            body['tools'] = tools
        options = {}
        for key in ('temperature', 'top_p', 'top_k', 'seed'):
            if key in params:
                options[key] = params[key]
                sent[key] = params[key]
        if 'max_tokens' in params:
            options['num_predict'] = params['max_tokens']
            sent['max_tokens'] = params['max_tokens']
        if options:
            body['options'] = options
        reasoning = params.get('reasoning') or params.get('reasoning_effort')
        think = reasoning_to_think(reasoning)
        if think is not None:
            body['think'] = think
            sent['reasoning'] = reasoning
        for key, value in params.items():
            if key not in sent and key in PROVIDER_PARAM_KEYS:
                ignored[key] = value
        return f"{provider.get('base_url','').rstrip('/')}/api/chat", body, sent, ignored, 'ollama'
    body = {'model': model, 'messages': messages, 'stream': bool(params.get('streaming', False))}
    if tools and int(provider.get('supports_tools') or 0):
        body['tools'] = tools
    for key in ('temperature', 'top_p', 'max_tokens', 'presence_penalty', 'frequency_penalty', 'seed', 'response_format'):
        if key in params:
            body[key] = params[key]
            sent[key] = params[key]
    extra = params.get('custom') or params.get('extra_body')
    if isinstance(extra, dict):
        body.update(extra)
        sent['custom'] = extra
    if provider_type == 'openrouter':
        reasoning = params.get('reasoning') or params.get('reasoning_effort')
        if reasoning is not None:
            reasoning_payload = None
            if reasoning == 'on':
                reasoning_payload = {'enabled': True}
            elif reasoning == 'off':
                reasoning_payload = {'enabled': False}
            elif reasoning in {'low', 'medium', 'high'}:
                reasoning_payload = {'effort': reasoning}
            if reasoning_payload is not None:
                body['reasoning'] = reasoning_payload
                sent['reasoning'] = reasoning
    for key, value in params.items():
        if key not in sent and key in PROVIDER_PARAM_KEYS:
            ignored[key] = value
    return f"{provider.get('base_url','').rstrip('/')}/chat/completions", body, sent, ignored, 'openai'


def provider_response_parts(resp_obj, mode):
    if not isinstance(resp_obj, dict):
        return '', None, None, None
    if mode == 'ollama':
        content = (resp_obj.get('message') or {}).get('content') or resp_obj.get('response') or ''
        prompt, completion = token_counts_from_ollama_response(resp_obj)
        total = ((prompt or 0) + (completion or 0)) if (prompt is not None or completion is not None) else None
        return content, prompt, completion, total
    choices = resp_obj.get('choices') or []
    msg = (choices[0].get('message') if choices and isinstance(choices[0], dict) else {}) or {}
    usage = resp_obj.get('usage') or {}
    return msg.get('content', ''), usage.get('prompt_tokens'), usage.get('completion_tokens'), usage.get('total_tokens')


class LegacyProviderClient(BaseProviderClient):
    def __init__(
        self,
        db,
        endpoint='https://ollama.com',
        api_key='',
        default_model='llama3.2',
        timeout=120.0,
        *,
        redacted_secret='***',
        utc_now=None,
        app_log=None,
        current_logging_config=None,
        broadcast=None,
        inject_runtime_request_context=None,
        list_agent_assets=None,
        prompt_scope_types=None,
        valid_asset_name=None,
        upsert=None,
    ):
        self.db = db
        self.endpoint = endpoint.rstrip('/')
        self.api_key = api_key
        self.default_model = default_model
        self.timeout = timeout
        self.calls = []
        self.redacted_secret = redacted_secret
        self.utc_now = utc_now or self._utc_now
        self.app_log = app_log
        self.current_logging_config = current_logging_config or (lambda: {})
        self.broadcast = broadcast
        self.inject_runtime_request_context = inject_runtime_request_context or (lambda messages, provider, model: messages)
        self.list_agent_assets = list_agent_assets
        self.prompt_scope_types = set(prompt_scope_types or {'global', 'dm', 'group', 'guild'})
        self.valid_asset_name = valid_asset_name or (lambda name: True)
        self.upsert = upsert

    @staticmethod
    def _utc_now():
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    def current_model(self, config: Any = None) -> str:
        model = getattr(self, 'model', None) or getattr(self, 'default_model', None)
        if model:
            return model
        if isinstance(config, dict):
            ollama_cfg = config.get('ollama')
            if isinstance(ollama_cfg, dict):
                model = ollama_cfg.get('default_model')
                if model:
                    return model
        elif config is not None:
            ollama_cfg = getattr(config, 'ollama', None)
            if isinstance(ollama_cfg, dict):
                model = ollama_cfg.get('default_model')
            else:
                model = getattr(ollama_cfg, 'default_model', None)
            if model:
                return model
        return 'llama3.2'

    async def ensure_defaults(self, cfg: Any = None):
        now = self.utc_now()
        ollama_cfg = getattr(cfg, 'ollama', {}) if cfg is not None else {}
        endpoint = str(ollama_cfg.get('endpoint', 'https://ollama.com') or 'https://ollama.com').rstrip('/')
        default_model = str(ollama_cfg.get('default_model', 'llama3.2') or 'llama3.2')
        api_key = str(ollama_cfg.get('api_key', '') or '')
        timeout = float(ollama_cfg.get('request_timeout_s', 120.0) or 120.0)
        fp, last4 = api_key_identity(api_key)
        cur = await self.db.execute('SELECT id FROM service_providers LIMIT 1')
        if not await cur.fetchone():
            await self.db.execute(
                'INSERT INTO service_providers(name,provider_type,base_url,enabled,default_model,api_key,api_key_fingerprint,api_key_last4,supports_tools,supports_reasoning,supports_temperature,timeout_s,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('ollama-default', 'ollama', endpoint, 1, default_model, api_key, fp, last4, 1, 1, 1, timeout, now, now),
            )
        cur = await self.db.execute("SELECT id FROM provider_parameters WHERE name='default-balanced'")
        if not await cur.fetchone():
            await self.db.execute(
                'INSERT INTO provider_parameters(name,description,params_json,created_at,updated_at) VALUES (?,?,?,?,?)',
                ('default-balanced', 'Balanced default generation parameters', json.dumps({'temperature': 0.4, 'top_p': 0.9, 'reasoning': 'medium'}), now, now),
            )

    async def sync_config(self, cfg: Any):
        if cfg is None:
            return
        ollama_cfg = getattr(cfg, 'ollama', {}) or {}
        endpoint = str(ollama_cfg.get('endpoint', 'https://ollama.com') or 'https://ollama.com').rstrip('/')
        model = str(ollama_cfg.get('default_model', 'llama3.2') or 'llama3.2')
        api_key = str(ollama_cfg.get('api_key', '') or '')
        timeout = float(ollama_cfg.get('request_timeout_s', 120.0) or 120.0)
        fp, last4 = api_key_identity(api_key)
        cur = await self.db.execute("SELECT id FROM service_providers WHERE name='ollama-default'")
        row = await cur.fetchone()
        now = self.utc_now()
        if row:
            await self.db.execute(
                'UPDATE service_providers SET base_url=?,default_model=?,api_key=?,api_key_fingerprint=?,api_key_last4=?,timeout_s=?,updated_at=? WHERE id=?',
                (endpoint, model, api_key, fp, last4, timeout, now, row[0]),
            )
        else:
            await self.db.execute(
                'INSERT INTO service_providers(name,provider_type,base_url,enabled,default_model,api_key,api_key_fingerprint,api_key_last4,supports_tools,supports_reasoning,supports_temperature,timeout_s,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('ollama-default', 'ollama', endpoint, 1, model, api_key, fp, last4, 1, 1, 1, timeout, now, now),
            )
        await self.db.commit()

    def redact_provider(self, row):
        if row is None:
            return None
        data = dict(row)
        secret = data.pop('api_key', None)
        data['api_key_present'] = bool(secret)
        data['api_key_preview'] = (self.redacted_secret + (data.get('api_key_last4') or '')) if secret else ''
        return data

    async def get_provider(self, token):
        if token in (None, ''):
            return None
        if str(token).isdigit():
            cur = await self.db.execute('SELECT * FROM service_providers WHERE id=?', (int(token),))
        else:
            cur = await self.db.execute('SELECT * FROM service_providers WHERE name=?', (str(token),))
        row = await cur.fetchone()
        return _dict_from_row(cur, row)

    async def list_providers(self, enabled_only: bool = False):
        sql = 'SELECT * FROM service_providers'
        if enabled_only:
            sql += ' WHERE enabled=1'
        sql += ' ORDER BY enabled DESC, name ASC'
        return await _dict_rows(await self.db.execute(sql))

    def provider_fields_from_input(self, data, existing=None):
        incoming = data.model_dump(exclude_unset=True)
        provider_type = incoming.get('provider_type') or (existing or {}).get('provider_type') or 'ollama'
        defaults = provider_defaults_for_type(provider_type)
        fields = {}
        for key in ('name', 'provider_type', 'base_url', 'default_model', 'enabled', 'timeout_s'):
            if key in incoming:
                fields[key] = incoming[key]
        for key in ('supports_tools', 'supports_reasoning', 'supports_temperature', 'supports_streaming'):
            if incoming.get(key) is not None:
                fields[key] = int(bool(incoming[key]))
            elif existing is None:
                fields[key] = defaults[key]
        if existing is None:
            fields.setdefault('auth_scheme', defaults['auth_scheme'])
        if 'api_key' in incoming and incoming['api_key'] != self.redacted_secret:
            secret = incoming.get('api_key') or ''
            fp, last4 = api_key_identity(secret)
            fields['api_key'] = secret
            fields['api_key_fingerprint'] = fp
            fields['api_key_last4'] = last4
        return fields

    async def create_provider(self, data):
        if not self.valid_asset_name(data.name):
            raise ValueError('invalid provider name')
        fields = self.provider_fields_from_input(data)
        now = self.utc_now()
        fields['created_at'] = now
        fields['updated_at'] = now
        cur = await self.db.execute(
            'INSERT INTO service_providers(name,provider_type,base_url,enabled,default_model,api_key,api_key_fingerprint,api_key_last4,auth_scheme,supports_tools,supports_reasoning,supports_temperature,supports_streaming,timeout_s,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (
                fields['name'],
                fields['provider_type'],
                fields['base_url'],
                int(fields.get('enabled', True)),
                fields['default_model'],
                fields.get('api_key'),
                fields.get('api_key_fingerprint'),
                fields.get('api_key_last4'),
                fields.get('auth_scheme', 'bearer'),
                int(fields.get('supports_tools', 0)),
                int(fields.get('supports_reasoning', 0)),
                int(fields.get('supports_temperature', 1)),
                int(fields.get('supports_streaming', 0)),
                float(fields.get('timeout_s', 120.0)),
                now,
                now,
            ),
        )
        await self.db.commit()
        return {'id': int(cur.lastrowid), 'ok': True}

    async def patch_provider(self, provider_id: int, data):
        existing = await self.get_provider(provider_id)
        if not existing:
            return None
        fields = self.provider_fields_from_input(data, existing)
        if 'name' in fields and not self.valid_asset_name(fields['name']):
            raise ValueError('invalid provider name')
        fields['updated_at'] = self.utc_now()
        if fields:
            await self.db.execute('UPDATE service_providers SET ' + ', '.join(f'{k}=?' for k in fields) + ' WHERE id=?', tuple(fields.values()) + (provider_id,))
            await self.db.commit()
        return {'ok': True}

    async def disable_provider(self, provider_id: int):
        cur = await self.db.execute('SELECT id FROM service_providers WHERE id=?', (provider_id,))
        if not await cur.fetchone():
            return None
        await self.db.execute('UPDATE service_providers SET enabled=0,updated_at=? WHERE id=?', (self.utc_now(), provider_id))
        await self.db.commit()
        return {'ok': True}

    async def set_provider_enabled(self, token, enabled: bool):
        row = await self.get_provider(token)
        if not row:
            return None
        await self.db.execute('UPDATE service_providers SET enabled=?,updated_at=? WHERE id=?', (1 if enabled else 0, self.utc_now(), row['id']))
        await self.db.commit()
        return row

    async def provider_params_for_profile(self, profile_id):
        if not profile_id:
            return {}
        cur = await self.db.execute('SELECT params_json FROM provider_parameters WHERE id=?', (int(profile_id),))
        row = await cur.fetchone()
        if not row:
            return {}
        try:
            data = json.loads(row[0] or '{}')
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    async def parameter_profiles(self):
        return await _dict_rows(await self.db.execute('SELECT id,name,description,params_json,created_at,updated_at FROM provider_parameters ORDER BY name'))

    async def get_parameter_profile(self, token):
        if token in (None, ''):
            return None
        if str(token).isdigit():
            cur = await self.db.execute('SELECT id,name,description,params_json,created_at,updated_at FROM provider_parameters WHERE id=?', (int(token),))
        else:
            cur = await self.db.execute('SELECT id,name,description,params_json,created_at,updated_at FROM provider_parameters WHERE name=?', (str(token),))
        row = await cur.fetchone()
        return _dict_from_row(cur, row)

    async def scope_profile_for(self, scope_type, scope_id):
        sid = normalize_scope_id(scope_type, scope_id)
        if sid is None:
            cur = await self.db.execute('SELECT * FROM scope_profiles WHERE scope_type=? AND scope_id IS NULL', (scope_type,))
        else:
            cur = await self.db.execute('SELECT * FROM scope_profiles WHERE scope_type=? AND scope_id=?', (scope_type, sid))
        row = await cur.fetchone()
        return _dict_from_row(cur, row)

    async def model_for_scope(self, default_model, scope_type, scope_id):
        if scope_id is not None:
            cur = await self.db.execute('SELECT model FROM model_overrides WHERE scope_type=? AND scope_id=?', (scope_type, str(scope_id)))
            row = await cur.fetchone()
            if row:
                return row[0]
        cur = await self.db.execute("SELECT model FROM model_overrides WHERE scope_type='global' AND scope_id IS NULL")
        row = await cur.fetchone()
        return row[0] if row else default_model

    async def reasoning_for_scope(self, scope_type, scope_id):
        if scope_id is not None:
            cur = await self.db.execute('SELECT mode FROM reasoning_overrides WHERE scope_type=? AND scope_id=?', (scope_type, str(scope_id)))
            row = await cur.fetchone()
            if row:
                return row[0]
        cur = await self.db.execute("SELECT mode FROM reasoning_overrides WHERE scope_type='global' AND scope_id IS NULL")
        row = await cur.fetchone()
        return row[0] if row else None

    async def resolve_binding(self, scope_type='panel', scope_id=None, user_id=None, task_id=None, bot_entry_id=None, roxanne_profile_id=None, model=None, params=None):
        chain = []
        profile = None
        if task_id is not None:
            cur = await self.db.execute('SELECT provider_id,model,parameter_profile_id FROM agent_tasks WHERE id=?', (int(task_id),))
            task_row = await cur.fetchone()
            if task_row and (task_row[0] or task_row[1] or task_row[2]):
                profile = {'provider_id': task_row[0], 'model': task_row[1], 'parameter_profile_id': task_row[2]}
                chain.append('task')
        if profile is None and roxanne_profile_id is not None:
            cur = await self.db.execute('SELECT provider_id,model,parameter_profile_id FROM roxanne_profiles WHERE id=? AND enabled=1', (int(roxanne_profile_id),))
            row = await cur.fetchone()
            if row and (row[0] or row[1] or row[2]):
                profile = {'provider_id': row[0], 'model': row[1], 'parameter_profile_id': row[2]}
                chain.append('roxanne')
        if profile is None and user_id:
            profile = await self.scope_profile_for('user', str(user_id))
            if profile:
                chain.append('user')
        if profile is None:
            profile = await self.scope_profile_for(scope_type, scope_id)
            if profile:
                chain.append(scope_type)
        if profile is None and bot_entry_id:
            cur = await self.db.execute('SELECT provider_id,model,parameter_profile_id FROM bot_entry_bindings WHERE bot_entry_id=? AND enabled=1 ORDER BY priority DESC,id DESC LIMIT 1', (int(bot_entry_id),))
            row = await cur.fetchone()
            if row and (row[0] or row[1] or row[2]):
                profile = {'provider_id': row[0], 'model': row[1], 'parameter_profile_id': row[2]}
                chain.append('bot_entry')
        if profile is None:
            profile = await self.scope_profile_for('global', None)
            if profile:
                chain.append('global')
        provider = None
        if profile and profile.get('provider_id'):
            provider = await self.get_provider(profile.get('provider_id'))
        if provider is None:
            cur = await self.db.execute('SELECT * FROM service_providers WHERE enabled=1 ORDER BY id LIMIT 1')
            row = await cur.fetchone()
            if row:
                provider = _dict_from_row(cur, row)
                chain.append('first_enabled_provider')
        if provider is None or not int(provider.get('enabled') or 0):
            raise RuntimeError('No model provider is configured for this scope yet.')
        resolved_model = model or (profile or {}).get('model') or provider.get('default_model')
        try:
            legacy_model = await self.model_for_scope(
                resolved_model,
                scope_type if scope_type in self.prompt_scope_types else 'global',
                scope_id if scope_type in self.prompt_scope_types else None,
            )
            if model is None and not (profile or {}).get('model') and legacy_model:
                resolved_model = legacy_model
        except Exception:
            pass
        resolved_params = {}
        if profile and profile.get('parameter_profile_id'):
            resolved_params.update(await self.provider_params_for_profile(profile.get('parameter_profile_id')))
        if params:
            resolved_params.update(params)
        try:
            reasoning_mode = await self.reasoning_for_scope(
                scope_type if scope_type in self.prompt_scope_types else 'global',
                scope_id if scope_type in self.prompt_scope_types else None,
            )
            if reasoning_mode and 'reasoning' not in resolved_params:
                resolved_params['reasoning'] = reasoning_mode
        except Exception:
            pass
        return {'provider': provider, 'model': resolved_model, 'params': resolved_params, 'source_chain': chain, 'warnings': []}

    async def effective_scope_payload(self, scope_type, scope_id, user_id=None):
        binding = await self.resolve_binding(scope_type, normalize_scope_id(scope_type, scope_id), user_id=user_id)
        asset_scope = scope_type if scope_type in self.prompt_scope_types else ('guild' if scope_type == 'channel' else 'dm' if scope_type == 'user' else 'global')
        asset_scope_id = normalize_scope_id(asset_scope, scope_id)
        tools = []
        skills = []
        if self.list_agent_assets is not None:
            tools = await self.list_agent_assets(self.db, 'tool', asset_scope, asset_scope_id, True, True, False)
            skills = await self.list_agent_assets(self.db, 'skill', asset_scope, asset_scope_id, True, True, False)
        return {
            'scope': {'scope_type': scope_type, 'scope_id': normalize_scope_id(scope_type, scope_id)},
            'provider': self.redact_provider(binding['provider']),
            'model': binding['model'],
            'parameters': binding['params'],
            'source_chain': binding['source_chain'],
            'warnings': binding['warnings'],
            'tools': tools,
            'skills': skills,
            'memory_enabled': True,
        }

    async def set_scope_provider(self, scope_type, scope_id, provider_token, model):
        provider = await self.get_provider(provider_token)
        if not provider:
            return None
        now = self.utc_now()
        if self.upsert is not None:
            await self.upsert(self.db, 'scope_profiles', ['scope_type', 'scope_id'], [scope_type, scope_id], {'provider_id': provider['id'], 'model': model, 'enabled': 1, 'updated_at': now, 'created_at': now})
        else:
            await self.db.upsert('scope_profiles', ['scope_type', 'scope_id'], [scope_type, scope_id], {'provider_id': provider['id'], 'model': model, 'enabled': 1, 'updated_at': now, 'created_at': now})
        return provider

    async def set_scope_params(self, scope_type, scope_id, profile_name):
        profile = await self.get_parameter_profile(profile_name)
        if not profile:
            return None
        now = self.utc_now()
        if self.upsert is not None:
            await self.upsert(self.db, 'scope_profiles', ['scope_type', 'scope_id'], [scope_type, scope_id], {'parameter_profile_id': profile['id'], 'enabled': 1, 'updated_at': now, 'created_at': now})
        else:
            await self.db.upsert('scope_profiles', ['scope_type', 'scope_id'], [scope_type, scope_id], {'parameter_profile_id': profile['id'], 'enabled': 1, 'updated_at': now, 'created_at': now})
        return profile

    async def reset_scope_provider(self, scope_type, scope_id):
        now = self.utc_now()
        if self.upsert is not None:
            await self.upsert(self.db, 'scope_profiles', ['scope_type', 'scope_id'], [scope_type, scope_id], {'provider_id': None, 'model': None, 'parameter_profile_id': None, 'enabled': 1, 'updated_at': now, 'created_at': now})
        else:
            await self.db.upsert('scope_profiles', ['scope_type', 'scope_id'], [scope_type, scope_id], {'provider_id': None, 'model': None, 'parameter_profile_id': None, 'enabled': 1, 'updated_at': now, 'created_at': now})
        return {'ok': True}

    async def list_provider_models(self, provider_id: int):
        return await _dict_rows(await self.db.execute('SELECT * FROM provider_models WHERE provider_id=? ORDER BY enabled DESC, model', (provider_id,)))

    async def upsert_provider_model(self, provider_id: int, data):
        if not await self.get_provider(provider_id):
            return None
        now = self.utc_now()
        fields = {
            'display_name': data.display_name,
            'enabled': int(data.enabled),
            'context_window_tokens': data.context_window_tokens,
            'supports_tools': None if data.supports_tools is None else int(data.supports_tools),
            'supports_reasoning': None if data.supports_reasoning is None else int(data.supports_reasoning),
            'supports_vision': None if data.supports_vision is None else int(data.supports_vision),
            'supports_json': None if data.supports_json is None else int(data.supports_json),
            'updated_at': now,
            'created_at': now,
        }
        if self.upsert is not None:
            await self.upsert(self.db, 'provider_models', ['provider_id', 'model'], [provider_id, data.model], fields)
        else:
            await self.db.upsert('provider_models', ['provider_id', 'model'], [provider_id, data.model], fields)
        return {'ok': True}

    async def test_provider(self, provider):
        provider = provider if isinstance(provider, dict) else await self.get_provider(provider)
        if not provider:
            return None
        endpoint = (provider.get('base_url') or '').rstrip('/')
        path = '/api/tags' if provider.get('provider_type') == 'ollama' else '/models'
        headers = json.loads(provider.get('headers_json') or '{}') if provider.get('headers_json') else {}
        if provider.get('api_key'):
            headers['Authorization'] = f"Bearer {provider['api_key']}"
        try:
            if self.current_logging_config().get('provider_http_debug') or log_is_enabled('debug', 'provider', self.current_logging_config()):
                await self._log('debug', 'provider', f'HTTP GET {endpoint + path}', {'method': 'GET', 'url': endpoint + path, 'headers': headers, 'provider': provider.get('name'), 'source': 'test'})
            async with httpx.AsyncClient(timeout=float(provider.get('timeout_s') or 10.0), headers=headers) as client:
                r = await client.get(endpoint + path)
            ok = 200 <= r.status_code < 300
            err = None if ok else f'HTTP {r.status_code}'
            if self.current_logging_config().get('provider_http_debug') or log_is_enabled('debug', 'provider', self.current_logging_config()):
                await self._log('debug', 'provider', f'HTTP response {r.status_code} {endpoint + path}', {'status_code': r.status_code, 'text': r.text, 'provider': provider.get('name'), 'source': 'test'})
            elif log_is_enabled('trace', 'provider', self.current_logging_config()):
                await self._log('trace', 'provider', f'HTTP response {r.status_code} {endpoint + path}', {'status_code': r.status_code, 'text': r.text, 'provider': provider.get('name'), 'source': 'test'})
        except Exception as e:
            ok = False
            err = type(e).__name__
        await self.db.execute('UPDATE service_providers SET last_test_at=?,last_test_ok=?,last_error=?,updated_at=? WHERE id=?', (self.utc_now(), int(ok), err, self.utc_now(), provider['id']))
        await self.db.commit()
        return {'ok': ok, 'error': err}

    async def test_config(self, cfg):
        endpoint = (cfg.ollama.get('endpoint', 'https://ollama.com') if cfg else 'https://ollama.com').rstrip('/')
        api_key = cfg.ollama.get('api_key', '') if cfg else ''
        headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
        try:
            if self.current_logging_config().get('provider_http_debug') or log_is_enabled('debug', 'provider', self.current_logging_config()):
                await self._log('debug', 'provider', f'HTTP GET {endpoint}/api/tags', {'method': 'GET', 'url': f'{endpoint}/api/tags', 'headers': headers, 'source': 'config-test'})
            async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
                r = await client.get(f'{endpoint}/api/tags')
            if self.current_logging_config().get('provider_http_debug') or log_is_enabled('debug', 'provider', self.current_logging_config()):
                await self._log('debug', 'provider', f'HTTP response {r.status_code} {endpoint}/api/tags', {'status_code': r.status_code, 'text': r.text, 'source': 'config-test'})
            elif log_is_enabled('trace', 'provider', self.current_logging_config()):
                await self._log('trace', 'provider', f'HTTP response {r.status_code} {endpoint}/api/tags', {'status_code': r.status_code, 'text': r.text, 'source': 'config-test'})
            return {'ok': r.status_code == 200, 'status_code': r.status_code}
        except Exception:
            return {'ok': False, 'error': 'connection_failed'}

    async def chat(self, messages, tools=None, model=None, scope_type='panel', scope_id=None, source=None, task_id=None, task_run_id=None, bot_entry_id=None, params=None, user_id=None, roxanne_profile_id=None, dynamic_context=None):
        source = source or ('task' if task_id is not None else scope_type if scope_type in {'discord', 'panel', 'news', 'roxanne'} else 'panel')
        try:
            binding = await self.resolve_binding(scope_type, scope_id, user_id=user_id, task_id=task_id, bot_entry_id=bot_entry_id, roxanne_profile_id=roxanne_profile_id, model=model, params=params)
            provider = binding['provider']
            model = binding['model']
            resolved_params = binding['params']
            legacy_api_key = None
        except Exception:
            provider = {'id': None, 'name': 'ollama-legacy', 'provider_type': 'ollama', 'base_url': self.endpoint, 'default_model': self.default_model, 'timeout_s': self.timeout, 'supports_tools': 1, 'supports_reasoning': 1, 'supports_temperature': 1}
            model = model or self.default_model
            resolved_params = dict(params or {})
            legacy_api_key = self.api_key
        if provider.get('provider_type') == 'ollama' and provider.get('name') == 'ollama-legacy':
            try:
                legacy_model = await self.model_for_scope(self.default_model, scope_type, scope_id)
                if model is None and legacy_model:
                    model = legacy_model
            except Exception:
                pass
        try:
            reasoning_mode = await self.reasoning_for_scope(scope_type, scope_id)
            if reasoning_mode and 'reasoning' not in resolved_params:
                resolved_params['reasoning'] = reasoning_mode
        except Exception:
            pass
        base_messages = tool_turns.strip_tool_turn_state_messages(messages)
        missing_tool_turn_placeholder = bool(dynamic_context) and not tool_turns.messages_have_tool_turn_state_placeholder(base_messages)
        messages = tool_turns.prepare_messages_for_tool_turn(base_messages, dynamic_context)
        if missing_tool_turn_placeholder:
            await self._log('warn', 'ollama', 'tool turn state placeholder missing; inserted ephemeral system message', {'source': source, 'task_id': task_id, 'task_run_id': task_run_id}, scope_type, scope_id)
        messages = self.inject_runtime_request_context(messages, provider, model)
        url, body, sent_params, ignored_params, mode = provider_chat_payload(provider, messages, tools, model, resolved_params)
        start = time.perf_counter()
        err = None
        resp_obj = None
        prompt_tokens = None
        completion_tokens = None
        total_tokens = None
        try:
            api_key = provider.get('api_key') or legacy_api_key or (self.api_key if provider.get('provider_type') == 'ollama' else '')
            headers = json.loads(provider.get('headers_json') or '{}') if provider.get('headers_json') else {}
            if api_key:
                headers['Authorization'] = f'Bearer {api_key}'
            if provider.get('provider_type') == 'openrouter':
                headers.setdefault('HTTP-Referer', 'http://127.0.0.1:8765')
                headers.setdefault('X-Title', 'Dirac')
            timeout = float(provider.get('timeout_s') or self.timeout)
            if self.current_logging_config().get('provider_http_debug') or log_is_enabled('debug', 'provider', self.current_logging_config()):
                await self._log('debug', 'provider', f'HTTP POST {url}', {'method': 'POST', 'url': url, 'headers': headers, 'json': body, 'provider': provider.get('name'), 'model': model, 'source': source, 'task_id': task_id, 'task_run_id': task_run_id}, scope_type, scope_id)
            async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
                r = await client.post(url, json=body)
                r.raise_for_status()
                resp_obj = r.json()
                content, prompt_tokens, completion_tokens, total_tokens = provider_response_parts(resp_obj, mode)
                if self.current_logging_config().get('provider_http_debug') or log_is_enabled('debug', 'provider', self.current_logging_config()):
                    await self._log('debug', 'provider', f'HTTP response {r.status_code} {url}', {'status_code': r.status_code, 'json': resp_obj, 'provider': provider.get('name'), 'model': model}, scope_type, scope_id)
                elif log_is_enabled('trace', 'provider', self.current_logging_config()):
                    await self._log('trace', 'provider', f'HTTP response {r.status_code} {url}', {'status_code': r.status_code, 'json': resp_obj, 'provider': provider.get('name'), 'model': model}, scope_type, scope_id)
                if mode == 'ollama':
                    return resp_obj
                return {
                    'message': {
                        'content': content,
                        'tool_calls': ((resp_obj.get('choices') or [{}])[0].get('message') or {}).get('tool_calls') if isinstance(resp_obj, dict) and resp_obj.get('choices') else None,
                    },
                    'provider_response': resp_obj,
                }
        except Exception as e:
            err = str(e)
            resp_obj = {'error': err}
            raise
        finally:
            latency = int((time.perf_counter() - start) * 1000)
            self.calls.append(body)
            await self.db.execute(
                'INSERT INTO provider_calls(provider_id,provider_name,provider_type,model,scope_type,scope_id,bot_entry_id,task_id,task_run_id,source,request_json,response_json,sent_params_json,ignored_params_json,prompt_tokens,completion_tokens,total_tokens,latency_ms,error,timestamp_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (provider.get('id'), provider.get('name') or 'unknown', provider.get('provider_type') or 'unknown', model, scope_type, scope_id, bot_entry_id, task_id, task_run_id, source, json.dumps(body), json.dumps(resp_obj), json.dumps(sent_params), json.dumps(ignored_params), prompt_tokens, completion_tokens, total_tokens, latency, err, self.utc_now()),
            )
            await self.db.execute(
                'INSERT INTO ollama_log(scope_type,scope_id,model,prompt_tokens,completion_tokens,latency_ms,request_json,response_json,error,timestamp_utc) VALUES (?,?,?,?,?,?,?,?,?,?)',
                (scope_type, scope_id, model, prompt_tokens, completion_tokens, latency, json.dumps(body), json.dumps(resp_obj), err, self.utc_now()),
            )
            await self.db.commit()
            if self.broadcast is not None:
                await self.broadcast({'type': 'ollama', 'data': {'scope_type': scope_type, 'scope_id': scope_id, 'model': model, 'provider': provider.get('name'), 'error': err}})

    async def provider_call_summary(self, limit: int | None = None):
        sql = "SELECT provider_name,provider_type,model,COUNT(*) calls,COALESCE(SUM(prompt_tokens),0) prompt_tokens,COALESCE(SUM(completion_tokens),0) completion_tokens,COALESCE(SUM(latency_ms),0) latency_ms,SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) errors FROM provider_calls GROUP BY provider_name,provider_type,model ORDER BY calls DESC"
        params = ()
        if limit is not None:
            sql += ' LIMIT ?'
            params = (int(limit),)
        return await _dict_rows(await self.db.execute(sql, params))

    async def provider_calls(self, provider_id=None, scope_type=None, scope_id=None, source=None, errors_only: bool = False, limit: int = 50):
        sql = 'SELECT * FROM provider_calls WHERE 1=1'
        p = []
        if provider_id is not None:
            sql += ' AND provider_id=?'
            p.append(provider_id)
        if scope_type:
            sql += ' AND scope_type=?'
            p.append(scope_type)
        if scope_id:
            sql += ' AND scope_id=?'
            p.append(scope_id)
        if source:
            sql += ' AND source=?'
            p.append(source)
        if errors_only:
            sql += ' AND error IS NOT NULL'
        sql += ' ORDER BY id DESC LIMIT ?'
        p.append(limit)
        return await _dict_rows(await self.db.execute(sql, tuple(p)))

    async def legacy_usage(self, scope_type=None, scope_id=None):
        params = []
        where = 'WHERE 1=1'
        if scope_type:
            where += ' AND scope_type=?'
            params.append(scope_type)
        if scope_id:
            where += ' AND scope_id=?'
            params.append(scope_id)
        cur = await self.db.execute(f'SELECT COUNT(*),COALESCE(SUM(prompt_tokens),0),COALESCE(SUM(completion_tokens),0),COALESCE(SUM(latency_ms),0),SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) FROM ollama_log {where}', tuple(params))
        calls, prompt_tokens, completion_tokens, latency_ms, errors = await cur.fetchone()
        return {'calls': calls, 'prompt_tokens': prompt_tokens, 'completion_tokens': completion_tokens, 'latency_ms': latency_ms, 'errors': errors}

    async def legacy_ollama_log(self, scope_id=None, limit: int = 50):
        sql = 'SELECT * FROM ollama_log WHERE 1=1'
        p = []
        if scope_id:
            sql += ' AND scope_id=?'
            p.append(scope_id)
        sql += ' ORDER BY id DESC LIMIT ?'
        p.append(limit)
        return await _dict_rows(await self.db.execute(sql, tuple(p)))

    async def secret_values(self):
        values = set()
        cur = await self.db.execute("SELECT api_key FROM service_providers WHERE api_key IS NOT NULL AND api_key!=''")
        for (value,) in await cur.fetchall():
            if value and len(str(value)) >= 4:
                values.add(str(value))
        return values

    async def _log(self, level, component, message, detail=None, scope_type=None, scope_id=None):
        if self.app_log is not None:
            await self.app_log(level, component, message, detail, scope_type, scope_id)
