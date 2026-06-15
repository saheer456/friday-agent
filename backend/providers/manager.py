import asyncio
import logging
import os
import re
import time
from typing import Any, AsyncIterator, Optional

from .base import BaseProvider, ProviderConfig, ProviderResponse, ProviderStatus
from .groq import GroqProvider
from .openrouter import OpenRouterProvider
from .cerebras import CerebrasProvider
from .ollama import OllamaProvider
from .nvidia import NvidiaProvider

logger = logging.getLogger("ProviderManager")


class ProviderManager:
    def __init__(self):
        self._providers: dict[str, BaseProvider] = {}
        self._fallback_order: list[str] = []
        self._rate_limiters: dict[str, float] = {}
        self._health_cache: dict[str, tuple[bool, float]] = {}
        self._rate_limited_until: dict[str, float] = {}
        self._usage_stats: dict[str, dict] = {}

    def _record_call(self, provider_name: str, duration: float, is_error: bool) -> None:
        if provider_name not in self._usage_stats:
            self._usage_stats[provider_name] = {"calls": 0, "errors": 0, "total_latency_ms": 0.0}
        self._usage_stats[provider_name]["calls"] += 1
        if is_error:
            self._usage_stats[provider_name]["errors"] += 1
        self._usage_stats[provider_name]["total_latency_ms"] += duration * 1000.0

    def get_usage_stats(self) -> dict[str, dict]:
        return self._usage_stats

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

        # ── NVIDIA Nemotron (primary when key present) ────────────────────────
        nvidia_key = (os.getenv("NVIDIA_API_KEY") or "").strip()
        if self.is_key_usable(nvidia_key) and "nvidia" not in self._providers:
            self.register("nvidia", NvidiaProvider())

        # ── Groq (standby / fallback) ─────────────────────────────────────────
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
            for p in ["nvidia", "groq", "cerebras", "openrouter", "ollama"]:
                if p not in order:
                    order.append(p)
            self.set_fallback_order(order)

        logger.debug(
            "[ProviderManager] Discovery complete providers=%s fallback_order=%s preferred=%s",
            sorted(self._providers.keys()),
            self._fallback_order,
            preferred or "<auto>",
        )

        # Auto fallback priority: NVIDIA → Groq → others
        if not preferred:
            priority = ["nvidia", "groq", "cerebras", "openrouter", "ollama"]
            order = [p for p in priority if p in self._providers]
            for p in self._fallback_order:
                if p not in order:
                    order.append(p)
            self._fallback_order = order

        logger.info(
            "[ProviderManager] Active fallback order: %s",
            self._fallback_order,
        )

    def _check_rate_limit(self, provider_name: str) -> bool:
        last_call = self._rate_limiters.get(provider_name, 0.0)
        now = time.monotonic()
        if now - last_call < 0.25:
            return False
        self._rate_limiters[provider_name] = now
        return True

    def _parse_retry_after(self, error_msg: str) -> float:
        match = re.search(r"try\s+again\s+in\s+(\d+(?:\.\d+)?)\s*(?:s|sec|second|seconds)?", error_msg, re.IGNORECASE)
        if match:
            return float(match.group(1))
            
        match = re.search(r"retry[-_]after\b\s*(?::|=)?\s*(\d+(?:\.\d+)?)", error_msg, re.IGNORECASE)
        if match:
            return float(match.group(1))
            
        match = re.search(r"limit\s+reset\s+in\s+(\d+(?:\.\d+)?)\s*(?:s|sec|second|seconds)?", error_msg, re.IGNORECASE)
        if match:
            return float(match.group(1))
            
        return 60.0

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
                remaining = until - time.monotonic()
                if remaining > 0:
                    logger.info(
                        "[ProviderManager] Skipping rate-limited provider=%s (%.0fs remaining)",
                        provider_name, remaining,
                    )
                    errors.append(f"{provider_name}: rate-limited ({remaining:.0f}s remaining)")
                    continue
                provider.status = ProviderStatus.HEALTHY

            while not self._check_rate_limit(provider_name):
                await asyncio.sleep(0.05)

            for attempt in range(provider.config.max_retries):
                t0 = time.monotonic()
                try:
                    result = await provider.chat(messages, tools=tools, **kwargs)
                    duration = time.monotonic() - t0
                    self._record_call(provider_name, duration, is_error=False)
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
                    duration = time.monotonic() - t0
                    self._record_call(provider_name, duration, is_error=True)
                    err_str = str(e)
                    err_msg = f"{provider_name}({provider.config.model}): {e}"
                    logger.warning(f"[ProviderManager] {provider_name} attempt {attempt + 1} failed: {e}")

                    if "404" in err_str:
                        provider.status = ProviderStatus.UNHEALTHY
                        errors.append(err_msg + " [model/endpoint not found — check model name]")
                        break

                    if "429" in err_str or "rate" in err_str.lower():
                        provider.status = ProviderStatus.RATE_LIMITED
                        cooldown = self._parse_retry_after(err_str)
                        self._rate_limited_until[provider_name] = time.monotonic() + cooldown
                        logger.warning(
                            "[ProviderManager] %s rate-limited, cooldown=%.0fs",
                            provider_name, cooldown,
                        )
                        wait = min(2 ** (attempt + 1), cooldown)
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
                remaining = until - time.monotonic()
                if remaining > 0:
                    logger.info(
                        "[ProviderManager] Skipping rate-limited provider=%s (%.0fs remaining)",
                        provider_name, remaining,
                    )
                    errors.append(f"{provider_name}: rate-limited ({remaining:.0f}s remaining)")
                    continue
                provider.status = ProviderStatus.HEALTHY

            while not self._check_rate_limit(provider_name):
                await asyncio.sleep(0.05)

            for attempt in range(provider.config.max_retries):
                t0 = time.monotonic()
                try:
                    text_chunks = 0
                    tool_chunks = 0
                    async for event in provider.stream(messages, tools=tools, **kwargs):
                        if event.get("type") == "error":
                            duration = time.monotonic() - t0
                            self._record_call(provider_name, duration, is_error=True)
                            err_detail = event['error']
                            errors.append(f"{provider_name}({provider.config.model}): {err_detail}")
                            logger.debug(
                                "[ProviderManager] Stream provider=%s returned error event: %s",
                                provider_name,
                                err_detail,
                            )
                            yield event
                            break
                        if event.get("type") == "text":
                            text_chunks += 1
                        elif event.get("type") == "tool_call":
                            tool_chunks += 1
                        yield event
                        if event.get("type") == "done":
                            duration = time.monotonic() - t0
                            self._record_call(provider_name, duration, is_error=False)
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
                    duration = time.monotonic() - t0
                    self._record_call(provider_name, duration, is_error=True)
                    err_str = str(e)
                    err_msg = f"{provider_name}({provider.config.model}): {e}"
                    logger.warning(f"[ProviderManager] {provider_name} stream attempt {attempt + 1} failed: {e}")

                    if "404" in err_str:
                        provider.status = ProviderStatus.UNHEALTHY
                        errors.append(err_msg + " [model/endpoint not found — check model name]")
                        break

                    if "429" in err_str or "rate" in err_str.lower():
                        provider.status = ProviderStatus.RATE_LIMITED
                        cooldown = self._parse_retry_after(err_str)
                        self._rate_limited_until[provider_name] = time.monotonic() + cooldown
                        logger.warning(
                            "[ProviderManager] %s stream rate-limited, cooldown=%.0fs",
                            provider_name, cooldown,
                        )
                        wait = min(2 ** (attempt + 1), cooldown)
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
