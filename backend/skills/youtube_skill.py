from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict

from youtube_transcript_api import YouTubeTranscriptApi

from .skill_base import BaseSkill, SkillResult, skill_action

from .. import rag


class YouTubeSkill(BaseSkill):
    name = "youtube"
    description = "Fetch the transcript of a YouTube video and ingest it into FRIDAY's memory."

    def configure(self, config: Dict[str, Any] = {}) -> bool:
        self._configured = True
        return True

    @skill_action(
        description="Fetch the transcript of a YouTube video, save it, and index it for future queries.",
        params={
            "url": {"type": "string", "description": "Full YouTube video URL."},
        },
        required=["url"],
    )
    def ingest_transcript(self, url: str) -> SkillResult:
        try:
            vid = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", url)
            if not vid:
                return SkillResult.invalid("Invalid YouTube URL.")
            transcript = YouTubeTranscriptApi.get_transcript(vid.group(1))
            text = " ".join(t["text"] for t in transcript)
            data_dir = Path(__file__).resolve().parent.parent.parent / "data"
            web_dir = data_dir / "web"
            web_dir.mkdir(parents=True, exist_ok=True)
            fp = web_dir / f"youtube_{vid.group(1)}.md"
            fp.write_text(f"# YouTube: {url}\n\n{text}", encoding="utf-8")
            rag.ingest_files()
            return SkillResult.ok(
                message=f"Ingested {len(text.split())} words from the YouTube video.",
                data={"words": len(text.split()), "file": fp.name},
            )
        except Exception as e:
            return SkillResult.fail(f"YouTube ingest failed: {e}")
