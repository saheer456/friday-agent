"""
gcalendar_skill.py — Google Calendar Skill
============================================
Create, list, and delete events on Google Calendar.
"""
from __future__ import annotations

import webbrowser
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .skill_base import BaseSkill, SkillResult, skill_action
from .google_auth import get_google_service, is_google_configured


class GCalendarSkill(BaseSkill):
    """Full Google Calendar integration."""

    name        = "gcalendar"
    description = (
        "Manage Google Calendar events. Create, list, and delete calendar events. "
        "Use this whenever the user mentions meetings, events, schedules, or reminders."
    )

    def __init__(self) -> None:
        super().__init__()
        if is_google_configured():
            self.configure()

    def configure(self, config: Dict[str, Any] = {}) -> bool:
        self._calendar_id = config.get("calendar_id", "primary")
        self._configured = True
        return True

    def _service(self):
        return get_google_service("calendar", "v3")

    # ── Actions ────────────────────────────────────────────────────────────────

    @skill_action(
        description=(
            "Create a new event on Google Calendar. "
            "Returns the event link which opens in the browser."
        ),
        params={
            "title":       {"type": "string", "description": "Event title."},
            "start_time":  {"type": "string", "description": "Start time in YYYY-MM-DD HH:MM format."},
            "duration_minutes": {"type": "integer", "description": "Duration in minutes (default 60)."},
            "location":    {"type": "string", "description": "Event location (optional)."},
            "description": {"type": "string", "description": "Event description (optional)."},
            "attendees":   {"type": "string", "description": "Comma-separated email addresses of attendees (optional)."},
        },
        required=["title", "start_time"],
    )
    def create_event(
        self,
        title: str,
        start_time: str,
        duration_minutes: int = 60,
        location: str = "",
        description: str = "",
        attendees: str = "",
    ) -> SkillResult:
        try:
            start_dt = datetime.strptime(start_time.strip(), "%Y-%m-%d %H:%M")
            end_dt = start_dt + timedelta(minutes=duration_minutes)

            event_body: Dict[str, Any] = {
                "summary": title,
                "start": {"dateTime": start_dt.isoformat(), "timeZone": "Asia/Kolkata"},
                "end":   {"dateTime": end_dt.isoformat(),   "timeZone": "Asia/Kolkata"},
            }
            if location:
                event_body["location"] = location
            if description:
                event_body["description"] = description
            if attendees:
                emails = [e.strip() for e in attendees.split(",") if e.strip()]
                event_body["attendees"] = [{"email": e} for e in emails]

            event = self._service().events().insert(
                calendarId=self._calendar_id, body=event_body
            ).execute()

            link = event.get("htmlLink", "")
            if link:
                webbrowser.open(link)

            return SkillResult.ok(
                message=f"Event '{title}' created for {start_time}.",
                data={
                    "event_id": event.get("id"),
                    "link":     link,
                    "title":    title,
                    "start":    start_time,
                },
            )
        except ValueError as e:
            return SkillResult.invalid(f"Bad date format: {e}. Use YYYY-MM-DD HH:MM")
        except Exception as e:
            return SkillResult.fail(f"Calendar error: {e}")

    @skill_action(
        description="List upcoming events from Google Calendar.",
        params={
            "max_results": {"type": "integer", "description": "Max events to return (default 10)."},
        },
        required=[],
    )
    def list_events(self, max_results: int = 10) -> SkillResult:
        try:
            now = datetime.utcnow().isoformat() + "Z"
            result = self._service().events().list(
                calendarId=self._calendar_id,
                timeMin=now,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            ).execute()

            events = result.get("items", [])
            entries = []
            for ev in events:
                start = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", "?"))
                entries.append({
                    "title": ev.get("summary", "Untitled"),
                    "start": start,
                    "location": ev.get("location", ""),
                    "id": ev.get("id"),
                })

            return SkillResult.ok(
                message=f"Found {len(entries)} upcoming events.",
                data={"events": entries},
            )
        except Exception as e:
            return SkillResult.fail(f"Calendar error: {e}")

    @skill_action(
        description="Delete a calendar event by its event ID.",
        params={
            "event_id": {"type": "string", "description": "The Google Calendar event ID."},
        },
        required=["event_id"],
    )
    def delete_event(self, event_id: str) -> SkillResult:
        try:
            self._service().events().delete(
                calendarId=self._calendar_id, eventId=event_id
            ).execute()
            return SkillResult.ok(message=f"Event {event_id} deleted.")
        except Exception as e:
            return SkillResult.fail(f"Delete failed: {e}")
