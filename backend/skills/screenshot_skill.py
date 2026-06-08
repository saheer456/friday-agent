from __future__ import annotations

import base64
import io
import os
import httpx
from typing import Any, Dict

from .skill_base import BaseSkill, SkillResult, skill_action
from .code_skill import _api_config


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
        permissions=["screenshot:capture"]
    )
    async def capture_screenshot(self) -> SkillResult:
        import asyncio
        def _grab():
            from PIL import ImageGrab
            return ImageGrab.grab()

        try:
            img = await asyncio.to_thread(_grab)
        except (ImportError, OSError):
            return SkillResult.fail("Screenshot not supported on this platform.")

        try:
            # Resize to max 1280px width to reduce latency and API token usage
            max_width = 1280
            if img.width > max_width:
                aspect = img.height / img.width
                new_height = int(max_width * aspect)
                # PIL.Image.Resampling.LANCZOS or default
                img = img.resize((max_width, new_height))

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)  # JPEG is smaller than PNG
            b64 = base64.b64encode(buf.getvalue()).decode()
            
            url, api_key, model = _api_config()
            # If using Groq, override to their standard vision model
            if "api.groq.com" in url.lower():
                model = "llama-3.2-11b-vision-preview"

            payload = {
                "model": model,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": "Describe what is on this screen concisely for a voice assistant response."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ]}],
                "max_tokens": 512,
            }
            
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    url,
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
