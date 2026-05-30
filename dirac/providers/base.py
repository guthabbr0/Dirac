from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseProviderClient(ABC):
    """Abstract provider surface used by bot.py.

    Implementations own provider-specific persistence, routing, payloads, HTTP
    calls, response parsing, and provider/operator visibility.
    """

    @abstractmethod
    async def chat(self, messages, tools=None, model=None, scope_type='panel', scope_id=None, source=None, task_id=None, task_run_id=None, bot_entry_id=None, params=None, user_id=None, roxanne_profile_id=None, dynamic_context=None):
        raise NotImplementedError

    @abstractmethod
    def current_model(self, config: Any = None) -> str:
        raise NotImplementedError

    @abstractmethod
    async def sync_config(self, cfg: Any):
        raise NotImplementedError

    @abstractmethod
    async def ensure_defaults(self, cfg: Any = None):
        raise NotImplementedError

    @abstractmethod
    async def list_providers(self, enabled_only: bool = False):
        raise NotImplementedError

    @abstractmethod
    async def get_provider(self, token):
        raise NotImplementedError

    @abstractmethod
    def redact_provider(self, row):
        raise NotImplementedError

    @abstractmethod
    async def create_provider(self, data):
        raise NotImplementedError

    @abstractmethod
    async def patch_provider(self, provider_id: int, data):
        raise NotImplementedError

    @abstractmethod
    async def disable_provider(self, provider_id: int):
        raise NotImplementedError

    @abstractmethod
    async def set_provider_enabled(self, token, enabled: bool):
        raise NotImplementedError

    @abstractmethod
    async def test_provider(self, provider):
        raise NotImplementedError

    @abstractmethod
    async def test_config(self, cfg):
        raise NotImplementedError

    @abstractmethod
    async def provider_calls(self, provider_id=None, scope_type=None, scope_id=None, source=None, errors_only: bool = False, limit: int = 50):
        raise NotImplementedError

    @abstractmethod
    async def provider_call_summary(self, limit: int | None = None):
        raise NotImplementedError

    @abstractmethod
    async def resolve_binding(self, scope_type='panel', scope_id=None, user_id=None, task_id=None, bot_entry_id=None, roxanne_profile_id=None, model=None, params=None):
        raise NotImplementedError

    @abstractmethod
    async def effective_scope_payload(self, scope_type, scope_id, user_id=None):
        raise NotImplementedError

    @abstractmethod
    async def provider_params_for_profile(self, profile_id):
        raise NotImplementedError

    @abstractmethod
    async def parameter_profiles(self):
        raise NotImplementedError

    @abstractmethod
    async def get_parameter_profile(self, token):
        raise NotImplementedError

    @abstractmethod
    async def list_provider_models(self, provider_id: int):
        raise NotImplementedError

    @abstractmethod
    async def upsert_provider_model(self, provider_id: int, data):
        raise NotImplementedError

    @abstractmethod
    async def set_scope_provider(self, scope_type, scope_id, provider_token, model):
        raise NotImplementedError

    @abstractmethod
    async def set_scope_params(self, scope_type, scope_id, profile_name):
        raise NotImplementedError

    @abstractmethod
    async def reset_scope_provider(self, scope_type, scope_id):
        raise NotImplementedError

    @abstractmethod
    async def model_for_scope(self, default_model, scope_type, scope_id):
        raise NotImplementedError

    @abstractmethod
    async def reasoning_for_scope(self, scope_type, scope_id):
        raise NotImplementedError

    @abstractmethod
    async def legacy_usage(self, scope_type=None, scope_id=None):
        raise NotImplementedError

    @abstractmethod
    async def legacy_ollama_log(self, scope_id=None, limit: int = 50):
        raise NotImplementedError

    @abstractmethod
    async def secret_values(self):
        raise NotImplementedError
