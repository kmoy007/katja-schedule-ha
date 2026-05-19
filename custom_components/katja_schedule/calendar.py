"""Single unified calendar entity exposing all schedule events.

Each event carries metadata in its ``description`` for the custom card to
parse:

    Who: Katja
    Status: new        # calendar | manual | new | changed | conflict
                       # | orphan | hidden_rule | hidden_oneoff
    Where: ...
    Flight: BA279 LAX→LHR
    DtEnd: 2026-05-28  # inclusive last day for multi-day spans
                       # (fr-2026-05-18-a / fr-2026-05-19-b — the card
                       # uses this to fan the row across each spanned
                       # day with italic/faded continuation styling)
    Starred: 1         # household-starred toggle state (fr-2026-05-19
                       # gap analysis — surfaces per-row star state so
                       # the card can render a star indicator + an
                       # accurate Star/Unstar button in the modal)

Status mirrors renderer.py classification on the web app, so the HA card can
show the same set of categories as the schedule UI (pending review,
cancelled/skipped, hidden-by-rule, hidden-one-off).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_API_URL, stable_id
from .coordinator import KatjaScheduleCoordinator
from .time_parser import event_to_datetimes

_LOGGER = logging.getLogger(__name__)

# Keep COMPARE_FIELDS in sync with renderer.py — these are the fields whose
# divergence between overlay and calendar cache marks an event as "changed".
COMPARE_FIELDS = ("date", "time", "what", "where")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KatjaScheduleCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [KatjaScheduleCalendar(coordinator, entry)],
        update_before_add=True,
    )


# Comparison normalization — must match renderer._normalize_for_diff on the
# web app side. Without this, Google iCal description churn (line endings,
# blank lines that become " · · " runs) flags events as CHANGED on every
# refresh even though the user hasn't modified anything.
import re as _re
_WS_RE = _re.compile(r"\s+")
_BULLET_RUN_RE = _re.compile(r"(\s*·\s*){2,}")


def _normalize_for_diff(s: str) -> str:
    if not s:
        return ""
    s = _BULLET_RUN_RE.sub(" · ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def _fields_differ(a: dict, b: dict) -> list[str]:
    return [
        f for f in COMPARE_FIELDS
        if _normalize_for_diff(a.get(f) or "") != _normalize_for_diff(b.get(f) or "")
    ]


def _matches_pruning_rule(rules: list[dict], ev: dict) -> bool:
    """Local copy of rules.pruning_pattern_matches — the integration ships
    standalone so it can't import the web app's modules. Behaviour must match
    the server side: contains/exact/starts_with on `what`, optional source
    scoping by calendar_label."""
    what = (ev.get("what") or "").lower()
    label = ev.get("calendar_label") or ""
    for r in rules or []:
        pat = (r.get("pattern") or "").strip().lower()
        if not pat:
            continue
        sources = r.get("sources") or []
        if sources and label not in sources:
            continue
        mode = r.get("match_mode") or "contains"
        if mode == "exact":
            if what == pat:
                return True
        elif mode == "starts_with":
            if what.startswith(pat):
                return True
        else:  # contains
            if pat in what:
                return True
    return False


def _classify_events(overlay: dict, cal_cache: dict) -> list[dict]:
    """Return all events tagged with status. Mirrors renderer.py except it
    also emits hidden categories so the card can reveal them under a toggle."""
    manual_events = overlay.get("manual_events", []) or []
    cal_events = cal_cache.get("events", []) or []
    excluded_ids = set(overlay.get("excluded_ids", []) or [])
    rules = overlay.get("pruning_rules", []) or []

    cal_by_id = {e["event_id"]: e for e in cal_events if e.get("event_id")}
    overlay_ids = {e.get("event_id") for e in manual_events if e.get("event_id")}
    have_sync = bool(cal_events)

    rows: list[dict] = []

    # 1) Overlay (curated) rows
    for ev in manual_events:
        row = dict(ev)
        ev_id = ev.get("event_id")
        if ev_id and ev_id in cal_by_id:
            cal_ev = cal_by_id[ev_id]
            diffs = _fields_differ(ev, cal_ev)
            if diffs:
                hand_edited = set(ev.get("hand_edited_fields") or [])
                row["status"] = (
                    "conflict" if any(f in hand_edited for f in diffs)
                    else "changed"
                )
            else:
                row["status"] = "calendar"
        elif ev_id and have_sync:
            row["status"] = "orphan"
        else:
            row["status"] = "manual" if ev.get("source") == "manual" else "calendar"
        rows.append(row)

    # 2) Calendar events not in overlay → "new" (pending) or hidden
    for cev in cal_events:
        ev_id = cev.get("event_id")
        if not ev_id or ev_id in overlay_ids:
            continue
        row = dict(cev)
        if ev_id in excluded_ids:
            row["status"] = (
                "hidden_rule" if _matches_pruning_rule(rules, cev)
                else "hidden_oneoff"
            )
        else:
            row["status"] = "new"
        rows.append(row)
    return rows


def _to_calendar_event(ev: dict) -> CalendarEvent | None:
    event_date = ev.get("date", "")
    time_str = ev.get("time", "")
    if not event_date:
        return None
    try:
        start, end = event_to_datetimes(event_date, time_str)
    except Exception:
        return None

    # fr-2026-05-18-a / fr-2026-05-19-b: multi-day spanning events carry
    # `dt_end` (inclusive last day per the overlay convention) so the web
    # app can fan the row onto every day it covers. Mirror that here:
    # extend the HA event's `end` to dt_end+1 day (HA all-day end is
    # exclusive) so stock HA calendar cards render the full banner, and
    # surface `DtEnd` in the description so the custom card can render
    # italic/faded continuation rows on intermediate days.
    dt_end_str = (ev.get("dt_end") or "").strip()
    has_multi_day = bool(dt_end_str and dt_end_str > event_date)
    if has_multi_day:
        try:
            end_d = date.fromisoformat(dt_end_str)
            if isinstance(end, datetime):
                # Timed event whose span crosses midnight into later
                # days — anchor end at end-of-dt_end in Pacific so the
                # banner length is correct.
                end = datetime(end_d.year, end_d.month, end_d.day,
                                23, 59, tzinfo=ZoneInfo("America/Los_Angeles"))
            else:
                end = end_d + timedelta(days=1)
        except ValueError:
            has_multi_day = False

    summary = ev.get("what", "") or ""
    if "drive" in summary.lower():
        summary = f"\U0001f697 {summary}"

    parts: list[str] = []
    if ev.get("who"):
        parts.append(f"Who: {ev['who']}")
    status = ev.get("status", "")
    if status:
        parts.append(f"Status: {status}")
    if ev.get("where"):
        parts.append(f"Where: {ev['where']}")
    if ev.get("flight"):
        f = ev["flight"]
        parts.append(
            f"Flight: {f.get('number','')} "
            f"{f.get('origin','')}→{f.get('destination','')}"
        )
    if ev.get("calendar_label"):
        parts.append(f"Source: {ev['calendar_label']}")
    # Card-only: surface the overlay event_id so the Skip-this-week button
    # can POST to /api/actions/skip-week/<id>. HA's CalendarEvent doesn't
    # expose ids in the calendar API response, and stuffing it into the
    # description is the same pattern Who/Status/Source already use. Last
    # line so it's least obtrusive in stock HA calendar cards.
    if ev.get("event_id"):
        parts.append(f"EventId: {ev['event_id']}")
    if has_multi_day:
        parts.append(f"DtEnd: {dt_end_str}")
    if ev.get("starred"):
        parts.append("Starred: 1")

    return CalendarEvent(
        summary=summary,
        start=start,
        end=end,
        location=ev.get("where", "") or "",
        description="\n".join(parts) if parts else None,
    )


def _is_hidden(ev: dict) -> bool:
    return ev.get("status") in ("hidden_rule", "hidden_oneoff")


def _is_flagged_text(what: str) -> bool:
    """Cancelled/skipped events keep the marker in `what` itself."""
    upper = (what or "").upper()
    return "CANCELLED" in upper or "SKIPPED" in upper


class KatjaScheduleCalendar(CoordinatorEntity, CalendarEntity):
    """Single calendar entity — all events, all categories.

    The custom card filters categories via the description's Status: line.
    Stock HA calendar cards will see every event including hidden ones.
    """

    def __init__(
        self,
        coordinator: KatjaScheduleCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        api_url = entry.data.get(CONF_API_URL, "")
        self._attr_unique_id = stable_id(api_url, "all")
        self._attr_name = "Schedule"

    def _all_rows(self) -> list[dict]:
        if not self.coordinator.data:
            return []
        overlay = self.coordinator.data.get("overlay", {}) or {}
        cal_cache = self.coordinator.data.get("calendar_cache", {}) or {}
        return _classify_events(overlay, cal_cache)

    @staticmethod
    def _ts(d) -> float:
        if isinstance(d, datetime):
            return d.timestamp()
        return datetime(d.year, d.month, d.day).timestamp()

    @property
    def event(self) -> CalendarEvent | None:
        """Next visible upcoming event — used as entity state. Hidden and
        cancelled/skipped events are excluded from the state but still
        returned by async_get_events."""
        try:
            now_ts = datetime.now().astimezone().timestamp()
            best, best_ts = None, None
            for ev in self._all_rows():
                if _is_hidden(ev) or _is_flagged_text(ev.get("what", "")):
                    continue
                cal_ev = _to_calendar_event(ev)
                if cal_ev is None:
                    continue
                ts = self._ts(cal_ev.start)
                if ts < now_ts:
                    continue
                if best_ts is None or ts < best_ts:
                    best, best_ts = cal_ev, ts
            return best
        except Exception as exc:
            _LOGGER.debug("Error in event property: %s", exc)
            return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime,
    ) -> list[CalendarEvent]:
        sd = start_date.date() if isinstance(start_date, datetime) else start_date
        ed = end_date.date() if isinstance(end_date, datetime) else end_date
        out: list[CalendarEvent] = []
        for ev in self._all_rows():
            ds = ev.get("date", "")
            if not ds:
                continue
            try:
                d = date.fromisoformat(ds)
            except ValueError:
                continue
            if d < sd or d > ed:
                continue
            cal_ev = _to_calendar_event(ev)
            if cal_ev:
                out.append(cal_ev)
        return out
