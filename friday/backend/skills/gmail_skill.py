"""
gmail_skill.py — Gmail Skill
==============================
Send and read emails via the Gmail API.
"""
from __future__ import annotations

import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any, Dict, List, Optional

from .skill_base import BaseSkill, SkillResult, skill_action
from .google_auth import get_google_service, is_google_configured


class GmailSkill(BaseSkill):
    """Full Gmail integration — send and read emails."""

    name        = "gmail"
    description = (
        "Send and read emails via Gmail. "
        "Use this whenever the user asks to send an email, check inbox, or read mail."
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

    # ── Actions ────────────────────────────────────────────────────────────────

    @skill_action(
        description="Send an email via Gmail.",
        params={
            "to":      {"type": "string", "description": "Recipient email address."},
            "subject": {"type": "string", "description": "Email subject line."},
            "body":    {"type": "string", "description": "Email body (plain text or HTML)."},
            "cc":      {"type": "string", "description": "CC recipients, comma-separated (optional)."},
            "bcc":     {"type": "string", "description": "BCC recipients, comma-separated (optional)."},
        },
        required=["to", "subject", "body"],
    )
    def send_email(self, to: str, subject: str, body: str, cc: str = "", bcc: str = "") -> SkillResult:
        try:
            msg = MIMEMultipart()
            msg["to"] = to
            msg["subject"] = subject
            if cc:
                msg["cc"] = cc
            if bcc:
                msg["bcc"] = bcc
            msg.attach(MIMEText(body, "plain"))

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
        description="Read recent emails from the inbox.",
        params={
            "max_results": {"type": "integer", "description": "Max emails to return (default 5)."},
            "unread_only": {"type": "boolean", "description": "Only return unread emails (default true)."},
        },
        required=[],
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
