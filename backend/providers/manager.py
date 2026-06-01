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
        self._rate_limited_until: dict[str, float] = {}

    def register(self, name: str, provider: BaseProvider) -> None:
        self._providers[name] = provider
        if name not in self._fallback_order:
            self._fallback_order.append(name)
        logger.debug(
            "[ProviderManager] Registered provider=%s model=%s base_url=%s",
            name,
            provider.config.model,
            provider.config.base_url,
        )

    def set_fallback_order(self, order: list[str]) -> None:
        self._fallback_order = [n for n in order if n in self._providers]

    def get(self, name: str) -> Optional[BaseProvider]:
        return self._providers.get(name)

    def is_key_usable(self, key: str) -> bool:
        key = (key or "").strip()
        return bool(key) and "your_" not in key.lower()

    def _discover_providers(self) -> None:
        preferred = os.getenv("FRIDAY_LLM_PROVIDER", "").strip().lower()
        allow_ollama = os.getenv("FRIDAY_ENABLE_OLLAMA", "").strip().lower() in {"1", "true", "yes", "on"}

        groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
        if self.is_key_usable(groq_key) and "groq" not in self._providers:
            self.register("groq", GroqProvider())

        cr_key = (os.getenv("CEREBRAS_API_KEY") or "").strip()
        if self.is_key_usable(cr_key) and "cerebras" not in self._providers:
            self.register("cerebras", CerebrasProvider())

        or_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
        if self.is_key_usable(or_key) and "openrouter" not in self._providers:
            self.register("openrouter", OpenRouterProvider())

        ollama_url = (os.getenv("OLLAMA_URL") or "http://localhost:11434/v1/chat/completions").strip()
        is_deployed = any(os.getenv(var) for var in ["RENDER", "PORT", "KUBERNETES_SERVICE_HOST", "GAE_ENV", "DEPLOYED", "PRODUCTION"])
        is_ollama_local = "localhost" in ollama_url or "127.0.0.1" in ollama_url
        should_register_ollama = (
            preferred == "ollama"
            or allow_ollama
            or (not is_deployed and not preferred)
        )

        if "ollama" not in self._providers and should_register_ollama:
            if not is_deployed or not is_ollama_local or allow_ollama:
                self.register("ollama", OllamaProvider())
            else:
                logger.info(
                    "[ProviderManager] Skipping local Ollama fallback in deployed environment: %s",
                    ollama_url,
                )

        if preferred:
            order = [preferred]
            for p in ["groq", "cerebras", "openrouter", "ollama"]:
                if p not in order:
                    order.append(p)
            self.set_fallback_order(order)

        logger.debug(
            "[ProviderManager] Discovery complete providers=%s fallback_order=%s preferred=%s",
            sorted(self._providers.keys()),
            self._fallback_order,
            preferred or "<auto>",
        )

        # Always ensure groq is first in fallback order (primary free-tier provider)
        if not preferred and "groq" in self._providers:
            order = ["groq"]
            for p in self._fallback_order:
                if p not in order:
                    order.append(p)
            self._fallback_order = order

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

        order = list(self._fallback_order)
        logger.debug(
            "[ProviderManager] Generate requested providers=%s messages=%d tools=%d heavy=%s",
            order,
            len(messages),
            len(tools or []),
            is_heavy,
        )

        errors = []
        for provider_name in order:
            provider = self._providers.get(provider_name)
            if not provider:
                continue
            logger.debug("[ProviderManager] Generate trying provider=%s", provider_name)

            if provider.status == ProviderStatus.RATE_LIMITED:
                until = self._rate_limited_until.get(provider_name, 0.0)
                if time.monotonic() < until:
                    continue
                provider.status = ProviderStatus.HEALTHY

            while not self._check_rate_limit(provider_name):
                await asyncio.sleep(0.05)

            for attempt in range(provider.config.max_retries):
                try:
                    result = await provider.chat(messages, tools=tools, **kwargs)
                    provider.status = ProviderStatus.HEALTHY
                    logger.debug(
                        "[ProviderManager] Generate succeeded provider=%s finish_reason=%s content_chars=%d tool_calls=%d",
                        provider_name,
                        result.finish_reason,
                        len(result.content or ""),
                        len(result.tool_calls or []),
                    )
                    return result
                except Exception as e:
                    err_str = str(e)
                    err_msg = f"{provider_name}({provider.config.model}): {e}"
                    logger.warning(f"[ProviderManager] {provider_name} attempt {attempt + 1} failed: {e}")

                    # 404 = model not found / bad endpoint — no point retrying
                    if "404" in err_str:
                        provider.status = ProviderStatus.UNHEALTHY
                        errors.append(err_msg + " [model/endpoint not found — check model name]")
                        break

                    if "429" in err_str or "rate" in err_str.lower():
                        provider.status = ProviderStatus.RATE_LIMITED
                        self._rate_limited_until[provider_name] = time.monotonic() + 60.0
                        wait = 2 ** (attempt + 1)
                        await asyncio.sleep(wait)
                        continue

                    if attempt < provider.config.max_retries - 1:
                        wait = 2 ** attempt
                        await asyncio.sleep(wait)
                        continue
                    errors.append(err_msg)
                    break

        if not errors:
            raise RuntimeError("No usable LLM providers registered. Please check that you configured GROQ_API_KEY, CEREBRAS_API_KEY, or OPENROUTER_API_KEY in your environment.")
        raise RuntimeError(f"All providers failed. Details: {'; '.join(errors)}")

    async def stream(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        is_heavy: bool = False,
        **kwargs,
    ) -> AsyncIterator[dict]:
        if not self._providers:
            self._discover_providers()

        order = list(self._fallback_order)
        logger.debug(
            "[ProviderManager] Stream requested providers=%s messages=%d tools=%d heavy=%s",
            order,
            len(messages),
            len(tools or []),
            is_heavy,
        )

        errors = []
        for provider_name in order:
            provider = self._providers.get(provider_name)
            if not provider:
                continue
            logger.debug("[ProviderManager] Stream trying provider=%s", provider_name)

            if provider.status == ProviderStatus.RATE_LIMITED:
                until = self._rate_limited_until.get(provider_name, 0.0)
                if time.monotonic() < until:
                    continue
                provider.status = ProviderStatus.HEALTHY

            while not self._check_rate_limit(provider_name):
                await asyncio.sleep(0.05)

            for attempt in range(provider.config.max_retries):
                try:
                    text_chunks = 0
                    tool_chunks = 0
                    async for event in provider.stream(messages, tools=tools, **kwargs):
                        if event.get("type") == "error":
                            err_detail = event['error']
                            errors.append(f"{provider_name}({provider.config.model}): {err_detail}")
                            logger.debug(
                                "[ProviderManager] Stream provider=%s returned error event: %s",
                                provider_name,
                                err_detail,
                            )
                            break
                        if event.get("type") == "text":
                            text_chunks += 1
                        elif event.get("type") == "tool_call":
                            tool_chunks += 1
                        yield event
                        if event.get("type") == "done":
                            provider.status = ProviderStatus.HEALTHY
                            logger.debug(
                                "[ProviderManager] Stream succeeded provider=%s finish_reason=%s text_chunks=%d tool_chunks=%d",
                                provider_name,
                                event.get("finish_reason"),
                                text_chunks,
                                tool_chunks,
                            )
                            return
                    else:
                        if attempt < provider.config.max_retries - 1:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        errors.append(f"{provider_name}({provider.config.model}): stream finished without done event")
                        break
                    break
                except Exception as e:
                    err_str = str(e)
                    err_msg = f"{provider_name}({provider.config.model}): {e}"
                    logger.warning(f"[ProviderManager] {provider_name} stream attempt {attempt + 1} failed: {e}")

                    # 404 = model not found / bad endpoint — no point retrying
                    if "404" in err_str:
                        provider.status = ProviderStatus.UNHEALTHY
                        errors.append(err_msg + " [model/endpoint not found — check model name]")
                        break

                    if "429" in err_str or "rate" in err_str.lower():
                        provider.status = ProviderStatus.RATE_LIMITED
                        self._rate_limited_until[provider_name] = time.monotonic() + 60.0
                        wait = 2 ** (attempt + 1)
                        await asyncio.sleep(wait)
                        continue

                    if attempt < provider.config.max_retries - 1:
                        wait = 2 ** attempt
                        await asyncio.sleep(wait)
                        continue
                    errors.append(err_msg)
                    break

        if not errors:
            err_msg = "No usable LLM providers registered. Please check that you configured GROQ_API_KEY, CEREBRAS_API_KEY, or OPENROUTER_API_KEY in your environment."
        else:
            err_msg = f"All LLM providers failed. Details: {'; '.join(errors)}"
        logger.error(f"All providers failed streaming. {err_msg}")
        yield {"type": "error", "error": err_msg}

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
