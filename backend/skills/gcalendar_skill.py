"""
gcalendar_skill.py — Google Calendar Skill
============================================
Create, list, update, and delete events on Google Calendar.
"""
from __future__ import annotations

import webbrowser
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .skill_base import BaseSkill, SkillResult, skill_action
from .google_auth import get_google_service, is_google_configured


class GCalendarSkill(BaseSkill):
    """Full Google Calendar integration."""

    name        = "gcalendar"
    description = (
        "Manage Google Calendar events. Create, list, update, and delete calendar events. "
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

    def health_check(self) -> bool:
        return is_google_configured()

    # ── Actions ────────────────────────────────────────────────────────────────

    @skill_action(
        description="Create a new event on Google Calendar.",
        params={
            "title":            {"type": "string", "description": "Event title."},
            "start_time":       {"type": "string", "description": "Start time in YYYY-MM-DD HH:MM format."},
            "duration_minutes": {"type": "integer", "description": "Duration in minutes (default 60)."},
            "location":         {"type": "string", "description": "Event location (optional)."},
            "description":      {"type": "string", "description": "Event description (optional)."},
            "attendees":        {"type": "string", "description": "Comma-separated email addresses of attendees (optional)."},
            "open_browser":     {"type": "boolean", "description": "Auto-open the event link in the browser (default true)."},
        },
        required=["title", "start_time"],
        permissions=["gcalendar:write"]
    )
    def create_event(
        self,
        title: str,
        start_time: str,
        duration_minutes: int = 60,
        location: str = "",
        description: str = "",
        attendees: str = "",
        open_browser: bool = True,
    ) -> SkillResult:
        try:
            start_dt = datetime.strptime(start_time.strip(), "%Y-%m-%d %H:%M")
            end_dt = start_dt + timedelta(minutes=duration_minutes)

            # Retrieve calendar timezone dynamically
            cal_info = self._service().calendars().get(calendarId=self._calendar_id).execute()
            tz = cal_info.get("timeZone", "UTC")

            event_body: Dict[str, Any] = {
                "summary": title,
                "start": {"dateTime": start_dt.isoformat(), "timeZone": tz},
                "end":   {"dateTime": end_dt.isoformat(),   "timeZone": tz},
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
            if open_browser and link:
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
        permissions=["gcalendar:read"]
    )
    def list_events(self, max_results: int = 10) -> SkillResult:
        try:
            now = datetime.now(timezone.utc).isoformat()
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
        description="Update an existing Google Calendar event.",
        params={
            "event_id":         {"type": "string", "description": "The ID of the event to update."},
            "title":            {"type": "string", "description": "New event title (optional)."},
            "start_time":       {"type": "string", "description": "New start time in YYYY-MM-DD HH:MM format (optional)."},
            "duration_minutes": {"type": "integer", "description": "New duration in minutes (optional)."},
            "location":         {"type": "string", "description": "New location (optional)."},
            "description":      {"type": "string", "description": "New description (optional)."},
            "open_browser":     {"type": "boolean", "description": "Auto-open the updated event link in browser (default false)."},
        },
        required=["event_id"],
        permissions=["gcalendar:write"]
    )
    def update_event(
        self,
        event_id: str,
        title: Optional[str] = None,
        start_time: Optional[str] = None,
        duration_minutes: Optional[int] = None,
        location: Optional[str] = None,
        description: Optional[str] = None,
        open_browser: bool = False,
    ) -> SkillResult:
        try:
            event = self._service().events().get(
                calendarId=self._calendar_id, eventId=event_id
            ).execute()

            cal_info = self._service().calendars().get(calendarId=self._calendar_id).execute()
            tz = cal_info.get("timeZone", "UTC")

            if title is not None:
                event["summary"] = title
            if location is not None:
                event["location"] = location
            if description is not None:
                event["description"] = description

            if start_time:
                start_dt = datetime.strptime(start_time.strip(), "%Y-%m-%d %H:%M")
                event["start"] = {"dateTime": start_dt.isoformat(), "timeZone": tz}
                if duration_minutes:
                    end_dt = start_dt + timedelta(minutes=duration_minutes)
                    event["end"] = {"dateTime": end_dt.isoformat(), "timeZone": tz}
                else:
                    # Maintain existing duration relative to new start time
                    orig_start_str = event["start"].get("dateTime", event["start"].get("date"))
                    orig_end_str = event["end"].get("dateTime", event["end"].get("date"))
                    orig_start = datetime.fromisoformat(orig_start_str.replace("Z", "+00:00"))
                    orig_end = datetime.fromisoformat(orig_end_str.replace("Z", "+00:00"))
                    dur = orig_end - orig_start
                    end_dt = start_dt + dur
                    event["end"] = {"dateTime": end_dt.isoformat(), "timeZone": tz}
            elif duration_minutes:
                orig_start_str = event["start"].get("dateTime", event["start"].get("date"))
                orig_start_dt = datetime.fromisoformat(orig_start_str.replace("Z", "+00:00"))
                end_dt = orig_start_dt + timedelta(minutes=duration_minutes)
                event["end"] = {"dateTime": end_dt.isoformat(), "timeZone": tz}

            updated = self._service().events().update(
                calendarId=self._calendar_id, eventId=event_id, body=event
            ).execute()

            link = updated.get("htmlLink", "")
            if open_browser and link:
                webbrowser.open(link)

            return SkillResult.ok(
                message=f"Event '{updated.get('summary')}' updated successfully.",
                data={"event_id": event_id, "link": link}
            )
        except Exception as e:
            return SkillResult.fail(f"Failed to update event: {e}")

    @skill_action(
        description="Delete a calendar event by its event ID.",
        params={
            "event_id": {"type": "string", "description": "The Google Calendar event ID."},
        },
        required=["event_id"],
        permissions=["gcalendar:write"]
    )
    def delete_event(self, event_id: str) -> SkillResult:
        try:
            self._service().events().delete(
                calendarId=self._calendar_id, eventId=event_id
            ).execute()
            return SkillResult.ok(message=f"Event {event_id} deleted.")
        except Exception as e:
            return SkillResult.fail(f"Delete failed: {e}")

    @skill_action(
        description="Find free time slots for a specific date (YYYY-MM-DD) between standard working hours 9 AM - 5 PM.",
        params={
            "date": {"type": "string", "description": "Date to inspect in YYYY-MM-DD format."}
        },
        required=["date"],
        permissions=["gcalendar:read"]
    )
    def find_free_time(self, date: str) -> SkillResult:
        try:
            date_str = date.strip()
            day_start_dt = datetime.strptime(f"{date_str} 09:00", "%Y-%m-%d %H:%M")
            day_end_dt = datetime.strptime(f"{date_str} 17:00", "%Y-%m-%d %H:%M")

            result = self._service().events().list(
                calendarId=self._calendar_id,
                timeMin=day_start_dt.isoformat() + "Z",
                timeMax=day_end_dt.isoformat() + "Z",
                singleEvents=True,
                orderBy="startTime"
            ).execute()

            events = result.get("items", [])
            busy_slots = []

            for ev in events:
                ev_start_str = ev.get("start", {}).get("dateTime")
                ev_end_str = ev.get("end", {}).get("dateTime")
                if ev_start_str and ev_end_str:
                    # Parse times, keeping timezone naive for comparison
                    start_dt = datetime.fromisoformat(ev_start_str.split("+")[0].split("Z")[0])
                    end_dt = datetime.fromisoformat(ev_end_str.split("+")[0].split("Z")[0])
                    busy_slots.append((start_dt, end_dt))

            free_slots = []
            current_time = day_start_dt
            for b_start, b_end in sorted(busy_slots, key=lambda x: x[0]):
                if b_start > current_time:
                    free_slots.append(f"{current_time.strftime('%H:%M')} - {b_start.strftime('%H:%M')}")
                if b_end > current_time:
                    current_time = b_end
            if current_time < day_end_dt:
                free_slots.append(f"{current_time.strftime('%H:%M')} - {day_end_dt.strftime('%H:%M')}")

            return SkillResult.ok(
                message=f"Found {len(free_slots)} free slots on {date_str}.",
                data={"date": date_str, "free_slots": free_slots}
            )
        except Exception as e:
            return SkillResult.fail(f"Failed to find free time: {e}")
