from __future__ import annotations

import hashlib
import json
import os
import time
import tomllib
from pathlib import Path
from typing import Any

import httpx

from dirac.providers.base import BaseProviderClient


def _api_key_identity(secret):
    value = str(secret or '')
    if not value:
        return None, None
    return 'sha256:' + hashlib.sha256(value.encode('utf-8')).hexdigest(), value[-4:]


class OpenAIProviderClient(BaseProviderClient):
    def __init__(self, config_path: str | Path | None = None, *, redacted_secret='***'):
        self.config_path = Path(config_path or os.environ.get('DIRAC_OPENAI_CONFIG') or 'openai.toml')
        self.redacted_secret = redacted_secret
        self.calls = []
        self.config = self._load_config()

    def _load_config(self):
        if not self.config_path.exists():
            return {}
        with open(self.config_path, 'rb') as f:
            return tomllib.load(f)

    def _provider(self):
        data = dict(self.config.get('provider') or self.config.get('openai') or {})
        api_key = str(data.get('api_key') or self.config.get('api_key') or '')
        fp, last4 = _api_key_identity(api_key)
        return {
            'id': data.get('id'),
            'name': data.get('name') or 'openai-compatible',
            'provider_type': data.get('provider_type') or 'openai_compatible',
            'base_url': str(data.get('base_url') or 'https://api.openai.com/v1').rstrip('/'),
            'enabled': int(data.get('enabled', True)),
            'default_model': data.get('default_model') or data.get('model') or self.config.get('model') or 'gpt-4.1-mini',
            'api_key': api_key,
            'api_key_fingerprint': fp,
            'api_key_last4': last4,
            'supports_tools': int(data.get('supports_tools', True)),
            'supports_reasoning': int(data.get('supports_reasoning', False)),
            'supports_temperature': int(data.get('supports_temperature', True)),
            'supports_streaming': int(data.get('supports_streaming', True)),
            'timeout_s': float(data.get('timeout_s') or self.config.get('timeout_s') or 120.0),
        }

    def _params(self):
        params = dict(self.config.get('params') or {})
        provider = self._provider()
        if provider.get('timeout_s'):
            params.setdefault('timeout_s', provider['timeout_s'])
        return params

    async def chat(self, messages, tools=None, model=None, scope_type='panel', scope_id=None, source=None, task_id=None, task_run_id=None, bot_entry_id=None, params=None, user_id=None, roxanne_profile_id=None, dynamic_context=None):
        provider = self._provider()
        model = model or provider.get('default_model')
        resolved_params = self._params()
        if params:
            resolved_params.update(params)
        body = {'model': model, 'messages': messages, 'stream': bool(resolved_params.get('streaming', False))}
        if tools and int(provider.get('supports_tools') or 0):
            body['tools'] = tools
        for key in ('temperature', 'top_p', 'max_tokens', 'presence_penalty', 'frequency_penalty', 'seed', 'response_format'):
            if key in resolved_params:
                body[key] = resolved_params[key]
        extra = resolved_params.get('custom') or resolved_params.get('extra_body')
        if isinstance(extra, dict):
            body.update(extra)
        headers = {}
        if provider.get('api_key'):
            headers['Authorization'] = f"Bearer {provider['api_key']}"
        url = f"{provider.get('base_url','').rstrip('/')}/chat/completions"
        timeout = float(resolved_params.get('timeout_s') or provider.get('timeout_s') or 120.0)
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            r = await client.post(url, json=body)
            r.raise_for_status()
            resp_obj = r.json()
        latency = int((time.perf_counter() - start) * 1000)
        self.calls.append({'url': url, 'body': body, 'latency_ms': latency, 'scope_type': scope_type, 'scope_id': scope_id})
        choices = resp_obj.get('choices') or []
        msg = (choices[0].get('message') if choices and isinstance(choices[0], dict) else {}) or {}
        return {'message': {'content': msg.get('content', ''), 'tool_calls': msg.get('tool_calls')}, 'provider_response': resp_obj}

    def current_model(self, config: Any = None) -> str:
        return str(self._provider().get('default_model') or 'gpt-4.1-mini')

    async def sync_config(self, cfg: Any):
        self.config = self._load_config()
        return {'ok': True}

    async def ensure_defaults(self, cfg: Any = None):
        return {'ok': True}

    async def list_providers(self, enabled_only: bool = False):
        provider = self._provider()
        return [provider] if provider.get('enabled') or not enabled_only else []

    async def get_provider(self, token):
        provider = self._provider()
        if token in (None, '', provider.get('id'), provider.get('name')):
            return provider
        if str(token).isdigit() and provider.get('id') and int(token) == int(provider.get('id')):
            return provider
        return None

    def redact_provider(self, row):
        if row is None:
            return None
        data = dict(row)
        secret = data.pop('api_key', None)
        data['api_key_present'] = bool(secret)
        data['api_key_preview'] = (self.redacted_secret + (data.get('api_key_last4') or '')) if secret else ''
        return data

    async def create_provider(self, data):
        return {'id': 1, 'ok': True, 'noop': True}

    async def patch_provider(self, provider_id: int, data):
        return {'ok': True, 'noop': True}

    async def disable_provider(self, provider_id: int):
        return {'ok': True, 'noop': True}

    async def set_provider_enabled(self, token, enabled: bool):
        return self._provider()

    async def test_provider(self, provider):
        provider = provider if isinstance(provider, dict) else self._provider()
        headers = {}
        if provider.get('api_key'):
            headers['Authorization'] = f"Bearer {provider['api_key']}"
        url = f"{provider.get('base_url','').rstrip('/')}/models"
        try:
            async with httpx.AsyncClient(timeout=float(provider.get('timeout_s') or 10.0), headers=headers) as client:
                r = await client.get(url)
            ok = 200 <= r.status_code < 300
            return {'ok': ok, 'error': None if ok else f'HTTP {r.status_code}'}
        except Exception as e:
            return {'ok': False, 'error': type(e).__name__}

    async def test_config(self, cfg):
        return await self.test_provider(self._provider())

    async def provider_calls(self, provider_id=None, scope_type=None, scope_id=None, source=None, errors_only: bool = False, limit: int = 50):
        return list(reversed(self.calls[-int(limit):]))

    async def provider_call_summary(self, limit: int | None = None):
        provider = self._provider()
        return [{'provider_name': provider['name'], 'provider_type': provider['provider_type'], 'model': provider['default_model'], 'calls': len(self.calls), 'prompt_tokens': 0, 'completion_tokens': 0, 'latency_ms': sum(c.get('latency_ms') or 0 for c in self.calls), 'errors': 0}]

    async def resolve_binding(self, scope_type='panel', scope_id=None, user_id=None, task_id=None, bot_entry_id=None, roxanne_profile_id=None, model=None, params=None):
        provider = self._provider()
        resolved = self._params()
        if params:
            resolved.update(params)
        return {'provider': provider, 'model': model or provider.get('default_model'), 'params': resolved, 'source_chain': ['openai.toml'], 'warnings': []}

    async def effective_scope_payload(self, scope_type, scope_id, user_id=None):
        binding = await self.resolve_binding(scope_type, scope_id, user_id=user_id)
        return {'scope': {'scope_type': scope_type, 'scope_id': scope_id}, 'provider': self.redact_provider(binding['provider']), 'model': binding['model'], 'parameters': binding['params'], 'source_chain': binding['source_chain'], 'warnings': binding['warnings'], 'tools': [], 'skills': [], 'memory_enabled': True}

    async def provider_params_for_profile(self, profile_id):
        return self._params()

    async def parameter_profiles(self):
        return [{'id': 1, 'name': 'openai.toml', 'description': 'Parameters loaded from openai.toml', 'params_json': json.dumps(self._params()), 'created_at': None, 'updated_at': None}]

    async def get_parameter_profile(self, token):
        return (await self.parameter_profiles())[0]

    async def list_provider_models(self, provider_id: int):
        provider = self._provider()
        return [{'provider_id': provider_id, 'model': provider.get('default_model'), 'display_name': provider.get('default_model'), 'enabled': 1}]

    async def upsert_provider_model(self, provider_id: int, data):
        return {'ok': True, 'noop': True}

    async def set_scope_provider(self, scope_type, scope_id, provider_token, model):
        return self._provider()

    async def set_scope_params(self, scope_type, scope_id, profile_name):
        return await self.get_parameter_profile(profile_name)

    async def reset_scope_provider(self, scope_type, scope_id):
        return {'ok': True, 'noop': True}

    async def model_for_scope(self, default_model, scope_type, scope_id):
        return default_model or self.current_model()

    async def reasoning_for_scope(self, scope_type, scope_id):
        return None

    async def legacy_usage(self, scope_type=None, scope_id=None):
        return {'calls': len(self.calls), 'prompt_tokens': 0, 'completion_tokens': 0, 'latency_ms': sum(c.get('latency_ms') or 0 for c in self.calls), 'errors': 0}

    async def legacy_ollama_log(self, scope_id=None, limit: int = 50):
        return []

    async def secret_values(self):
        provider = self._provider()
        return {provider['api_key']} if provider.get('api_key') else set()
