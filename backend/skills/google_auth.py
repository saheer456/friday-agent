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

from pathlib import Path

# All scopes needed across every Google skill.
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

_DATA_DIR   = Path(__file__).resolve().parent.parent.parent / "data"
_CREDS_FILE = _DATA_DIR / "google_credentials.json"
_TOKEN_FILE = _DATA_DIR / "google_token.json"

_cached_creds = None


def is_google_configured() -> bool:
    """Check if Google credentials file exists (doesn't validate token)."""
    return _CREDS_FILE.exists()


def _get_credentials():
    """Load or create OAuth2 credentials. Opens browser on first use.
    Imports google-auth lazily so the module can be imported on Render
    even when the google packages are not installed.
    """
    global _cached_creds

    # Lazy imports — only resolve when actually needed
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as e:
        raise ImportError(
            "Google API packages are not installed. "
            "Run: pip install google-api-python-client google-auth-oauthlib"
        ) from e

    if _cached_creds and _cached_creds.valid:
        return _cached_creds

    creds = None

    if _TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_FILE), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if not _CREDS_FILE.exists():
            raise FileNotFoundError(
                f"Google credentials not found at {_CREDS_FILE}.\n"
                "Download from Google Cloud Console → Credentials → OAuth 2.0 Client ID\n"
                "and save as data/google_credentials.json"
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(_CREDS_FILE), SCOPES)
        creds = flow.run_local_server(port=0)
        _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        print("[Google] ✓ Authenticated and token saved")

    _cached_creds = creds
    return creds


def get_google_service(api_name: str, api_version: str):
    """
    Build and return an authenticated Google API service.
    Raises ImportError if google packages aren't installed.
    Raises FileNotFoundError if credentials file is missing.
    """
    try:
        from googleapiclient.discovery import build
    except ImportError as e:
        raise ImportError(
            "google-api-python-client is not installed. "
            "Run: pip install google-api-python-client"
        ) from e

    creds = _get_credentials()
    return build(api_name, api_version, credentials=creds)
