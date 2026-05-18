import asyncio
import logging
import os
import time
from typing import Any, AsyncIterator, Optional

from .base import BaseProvider, ProviderConfig, ProviderResponse, ProviderStatus
from .groq import GroqProvider
from .openrouter import OpenRouterProvider
from .cerebras import CerebrasProvider
from .ollama import OllamaProvider

logger = logging.getLogger("ProviderManager")


class ProviderManager:
    def __init__(self):
        self._providers: dict[str, BaseProvider] = {}
        self._fallback_order: list[str] = []
        self._rate_limiters: dict[str, float] = {}
        self._health_cache: dict[str, tuple[bool, float]] = {}

    def register(self, name: str, provider: BaseProvider) -> None:
        self._providers[name] = provider
        if name not in self._fallback_order:
            self._fallback_order.append(name)

    def set_fallback_order(self, order: list[str]) -> None:
        self._fallback_order = [n for n in order if n in self._providers]

    def get(self, name: str) -> Optional[BaseProvider]:
        return self._providers.get(name)

    def is_key_usable(self, key: str) -> bool:
        key = (key or "").strip()
        return bool(key) and "your_" not in key.lower()

    def _discover_providers(self) -> None:
        groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
        if self.is_key_usable(groq_key) and "groq" not in self._providers:
            self.register("groq", GroqProvider())

        cr_key = (os.getenv("CEREBRAS_API_KEY") or "").strip()
        if self.is_key_usable(cr_key) and "cerebras" not in self._providers:
            self.register("cerebras", CerebrasProvider())

        or_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
        if self.is_key_usable(or_key) and "openrouter" not in self._providers:
            self.register("openrouter", OpenRouterProvider())

        if "ollama" not in self._providers:
            self.register("ollama", OllamaProvider())

        preferred = os.getenv("FRIDAY_LLM_PROVIDER", "").strip().lower()
        if preferred:
            order = [preferred]
            for p in ["groq", "cerebras", "openrouter", "ollama"]:
                if p not in order:
                    order.append(p)
            self.set_fallback_order(order)

    def _check_rate_limit(self, provider_name: str) -> bool:
        last_call = self._rate_limiters.get(provider_name, 0.0)
        now = time.monotonic()
        if now - last_call < 0.25:
            return False
        self._rate_limiters[provider_name] = now
        return True

    async def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        is_heavy: bool = False,
        **kwargs,
    ) -> ProviderResponse:
        if not self._providers:
            self._discover_providers()

        if is_heavy and "cerebras" in self._fallback_order:
            order = list(self._fallback_order)
            order.remove("cerebras")
            order.insert(0, "cerebras")
        else:
            order = list(self._fallback_order)

        last_error = ""
        for provider_name in order:
            provider = self._providers.get(provider_name)
            if not provider:
                continue

            if provider.status == ProviderStatus.RATE_LIMITED:
                continue

            if not self._check_rate_limit(provider_name):
                await asyncio.sleep(0.1)

            for attempt in range(provider.config.max_retries):
                try:
                    result = await provider.chat(messages, tools=tools, **kwargs)
                    provider.status = ProviderStatus.HEALTHY
                    return result
                except Exception as e:
                    last_error = f"{provider_name}: {e}"
                    logger.warning(f"[ProviderManager] {provider_name} attempt {attempt + 1} failed: {e}")

                    if "429" in str(e) or "rate" in str(e).lower():
                        provider.status = ProviderStatus.RATE_LIMITED
                        wait = 2 ** (attempt + 1)
                        await asyncio.sleep(wait)
                        continue

                    if attempt < provider.config.max_retries - 1:
                        wait = 2 ** attempt
                        await asyncio.sleep(wait)
                        continue
                    break

        raise RuntimeError(f"All providers failed. Last error: {last_error}")

    async def stream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        is_heavy: bool = False,
        **kwargs,
    ) -> AsyncIterator[dict]:
        if not self._providers:
            self._discover_providers()

        if is_heavy and "cerebras" in self._fallback_order:
            order = list(self._fallback_order)
            order.remove("cerebras")
            order.insert(0, "cerebras")
        else:
            order = list(self._fallback_order)

        last_error = ""
        for provider_name in order:
            provider = self._providers.get(provider_name)
            if not provider:
                continue

            if provider.status == ProviderStatus.RATE_LIMITED:
                continue

            if not self._check_rate_limit(provider_name):
                await asyncio.sleep(0.1)

            for attempt in range(provider.config.max_retries):
                try:
                    async for event in provider.stream(messages, tools=tools, **kwargs):
                        if event.get("type") == "error":
                            last_error = f"{provider_name}: {event['error']}"
                            break
                        yield event
                        if event.get("type") == "done":
                            provider.status = ProviderStatus.HEALTHY
                            return
                    else:
                        continue
                    break
                except Exception as e:
                    last_error = f"{provider_name}: {e}"
                    logger.warning(f"[ProviderManager] {provider_name} stream attempt {attempt + 1} failed: {e}")

                    if "429" in str(e) or "rate" in str(e).lower():
                        provider.status = ProviderStatus.RATE_LIMITED
                        wait = 2 ** (attempt + 1)
                        await asyncio.sleep(wait)
                        continue

                    if attempt < provider.config.max_retries - 1:
                        wait = 2 ** attempt
                        await asyncio.sleep(wait)
                        continue
                    break

        logger.error(f"All providers failed streaming. Last error: {last_error}")

    async def health_check_all(self) -> dict[str, bool]:
        results = {}
        for name, provider in self._providers.items():
            try:
                ok = await provider.health_check()
                results[name] = ok
            except Exception:
                results[name] = False
        return results


provider_manager = ProviderManager()
