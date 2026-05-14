"""
google_auth.py — Shared Google OAuth2 Authentication
=====================================================
Handles OAuth2 flow for all Google Workspace APIs.
On first use, opens a browser window for consent.
Saves/refreshes tokens in data/google_token.json.

Usage:
    from backend.skills.google_auth import get_google_service
    calendar = get_google_service("calendar", "v3")
    gmail    = get_google_service("gmail", "v1")
"""
from __future__ import annotations

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# All scopes needed across every Google skill.
# Requested once on first auth; adding new scopes later
# will require the user to re-authenticate.
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_CREDS_FILE = _DATA_DIR / "google_credentials.json"
_TOKEN_FILE = _DATA_DIR / "google_token.json"

_cached_creds: Credentials | None = None


def _get_credentials() -> Credentials:
    """Load or create OAuth2 credentials. Opens browser on first use."""
    global _cached_creds

    if _cached_creds and _cached_creds.valid:
        return _cached_creds

    creds = None

    # Load saved token
    if _TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_FILE), SCOPES)

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None   # force re-auth

    # No valid creds — run full OAuth flow
    if not creds or not creds.valid:
        if not _CREDS_FILE.exists():
            raise FileNotFoundError(
                f"Google credentials not found at {_CREDS_FILE}.\n"
                "Download from Google Cloud Console → Credentials → OAuth 2.0 Client ID\n"
                "and save as data/google_credentials.json"
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(_CREDS_FILE), SCOPES)
        creds = flow.run_local_server(port=0)
        # Save for next time
        _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        print("[Google] ✓ Authenticated and token saved")

    _cached_creds = creds
    return creds


def get_google_service(api_name: str, api_version: str):
    """
    Build and return an authenticated Google API service.

    Examples:
        calendar = get_google_service("calendar", "v3")
        gmail    = get_google_service("gmail", "v1")
        docs     = get_google_service("docs", "v1")
        sheets   = get_google_service("sheets", "v4")
    """
    creds = _get_credentials()
    return build(api_name, api_version, credentials=creds)


def is_google_configured() -> bool:
    """Check if Google credentials file exists (doesn't validate token)."""
    return _CREDS_FILE.exists()
