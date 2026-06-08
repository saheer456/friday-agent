"""
gdocs_skill.py — Google Docs Skill
====================================
Create, read, update, and search Google Docs.
"""
from __future__ import annotations

import webbrowser
from typing import Any, Dict, Optional, List

from .skill_base import BaseSkill, SkillResult, skill_action
from .google_auth import get_google_service, is_google_configured


class GDocsSkill(BaseSkill):
    """Google Docs integration — create, read, update, and search documents."""

    name        = "gdocs"
    description = (
        "Create, read, update, and search Google Docs. "
        "Use this when the user wants to create a document, write notes, or edit/search existing docs."
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

    def health_check(self) -> bool:
        return is_google_configured()

    # ── Actions ────────────────────────────────────────────────────────────────

    @skill_action(
        description="Create a new Google Doc with a title and optional content.",
        params={
            "title":        {"type": "string", "description": "Document title."},
            "content":      {"type": "string", "description": "Text content to insert (optional)."},
            "open_browser": {"type": "boolean", "description": "Auto-open the created document in the browser (default true)."},
        },
        required=["title"],
        permissions=["gdocs:write"]
    )
    def create_doc(self, title: str, content: str = "", open_browser: bool = True) -> SkillResult:
        try:
            doc = self._docs_service().documents().create(
                body={"title": title}
            ).execute()

            doc_id = doc.get("documentId")
            doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"

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

            if open_browser:
                webbrowser.open(doc_url)

            return SkillResult.ok(
                message=f"Google Doc '{title}' created successfully.",
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
        permissions=["gdocs:read"]
    )
    def read_doc(self, doc_id: str) -> SkillResult:
        try:
            doc = self._docs_service().documents().get(documentId=doc_id).execute()
            title = doc.get("title", "Untitled")

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

    @skill_action(
        description="Update or append text content to an existing Google Doc.",
        params={
            "doc_id":       {"type": "string", "description": "The unique document ID."},
            "content":      {"type": "string", "description": "Text content to insert/append."},
            "append":       {"type": "boolean", "description": "If true, append to the end of document. Otherwise, insert at the beginning (default true)."},
            "open_browser": {"type": "boolean", "description": "Auto-open the document in the browser (default false)."},
        },
        required=["doc_id", "content"],
        permissions=["gdocs:write"]
    )
    def update_doc(self, doc_id: str, content: str, append: bool = True, open_browser: bool = False) -> SkillResult:
        try:
            doc_service = self._docs_service()
            doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
            
            if append:
                doc = doc_service.documents().get(documentId=doc_id).execute()
                body_content = doc.get("body", {}).get("content", [])
                
                end_index = 1
                if body_content:
                    end_index = body_content[-1].get("endIndex", 1) - 1
                    if end_index < 1:
                        end_index = 1
                        
                requests = [{
                    "insertText": {
                        "location": {"index": end_index},
                        "text": content,
                    }
                }]
            else:
                requests = [{
                    "insertText": {
                        "location": {"index": 1},
                        "text": content,
                    }
                }]
                
            doc_service.documents().batchUpdate(
                documentId=doc_id, body={"requests": requests}
            ).execute()
            
            if open_browser:
                webbrowser.open(doc_url)
                
            return SkillResult.ok(
                message="Google Doc updated successfully.",
                data={"doc_id": doc_id, "url": doc_url}
            )
        except Exception as e:
            return SkillResult.fail(f"Failed to update Google Doc: {e}")

    @skill_action(
        description="List the user's Google Docs from Google Drive.",
        params={
            "max_results": {"type": "integer", "description": "Max documents to return (default 10)."}
        },
        required=[],
        permissions=["gdocs:read"]
    )
    def list_docs(self, max_results: int = 10) -> SkillResult:
        try:
            q = "mimeType = 'application/vnd.google-apps.document' and trashed = false"
            results = self._drive_service().files().list(
                q=q,
                pageSize=max_results,
                fields="files(id, name, createdTime)"
            ).execute()
            
            files = results.get("files", [])
            docs_list = []
            for f in files:
                docs_list.append({
                    "id": f.get("id"),
                    "title": f.get("name"),
                    "created_time": f.get("createdTime"),
                    "url": f"https://docs.google.com/document/d/{f.get('id')}/edit"
                })
                
            return SkillResult.ok(
                message=f"Found {len(docs_list)} Google Docs.",
                data={"documents": docs_list}
            )
        except Exception as e:
            return SkillResult.fail(f"Failed to list Google Docs: {e}")

    @skill_action(
        description="Search for Google Docs by title keyword matching.",
        params={
            "query": {"type": "string", "description": "Search query keyword for document title."}
        },
        required=["query"],
        permissions=["gdocs:read"]
    )
    def search_docs(self, query: str) -> SkillResult:
        try:
            escaped_query = query.replace("'", "\\'")
            q = f"mimeType = 'application/vnd.google-apps.document' and name contains '{escaped_query}' and trashed = false"
            results = self._drive_service().files().list(
                q=q,
                pageSize=10,
                fields="files(id, name, createdTime)"
            ).execute()
            
            files = results.get("files", [])
            docs_list = []
            for f in files:
                docs_list.append({
                    "id": f.get("id"),
                    "title": f.get("name"),
                    "created_time": f.get("createdTime"),
                    "url": f"https://docs.google.com/document/d/{f.get('id')}/edit"
                })
                
            return SkillResult.ok(
                message=f"Found {len(docs_list)} matching Google Docs.",
                data={"documents": docs_list}
            )
        except Exception as e:
            return SkillResult.fail(f"Failed to search Google Docs: {e}")
