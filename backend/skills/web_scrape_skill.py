from __future__ import annotations

import time
import random
import httpx
from bs4 import BeautifulSoup
from readability import Document
from typing import Any, Dict, Optional

from .skill_base import BaseSkill, SkillResult, skill_action

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0"
]

# Simple In-Memory Scraping Cache: {url: (timestamp, full_extracted_text)}
_SCRAPE_CACHE: Dict[str, tuple[float, str]] = {}
_CACHE_TTL_SECONDS = 300.0  # 5 minutes


class WebScrapeSkill(BaseSkill):
    name = "web_scrape"
    description = "Fetch and extract readable text from a URL or PDF."

    def configure(self, config: Dict[str, Any] = {}) -> bool:
        self._configured = True
        return True

    @skill_action(
        description="Scrape a URL and extract its main readable content as text, with PDF support.",
        params={
            "url": {"type": "string", "description": "The URL to scrape."},
            "max_chars": {"type": "integer", "description": "Maximum characters to return (default 5000)."},
        },
        required=["url"],
        permissions=["web_scrape:read"]
    )
    async def scrape_url(self, url: str, max_chars: int = 5000) -> SkillResult:
        try:
            url_str = url.strip()
            now = time.time()
            
            # Check Cache
            if url_str in _SCRAPE_CACHE:
                cached_time, cached_content = _SCRAPE_CACHE[url_str]
                if now - cached_time < _CACHE_TTL_SECONDS:
                    truncated = len(cached_content) > max_chars
                    text = cached_content[:max_chars]
                    return SkillResult.ok(
                        message=f"Retrieved scraped content from cache for {url_str}.",
                        data={"content": text, "url": url_str, "truncated": truncated, "cached": True},
                    )

            # Fetch URL
            headers = {"User-Agent": random.choice(_USER_AGENTS)}
            async with httpx.AsyncClient() as client:
                r = await client.get(url_str, headers=headers, follow_redirects=True, timeout=12.0)
            r.raise_for_status()

            full_text = ""
            # Check if PDF Content
            url_lower = url_str.lower()
            is_pdf = url_lower.endswith(".pdf") or "application/pdf" in r.headers.get("content-type", "").lower()
            if is_pdf:
                try:
                    import io
                    try:
                        import pypdf
                        reader = pypdf.PdfReader(io.BytesIO(r.content))
                        full_text = "\n".join(page.extract_text() for page in reader.pages)
                    except ImportError:
                        import PyPDF2
                        reader = PyPDF2.PdfReader(io.BytesIO(r.content))
                        full_text = "\n".join(page.extract_text() for page in reader.pages)
                except Exception as pdf_err:
                    return SkillResult.fail(f"Failed to parse PDF from {url_str}: {pdf_err}")
            else:
                doc = Document(r.text)
                soup = BeautifulSoup(doc.summary(), "html.parser")
                for tag in soup(["script", "style"]):
                    tag.extract()
                full_text = soup.get_text(separator="\n", strip=True)

            # Cache the full content
            if full_text:
                _SCRAPE_CACHE[url_str] = (now, full_text)

            truncated = len(full_text) > max_chars
            text = full_text[:max_chars]

            return SkillResult.ok(
                message=f"Scraped {len(text)} chars from {url_str}.",
                data={"content": text, "url": url_str, "truncated": truncated},
            )
        except httpx.TimeoutException:
            return SkillResult.fail(f"Scraping timed out for {url}.")
        except Exception as e:
            return SkillResult.fail(f"Scraping failed: {e}")
