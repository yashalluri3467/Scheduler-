"""
app.py  —  CalendarScheduler  (all bugs fixed + custom category support)

Fixes vs previous version
──────────────────────────
 1. _load_events now fetches past 7 days so newly created events appear immediately
 2. Category filter fixed: empty string = no filter (was breaking team-event fetch)
 3. Custom workload categories stored server-side; GET/POST /api/categories
 4. /api/events serialiser now includes 'category_label' for custom categories
 5. /api/team_event stores category on created event so it shows in All Events
 6. traceback printed on ALL errors so VS terminal shows the real exception
"""

import os
import sys
import traceback
import json
from datetime import datetime, timezone, timedelta, date
from typing import List, Dict

from flask import Flask, render_template, jsonify, request

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from env import get_env, load_dotenv
from models           import (
    CalendarType, CalendarEvent, BookingRequest,
    DayIntensityReport, EventIntensity,
    CRITICAL_KEYWORDS, HIGH_KEYWORDS, LOW_KEYWORDS,
)
from calendar_service import GoogleCalendarService
from intensity_engine import IntensityEngine
from availability     import AvailabilityService
from smart_scheduler  import SmartScheduler

load_dotenv()

app = Flask(__name__)
app.secret_key = get_env("FLASK_SECRET_KEY", "calsched-2025")

# ── Calendar config ──────────────────────────────────────────────────────────
CALENDARS = [
    ("primary", CalendarType.PERSONAL),
    # ("work@company.com", CalendarType.WORK),
]
PRIMARY_CALENDAR = "primary"
LOOK_AHEAD_DAYS  = 30

# ── Custom categories (persisted in memory; survives restart via JSON file) ──
CATEGORIES_FILE = os.path.join(BASE, "custom_categories.json")

def _load_custom_categories() -> Dict[str, dict]:
    """
    Returns dict keyed by id:
      { "work": {"id":"work","label":"Work","color":"#9b79f5","builtin":True},
        "my_cat": {"id":"my_cat","label":"Deep Work","color":"#f0b429","builtin":False} }
    """
    builtin = {
        "personal": {"id":"personal","label":"Personal","color":"#4f8ef7","builtin":True},
        "work":     {"id":"work",    "label":"Work",    "color":"#9b79f5","builtin":True},
        "other":    {"id":"other",   "label":"Other",   "color":"#6b6f83","builtin":True},
    }
    if os.path.exists(CATEGORIES_FILE):
        try:
            with open(CATEGORIES_FILE) as f:
                custom = json.load(f)
            builtin.update(custom)
        except Exception:
            pass
    return builtin

def _save_custom_categories(cats: dict):
    custom = {k: v for k, v in cats.items() if not v.get("builtin")}
    try:
        with open(CATEGORIES_FILE, "w") as f:
            json.dump(custom, f, indent=2)
    except Exception:
        pass

# In-memory state
_categories: Dict[str, dict] = _load_custom_categories()
_engine    = IntensityEngine()
_avail     = AvailabilityService()
_scheduler = SmartScheduler(_avail, _engine)
_service:  GoogleCalendarService | None = None
_cache:    List[CalendarEvent]          = []


# ── Service singleton ────────────────────────────────────────────────────────
def get_service() -> GoogleCalendarService:
    global _service
    if _service is None:
        _service = GoogleCalendarService()
    return _service


# ── Event loader + serialiser ────────────────────────────────────────────────
def _load_events() -> List[CalendarEvent]:
    global _cache
    # FIX: start 7 days ago so recently created events always appear
    now    = datetime.now(timezone.utc) - timedelta(days=7)
    future = now + timedelta(days=LOOK_AHEAD_DAYS + 7)
    raw    = get_service().get_consolidated_events(CALENDARS, now, future)
    _cache = _engine.score_and_label(raw)
    return _cache


