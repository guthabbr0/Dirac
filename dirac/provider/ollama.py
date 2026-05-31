from __future__ import annotations

import httpx

from dirac.types import ProviderRequest, ProviderResponse

from .base import BaseProviderClient


class OllamaProviderClient(BaseProviderClient):
    def __init__(
        self, *, base_url: str, api_key: str = "", timeout_s: float = 120.0, name: str = "ollama"
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.name = name

    async def chat(self, request: ProviderRequest) -> ProviderResponse:
        body = {
            "model": request.model,
            "messages": request.messages,
            "stream": False,
        }
        if request.tools:
            body["tools"] = request.tools
        if request.params:
            body["options"] = {
                key: value
                for key, value in request.params.items()
                if key in {"temperature", "top_p", "top_k", "seed"}
            }
            if "max_tokens" in request.params:
                body["options"]["num_predict"] = request.params["max_tokens"]
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient(timeout=self.timeout_s, headers=headers) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=body)
            response.raise_for_status()
            raw = response.json()
        message = raw.get("message") if isinstance(raw, dict) else None
        content = (message or {}).get("content") or raw.get("response", "")
        tool_calls = (message or {}).get("tool_calls") or []
        return ProviderResponse(
            content=content,
            raw=raw,
            tool_calls=tool_calls,
            provider_name=self.name,
            model=request.model,
        )
