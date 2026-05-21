from __future__ import annotations

from typing import Any, Dict, List, Optional

from duckduckgo_search import DDGS

from .skill_base import BaseSkill, SkillResult, skill_action


class WebSearchSkill(BaseSkill):
    name = "web_search"
    description = "Search the web for real-time information using DuckDuckGo."

    def configure(self, config: Dict[str, Any] = {}) -> bool:
        self._configured = True
        return True

    @skill_action(
        description="Search the web for information. Returns title, snippet, and URL for top results.",
        params={
            "query": {"type": "string", "description": "Search query."},
            "max_results": {"type": "integer", "description": "Number of results to return (default 3)."},
        },
        required=["query"],
    )
    async def search_web(self, query: str, max_results: int = 3) -> SkillResult:
        try:
            import asyncio
            def _ddgs_run():
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=max_results))

            results = await asyncio.to_thread(_ddgs_run)
            if not results:
                return SkillResult.ok(message="No results found.", data={"results": []})
            formatted = []
            for r in results:
                formatted.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "url": r.get("href", ""),
                })
            return SkillResult.ok(
                message=f"Found {len(formatted)} results.",
                data={"results": formatted},
            )
        except Exception as e:
            return SkillResult.fail(f"Web search failed: {e}")
