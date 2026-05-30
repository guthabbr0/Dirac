from __future__ import annotations

import json
from typing import Any

from dirac.providers.base import BaseProviderClient


class SimProviderClient(BaseProviderClient):
    def __init__(self):
        self.calls = []
        self.provider = {
            'id': 1,
            'name': 'sim-provider',
            'provider_type': 'sim',
            'base_url': 'sim://provider',
            'enabled': 1,
            'default_model': 'sim-model',
            'api_key': '',
            'supports_tools': 1,
            'supports_reasoning': 0,
            'supports_temperature': 1,
            'supports_streaming': 0,
            'timeout_s': 0.1,
        }

    async def chat(self, messages, tools=None, model=None, scope_type='panel', scope_id=None, source=None, task_id=None, task_run_id=None, bot_entry_id=None, params=None, user_id=None, roxanne_profile_id=None, dynamic_context=None):
        call = {'messages': messages, 'tools': tools, 'model': model or self.provider['default_model'], 'scope_type': scope_type, 'scope_id': scope_id, 'params': params or {}}
        self.calls.append(call)
        return {'message': {'content': 'simulated provider response', 'tool_calls': None}, 'provider_response': {'simulated': True, 'model': call['model']}}

    def current_model(self, config: Any = None) -> str:
        return self.provider['default_model']

    async def sync_config(self, cfg: Any):
        return {'ok': True}

    async def ensure_defaults(self, cfg: Any = None):
        return {'ok': True}

    async def list_providers(self, enabled_only: bool = False):
        return [dict(self.provider)] if self.provider['enabled'] or not enabled_only else []

    async def get_provider(self, token):
        if token in (None, '', 1, '1', self.provider['name']):
            return dict(self.provider)
        return None

    def redact_provider(self, row):
        if row is None:
            return None
        data = dict(row)
        data.pop('api_key', None)
        data['api_key_present'] = False
        data['api_key_preview'] = ''
        return data

    async def create_provider(self, data):
        return {'id': 1, 'ok': True, 'noop': True}

    async def patch_provider(self, provider_id: int, data):
        return {'ok': True, 'noop': True}

    async def disable_provider(self, provider_id: int):
        return {'ok': True, 'noop': True}

    async def set_provider_enabled(self, token, enabled: bool):
        self.provider['enabled'] = int(bool(enabled))
        return dict(self.provider)

    async def test_provider(self, provider):
        return {'ok': True, 'error': None, 'simulated': True}

    async def test_config(self, cfg):
        return {'ok': True, 'status_code': 200, 'simulated': True}

    async def provider_calls(self, provider_id=None, scope_type=None, scope_id=None, source=None, errors_only: bool = False, limit: int = 50):
        return list(reversed(self.calls[-int(limit):]))

    async def provider_call_summary(self, limit: int | None = None):
        return [{'provider_name': self.provider['name'], 'provider_type': self.provider['provider_type'], 'model': self.provider['default_model'], 'calls': len(self.calls), 'prompt_tokens': 0, 'completion_tokens': 0, 'latency_ms': 0, 'errors': 0}]

    async def resolve_binding(self, scope_type='panel', scope_id=None, user_id=None, task_id=None, bot_entry_id=None, roxanne_profile_id=None, model=None, params=None):
        return {'provider': dict(self.provider), 'model': model or self.provider['default_model'], 'params': dict(params or {}), 'source_chain': ['sim'], 'warnings': []}

    async def effective_scope_payload(self, scope_type, scope_id, user_id=None):
        binding = await self.resolve_binding(scope_type, scope_id, user_id=user_id)
        return {'scope': {'scope_type': scope_type, 'scope_id': scope_id}, 'provider': self.redact_provider(binding['provider']), 'model': binding['model'], 'parameters': binding['params'], 'source_chain': binding['source_chain'], 'warnings': binding['warnings'], 'tools': [], 'skills': [], 'memory_enabled': True}

    async def provider_params_for_profile(self, profile_id):
        return {}

    async def parameter_profiles(self):
        return [{'id': 1, 'name': 'sim-default', 'description': 'Simulated defaults', 'params_json': json.dumps({}), 'created_at': None, 'updated_at': None}]

    async def get_parameter_profile(self, token):
        return (await self.parameter_profiles())[0]

    async def list_provider_models(self, provider_id: int):
        return [{'provider_id': provider_id, 'model': self.provider['default_model'], 'display_name': self.provider['default_model'], 'enabled': 1}]

    async def upsert_provider_model(self, provider_id: int, data):
        return {'ok': True, 'noop': True}

    async def set_scope_provider(self, scope_type, scope_id, provider_token, model):
        return dict(self.provider)

    async def set_scope_params(self, scope_type, scope_id, profile_name):
        return await self.get_parameter_profile(profile_name)

    async def reset_scope_provider(self, scope_type, scope_id):
        return {'ok': True, 'noop': True}

    async def model_for_scope(self, default_model, scope_type, scope_id):
        return default_model or self.provider['default_model']

    async def reasoning_for_scope(self, scope_type, scope_id):
        return None

    async def legacy_usage(self, scope_type=None, scope_id=None):
        return {'calls': len(self.calls), 'prompt_tokens': 0, 'completion_tokens': 0, 'latency_ms': 0, 'errors': 0}

    async def legacy_ollama_log(self, scope_id=None, limit: int = 50):
        return []

    async def secret_values(self):
        return set()
