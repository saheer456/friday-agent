import json
import os
from typing import Any, AsyncIterator

import httpx

from .base import BaseProvider, ProviderConfig, ProviderResponse, ProviderStatus

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "meta-llama/llama-3.1-8b-instruct:free"


class OpenRouterProvider(BaseProvider):
    name = "openrouter"

    def __init__(self, config: ProviderConfig = None):
        if config is None:
            key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
            model = (os.getenv("OPENROUTER_MODEL") or DEFAULT_MODEL).strip()
            config = ProviderConfig(
                api_key=key,
                base_url=OPENROUTER_URL,
                model=model,
                timeout=120.0,
                extra_headers={
                    "HTTP-Referer": (os.getenv("OPENROUTER_HTTP_REFERER") or "http://localhost").strip(),
                    "X-Title": (os.getenv("OPENROUTER_APP_TITLE") or "FRIDAY").strip(),
                },
            )
        self.config = config
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.config.timeout,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            )
        return self._client

    async def chat(self, messages: list[dict], **kwargs) -> ProviderResponse:
        client = self._get_client()
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            **self.config.extra_headers,
        }
        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 800),
        }
        if kwargs.get("tools"):
            payload["tools"] = kwargs["tools"]

        resp = await client.post(self.config.base_url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        msg = choice.get("message", {})

        return ProviderResponse(
            content=msg.get("content", "") or "",
            tool_calls=msg.get("tool_calls", []),
            finish_reason=choice.get("finish_reason", ""),
            usage=data.get("usage", {}),
        )

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[dict]:
        client = self._get_client()
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            **self.config.extra_headers,
        }
        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": True,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 800),
        }
        if kwargs.get("tools"):
            payload["tools"] = kwargs["tools"]

        async with client.stream("POST", self.config.base_url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                raw = line[6:]
                if raw.strip() == "[DONE]":
                    break
                try:
                    obj = json.loads(raw)
                    if "error" in obj:
                        yield {"type": "error", "error": obj["error"]}
                        return
                    delta = (obj.get("choices") or [{}])[0].get("delta") or {}
                    if delta.get("content"):
                        yield {"type": "text", "text": delta["content"]}
                    if "tool_calls" in delta:
                        for tc in delta["tool_calls"]:
                            yield {"type": "tool_call", "index": tc["index"], "delta": tc}
                    if (obj.get("choices") or [{}])[0].get("finish_reason"):
                        yield {"type": "done", "finish_reason": (obj.get("choices") or [{}])[0]["finish_reason"]}
                except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                    continue

    async def health_check(self) -> bool:
        try:
            client = self._get_client()
            r = await client.get("https://openrouter.ai/api/v1/auth/key",
                                 headers={"Authorization": f"Bearer {self.config.api_key}"},
                                 timeout=5.0)
            self.status = ProviderStatus.HEALTHY if r.is_success else ProviderStatus.UNHEALTHY
            return r.is_success
        except Exception:
            self.status = ProviderStatus.UNHEALTHY
            return False
