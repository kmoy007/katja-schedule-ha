"""Parse the schedule app's time strings into (hour, minute) tuples.

Ported from ical_feed.py — handles the same formats:
  - "All day" / "—"
  - Ranges: "5:15–6:45 PM", "8:30 AM–2:30 PM", "3:30–5:00 PM"
  - Single times: "7:30 PM" (default 30 min duration)
  - Unparseable: "After match" → treated as unknown
"""
from __future__ import annotations

import re
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

LA = ZoneInfo("America/Los_Angeles")

_TIME_PAIR_RE = re.compile(r"\s*[–—-]\s*", re.UNICODE)
_TIME_SINGLE_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.IGNORECASE)
_AMPM_RE = re.compile(r"\b(am|pm)\b", re.IGNORECASE)


def _parse_single(s: str) -> tuple[int, int] | None:
    if not s:
        return None
    m = _TIME_SINGLE_RE.search(s)
    if not m:
        return None
    hr = int(m.group(1))
    mn = int(m.group(2) or "0")
    ampm = (m.group(3) or "").lower()
    if ampm == "pm" and hr != 12:
        hr += 12
    if ampm == "am" and hr == 12:
        hr = 0
    if 0 <= hr <= 23 and 0 <= mn <= 59:
        return (hr, mn)
    return None


def parse_time(time_str: str) -> dict:
    """Return {kind, start, end} where start/end are (h,m) or None."""
    if not time_str or not time_str.strip():
        return {"kind": "unknown"}
    t = time_str.strip()
    tl = t.lower()
    if tl.startswith("all day") or tl == "—":
        return {"kind": "all_day"}

    parts = _TIME_PAIR_RE.split(t, maxsplit=1)
    if len(parts) == 2 and re.search(r"\d", parts[0]) and re.search(r"\d", parts[1]):
        start_str, end_str = parts[0], parts[1]
        if not _AMPM_RE.search(start_str):
            end_ampm = _AMPM_RE.search(end_str)
            if end_ampm:
                start_str = f"{start_str} {end_ampm.group(1)}"
        start_hm = _parse_single(start_str)
        end_hm = _parse_single(end_str)
        if start_hm and end_hm:
            return {"kind": "range", "start": start_hm, "end": end_hm}

    hm = _parse_single(t)
    if hm:
        return {"kind": "single", "start": hm, "end": None}

    return {"kind": "unknown"}


def event_to_datetimes(
    event_date: str, time_str: str,
) -> tuple[datetime | date, datetime | date]:
    """Convert an event's date + time string to HA-compatible start/end.

    Returns aware datetimes for timed events or date objects for all-day.
    """
    d = date.fromisoformat(event_date)
    parsed = parse_time(time_str)
    kind = parsed["kind"]

    if kind == "all_day" or kind == "unknown":
        return d, d + timedelta(days=1)

    if kind == "range":
        sh, sm = parsed["start"]
        eh, em = parsed["end"]
        start = datetime(d.year, d.month, d.day, sh, sm, tzinfo=LA)
        end = datetime(d.year, d.month, d.day, eh, em, tzinfo=LA)
        if end <= start:
            end += timedelta(days=1)
        return start, end

    # Single time — 30 min default duration
    sh, sm = parsed["start"]
    start = datetime(d.year, d.month, d.day, sh, sm, tzinfo=LA)
    return start, start + timedelta(minutes=30)
