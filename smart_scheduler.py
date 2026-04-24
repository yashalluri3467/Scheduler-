"""
smart_scheduler.py
Finds the best N time slots, scoring by day load, time-of-day, and day quality.
"""

from datetime import date, timedelta
from typing import List, Optional
from models import CalendarEvent, TimeSlot


class SmartScheduler:

    PREFERRED_MORNING   = (9, 12)   # 09:00–12:00
    PREFERRED_AFTERNOON = (14, 16)  # 14:00–16:00

    def __init__(self, availability, intensity_engine=None):
        """
        availability:     AvailabilityService instance  (required)
        intensity_engine: IntensityEngine instance       (optional, for future use)
        """
        self.availability     = availability
        self.intensity_engine = intensity_engine

    # ── Public ────────────────────────────────────────────────────────────────

    def find_best_slots(
        self,
        events: List[CalendarEvent],
        duration_minutes: int,
        top_n: int = 5,
        prefer_low_intensity: bool = True,
        look_ahead_days: int = 30,
    ) -> list:
        """Return top_n dicts: slot data + fit_score + reason."""
        today    = date.today()
        end_date = today + timedelta(days=look_ahead_days)

        slots = self.availability.find_slot_for_duration(
            events, today, end_date, duration_minutes
        )
        if not slots:
            return []

        scored = sorted(
            [(s, self._slot_score(s, prefer_low_intensity)) for s in slots],
            key=lambda x: x[1],
            reverse=True,
        )

        return [
            {
                "start":       s.start.isoformat(),
                "end":         s.end.isoformat(),
                "start_label": s.start.strftime("%a %d %b  %H:%M"),
                "end_label":   s.end.strftime("%H:%M"),
                "duration":    s.duration_minutes,
                "day_load":    s.day_load_score,
                "fit_score":   score,
                "reason":      self._reason(s, score),
            }
            for s, score in scored[:top_n]
        ]

    def find_best_slot(
        self,
        events: List[CalendarEvent],
        duration: int,
    ) -> Optional[TimeSlot]:
        """Simple helper: return the single best slot (backward-compat)."""
        today = date.today()
        end   = today + timedelta(days=14)
        slots = self.availability.find_slot_for_duration(events, today, end, duration)
        return slots[0] if slots else None

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _slot_score(self, slot: TimeSlot, prefer_low: bool) -> int:
        score = 100

        if prefer_low:
            score -= slot.day_load_score            # 0–100 penalty for busy days

        h = slot.start.hour
        if self.PREFERRED_MORNING[0] <= h < self.PREFERRED_MORNING[1]:
            score += 15
        elif self.PREFERRED_AFTERNOON[0] <= h < self.PREFERRED_AFTERNOON[1]:
            score += 10

        score += max(0, (18 - h))                   # earlier in day = slight bonus

        if slot.duration_minutes > 60:
            score += 10                             # buffer slots preferred

        dow = slot.start.weekday()                  # 0=Mon
        if dow in (1, 2, 3):                        # Tue/Wed/Thu
            score += 8

        return max(0, min(100, score))

    def _reason(self, slot: TimeSlot, score: int) -> str:
        parts = []
        h   = slot.start.hour
        dow = slot.start.weekday()

        if slot.day_load_score <= 20:
            parts.append("quiet day")
        elif slot.day_load_score <= 50:
            parts.append("moderate load")
        else:
            parts.append("busy day")

        if self.PREFERRED_MORNING[0] <= h < self.PREFERRED_MORNING[1]:
            parts.append("prime morning window")
        elif self.PREFERRED_AFTERNOON[0] <= h < self.PREFERRED_AFTERNOON[1]:
            parts.append("good afternoon slot")
        elif h < 8:
            parts.append("early start")
        elif h >= 17:
            parts.append("late in the day")

        if dow in (1, 2, 3):
            parts.append("mid-week focus day")

        return " · ".join(parts) if parts else "available slot"