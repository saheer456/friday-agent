"""
gmail_skill.py — Gmail Skill
==============================
Send, read, search, and reply to emails via the Gmail API.
"""
from __future__ import annotations

import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any, Dict, List, Optional

from .skill_base import BaseSkill, SkillResult, skill_action
from .google_auth import get_google_service, is_google_configured


class GmailSkill(BaseSkill):
    """Full Gmail integration — send, read, search, and reply to emails."""

    name        = "gmail"
    description = (
        "Send and read emails via Gmail. "
        "Use this whenever the user asks to send an email, check inbox, read mail, or reply."
    )

    def __init__(self) -> None:
        super().__init__()
        if is_google_configured():
            self.configure()

    def configure(self, config: Dict[str, Any] = {}) -> bool:
        self._configured = True
        return True

    def _service(self):
        return get_google_service("gmail", "v1")

    def health_check(self) -> bool:
        return is_google_configured()

    # ── Actions ────────────────────────────────────────────────────────────────

    @skill_action(
        description="Send an email via Gmail.",
        params={
            "to":      {"type": "string", "description": "Recipient email address."},
            "subject": {"type": "string", "description": "Email subject line."},
            "body":    {"type": "string", "description": "Email body (plain text or HTML)."},
            "cc":      {"type": "string", "description": "CC recipients, comma-separated (optional)."},
            "bcc":     {"type": "string", "description": "BCC recipients, comma-separated (optional)."},
            "is_html": {"type": "boolean", "description": "Send as HTML format instead of plain text (optional)."},
        },
        required=["to", "subject", "body"],
        permissions=["gmail:write"]
    )
    def send_email(self, to: str, subject: str, body: str, cc: str = "", bcc: str = "", is_html: bool = False) -> SkillResult:
        try:
            msg = MIMEMultipart()
            msg["to"] = to
            msg["subject"] = subject
            if cc:
                msg["cc"] = cc
            if bcc:
                msg["bcc"] = bcc
            
            sub_type = "html" if (is_html or "<html>" in body.lower() or "<div" in body.lower() or "<p>" in body.lower()) else "plain"
            msg.attach(MIMEText(body, sub_type))

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            sent = self._service().users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()

            return SkillResult.ok(
                message=f"Email sent to {to}.",
                data={"message_id": sent.get("id"), "to": to, "subject": subject},
            )
        except Exception as e:
            return SkillResult.fail(f"Gmail send failed: {e}")

    @skill_action(
        description="Read recent emails from the inbox. Returns subject, snippet, and sender.",
        params={
            "max_results": {"type": "integer", "description": "Max emails to return (default 5)."},
            "unread_only": {"type": "boolean", "description": "Only return unread emails (default true)."},
        },
        required=[],
        permissions=["gmail:read"]
    )
    def read_inbox(self, max_results: int = 5, unread_only: bool = True) -> SkillResult:
        try:
            query = "is:unread" if unread_only else ""
            result = self._service().users().messages().list(
                userId="me", q=query, maxResults=max_results
            ).execute()

            messages = result.get("messages", [])
            emails: List[Dict] = []

            for msg_ref in messages:
                msg = self._service().users().messages().get(
                    userId="me", id=msg_ref["id"], format="metadata",
                    metadataHeaders=["From", "Subject", "Date"]
                ).execute()

                headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                emails.append({
                    "id":      msg_ref["id"],
                    "from":    headers.get("From", "?"),
                    "subject": headers.get("Subject", "(no subject)"),
                    "date":    headers.get("Date", "?"),
                    "snippet": msg.get("snippet", "")[:150],
                })

            return SkillResult.ok(
                message=f"Found {len(emails)} emails.",
                data={"emails": emails},
            )
        except Exception as e:
            return SkillResult.fail(f"Gmail read failed: {e}")

    @skill_action(
        description="Read the full body text of a specific email message by ID.",
        params={
            "message_id": {"type": "string", "description": "The unique ID of the Gmail message."}
        },
        required=["message_id"],
        permissions=["gmail:read"]
    )
    def read_email(self, message_id: str) -> SkillResult:
        try:
            msg = self._service().users().messages().get(
                userId="me", id=message_id, format="full"
            ).execute()

            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            
            # Extract plain text recursively
            body = ""
            payload = msg.get("payload", {})
            parts = payload.get("parts")

            def _extract_body(parts_list) -> str:
                for part in parts_list:
                    mime = part.get("mimeType", "")
                    b_data = part.get("body", {}).get("data", "")
                    if mime == "text/plain" and b_data:
                        return base64.urlsafe_b64decode(b_data).decode("utf-8", errors="replace")
                    elif part.get("parts"):
                        res = _extract_body(part["parts"])
                        if res:
                            return res
                return ""

            if parts:
                body = _extract_body(parts)
            else:
                body_data = payload.get("body", {}).get("data", "")
                if body_data:
                    body = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")

            if not body:
                body = msg.get("snippet", "")

            return SkillResult.ok(
                message="Email content retrieved.",
                data={
                    "id": message_id,
                    "from": headers.get("From", "?"),
                    "to": headers.get("To", "?"),
                    "subject": headers.get("Subject", "(no subject)"),
                    "date": headers.get("Date", "?"),
                    "body": body
                }
            )
        except Exception as e:
            return SkillResult.fail(f"Failed to read email {message_id}: {e}")

    @skill_action(
        description="Search for emails using a Gmail search query (e.g. 'from:john invoice').",
        params={
            "query": {"type": "string", "description": "Gmail search query string."},
            "max_results": {"type": "integer", "description": "Max matching emails to return (default 5)."},
        },
        required=["query"],
        permissions=["gmail:read"]
    )
    def search_email(self, query: str, max_results: int = 5) -> SkillResult:
        try:
            result = self._service().users().messages().list(
                userId="me", q=query, maxResults=max_results
            ).execute()

            messages = result.get("messages", [])
            emails: List[Dict] = []

            for msg_ref in messages:
                msg = self._service().users().messages().get(
                    userId="me", id=msg_ref["id"], format="metadata",
                    metadataHeaders=["From", "Subject", "Date"]
                ).execute()

                headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                emails.append({
                    "id":      msg_ref["id"],
                    "from":    headers.get("From", "?"),
                    "subject": headers.get("Subject", "(no subject)"),
                    "date":    headers.get("Date", "?"),
                    "snippet": msg.get("snippet", "")[:150],
                })

            return SkillResult.ok(
                message=f"Found {len(emails)} matching emails.",
                data={"emails": emails}
            )
        except Exception as e:
            return SkillResult.fail(f"Email search failed: {e}")

    @skill_action(
        description="Reply to an email thread by composing and sending a message in reply.",
        params={
            "message_id": {"type": "string", "description": "The unique ID of the message to reply to."},
            "body":       {"type": "string", "description": "The body content of the reply."},
        },
        required=["message_id", "body"],
        permissions=["gmail:write"]
    )
    def reply_to_email(self, message_id: str, body: str) -> SkillResult:
        try:
            orig = self._service().users().messages().get(
                userId="me", id=message_id, format="metadata",
                metadataHeaders=["Message-ID", "Subject", "From"]
            ).execute()

            thread_id = orig.get("threadId")
            headers = {h["name"]: h["value"] for h in orig.get("payload", {}).get("headers", [])}
            
            orig_msg_id = headers.get("Message-ID")
            orig_subject = headers.get("Subject", "")
            orig_from = headers.get("From")

            subject = orig_subject
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"

            msg = MIMEMultipart()
            msg["to"] = orig_from
            msg["subject"] = subject
            if orig_msg_id:
                msg["In-Reply-To"] = orig_msg_id
                msg["References"] = orig_msg_id
            
            msg.attach(MIMEText(body, "plain"))
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

            sent = self._service().users().messages().send(
                userId="me", body={"raw": raw, "threadId": thread_id}
            ).execute()

            return SkillResult.ok(
                message=f"Reply sent to {orig_from}.",
                data={"message_id": sent.get("id"), "thread_id": thread_id}
            )
        except Exception as e:
            return SkillResult.fail(f"Reply to email failed: {e}")
