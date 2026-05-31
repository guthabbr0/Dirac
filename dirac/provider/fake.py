from __future__ import annotations

from dirac.types import ProviderRequest, ProviderResponse

from .base import BaseProviderClient


class FakeProviderClient(BaseProviderClient):
    def __init__(self, content: str = "ok", name: str = "fake") -> None:
        self.content = content
        self.name = name
        self.requests: list[ProviderRequest] = []

    async def chat(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        return ProviderResponse(
            content=self.content, raw={"fake": True}, provider_name=self.name, model=request.model
        )
