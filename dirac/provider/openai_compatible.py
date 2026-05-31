from __future__ import annotations

import httpx

from dirac.types import ProviderRequest, ProviderResponse

from .base import BaseProviderClient


class OpenAICompatibleProviderClient(BaseProviderClient):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        timeout_s: float = 120.0,
        name: str = "openai-compatible",
        default_headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.name = name
        self.default_headers = dict(default_headers or {})

    async def chat(self, request: ProviderRequest) -> ProviderResponse:
        body = {
            "model": request.model,
            "messages": request.messages,
            "stream": False,
        }
        if request.tools:
            body["tools"] = request.tools
        for key in (
            "temperature",
            "top_p",
            "max_tokens",
            "presence_penalty",
            "frequency_penalty",
            "seed",
            "response_format",
        ):
            if key in request.params:
                body[key] = request.params[key]
        headers = dict(self.default_headers)
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=self.timeout_s, headers=headers) as client:
            response = await client.post(f"{self.base_url}/chat/completions", json=body)
            response.raise_for_status()
            raw = response.json()
        choices = raw.get("choices") or []
        message = (
            choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
        ) or {}
        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        return ProviderResponse(
            content=message.get("content") or "",
            raw=raw,
            tool_calls=message.get("tool_calls") or [],
            usage=usage,
            provider_name=self.name,
            model=request.model,
        )
