from __future__ import annotations

import httpx
from bs4 import BeautifulSoup
from readability import Document
from typing import Any, Dict

from .skill_base import BaseSkill, SkillResult, skill_action

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


class WebScrapeSkill(BaseSkill):
    name = "web_scrape"
    description = "Fetch and extract the main readable content from a URL."

    def configure(self, config: Dict[str, Any] = {}) -> bool:
        self._configured = True
        return True

    @skill_action(
        description="Scrape a URL and extract its main readable content as text.",
        params={
            "url": {"type": "string", "description": "The URL to scrape."},
            "max_chars": {"type": "integer", "description": "Maximum characters to return (default 3000)."},
        },
        required=["url"],
    )
    def scrape_url(self, url: str, max_chars: int = 3000) -> SkillResult:
        try:
            r = httpx.get(url, headers=_HEADERS, follow_redirects=True, timeout=10.0)
            r.raise_for_status()
            doc = Document(r.text)
            soup = BeautifulSoup(doc.summary(), "html.parser")
            for tag in soup(["script", "style"]):
                tag.extract()
            text = soup.get_text(separator="\n", strip=True)
            if len(text) > max_chars:
                text = text[:max_chars] + "... [Content Truncated]"
            return SkillResult.ok(
                message=f"Scraped {len(text)} chars from {url}.",
                data={"content": text, "url": url},
            )
        except httpx.TimeoutException:
            return SkillResult.fail(f"Scraping timed out for {url}.")
        except Exception as e:
            return SkillResult.fail(f"Scraping failed: {e}")
