from __future__ import annotations

import urllib.parse
from typing import Any, Dict, List, Optional

try:
    from duckduckgo_search import AsyncDDGS
except ImportError:
    AsyncDDGS = None

from .skill_base import BaseSkill, SkillResult, skill_action


class WebSearchSkill(BaseSkill):
    name = "web_search"
    description = "Search the web for real-time information, news, and images using DuckDuckGo with Wikipedia fallback."

    def configure(self, config: Dict[str, Any] = {}) -> bool:
        self._configured = True
        return True

    async def _wikipedia_fallback(self, query: str, limit: int) -> List[Dict[str, str]]:
        """Fallback Wikipedia search when DuckDuckGo is blocked or rate-limited."""
        import httpx
        try:
            encoded_query = urllib.parse.quote(query)
            wiki_url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={encoded_query}&limit={limit}&namespace=0&format=json"
            async with httpx.AsyncClient() as client:
                resp = await client.get(wiki_url, timeout=5.0)
                if resp.status_code == 200:
                    data = resp.json()
                    if len(data) >= 4:
                        results = []
                        for idx in range(len(data[1])):
                            results.append({
                                "title": data[1][idx],
                                "snippet": data[2][idx],
                                "url": data[3][idx]
                            })
                        return results
        except Exception:
            pass
        return []

    @skill_action(
        description="Search the web for information. Returns title, snippet, and URL for top results.",
        params={
            "query": {"type": "string", "description": "Search query."},
            "max_results": {"type": "integer", "description": "Number of results to return (default 3)."},
        },
        required=["query"],
        permissions=["web_search:read"]
    )
    async def search_web(self, query: str, max_results: int = 3) -> SkillResult:
        try:
            results = []
            try:
                if AsyncDDGS is not None:
                    async with AsyncDDGS() as ddgs:
                        res = await ddgs.text(query, max_results=max_results)
                        results = list(res)
                else:
                    import asyncio
                    def _run_sync():
                        from duckduckgo_search import DDGS
                        with DDGS() as ddgs:
                            return list(ddgs.text(query, max_results=max_results))
                    results = await asyncio.to_thread(_run_sync)
            except Exception as ddg_err:
                # If DuckDuckGo rate-limits or fails, attempt Wikipedia fallback
                results = await self._wikipedia_fallback(query, max_results)
                if not results:
                    raise ddg_err

            formatted = []
            for r in results:
                formatted.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("body", r.get("snippet", "")),
                    "url": r.get("href", r.get("url", "")),
                })
            return SkillResult.ok(
                message=f"Found {len(formatted)} results.",
                data={"results": formatted},
            )
        except Exception as e:
            return SkillResult.fail(f"Web search failed: {e}")

    @skill_action(
        description="Search the web for news articles. Returns article title, snippet, date, source, and URL.",
        params={
            "query": {"type": "string", "description": "News search query."},
            "max_results": {"type": "integer", "description": "Number of news articles to return (default 3)."},
        },
        required=["query"],
        permissions=["web_search:read"]
    )
    async def search_news(self, query: str, max_results: int = 3) -> SkillResult:
        try:
            if AsyncDDGS is not None:
                async with AsyncDDGS() as ddgs:
                    res = await ddgs.news(query, max_results=max_results)
                    results = list(res)
            else:
                import asyncio
                def _run_sync():
                    from duckduckgo_search import DDGS
                    with DDGS() as ddgs:
                        return list(ddgs.news(query, max_results=max_results))
                results = await asyncio.to_thread(_run_sync)

            formatted = []
            for r in results:
                formatted.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "date": r.get("date", ""),
                    "source": r.get("source", ""),
                    "url": r.get("url", ""),
                })
            return SkillResult.ok(
                message=f"Found {len(formatted)} news results.",
                data={"results": formatted}
            )
        except Exception as e:
            return SkillResult.fail(f"News search failed: {e}")

    @skill_action(
        description="Search the web for images. Returns image title, image URL, source page URL, and thumbnail.",
        params={
            "query": {"type": "string", "description": "Image search query."},
            "max_results": {"type": "integer", "description": "Number of image results to return (default 3)."},
        },
        required=["query"],
        permissions=["web_search:read"]
    )
    async def search_images(self, query: str, max_results: int = 3) -> SkillResult:
        try:
            if AsyncDDGS is not None:
                async with AsyncDDGS() as ddgs:
                    res = await ddgs.images(query, max_results=max_results)
                    results = list(res)
            else:
                import asyncio
                def _run_sync():
                    from duckduckgo_search import DDGS
                    with DDGS() as ddgs:
                        return list(ddgs.images(query, max_results=max_results))
                results = await asyncio.to_thread(_run_sync)

            formatted = []
            for r in results:
                formatted.append({
                    "title": r.get("title", ""),
                    "image_url": r.get("image", ""),
                    "url": r.get("url", ""),
                    "thumbnail": r.get("thumbnail", ""),
                })
            return SkillResult.ok(
                message=f"Found {len(formatted)} image results.",
                data={"results": formatted}
            )
        except Exception as e:
            return SkillResult.fail(f"Image search failed: {e}")
