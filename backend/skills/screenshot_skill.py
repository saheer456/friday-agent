from __future__ import annotations

import base64
import io
import os
import httpx
from typing import Any, Dict

from .skill_base import BaseSkill, SkillResult, skill_action


class ScreenshotSkill(BaseSkill):
    name = "screenshot"
    description = "Capture a screenshot of the screen and use AI to describe what's on it."

    def configure(self, config: Dict[str, Any] = {}) -> bool:
        self._configured = True
        return True

    @skill_action(
        description="Take a screenshot and describe what's visible on the screen using AI vision.",
        params={},
        required=[],
    )
    def capture_screenshot(self) -> SkillResult:
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab()
        except (ImportError, OSError):
            return SkillResult.fail("Screenshot not supported on this platform.")

        try:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            api_key = os.getenv("GROQ_API_KEY", "")
            payload = {
                "model": "meta-llama/llama-4-scout-17b-16e-instruct",
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": "Describe what is on this screen concisely for a voice assistant response."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ]}],
                "max_tokens": 512,
            }
            r = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=30.0,
            )
            r.raise_for_status()
            desc = r.json()["choices"][0]["message"]["content"]
            return SkillResult.ok(
                message="Screenshot captured and analysed.",
                data={"description": desc},
            )
        except Exception as e:
            return SkillResult.fail(f"Screenshot analysis failed: {e}")
