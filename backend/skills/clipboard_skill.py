from __future__ import annotations

import pyperclip
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .skill_base import BaseSkill, SkillResult, skill_action


class ClipboardSkill(BaseSkill):
    name = "clipboard"
    description = "Read and write the contents of the system clipboard (text and images)."

    def configure(self, config: Dict[str, Any] = {}) -> bool:
        self._configured = True
        return True

    @skill_action(
        description="Read the current text content of the system clipboard.",
        params={},
        required=[],
        permissions=["clipboard:read"]
    )
    def read_clipboard(self) -> SkillResult:
        try:
            raw_text = pyperclip.paste()
            text = raw_text[:4000]
            truncated = len(raw_text) > 4000
            return SkillResult.ok(
                message="Clipboard read.",
                data={"text": text, "truncated": truncated},
            )
        except Exception as e:
            return SkillResult.fail(f"Clipboard read failed: {e}")

    @skill_action(
        description="Write text content back to the system clipboard.",
        params={
            "text": {"type": "string", "description": "Text to write to the clipboard."}
        },
        required=["text"],
        permissions=["clipboard:write"]
    )
    def write_clipboard(self, text: str) -> SkillResult:
        try:
            pyperclip.copy(text)
            return SkillResult.ok(
                message="Text copied to clipboard.",
                data={"chars_copied": len(text)}
            )
        except Exception as e:
            return SkillResult.fail(f"Clipboard write failed: {e}")

    @skill_action(
        description="Grab an image from the system clipboard, save it to the workspace, and return metadata.",
        params={
            "save_path": {"type": "string", "description": "Destination file path to save the clipboard image (optional)."}
        },
        required=[],
        permissions=["clipboard:read", "terminal:write"]
    )
    def read_clipboard_image(self, save_path: Optional[str] = None) -> SkillResult:
        try:
            from PIL import ImageGrab
            img = ImageGrab.grabclipboard()
            if img is None:
                return SkillResult.fail("No image found in clipboard.")
            
            # Resolve workspace path
            workspace_dir = Path(__file__).resolve().parent.parent.parent
            if save_path:
                p = Path(save_path).expanduser()
                if not p.is_absolute():
                    p = workspace_dir / p
                p = p.resolve()
                if not p.is_relative_to(workspace_dir):
                    return SkillResult.fail("Save path is outside of workspace.")
            else:
                data_dir = workspace_dir / "data" / "clipboard"
                data_dir.mkdir(parents=True, exist_ok=True)
                p = data_dir / f"clip_image_{int(time.time())}.png"

            # Check if PIL image type is valid to save
            if hasattr(img, "save"):
                img.save(p, format="PNG")
                return SkillResult.ok(
                    message=f"Clipboard image saved to {p.name}.",
                    data={"saved_path": str(p), "size": img.size}
                )
            else:
                # Sometimes grabclipboard returns a list of files (if files were copied)
                return SkillResult.fail(f"Clipboard content is not a PIL image. Content: {img}")
        except Exception as e:
            return SkillResult.fail(f"Clipboard image grab failed: {e}")