def _serial_event(e: CalendarEvent) -> dict:
    try:
        start_label = e.start.strftime("%a %d %b  %H:%M")
        end_label   = e.end.strftime("%H:%M")
    except Exception:
        start_label = str(e.start)
        end_label   = str(e.end)

    cat_id    = getattr(e, "_custom_category", e.calendar_type.value)
    cat_info  = _categories.get(cat_id, _categories.get(e.calendar_type.value, {}))

    return {
        "uid":             e.uid,
        "title":           e.title,
        "start":           e.start.isoformat(),
        "end":             e.end.isoformat(),
        "start_label":     start_label,
        "end_label":       end_label,
        "duration_min":    e.duration_minutes,
        "calendar_type":   e.calendar_type.value,
        "category_id":     cat_id,
        "category_label":  cat_info.get("label", cat_id),
        "category_color":  cat_info.get("color", "#6b6f83"),
        "description":     e.description or "",
        "location":        e.location or "",
        "attendees":       e.attendees or [],
        "is_all_day":      e.is_all_day,
        "intensity_score": e.intensity_score,
        "intensity":       e.intensity.name,
    }


def _serial_slot(s) -> dict:
    return {
        "start":       s.start.isoformat(),
        "end":         s.end.isoformat(),
        "start_label": s.start.strftime("%a %d %b  %H:%M"),
        "end_label":   s.end.strftime("%H:%M"),
        "duration":    s.duration_minutes,
        "day_load":    s.day_load_score,
    }


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ════════════════════════════════════════════════════════════════════════════
#  Routes
# ════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


# ── 1 · Events ───────────────────────────────────────────────────────────────
@app.route("/api/events")
def api_events():
    try:
        events = _load_events()
        # FIX: only filter when cat is a non-empty known value
        cat = request.args.get("category", "").strip().lower()
        if cat:
            # match both built-in CalendarType and custom category ids
            events = [e for e in events
                      if e.calendar_type.value == cat
                      or getattr(e, "_custom_category", "") == cat]
        return jsonify({
            "ok":     True,
            "events": [_serial_event(e) for e in events],
            "total":  len(events),
        })
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 500


# ── 2 · Day report ───────────────────────────────────────────────────────────
@app.route("/api/day_report")
def api_day_report():
    global _cache
    # Auto-fetch if cache is empty — no more "sync first" errors
    if not _cache:
        try:
            _load_events()
        except Exception as exc:
            traceback.print_exc()
            return jsonify({"ok": False, "error": f"Could not load events: {exc}"}), 500

    if not _cache:
        return jsonify({"ok": True, "days": []})   # nothing in calendar = empty list, not error

    by_day: dict = {}
    for e in _cache:
        k = e.start.strftime("%Y-%m-%d")
        by_day.setdefault(k, []).append(e)

    days = []
    for k in sorted(by_day):
        evts = by_day[k]
        rpt  = DayIntensityReport(date=evts[0].start, events=evts)
        days.append({
            "date":            k,
            "day_label":       evts[0].start.strftime("%A %d %b"),
            "event_count":     rpt.event_count,
            "total_hours":     round(rpt.total_hours, 1),
            "intensity_score": rpt.total_intensity_score,
            "avg_score":       rpt.average_intensity_score,
            "intensity":       rpt.day_intensity.name,
            "events":          [_serial_event(e) for e in evts],
        })
    return jsonify({"ok": True, "days": days})


# ── 3 · Availability ─────────────────────────────────────────────────────────
@app.route("/api/availability", methods=["GET"])
def api_avail_get():
    return jsonify({"ok": True, "windows": [
        {"day": w.day, "day_name": w.day_name,
         "start_time": w.start_time, "end_time": w.end_time,
         "is_available": w.is_available}
        for w in [_avail.windows.get(d) for d in range(7)] if w
    ]})

@app.route("/api/availability", methods=["POST"])
def api_avail_set():
    d = request.json or {}
    _avail.set_window(int(d.get("day",0)), d.get("start_time","08:00"),
                      d.get("end_time","17:30"), bool(d.get("is_available",True)))
    return jsonify({"ok": True})


# ── 4 · Free slots ───────────────────────────────────────────────────────────
@app.route("/api/slots")
def api_slots():
    duration = int(request.args.get("duration", 30))
    today    = date.today()
    end_date = today + timedelta(days=LOOK_AHEAD_DAYS)
    slots    = _avail.find_slot_for_duration(_cache, today, end_date, duration)
    return jsonify({"ok": True, "slots": [_serial_slot(s) for s in slots[:60]]})


