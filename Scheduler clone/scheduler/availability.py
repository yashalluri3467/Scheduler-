"""
availability.py — Step 4
  • Store per-day availability windows (e.g. Mon-Fri 08:00-17:30)
  • Subtract busy events to compute free slots
  • Filter slots by minimum duration
  • Rank by intensity load (via IntensityEngine)
"""

from datetime import datetime, timedelta, date, timezone
from typing import List, Dict
from models import AvailabilityWindow, CalendarEvent, TimeSlot
from intensity_engine import IntensityEngine


# ── Default windows: Mon–Fri 08:00-17:30, weekends off ──────────────────────
DEFAULT_WINDOWS: List[AvailabilityWindow] = [
    AvailabilityWindow(day=0, start_time="08:00", end_time="17:30"),  # Monday
    AvailabilityWindow(day=1, start_time="08:00", end_time="17:30"),  # Tuesday
    AvailabilityWindow(day=2, start_time="08:00", end_time="17:30"),  # Wednesday
    AvailabilityWindow(day=3, start_time="08:00", end_time="17:30"),  # Thursday
    AvailabilityWindow(day=4, start_time="08:00", end_time="17:30"),  # Friday
    AvailabilityWindow(day=5, start_time="09:00", end_time="12:00", is_available=False),  # Saturday
    AvailabilityWindow(day=6, start_time="09:00", end_time="12:00", is_available=False),  # Sunday
]


class AvailabilityService:

    def __init__(self, windows: List[AvailabilityWindow] = None):
        self.windows: Dict[int, AvailabilityWindow] = {}
        for w in (windows or DEFAULT_WINDOWS):
            self.windows[w.day] = w
        self._engine = IntensityEngine()

    # ── Configure windows ────────────────────────────────────────────────

    def set_window(self, day: int, start_time: str, end_time: str, is_available: bool = True):
        """Update availability for one day.  day: 0=Mon … 6=Sun"""
        self.windows[day] = AvailabilityWindow(
            day=day,
            start_time=start_time,
            end_time=end_time,
            is_available=is_available,
        )

    def get_window(self, day: int) -> AvailabilityWindow | None:
        return self.windows.get(day)

    def print_schedule(self):
        print("\n── Availability Windows ─────────────────────────────────────────")
        for day in range(7):
            w = self.windows.get(day)
            if w:
                status = f"{w.start_time} – {w.end_time}" if w.is_available else "UNAVAILABLE"
                print(f"  {w.day_name:<12} {status}")
        print("─────────────────────────────────────────────────────────────────\n")

    # ── Core: find free slots in a date range ───────────────────────────

    def get_free_slots(
        self,
        events: List[CalendarEvent],
        from_date: date,
        to_date: date,
        min_duration_minutes: int = 30,
        slot_step_minutes: int = 15,
    ) -> List[TimeSlot]:
        """
        Walk every day in [from_date, to_date].
        For each day with an availability window, subtract busy periods
        and collect free slots ≥ min_duration_minutes.
        Returns slots ranked by day intensity load (least busy first).
        """
        all_free: List[TimeSlot] = []

        current = from_date
        while current <= to_date:
            day_of_week = current.weekday()   # 0=Mon
            window = self.windows.get(day_of_week)

            if not window or not window.is_available:
                current += timedelta(days=1)
                continue

            start_delta, end_delta = window.to_times()
            day_start = datetime.combine(current, datetime.min.time(), tzinfo=timezone.utc) + start_delta
            day_end   = datetime.combine(current, datetime.min.time(), tzinfo=timezone.utc) + end_delta

            # Collect busy intervals for this day
            day_events = [
                e for e in events
                if e.start.date() == current and not e.is_all_day
            ]
            busy = [(e.start, e.end) for e in day_events]
            busy.sort(key=lambda x: x[0])

            # Generate free slots by walking the window and subtracting busy periods
            free_in_day = self._subtract_busy(day_start, day_end, busy, min_duration_minutes)
            all_free.extend(free_in_day)

            current += timedelta(days=1)

        # Rank by day intensity load
        all_free = self._engine.rank_slots(all_free, events, prefer_low_intensity=True)
        return all_free

    def find_slot_for_duration(
        self,
        events: List[CalendarEvent],
        from_date: date,
        to_date: date,
        duration_minutes: int,
        slot_step_minutes: int = 15,
    ) -> List[TimeSlot]:
        """
        Return only slots that have at least `duration_minutes` of continuous free time,
        in intensity-ranked order.
        """
        all_slots = self.get_free_slots(
            events, from_date, to_date,
            min_duration_minutes=duration_minutes,
            slot_step_minutes=slot_step_minutes,
        )
        return [s for s in all_slots if s.duration_minutes >= duration_minutes]

    # ── Helper ───────────────────────────────────────────────────────────

    @staticmethod
    def _subtract_busy(
        window_start: datetime,
        window_end: datetime,
        busy: List[tuple],
        min_minutes: int,
    ) -> List[TimeSlot]:
        """
        Given a window and a sorted list of busy (start, end) pairs,
        return the free segments that are ≥ min_minutes.
        """
        free: List[TimeSlot] = []
        cursor = window_start

        for b_start, b_end in busy:
            # Clamp busy to within window
            b_start = max(b_start, window_start)
            b_end   = min(b_end,   window_end)

            if b_start > cursor:
                gap_minutes = int((b_start - cursor).total_seconds() / 60)
                if gap_minutes >= min_minutes:
                    free.append(TimeSlot(start=cursor, end=b_start))
            cursor = max(cursor, b_end)

        # Remaining tail of window
        if cursor < window_end:
            gap_minutes = int((window_end - cursor).total_seconds() / 60)
            if gap_minutes >= min_minutes:
                free.append(TimeSlot(start=cursor, end=window_end))

        return free
