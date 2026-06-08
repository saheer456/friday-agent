from __future__ import annotations

import os
import re
import urllib.parse
import asyncio
from pathlib import Path
from typing import Any, Dict

from youtube_transcript_api import YouTubeTranscriptApi
from .skill_base import BaseSkill, SkillResult, skill_action
from .. import rag


class YouTubeSkill(BaseSkill):
    name = "youtube"
    description = "Fetch transcripts, search videos, and retrieve information from YouTube."

    def configure(self, config: Dict[str, Any] = {}) -> bool:
        self._configured = True
        return True

    @skill_action(
        description="Fetch the transcript of a YouTube video, save it, and index it for future queries.",
        params={
            "url": {"type": "string", "description": "Full YouTube video URL."},
        },
        required=["url"],
        permissions=["youtube:read", "terminal:write"]
    )
    async def ingest_transcript(self, url: str) -> SkillResult:
        try:
            vid = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", url)
            if not vid:
                return SkillResult.invalid("Invalid YouTube URL.")
            
            # Fetch transcript asynchronously in a separate thread
            transcript = await asyncio.to_thread(YouTubeTranscriptApi.get_transcript, vid.group(1))
            text = " ".join(t["text"] for t in transcript)
            
            # Save to workspace
            data_dir = Path(__file__).resolve().parent.parent.parent / "data"
            web_dir = data_dir / "web"
            web_dir.mkdir(parents=True, exist_ok=True)
            fp = web_dir / f"youtube_{vid.group(1)}.md"
            fp.write_text(f"# YouTube: {url}\n\n{text}", encoding="utf-8")
            
            # Index into memory
            await asyncio.to_thread(rag.ingest_files)
            
            return SkillResult.ok(
                message=f"Ingested {len(text.split())} words from the YouTube video.",
                data={"words": len(text.split()), "file": fp.name},
            )
        except Exception as e:
            return SkillResult.fail(f"YouTube transcript ingest failed: {e}")

    @skill_action(
        description="Search for videos on YouTube. Returns titles, links, durations, and publishers.",
        params={
            "query": {"type": "string", "description": "Search query for YouTube videos."},
            "max_results": {"type": "integer", "description": "Number of videos to return (default 3)."},
        },
        required=["query"],
        permissions=["youtube:read"]
    )
    async def search_youtube(self, query: str, max_results: int = 3) -> SkillResult:
        try:
            from duckduckgo_search import AsyncDDGS
            # Search specifically on youtube.com domain
            async with AsyncDDGS() as ddgs:
                res = await ddgs.videos(f"site:youtube.com {query}", max_results=max_results)
                results = list(res)
            
            formatted = []
            for r in results:
                formatted.append({
                    "title": r.get("title", ""),
                    "url": r.get("content", r.get("embed_url", "")),
                    "duration": r.get("duration", ""),
                    "publisher": r.get("publisher", "YouTube"),
                })
            return SkillResult.ok(
                message=f"Found {len(formatted)} videos on YouTube.",
                data={"videos": formatted}
            )
        except Exception as e:
            return SkillResult.fail(f"YouTube search failed: {e}")

    @skill_action(
        description="Retrieve basic information (title, author, thumbnail) for a YouTube video URL using oEmbed.",
        params={
            "url": {"type": "string", "description": "Full YouTube video URL."},
        },
        required=["url"],
        permissions=["youtube:read"]
    )
    async def get_video_info(self, url: str) -> SkillResult:
        try:
            import httpx
            oembed_url = f"https://www.youtube.com/oembed?url={urllib.parse.quote(url)}&format=json"
            async with httpx.AsyncClient() as client:
                r = await client.get(oembed_url, timeout=5.0)
            if r.status_code == 200:
                data = r.json()
                return SkillResult.ok(
                    message="Video info retrieved.",
                    data={
                        "title": data.get("title"),
                        "author": data.get("author_name"),
                        "author_url": data.get("author_url"),
                        "thumbnail": data.get("thumbnail_url"),
                        "type": data.get("type")
                    }
                )
            else:
                return SkillResult.fail(f"Could not retrieve video info. oEmbed returned status {r.status_code}.")
        except Exception as e:
            return SkillResult.fail(f"Failed to get video info: {e}")
