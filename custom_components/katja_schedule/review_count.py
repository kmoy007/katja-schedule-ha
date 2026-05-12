"""Pure-Python unified review count — calendar-diff items + agent
proposals folded by event_id, mirroring the web app's
`build_review_inbox` so the HA pending-review sensor matches the
"X awaiting review" badge on the schedule page (fr-2026-05-05-f
reopened scope).

This module deliberately has zero `homeassistant.*` imports so it can
be unit-tested without a HA test harness.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

try:
    from zoneinfo import ZoneInfo  # py3.9+
except ImportError:  # pragma: no cover — HA runs on 3.11+
    ZoneInfo = None  # type: ignore

REVIEW_STATUSES = ("new", "changed", "orphan", "conflict")
EVENT_ID_PROPOSAL_KINDS = ("accept", "hide", "merge")

# Match the web app's `build_review_inbox` cutoff (fr-2026-05-10-b in
# app.py): calendar-diff items for dates older than today − 2 (Pacific)
# stop counting. Past CHANGED/ORPHAN rows would otherwise pile up
# forever — a calendar-ingest schema change can surface dozens of
# stale rows the user has no intention of triaging, inflating the HA
# pending-pill while the web review queue (which already filters)
# stays empty.
_PACIFIC_CUTOFF_DAYS = 2


def _pacific_cutoff_iso(today: Optional[date] = None) -> str:
    """Return the inclusive lower bound (ISO date string) for review
    items. Rows with `date < cutoff_iso` are dropped from the count.
    `today` is injectable so tests can pin the cutoff deterministically.
    """
    if today is None:
        if ZoneInfo is not None:
            from datetime import datetime
            today = datetime.now(ZoneInfo("America/Los_Angeles")).date()
        else:  # pragma: no cover
            today = date.today()
    return (today - timedelta(days=_PACIFIC_CUTOFF_DAYS)).isoformat()


def unified_review_count(classified_events: list[dict],
                          overlay: dict,
                          today: Optional[date] = None) -> int:
    """Number of distinct items awaiting human decision.

    `classified_events` is the output of `calendar._classify_events`
    (already filtered or unfiltered — we filter here). `overlay` is the
    raw overlay dict; we read `proposed_edits` for pending proposals.

    Folding rule: a calendar-diff item and a proposal that share an
    `args.event_id` count as one. Proposals on the same event_id with
    no calendar-diff match also fold together. Proposals without an
    event_id (manual `add` / `update` / `remove`) always count as
    standalone entries.

    Calendar-diff items dated before `today - 2 days` (Pacific) are
    dropped, matching the web `build_review_inbox` cutoff. Agent
    proposals are NOT date-filtered — a proposal queued against a past
    row may still be intentional and should remain actionable.
    """
    cutoff_iso = _pacific_cutoff_iso(today)
    cal_eids: set[str] = set()
    groups = 0
    for r in classified_events or []:
        if r.get("status") not in REVIEW_STATUSES:
            continue
        if (r.get("date") or "") < cutoff_iso:
            continue
        eid = r.get("event_id") or ""
        if eid:
            cal_eids.add(eid)
        groups += 1

    seen_proposal_eids: set[str] = set()
    for p in (overlay.get("proposed_edits") or []):
        if p.get("status") != "pending":
            continue
        eid = ""
        if p.get("kind") in EVENT_ID_PROPOSAL_KINDS:
            eid = (p.get("args") or {}).get("event_id") or ""
        if eid:
            if eid in cal_eids or eid in seen_proposal_eids:
                continue
            seen_proposal_eids.add(eid)
            groups += 1
        else:
            groups += 1
    return groups


def review_breakdown(classified_events: list[dict],
                      overlay: dict,
                      today: Optional[date] = None) -> dict:
    """Per-status counts plus a `proposed` total — used by the sensor's
    `extra_state_attributes` so HA dashboards can break the unified
    number down (e.g. "12 awaiting (4 new, 1 changed, 7 proposed)").

    Applies the same past-event cutoff as `unified_review_count` so
    breakdown + total stay consistent.
    """
    cutoff_iso = _pacific_cutoff_iso(today)
    counts = {s: 0 for s in REVIEW_STATUSES}
    for r in classified_events or []:
        s = r.get("status", "")
        if s not in counts:
            continue
        if (r.get("date") or "") < cutoff_iso:
            continue
        counts[s] += 1
    counts["proposed"] = sum(
        1 for e in (overlay.get("proposed_edits") or [])
        if e.get("status") == "pending"
    )
    return counts
