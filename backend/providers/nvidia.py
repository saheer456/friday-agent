import json
import os
import asyncio
import logging
from typing import Any, AsyncIterator

import httpx

from .base import BaseProvider, ProviderConfig, ProviderResponse, ProviderStatus

logger = logging.getLogger("NvidiaProvider")
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"


class NvidiaProvider(BaseProvider):
    """
    OpenAI-compatible provider for NVIDIA NIM / Nemotron Ultra.

    Supports extended streaming fields:
      - ``delta.content``           → regular text tokens (type="text")
      - ``delta.reasoning_content`` → internal chain-of-thought tokens (type="reasoning")

    The manager treats type="reasoning" chunks the same as type="text" so the
    brain receives them inline.  brain.py ignores unknown event types anyway,
    so adding reasoning passthrough is non-breaking.
    """

    name = "nvidia"

    def __init__(self, config: ProviderConfig = None):
        if config is None:
            key = (os.getenv("NVIDIA_API_KEY") or "").strip()
            model = (os.getenv("NVIDIA_MODEL") or DEFAULT_MODEL).strip()
            config = ProviderConfig(
                api_key=key,
                base_url=NVIDIA_URL,
                model=model,
                timeout=120.0,   # Nemotron is big — give it time
                max_retries=3,
            )
        self.config = config
        self._client: httpx.AsyncClient | None = None

    # ── internal helpers ─────────────────────────────────────────────────────

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.config.timeout,
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self._client

    def _build_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, messages: list[dict], stream: bool, **kwargs) -> dict:
        is_heavy = kwargs.get("is_heavy", True)
        
        # If user explicitly turned off thinking or budget is 0
        enable_thinking = kwargs.get("enable_thinking", True)
        reasoning_budget = kwargs.get("reasoning_budget")
        
        if reasoning_budget == 0 or not enable_thinking:
            enable_thinking = False
            reasoning_budget = 0
        else:
            reasoning_budget = 16384 if is_heavy else 4096
            
        max_tokens = kwargs.get("max_tokens")
        if not max_tokens:
            max_tokens = 16384 if is_heavy else 4096

        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": stream,
            "temperature": kwargs.get("temperature", 1.0),
            "top_p": kwargs.get("top_p", 0.95),
            "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
            "reasoning_budget": reasoning_budget,
        }
        if kwargs.get("tools"):
            payload["tools"] = kwargs["tools"]
        return payload

    # ── BaseProvider interface ────────────────────────────────────────────────

    async def chat(self, messages: list[dict], **kwargs) -> ProviderResponse:
        client = self._get_client()
        payload = self._build_payload(messages, stream=False, **kwargs)

        resp = await client.post(
            self.config.base_url,
            headers=self._build_headers(),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        msg = choice.get("message", {})

        # Merge reasoning_content (if present) before the regular content
        reasoning = msg.get("reasoning_content") or ""
        content = msg.get("content") or ""
        combined = (f"<think>\n{reasoning}\n</think>\n\n" + content) if reasoning else content

        return ProviderResponse(
            content=combined,
            tool_calls=msg.get("tool_calls", []),
            finish_reason=choice.get("finish_reason", ""),
            usage=data.get("usage", {}),
        )

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[dict]:
        client = self._get_client()
        payload = self._build_payload(messages, stream=True, **kwargs)

        async with client.stream(
            "POST",
            self.config.base_url,
            headers=self._build_headers(),
            json=payload,
        ) as resp:
            resp.raise_for_status()
            iterator = resp.aiter_lines().__aiter__()
            while True:
                try:
                    # Enforce a 30-second idle timeout between chunks
                    line = await asyncio.wait_for(iterator.__anext__(), timeout=30.0)
                except asyncio.TimeoutError:
                    logger.warning("[Nvidia] Streaming idle timeout (no data for 30s). Aborting.")
                    yield {"type": "error", "error": "Streaming idle timeout"}
                    return
                except StopAsyncIteration:
                    break

                if not line or not line.startswith("data: "):
                    continue
                raw = line[6:]
                if raw.strip() == "[DONE]":
                    yield {"type": "done", "finish_reason": "stop"}
                    return
                try:
                    obj = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    continue

                if "error" in obj:
                    yield {"type": "error", "error": obj["error"]}
                    return

                choices = obj.get("choices") or []
                if not choices:
                    continue

                choice = choices[0]
                delta = choice.get("delta") or {}

                # ── reasoning / thinking tokens ──────────────────────────────
                reasoning = delta.get("reasoning_content")
                if reasoning:
                    yield {"type": "reasoning", "text": reasoning}

                # ── regular content tokens ───────────────────────────────────
                content = delta.get("content")
                if content:
                    yield {"type": "text", "text": content}

                # ── tool calls ───────────────────────────────────────────────
                tool_calls = delta.get("tool_calls")
                if tool_calls:
                    for tc in tool_calls:
                        yield {"type": "tool_call", "index": tc["index"], "delta": tc}

                # ── finish signal ────────────────────────────────────────────
                finish = choice.get("finish_reason")
                if finish:
                    yield {"type": "done", "finish_reason": finish}
                    return

    async def health_check(self) -> bool:
        """
        NVIDIA NIM doesn't expose a cheap /models endpoint like Groq/OpenRouter.
        We do a minimal ping to the completions endpoint with a tiny payload.
        """
        try:
            client = self._get_client()
            payload = {
                "model": self.config.model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
                "stream": False,
                # No thinking for health check — keep it fast
                "chat_template_kwargs": {"enable_thinking": False},
                "reasoning_budget": 0,
            }
            r = await client.post(
                self.config.base_url,
                headers=self._build_headers(),
                json=payload,
                timeout=10.0,
            )
            ok = r.is_success
            self.status = ProviderStatus.HEALTHY if ok else ProviderStatus.UNHEALTHY
            return ok
        except Exception:
            self.status = ProviderStatus.UNHEALTHY
            return False
