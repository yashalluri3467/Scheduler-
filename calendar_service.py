"""
calendar_service.py
Google Calendar REST v3 — fetch, create (with bulk attendees), delete.
"""

from datetime import datetime
from googleapiclient.discovery import build
from models import CalendarEvent, CalendarType, BookingRequest
from auth   import get_credentials


class GoogleCalendarService:

    def __init__(self):
        creds        = get_credentials()
        self.service = build("calendar", "v3", credentials=creds)

    # ── Fetch events from one calendar ────────────────────────────────────────

    def get_events(
        self,
        calendar_id: str,
        from_dt: datetime,
        to_dt: datetime,
        cal_type: CalendarType = CalendarType.PERSONAL,
    ):
        result = self.service.events().list(
            calendarId    = calendar_id,
            timeMin       = from_dt.isoformat(),
            timeMax       = to_dt.isoformat(),
            singleEvents  = True,
            orderBy       = "startTime",
            maxResults    = 2500,
        ).execute()

        events = []
        for item in result.get("items", []):
            try:
                start_raw = item["start"].get("dateTime", item["start"].get("date",""))
                end_raw   = item["end"].get("dateTime",   item["end"].get("date",""))
                is_all_day = "dateTime" not in item["start"]

                start_dt = datetime.fromisoformat(start_raw.replace("Z","+00:00"))
                end_dt   = datetime.fromisoformat(end_raw.replace("Z","+00:00"))

                attendees = [a["email"] for a in item.get("attendees",[]) if a.get("email")]

                # Infer calendar type from item colour / description if multi-cal
                inferred_type = cal_type

                events.append(CalendarEvent(
                    uid           = item["id"],
                    title         = item.get("summary","(no title)"),
                    start         = start_dt,
                    end           = end_dt,
                    calendar_type = inferred_type,
                    description   = item.get("description",""),
                    location      = item.get("location",""),
                    attendees     = attendees,
                    is_all_day    = is_all_day,
                    calendar_id   = calendar_id,
                ))
            except Exception:
                pass

        return events

    # ── Merge multiple calendars ──────────────────────────────────────────────

    def get_consolidated_events(self, calendars, from_dt, to_dt):
        all_events = []
        seen       = set()
        for cal_id, cal_type in calendars:
            try:
                for e in self.get_events(cal_id, from_dt, to_dt, cal_type):
                    if e.uid not in seen:
                        all_events.append(e)
                        seen.add(e.uid)
            except Exception as exc:
                print(f"  [calendar_service] error fetching {cal_id}: {exc}")
        return sorted(all_events, key=lambda e: e.start)

    # ── Create event with multiple attendees ──────────────────────────────────

    def create_event(
        self,
        calendar_id: str,
        booking: BookingRequest,
        attendees: list = None,
    ) -> str:
        """
        Creates the event and sends Google invites to all attendees.
        attendees: list of email strings (supports up to 200 per Google limits).
        """
        if attendees is None:
            attendees = [booking.attendee_email]

        # De-duplicate while preserving order
        seen_emails = set()
        clean = []
        for e in attendees:
            e = e.strip().lower()
            if e and "@" in e and e not in seen_emails:
                clean.append(e)
                seen_emails.add(e)

        body = {
            "summary":     booking.event_title,
            "description": booking.description or "Scheduled via CalendarScheduler",
            "start":       {"dateTime": booking.selected_start.isoformat(),
                            "timeZone": "Asia/Kolkata"},
            "end":         {"dateTime": booking.selected_end.isoformat(),
                            "timeZone": "Asia/Kolkata"},
            "attendees":   [{"email": e} for e in clean],
            "reminders":   {
                "useDefault": False,
                "overrides":  [
                    {"method": "email",  "minutes": 1440},
                    {"method": "popup",  "minutes": 15},
                ],
            },
            "guestsCanModify":       False,
            "guestsCanInviteOthers": False,
        }

        created = self.service.events().insert(
            calendarId  = calendar_id,
            body        = body,
            sendUpdates = "all",      # sends invite emails
        ).execute()

        return created["id"]

    # ── Delete event ──────────────────────────────────────────────────────────

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        self.service.events().delete(
            calendarId  = calendar_id,
            eventId     = event_id,
            sendUpdates = "all",      # notifies attendees of cancellation
        ).execute()