# ── 5 · Book single event ────────────────────────────────────────────────────
@app.route("/api/book", methods=["POST"])
def api_book():
    d = request.json or {}
    missing = [f for f in ("name","email","start","end") if not d.get(f)]
    if missing:
        return jsonify({"ok":False,"error":f"Missing: {', '.join(missing)}"}), 400
    try:
        start_dt = _parse_dt(d["start"])
        end_dt   = _parse_dt(d["end"])
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(minutes=int(d.get("duration",30)))
        booking = BookingRequest(
            attendee_name    = d["name"].strip(),
            attendee_email   = d["email"].strip(),
            event_title      = (d.get("title") or "Meeting").strip(),
            duration_minutes = int(d.get("duration",30)),
            selected_start   = start_dt,
            selected_end     = end_dt,
            description      = (d.get("description") or "").strip(),
        )
        eid = get_service().create_event(
            PRIMARY_CALENDAR, booking, attendees=[d["email"].strip()])
        return jsonify({"ok":True,"id":eid,
                        "message":f"Event created. Invite sent to {d['email']}."})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok":False,"error":str(exc)}), 500


# ── 6 · Team event ───────────────────────────────────────────────────────────
@app.route("/api/team_event", methods=["POST"])
def api_team_event():
    d = request.json or {}

    # Parse emails
    raw = d.get("emails", [])
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.replace("\n",",").split(",")]
    seen, emails = set(), []
    for e in raw:
        e = e.strip().lower()
        if e and "@" in e and "." in e and e not in seen:
            emails.append(e); seen.add(e)
    if not emails:
        return jsonify({"ok":False,"error":"No valid email addresses provided."}), 400
    emails = emails[:50]

    try:
        start_dt = _parse_dt(d["start"])
        end_dt   = _parse_dt(d["end"])
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(minutes=int(d.get("duration",60)))
    except (KeyError, ValueError) as exc:
        return jsonify({"ok":False,"error":f"Invalid datetime: {exc}"}), 400

    # Build a description that tags the category so it's visible after re-fetch
    cat_id    = (d.get("category") or "work").strip().lower()
    cat_label = _categories.get(cat_id, {}).get("label", cat_id)
    desc_parts = []
    if d.get("description","").strip():
        desc_parts.append(d["description"].strip())
    desc_parts.append(f"[Category: {cat_label}]")
    desc_parts.append(f"[Scheduled via CalendarScheduler — Team Event]")
    full_desc = "\n".join(desc_parts)

    booking = BookingRequest(
        attendee_name    = (d.get("organizer_name") or "Organizer").strip(),
        attendee_email   = emails[0],
        event_title      = (d.get("title") or "Team Meeting").strip(),
        duration_minutes = int(d.get("duration",60)),
        selected_start   = start_dt,
        selected_end     = end_dt,
        description      = full_desc,
    )
    try:
        eid = get_service().create_event(PRIMARY_CALENDAR, booking, attendees=emails)
        return jsonify({
            "ok":True,"id":eid,"count":len(emails),
            "message":f"'{booking.event_title}' created. {len(emails)} invite(s) sent.",
        })
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok":False,"error":str(exc)}), 500


# ── 7 · Delete event ─────────────────────────────────────────────────────────
@app.route("/api/delete/<event_id>", methods=["DELETE"])
def api_delete(event_id):
    global _cache
    try:
        get_service().delete_event(PRIMARY_CALENDAR, event_id)
        _cache = [e for e in _cache if e.uid != event_id]
        return jsonify({"ok":True,"message":"Event deleted."})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"ok":False,"error":str(exc)}), 500


