"""
gsheets_skill.py — Google Sheets Skill
========================================
Create, read, append, update, and delete cells/rows on Google Sheets.
"""
from __future__ import annotations

import json
import webbrowser
from typing import Any, Dict, List, Optional

from .skill_base import BaseSkill, SkillResult, skill_action
from .google_auth import get_google_service, is_google_configured


class GSheetsSkill(BaseSkill):
    """Google Sheets integration — create, read, append, and edit data."""

    name        = "gsheets"
    description = (
        "Create, read, and update Google Sheets spreadsheets. "
        "Use this when the user wants to create a spreadsheet, add data, edit cells, or read sheet data."
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

    def _drive_service(self):
        return get_google_service("drive", "v3")

    def health_check(self) -> bool:
        return is_google_configured()

    # ── Actions ────────────────────────────────────────────────────────────────

    @skill_action(
        description="Create a new Google Sheet with optional headers and data rows. Supports JSON arrays.",
        params={
            "title":        {"type": "string",  "description": "Spreadsheet title."},
            "headers":      {"type": "string",  "description": "Comma-separated column headers (optional)."},
            "rows":         {"type": "string",  "description": "Legacy pipe-separated rows (optional)."},
            "rows_json":    {"type": "string",  "description": "JSON array of arrays representing rows, e.g. '[[\"Val1\", \"Val2\"], [\"Val3\", \"Val4\"]]' (optional)."},
            "open_browser": {"type": "boolean", "description": "Auto-open the sheet in the browser (default true)."},
        },
        required=["title"],
        permissions=["gsheets:write"]
    )
    def create_sheet(self, title: str, headers: str = "", rows: str = "", rows_json: str = "", open_browser: bool = True) -> SkillResult:
        try:
            spreadsheet = self._service().spreadsheets().create(
                body={"properties": {"title": title}}
            ).execute()

            sheet_id = spreadsheet.get("spreadsheetId")
            sheet_url = spreadsheet.get("spreadsheetUrl", f"https://docs.google.com/spreadsheets/d/{sheet_id}")

            values = []
            if headers:
                values.append([h.strip() for h in headers.split(",")])
            
            if rows_json:
                try:
                    parsed_rows = json.loads(rows_json)
                    if isinstance(parsed_rows, list):
                        values.extend(parsed_rows)
                except Exception as json_err:
                    return SkillResult.invalid(f"Invalid JSON format for rows_json: {json_err}")
            elif rows:
                for row_str in rows.split("|"):
                    values.append([c.strip() for c in row_str.split(",")])

            if values:
                self._service().spreadsheets().values().update(
                    spreadsheetId=sheet_id,
                    range="A1",
                    valueInputOption="USER_ENTERED",
                    body={"values": values},
                ).execute()

            if open_browser:
                webbrowser.open(sheet_url)

            return SkillResult.ok(
                message=f"Google Sheet '{title}' created successfully.",
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
        permissions=["gsheets:read"]
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
        description="Append rows to an existing Google Sheet. Supports JSON arrays.",
        params={
            "sheet_id":      {"type": "string", "description": "Spreadsheet ID."},
            "rows":          {"type": "string", "description": "Legacy pipe-separated rows (optional)."},
            "rows_json":     {"type": "string", "description": "JSON array of arrays representing rows to append (optional)."},
            "range":         {"type": "string", "description": "Starting cell range (default 'A1')."},
            "open_browser":  {"type": "boolean", "description": "Auto-open the sheet in the browser (default false)."},
        },
        required=["sheet_id"],
        permissions=["gsheets:write"]
    )
    def append_rows(self, sheet_id: str, rows: str = "", rows_json: str = "", range: str = "A1", open_browser: bool = False) -> SkillResult:
        try:
            values = []
            if rows_json:
                try:
                    parsed_rows = json.loads(rows_json)
                    if isinstance(parsed_rows, list):
                        values.extend(parsed_rows)
                except Exception as json_err:
                    return SkillResult.invalid(f"Invalid JSON format for rows_json: {json_err}")
            elif rows:
                for row_str in rows.split("|"):
                    values.append([c.strip() for c in row_str.split(",")])

            if not values:
                return SkillResult.invalid("No row data provided to append.")

            result = self._service().spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range=range,
                valueInputOption="USER_ENTERED",
                body={"values": values},
            ).execute()

            updated = result.get("updates", {}).get("updatedRows", 0)
            
            if open_browser:
                sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
                webbrowser.open(sheet_url)

            return SkillResult.ok(
                message=f"Appended {updated} rows to sheet.",
                data={"sheet_id": sheet_id, "rows_appended": updated},
            )
        except Exception as e:
            return SkillResult.fail(f"Google Sheets append error: {e}")

    @skill_action(
        description="Update the value/formula of a single cell or a range in a Google Sheet.",
        params={
            "sheet_id": {"type": "string", "description": "Spreadsheet ID."},
            "range":    {"type": "string", "description": "Cell range (e.g. 'Sheet1!A1' or 'B5')."},
            "value":    {"type": "string", "description": "Value or formula to write to the cell (formulas start with '=')."},
        },
        required=["sheet_id", "range", "value"],
        permissions=["gsheets:write"]
    )
    def update_cell(self, sheet_id: str, range: str, value: str) -> SkillResult:
        try:
            self._service().spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=range,
                valueInputOption="USER_ENTERED",
                body={"values": [[value]]},
            ).execute()
            return SkillResult.ok(message=f"Cell/range {range} updated.")
        except Exception as e:
            return SkillResult.fail(f"Cell update failed: {e}")

    @skill_action(
        description="Delete a range of rows from a spreadsheet sheet.",
        params={
            "sheet_id":     {"type": "string",  "description": "Spreadsheet ID."},
            "start_row":    {"type": "integer", "description": "1-based starting row index to delete."},
            "num_rows":     {"type": "integer", "description": "Number of rows to delete (default 1)."},
            "sheet_index":  {"type": "integer", "description": "0-based index of the sub-sheet to delete from (default 0)."},
        },
        required=["sheet_id", "start_row"],
        permissions=["gsheets:write"]
    )
    def delete_rows(self, sheet_id: str, start_row: int, num_rows: int = 1, sheet_index: int = 0) -> SkillResult:
        try:
            sheet_metadata = self._service().spreadsheets().get(spreadsheetId=sheet_id).execute()
            sheets = sheet_metadata.get("sheets", [])
            if not sheets or sheet_index >= len(sheets):
                return SkillResult.fail(f"Sub-sheet index {sheet_index} not found.")

            gid = sheets[sheet_index].get("properties", {}).get("sheetId", 0)

            # Google Sheets API delete dimension is 0-based, end index is exclusive
            start_index = start_row - 1
            end_index = start_index + num_rows

            body = {
                "requests": [{
                    "deleteDimension": {
                        "range": {
                            "sheetId": gid,
                            "dimension": "ROWS",
                            "startIndex": start_index,
                            "endIndex": end_index
                        }
                    }
                }]
            }

            self._service().spreadsheets().batchUpdate(
                spreadsheetId=sheet_id, body=body
            ).execute()

            return SkillResult.ok(message=f"Deleted {num_rows} rows starting from row {start_row}.")
        except Exception as e:
            return SkillResult.fail(f"Failed to delete rows: {e}")

    @skill_action(
        description="List the user's Google Sheets spreadsheets from Google Drive.",
        params={
            "max_results": {"type": "integer", "description": "Max spreadsheets to return (default 10)."}
        },
        required=[],
        permissions=["gsheets:read"]
    )
    def list_sheets(self, max_results: int = 10) -> SkillResult:
        try:
            drive = self._drive_service()
            q = "mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
            results = drive.files().list(
                q=q,
                pageSize=max_results,
                fields="files(id, name, createdTime)"
            ).execute()

            files = results.get("files", [])
            sheets_list = []
            for f in files:
                sheets_list.append({
                    "id": f.get("id"),
                    "title": f.get("name"),
                    "created_time": f.get("createdTime"),
                    "url": f"https://docs.google.com/spreadsheets/d/{f.get('id')}/edit"
                })

            return SkillResult.ok(
                message=f"Found {len(sheets_list)} spreadsheets.",
                data={"spreadsheets": sheets_list}
            )
        except Exception as e:
            return SkillResult.fail(f"Failed to list spreadsheets: {e}")
