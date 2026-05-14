"""
gsheets_skill.py — Google Sheets Skill
========================================
Create, read, and append to Google Sheets.
"""
from __future__ import annotations

import webbrowser
from typing import Any, Dict, List, Optional

from .skill_base import BaseSkill, SkillResult, skill_action
from .google_auth import get_google_service, is_google_configured


class GSheetsSkill(BaseSkill):
    """Google Sheets integration — create, read, and append data."""

    name        = "gsheets"
    description = (
        "Create, read, and update Google Sheets spreadsheets. "
        "Use this when the user wants to create a spreadsheet, add data, or read sheet data."
    )

    def __init__(self) -> None:
        super().__init__()
        if is_google_configured():
            self.configure()

    def configure(self, config: Dict[str, Any] = {}) -> bool:
        self._configured = True
        return True

    def _service(self):
        return get_google_service("sheets", "v4")

    # ── Actions ────────────────────────────────────────────────────────────────

    @skill_action(
        description="Create a new Google Sheet with optional headers and data rows. Opens in browser.",
        params={
            "title":   {"type": "string",  "description": "Spreadsheet title."},
            "headers": {"type": "string",  "description": "Comma-separated column headers (optional)."},
            "rows":    {"type": "string",  "description": "Rows of data, pipe-separated rows, comma-separated values. E.g. 'a,b,c|d,e,f' (optional)."},
        },
        required=["title"],
    )
    def create_sheet(self, title: str, headers: str = "", rows: str = "") -> SkillResult:
        try:
            spreadsheet = self._service().spreadsheets().create(
                body={"properties": {"title": title}}
            ).execute()

            sheet_id = spreadsheet.get("spreadsheetId")
            sheet_url = spreadsheet.get("spreadsheetUrl", f"https://docs.google.com/spreadsheets/d/{sheet_id}")

            # Build values to insert
            values = []
            if headers:
                values.append([h.strip() for h in headers.split(",")])
            if rows:
                for row_str in rows.split("|"):
                    values.append([c.strip() for c in row_str.split(",")])

            if values:
                self._service().spreadsheets().values().update(
                    spreadsheetId=sheet_id,
                    range="A1",
                    valueInputOption="RAW",
                    body={"values": values},
                ).execute()

            webbrowser.open(sheet_url)

            return SkillResult.ok(
                message=f"Google Sheet '{title}' created and opened in browser.",
                data={"sheet_id": sheet_id, "url": sheet_url, "title": title, "rows": len(values)},
            )
        except Exception as e:
            return SkillResult.fail(f"Google Sheets error: {e}")

    @skill_action(
        description="Read data from an existing Google Sheet.",
        params={
            "sheet_id": {"type": "string", "description": "Spreadsheet ID."},
            "range":    {"type": "string", "description": "Cell range to read (default 'A1:Z100')."},
        },
        required=["sheet_id"],
    )
    def read_sheet(self, sheet_id: str, range: str = "A1:Z100") -> SkillResult:
        try:
            result = self._service().spreadsheets().values().get(
                spreadsheetId=sheet_id, range=range
            ).execute()

            values = result.get("values", [])
            return SkillResult.ok(
                message=f"Read {len(values)} rows from sheet.",
                data={"rows": values[:100], "total_rows": len(values), "sheet_id": sheet_id},
            )
        except Exception as e:
            return SkillResult.fail(f"Google Sheets read error: {e}")

    @skill_action(
        description="Append rows to an existing Google Sheet.",
        params={
            "sheet_id": {"type": "string", "description": "Spreadsheet ID."},
            "rows":     {"type": "string", "description": "Rows to append, pipe-separated rows, comma-separated values."},
        },
        required=["sheet_id", "rows"],
    )
    def append_rows(self, sheet_id: str, rows: str) -> SkillResult:
        try:
            values = []
            for row_str in rows.split("|"):
                values.append([c.strip() for c in row_str.split(",")])

            result = self._service().spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range="A1",
                valueInputOption="RAW",
                body={"values": values},
            ).execute()

            updated = result.get("updates", {}).get("updatedRows", 0)
            return SkillResult.ok(
                message=f"Appended {updated} rows to sheet.",
                data={"sheet_id": sheet_id, "rows_appended": updated},
            )
        except Exception as e:
            return SkillResult.fail(f"Google Sheets append error: {e}")