# ── 8 · Intensity scorer ─────────────────────────────────────────────────────
@app.route("/api/intensity", methods=["POST"])
def api_intensity():
    d            = request.json or {}
    title        = d.get("title","")
    description  = d.get("description","")
    duration_min = int(d.get("duration_min",30))
    attendees_n  = int(d.get("attendee_count",0))
    cal_str      = d.get("calendar_type","personal")
    start_hour   = int(d.get("start_hour",9))

    cal_map  = {"work":CalendarType.WORK,"personal":CalendarType.PERSONAL,"other":CalendarType.OTHER}
    cal_type = cal_map.get(cal_str.lower(), CalendarType.PERSONAL)

    fake_start = datetime(2025,1,6,start_hour,0,tzinfo=timezone.utc)
    fake_end   = fake_start + timedelta(minutes=max(1,duration_min))
    fake       = CalendarEvent(
        uid="__preview__", title=title, start=fake_start, end=fake_end,
        calendar_type=cal_type, description=description,
        attendees=[f"a{i}@x.com" for i in range(attendees_n)],
    )
    score     = max(0,min(100,_engine.score_event(fake,[])))
    intensity = _engine._score_to_intensity(score)

    text    = (title+" "+description).lower()
    kw_crit = [k for k in CRITICAL_KEYWORDS if k in text]
    kw_high = [k for k in HIGH_KEYWORDS     if k in text]
    kw_low  = [k for k in LOW_KEYWORDS      if k in text]

    dur_pts = int((min(duration_min,180)/180)*20)
    att_pts = min(attendees_n*3,15)
    cal_pts = 10 if cal_type==CalendarType.WORK else 0
    tod_pts = (8 if (start_hour<8 or start_hour>=18) else -5 if 12<=start_hour<=13 else 0)
    kw_pts  = 30 if kw_crit else (20 if kw_high else (-10 if kw_low else 0))

    return jsonify({
        "ok":True,"score":score,"intensity":intensity.name,
        "factors":[
            {"label":"Keywords",     "points":kw_pts, "detail":", ".join(kw_crit or kw_high or kw_low) or "none matched"},
            {"label":"Duration",     "points":dur_pts,"detail":f"{duration_min}min"},
            {"label":"Attendees",    "points":att_pts,"detail":f"{attendees_n} attendee(s)"},
            {"label":"Calendar type","points":cal_pts,"detail":cal_str},
            {"label":"Time of day",  "points":tod_pts,"detail":f"{start_hour:02d}:00"},
            {"label":"Day density",  "points":0,      "detail":"n/a for preview"},
        ],
        "keywords":{"critical":kw_crit,"high":kw_high,"low":kw_low},
    })


# ── 9 · Smart Scheduler ──────────────────────────────────────────────────────
@app.route("/api/smart_schedule")
def api_smart_schedule():
    duration   = int(request.args.get("duration",60))
    category   = request.args.get("category","").strip().lower()
    prefer_low = request.args.get("prefer","low_intensity")=="low_intensity"
    events     = list(_cache)
    if category:
        events = [e for e in events if e.calendar_type.value==category]
    slots = _scheduler.find_best_slots(events,duration,top_n=5,prefer_low_intensity=prefer_low)
    return jsonify({"ok":True,"duration":duration,"slots":slots})


# ── 10 · Custom Categories  GET / POST / DELETE ───────────────────────────────
@app.route("/api/categories", methods=["GET"])
def api_categories_get():
    return jsonify({"ok":True,"categories":list(_categories.values())})


@app.route("/api/categories", methods=["POST"])
def api_categories_post():
    global _categories
    d     = request.json or {}
    label = (d.get("label") or "").strip()
    color = (d.get("color") or "#4f8ef7").strip()
    if not label:
        return jsonify({"ok":False,"error":"Label required"}), 400
    # Generate id from label
    cat_id = label.lower().replace(" ","_")[:24]
    if cat_id in _categories and _categories[cat_id].get("builtin"):
        return jsonify({"ok":False,"error":"Cannot overwrite built-in category"}), 400
    _categories[cat_id] = {"id":cat_id,"label":label,"color":color,"builtin":False}
    _save_custom_categories(_categories)
    return jsonify({"ok":True,"category":_categories[cat_id]})


@app.route("/api/categories/<cat_id>", methods=["DELETE"])
def api_categories_delete(cat_id):
    global _categories
    if cat_id not in _categories:
        return jsonify({"ok":False,"error":"Not found"}), 404
    if _categories[cat_id].get("builtin"):
        return jsonify({"ok":False,"error":"Cannot delete built-in category"}), 400
    del _categories[cat_id]
    _save_custom_categories(_categories)
    return jsonify({"ok":True})


# ── startup ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n  CalendarScheduler -> http://127.0.0.1:5000\n")
    app.run(debug=True, port=5000, use_reloader=False)
