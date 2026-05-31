from __future__ import annotations

from collections.abc import Mapping

from dirac.types import ProviderRequest, ProviderResponse

from .base import BaseProviderClient, ProviderError


class ProviderRouter(BaseProviderClient):
    """Chooses one provider client without leaking concrete clients upstream."""

    def __init__(
        self, providers: Mapping[str, BaseProviderClient], default: str = "default"
    ) -> None:
        self.providers = dict(providers)
        self.default = default
        self.name = "router"

    async def chat(self, request: ProviderRequest) -> ProviderResponse:
        provider_name = str(request.metadata.get("provider") or self.default)
        client = self.providers.get(provider_name)
        if client is None:
            raise ProviderError(f"provider not configured: {provider_name}")
        return await client.chat(request)
