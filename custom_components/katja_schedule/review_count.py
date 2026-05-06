"""Pure-Python unified review count — calendar-diff items + agent
proposals folded by event_id, mirroring the web app's
`build_review_inbox` so the HA pending-review sensor matches the
"X awaiting review" badge on the schedule page (fr-2026-05-05-f
reopened scope).

This module deliberately has zero `homeassistant.*` imports so it can
be unit-tested without a HA test harness.
"""
from __future__ import annotations

REVIEW_STATUSES = ("new", "changed", "orphan", "conflict")
EVENT_ID_PROPOSAL_KINDS = ("accept", "hide", "merge")


def unified_review_count(classified_events: list[dict],
                          overlay: dict) -> int:
    """Number of distinct items awaiting human decision.

    `classified_events` is the output of `calendar._classify_events`
    (already filtered or unfiltered — we filter here). `overlay` is the
    raw overlay dict; we read `proposed_edits` for pending proposals.

    Folding rule: a calendar-diff item and a proposal that share an
    `args.event_id` count as one. Proposals on the same event_id with
    no calendar-diff match also fold together. Proposals without an
    event_id (manual `add` / `update` / `remove`) always count as
    standalone entries.
    """
    cal_eids: set[str] = set()
    groups = 0
    for r in classified_events or []:
        if r.get("status") not in REVIEW_STATUSES:
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
                      overlay: dict) -> dict:
    """Per-status counts plus a `proposed` total — used by the sensor's
    `extra_state_attributes` so HA dashboards can break the unified
    number down (e.g. "12 awaiting (4 new, 1 changed, 7 proposed)")."""
    counts = {s: 0 for s in REVIEW_STATUSES}
    for r in classified_events or []:
        s = r.get("status", "")
        if s in counts:
            counts[s] += 1
    counts["proposed"] = sum(
        1 for e in (overlay.get("proposed_edits") or [])
        if e.get("status") == "pending"
    )
    return counts
