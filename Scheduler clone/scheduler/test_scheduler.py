"""
test_scheduler.py — Quick unit tests (no network calls)
Run:  python test_scheduler.py
"""

import unittest
from datetime import datetime, timezone, timedelta, date
from models import CalendarEvent, CalendarType, EventIntensity, AvailabilityWindow
from intensity_engine import IntensityEngine
from availability import AvailabilityService


def make_event(title, start_hour, duration_min=60,
               cal_type=CalendarType.WORK, attendees=None, desc=""):
    start = datetime(2025, 6, 2, start_hour, 0, tzinfo=timezone.utc)
    end   = start + timedelta(minutes=duration_min)
    return CalendarEvent(
        uid=title, title=title, start=start, end=end,
        calendar_type=cal_type, description=desc,
        attendees=attendees or []
    )


class TestIntensityEngine(unittest.TestCase):
    def setUp(self):
        self.engine = IntensityEngine()

    def test_critical_keyword_raises_score(self):
        e = make_event("Board deadline presentation", 9)
        self.engine.score_and_label([e])
        self.assertGreaterEqual(e.intensity_score, 40)  # ≥40 for multi-keyword title
        self.assertIn(e.intensity, [EventIntensity.MEDIUM, EventIntensity.HIGH, EventIntensity.CRITICAL])

    def test_low_keyword_lowers_score(self):
        e = make_event("Lunch with friends", 12, cal_type=CalendarType.PERSONAL)
        self.engine.score_and_label([e])
        self.assertLessEqual(e.intensity_score, 40)

    def test_many_attendees_raises_score(self):
        e = make_event("Standup", 9, attendees=["a@a.com","b@b.com","c@c.com","d@d.com","e@e.com"])
        self.engine.score_and_label([e])
        self.assertGreater(e.intensity_score, 20)

    def test_long_meeting_higher_than_short(self):
        short = make_event("Short", 10, duration_min=15)
        long_ = make_event("Long",  10, duration_min=120)
        self.engine.score_and_label([short, long_])
        self.assertGreater(long_.intensity_score, short.intensity_score)

    def test_dense_day_raises_scores(self):
        events = [make_event(f"Meeting {i}", 9+i) for i in range(5)]
        self.engine.score_and_label(events)
        # Each event should have density bonus applied
        self.assertTrue(all(e.intensity_score > 0 for e in events))

    def test_slot_ranking_least_busy_first(self):
        from models import TimeSlot
        busy_day  = [make_event("Exec review deadline", 9, desc="critical board"),
                     make_event("Sprint planning",      11)]
        quiet_day = [make_event("Coffee chat", 14, cal_type=CalendarType.PERSONAL)]
        all_events = busy_day + quiet_day
        self.engine.score_and_label(all_events)

        # Create one slot per day
        d1 = datetime(2025, 6, 2, 15, 0, tzinfo=timezone.utc)
        d2 = datetime(2025, 6, 3, 15, 0, tzinfo=timezone.utc)
        slots = [
            TimeSlot(start=d1, end=d1+timedelta(hours=1)),
            TimeSlot(start=d2, end=d2+timedelta(hours=1)),
        ]
        ranked = self.engine.rank_slots(slots, all_events)
        # The quiet day slot (d2) should come first
        self.assertEqual(ranked[0].start.date(), d2.date())


class TestAvailability(unittest.TestCase):
    def setUp(self):
        self.avail = AvailabilityService()

    def test_weekend_no_slots(self):
        # Saturday = 5
        saturday = date(2025, 6, 7)   # a Saturday
        slots = self.avail.get_free_slots([], saturday, saturday, min_duration_minutes=30)
        self.assertEqual(slots, [])

    def test_weekday_has_slots(self):
        monday = date(2025, 6, 2)
        slots = self.avail.get_free_slots([], monday, monday, min_duration_minutes=30)
        self.assertGreater(len(slots), 0)

    def test_busy_event_removes_slot(self):
        monday = date(2025, 6, 2)
        # All-day block: a single 9h event covering most of the window
        block = CalendarEvent(
            uid="block", title="Blocked",
            start=datetime(2025, 6, 2, 8, 0, tzinfo=timezone.utc),
            end=  datetime(2025, 6, 2, 17, 30, tzinfo=timezone.utc),
        )
        slots = self.avail.get_free_slots([block], monday, monday, min_duration_minutes=30)
        self.assertEqual(slots, [])

    def test_partial_busy_leaves_gap(self):
        monday = date(2025, 6, 2)
        busy = CalendarEvent(
            uid="b", title="Morning block",
            start=datetime(2025, 6, 2, 8, 0, tzinfo=timezone.utc),
            end=  datetime(2025, 6, 2, 14, 0, tzinfo=timezone.utc),
        )
        slots = self.avail.get_free_slots([busy], monday, monday, min_duration_minutes=30)
        self.assertTrue(all(s.start >= datetime(2025, 6, 2, 14, 0, tzinfo=timezone.utc)
                            for s in slots))

    def test_set_window_updates_correctly(self):
        self.avail.set_window(0, "09:00", "16:00", is_available=True)
        w = self.avail.get_window(0)
        self.assertEqual(w.start_time, "09:00")
        self.assertEqual(w.end_time,   "16:00")


if __name__ == "__main__":
    unittest.main(verbosity=2)
