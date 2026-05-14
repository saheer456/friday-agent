"""
gdocs_skill.py — Google Docs Skill
====================================
Create and read Google Docs.
"""
from __future__ import annotations

import webbrowser
from typing import Any, Dict, Optional

from .skill_base import BaseSkill, SkillResult, skill_action
from .google_auth import get_google_service, is_google_configured


class GDocsSkill(BaseSkill):
    """Google Docs integration — create and read documents."""

    name        = "gdocs"
    description = (
        "Create and read Google Docs. "
        "Use this when the user wants to create a document, write notes, or read an existing doc."
    )

    def __init__(self) -> None:
        super().__init__()
        if is_google_configured():
            self.configure()

    def configure(self, config: Dict[str, Any] = {}) -> bool:
        self._configured = True
        return True

    def _docs_service(self):
        return get_google_service("docs", "v1")

    def _drive_service(self):
        return get_google_service("drive", "v3")

    # ── Actions ────────────────────────────────────────────────────────────────

    @skill_action(
        description="Create a new Google Doc with a title and optional content. Opens it in the browser.",
        params={
            "title":   {"type": "string", "description": "Document title."},
            "content": {"type": "string", "description": "Text content to insert (optional)."},
        },
        required=["title"],
    )
    def create_doc(self, title: str, content: str = "") -> SkillResult:
        try:
            doc = self._docs_service().documents().create(
                body={"title": title}
            ).execute()

            doc_id = doc.get("documentId")
            doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"

            # Insert content if provided
            if content:
                requests = [{
                    "insertText": {
                        "location": {"index": 1},
                        "text": content,
                    }
                }]
                self._docs_service().documents().batchUpdate(
                    documentId=doc_id, body={"requests": requests}
                ).execute()

            webbrowser.open(doc_url)

            return SkillResult.ok(
                message=f"Google Doc '{title}' created and opened in browser.",
                data={"doc_id": doc_id, "url": doc_url, "title": title},
            )
        except Exception as e:
            return SkillResult.fail(f"Google Docs error: {e}")

    @skill_action(
        description="Read the text content of an existing Google Doc by its document ID.",
        params={
            "doc_id": {"type": "string", "description": "Google Doc document ID."},
        },
        required=["doc_id"],
    )
    def read_doc(self, doc_id: str) -> SkillResult:
        try:
            doc = self._docs_service().documents().get(documentId=doc_id).execute()
            title = doc.get("title", "Untitled")

            # Extract plain text from the document body
            body = doc.get("body", {})
            text_parts = []
            for element in body.get("content", []):
                para = element.get("paragraph", {})
                for pe in para.get("elements", []):
                    text_run = pe.get("textRun", {})
                    if text_run.get("content"):
                        text_parts.append(text_run["content"])

            content = "".join(text_parts).strip()
            return SkillResult.ok(
                message=f"Read document '{title}' ({len(content)} chars).",
                data={"title": title, "content": content[:8000], "doc_id": doc_id},
            )
        except Exception as e:
            return SkillResult.fail(f"Google Docs read error: {e}")
