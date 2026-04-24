"""
models.py — Event data types and intensity scoring engine
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional
import math


class CalendarType(Enum):
    PERSONAL = "personal"
    WORK = "work"
    OTHER = "other"


class EventIntensity(Enum):
    LOW = 1        # Score  0-25  — casual, flexible
    MEDIUM = 2     # Score 26-50  — regular meeting
    HIGH = 3       # Score 51-75  — important, prep needed
    CRITICAL = 4   # Score 76-100 — deadline / exec-level


# ── Keyword tables ──────────────────────────────────────────────────────────
CRITICAL_KEYWORDS = [
    "deadline", "board", "exec", "ceo", "cto", "launch", "release",
    "urgent", "emergency", "critical", "interview", "demo", "pitch"
]
HIGH_KEYWORDS = [
    "review", "presentation", "all-hands", "sprint", "planning",
    "standup", "retrospective", "performance", "client", "investor",
    "important", "priority", "meeting"
]
LOW_KEYWORDS = [
    "lunch", "break", "coffee", "casual", "optional", "social",
    "birthday", "personal", "ooo", "out of office", "holiday"
]


@dataclass
class CalendarEvent:
    uid: str
    title: str
    start: datetime
    end: datetime
    calendar_type: CalendarType = CalendarType.PERSONAL
    description: str = ""
    location: str = ""
    attendees: List[str] = field(default_factory=list)
    is_all_day: bool = False
    calendar_id: str = ""
    intensity_score: int = 0          # 0-100, computed after fetch
    intensity: EventIntensity = EventIntensity.MEDIUM

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() / 60)

    @property
    def duration_hours(self) -> float:
        return self.duration_minutes / 60

    def __str__(self):
        tag = f"[{self.calendar_type.value.upper()}]"
        badge = self.intensity.name
        return (
            f"{tag} {self.title} | "
            f"{self.start.strftime('%a %d %b %Y %H:%M')} → "
            f"{self.end.strftime('%H:%M')} "
            f"({self.duration_minutes}min) | "
            f"Intensity: {badge} ({self.intensity_score})"
        )


@dataclass
class TimeSlot:
    start: datetime
    end: datetime
    is_available: bool = True
    day_load_score: int = 0   # 0-100: how busy the day already is

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() / 60)


@dataclass
class AvailabilityWindow:
    """User-configured working hours per day of week."""
    # day: 0=Monday … 6=Sunday
    day: int
    start_time: str   # "HH:MM"
    end_time: str     # "HH:MM"
    is_available: bool = True

    @property
    def day_name(self) -> str:
        return ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"][self.day]

    def to_times(self):
        sh, sm = map(int, self.start_time.split(":"))
        eh, em = map(int, self.end_time.split(":"))
        return timedelta(hours=sh, minutes=sm), timedelta(hours=eh, minutes=em)


@dataclass
class BookingRequest:
    attendee_name: str
    attendee_email: str
    event_title: str
    duration_minutes: int
    selected_start: datetime
    selected_end: datetime
    description: str = ""


@dataclass
class DayIntensityReport:
    date: datetime
    events: List[CalendarEvent] = field(default_factory=list)

    @property
    def event_count(self) -> int:
        return len(self.events)

    @property
    def total_hours(self) -> float:
        return sum(e.duration_hours for e in self.events)

    @property
    def total_intensity_score(self) -> int:
        if not self.events:
            return 0
        return min(100, sum(e.intensity_score for e in self.events))

    @property
    def average_intensity_score(self) -> int:
        if not self.events:
            return 0
        return int(self.total_intensity_score / len(self.events))

    @property
    def day_intensity(self) -> EventIntensity:
        s = self.average_intensity_score
        if s <= 25:  return EventIntensity.LOW
        if s <= 50:  return EventIntensity.MEDIUM
        if s <= 75:  return EventIntensity.HIGH
        return EventIntensity.CRITICAL

    def summary(self) -> str:
        return (
            f"{self.date.strftime('%A %d %b')} | "
            f"{self.event_count} events | "
            f"{self.total_hours:.1f}h booked | "
            f"Day load: {self.day_intensity.name} ({self.total_intensity_score})"
        )
