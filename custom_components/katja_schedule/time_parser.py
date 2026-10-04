"""Read the schedule app's time strings into start and end times.

A port of the web app's `ical_feed.clock_span`, the server's one reading
of a row's display time (its calendar feed, the iPhone app and its drive
lookups use it), because this integration ships on its own and can't
import it. The main repo's tests/time_span_cases.json holds this copy, the
server and the web's day grid to one table; change them together.

  - "All day" / "—" / no clock time ("TBD", "After 3"): all day
  - Ranges: "5:15–6:45 PM" (the start shares the PM), "11:30–1:00 PM" (a
    start that took the end's PM and came out after the end is the
    morning), "10:00 PM–1:00 AM" (an end before the start is the next
    day's), "11:00–1:00" (no AM/PM: crossing noon)
  - Single times: "7:30 PM", "9 AM", "17:30" alone, "U10 at 4:15 PM"
    (30 min default duration); a bare number or a time with no AM/PM
    among words ("Leave 3:30") is no clock time
"""
from __future__ import annotations

import re
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

LA = ZoneInfo("America/Los_Angeles")

_TIME_PAIR_RE = re.compile(r"\s*[–—-]\s*", re.UNICODE)
_TIME_SINGLE_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(?:(am|pm)\b)?", re.IGNORECASE)
_AMPM_RE = re.compile(r"\b(am|pm)\b", re.IGNORECASE)
_NOON_RE = re.compile(r"\bnoon\b", re.IGNORECASE)
_MIDNIGHT_RE = re.compile(r"\bmidnight\b", re.IGNORECASE)


def _parse_single(s: str) -> tuple[int, int] | None:
    text = (s or "").strip()
    for m in _TIME_SINGLE_RE.finditer(text):
        alone = m.group(2) is not None and m.group(0).strip() == text
        if not m.group(3) and not alone:
            continue
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
    """Return {kind, start, end} where start/end are (h,m) or None; a
    range also says whether its start took the end's AM/PM and whether
    the end had its own."""
    if not time_str or not time_str.strip():
        return {"kind": "unknown"}
    t = time_str.strip()
    tl = t.lower()
    if tl.startswith("all day") or tl == "—":
        return {"kind": "all_day"}
    t = _MIDNIGHT_RE.sub("12:00 AM", _NOON_RE.sub("12:00 PM", t))

    parts = _TIME_PAIR_RE.split(t, maxsplit=1)
    if len(parts) == 2 and re.search(r"\d", parts[0]) and re.search(r"\d", parts[1]):
        start_str, end_str = parts[0], parts[1]
        end_ampm = _AMPM_RE.search(end_str)
        borrowed = not _AMPM_RE.search(start_str) and bool(end_ampm)
        if borrowed:
            start_str = f"{start_str} {end_ampm.group(1)}"
        start_hm = _parse_single(start_str)
        end_hm = _parse_single(end_str)
        if start_hm and end_hm:
            return {"kind": "range", "start": start_hm, "end": end_hm,
                    "borrowed": borrowed, "end_meridiem": bool(end_ampm)}

    hm = _parse_single(t)
    if hm:
        return {"kind": "single", "start": hm, "end": None}

    return {"kind": "unknown"}


def clock_span(time_str: str) -> tuple[int, int | None] | None:
    """(start, end) in minutes from midnight, an end past midnight 1440
    more, end None for one time; None with no clock time."""
    parsed = parse_time(time_str)
    if parsed["kind"] not in ("range", "single"):
        return None
    sh, sm = parsed["start"]
    start, end = sh * 60 + sm, None
    if parsed["kind"] == "range":
        eh, em = parsed["end"]
        end = eh * 60 + em
        half = 12 * 60
        if parsed["borrowed"] and start > end:
            start += -half if start >= half else half
        if end < start:
            crosses_noon = not parsed["end_meridiem"] and end + half > start
            end += half if crosses_noon else 2 * half
    return start, end


def event_to_datetimes(
    event_date: str, time_str: str,
) -> tuple[datetime | date, datetime | date]:
    """Convert an event's date + time string to HA-compatible start/end.

    Returns aware datetimes for timed events or date objects for all-day.
    One time, or a zero-length range, gets half an hour, as the server's
    calendar feed gives it: an end must come after the start.
    """
    d = date.fromisoformat(event_date)
    span = clock_span(time_str)
    if span is None:
        return d, d + timedelta(days=1)

    def at(minutes: int) -> datetime:
        day = d + timedelta(days=minutes // (24 * 60))
        clock = minutes % (24 * 60)
        return datetime(day.year, day.month, day.day, clock // 60, clock % 60, tzinfo=LA)

    start_min, end_min = span
    start = at(start_min)
    if end_min is None or end_min <= start_min:
        return start, start + timedelta(minutes=30)
    return start, at(end_min)
