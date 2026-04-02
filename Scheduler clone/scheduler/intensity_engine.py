"""
intensity_engine.py — Scores every event 0-100 and ranks time slots
by how well they fit given the day's existing intensity load.

Scoring factors
───────────────
  1. Keywords in title/description          (+10 to +30)
  2. Duration                               (long meetings = higher)
  3. Attendee count                         (more people = higher)
  4. Calendar type (work vs personal)       (work bumps score)
  5. Time of day                            (early morning / late = moderate bump)
  6. Day density penalty                    (many events = higher load)
"""

from datetime import datetime, timedelta
from typing import List
from models import (
    CalendarEvent, CalendarType, EventIntensity,
    TimeSlot, CRITICAL_KEYWORDS, HIGH_KEYWORDS, LOW_KEYWORDS
)


class IntensityEngine:

    # ── 1. Per-event score ────────────────────────────────────────────────

    def score_event(self, event: CalendarEvent, same_day_events: List[CalendarEvent]) -> int:
        score = 0
        text = (event.title + " " + event.description).lower()

        # Keyword check
        if any(kw in text for kw in CRITICAL_KEYWORDS):
            score += 30
        elif any(kw in text for kw in HIGH_KEYWORDS):
            score += 20
        elif any(kw in text for kw in LOW_KEYWORDS):
            score -= 10

        # Duration factor (0-20 pts)
        # 15 min → 2 pts  |  30 min → 5  |  60 min → 10  |  120+ min → 20
        dur = min(event.duration_minutes, 180)
        score += int((dur / 180) * 20)

        # Attendee count (0-15 pts)
        attendee_pts = min(len(event.attendees) * 3, 15)
        score += attendee_pts

        # Calendar type
        if event.calendar_type == CalendarType.WORK:
            score += 10

        # Time-of-day factor: early morning (<8) or late (>18) = slightly higher stress
        hour = event.start.hour
        if hour < 8 or hour >= 18:
            score += 8
        elif 9 <= hour <= 11:   # prime morning window — neutral
            score += 0
        elif 12 <= hour <= 13:  # lunch hour — mild reduction
            score -= 5

        # Day density: each extra event on same day adds 3 pts (max 15)
        other_events = [e for e in same_day_events if e.uid != event.uid]
        score += min(len(other_events) * 3, 15)

        return max(0, min(100, score))

    def score_and_label(self, events: List[CalendarEvent]) -> List[CalendarEvent]:
        """Score every event in-place, grouped by day for density factor."""
        by_day: dict[str, List[CalendarEvent]] = {}
        for e in events:
            key = e.start.strftime("%Y-%m-%d")
            by_day.setdefault(key, []).append(e)

        for e in events:
            key = e.start.strftime("%Y-%m-%d")
            e.intensity_score = self.score_event(e, by_day[key])
            e.intensity = self._score_to_intensity(e.intensity_score)

        return events

    # ── 2. Time-slot ranking ──────────────────────────────────────────────

    def rank_slots(
        self,
        slots: List[TimeSlot],
        events: List[CalendarEvent],
        prefer_low_intensity: bool = True
    ) -> List[TimeSlot]:
        """
        Annotate each slot with the day's existing intensity load,
        then sort so the least-loaded windows come first.
        """
        day_loads: dict[str, int] = {}
        by_day: dict[str, List[CalendarEvent]] = {}

        for e in events:
            key = e.start.strftime("%Y-%m-%d")
            by_day.setdefault(key, []).append(e)

        for day_key, day_events in by_day.items():
            total = sum(e.intensity_score for e in day_events)
            day_loads[day_key] = min(100, total)

        for slot in slots:
            key = slot.start.strftime("%Y-%m-%d")
            slot.day_load_score = day_loads.get(key, 0)

        if prefer_low_intensity:
            slots.sort(key=lambda s: (s.day_load_score, s.start))
        else:
            slots.sort(key=lambda s: s.start)

        return slots

    # ── 3. Day report ─────────────────────────────────────────────────────

    def day_load_score(self, events: List[CalendarEvent]) -> int:
        """Return 0-100 aggregate load for a list of events on one day."""
        if not events:
            return 0
        return min(100, sum(e.intensity_score for e in events))

    # ── helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _score_to_intensity(score: int) -> EventIntensity:
        if score <= 25:  return EventIntensity.LOW
        if score <= 50:  return EventIntensity.MEDIUM
        if score <= 75:  return EventIntensity.HIGH
        return EventIntensity.CRITICAL

    @staticmethod
    def intensity_badge(intensity: EventIntensity) -> str:
        return {
            EventIntensity.LOW:      "🟢 LOW",
            EventIntensity.MEDIUM:   "🔵 MEDIUM",
            EventIntensity.HIGH:     "🟠 HIGH",
            EventIntensity.CRITICAL: "🔴 CRITICAL",
        }[intensity]
