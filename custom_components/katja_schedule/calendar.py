"""Calendar entities — one per family member + a shared calendar."""
from __future__ import annotations

import logging
from datetime import date, datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, FAMILY_MEMBERS, SHARED_KEYWORDS
from .coordinator import KatjaScheduleCoordinator
from .time_parser import event_to_datetimes

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KatjaScheduleCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for member in FAMILY_MEMBERS:
        entities.append(KatjaPersonCalendar(coordinator, entry, member))
    entities.append(KatjaPersonCalendar(coordinator, entry, "Shared"))
    async_add_entities(entities, update_before_add=True)


def _matches_person(who: str, person: str) -> bool:
    """Does the event's 'who' field belong to this person's calendar?"""
    if not who:
        return person == "Shared"
    wl = who.lower().strip()
    if person == "Shared":
        return any(kw in wl for kw in SHARED_KEYWORDS) or not any(
            m.lower() in wl for m in FAMILY_MEMBERS
        )
    return person.lower() in wl


def _event_to_calendar_event(ev: dict) -> CalendarEvent | None:
    """Convert an overlay event dict to a HA CalendarEvent."""
    event_date = ev.get("date", "")
    time_str = ev.get("time", "")
    if not event_date:
        return None
    try:
        start, end = event_to_datetimes(event_date, time_str)
    except (ValueError, TypeError):
        return None

    summary = ev.get("what", "")
    is_drive = "drive" in summary.lower()
    if is_drive:
        summary = f"\U0001f697 {summary}"

    description_parts = []
    if ev.get("where"):
        description_parts.append(ev["where"])
    status = ev.get("status", "")
    if status and status not in ("manual", "calendar"):
        description_parts.append(f"Status: {status}")
    if ev.get("flight"):
        f = ev["flight"]
        description_parts.append(
            f"Flight: {f.get('number', '')} {f.get('origin', '')}→{f.get('destination', '')}"
        )

    return CalendarEvent(
        summary=summary,
        start=start,
        end=end,
        location=ev.get("where", ""),
        description="\n".join(description_parts) if description_parts else None,
    )


class KatjaPersonCalendar(CoordinatorEntity, CalendarEntity):
    """Calendar entity for one family member (or the shared calendar)."""

    def __init__(
        self,
        coordinator: KatjaScheduleCoordinator,
        entry: ConfigEntry,
        person: str,
    ) -> None:
        super().__init__(coordinator)
        self._person = person
        slug = person.lower().replace(" ", "_")
        self._attr_unique_id = f"{entry.entry_id}_{slug}"
        self._attr_name = f"Katja Schedule — {person}"

    def _get_events_for_person(self) -> list[dict]:
        if not self.coordinator.data:
            return []
        overlay = self.coordinator.data.get("overlay", {})
        events = overlay.get("manual_events", [])
        return [e for e in events if _matches_person(e.get("who", ""), self._person)]

    @property
    def event(self) -> CalendarEvent | None:
        """The next upcoming event — used as the entity state."""
        now = datetime.now().astimezone()
        today = now.date()
        best = None
        best_start = None
        for ev in self._get_events_for_person():
            cal_ev = _event_to_calendar_event(ev)
            if cal_ev is None:
                continue
            ev_start = cal_ev.start
            if isinstance(ev_start, date) and not isinstance(ev_start, datetime):
                if ev_start < today:
                    continue
            elif isinstance(ev_start, datetime):
                if ev_start < now:
                    continue
            if best_start is None or ev_start < best_start:
                best = cal_ev
                best_start = ev_start
        return best

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return events in the given range."""
        result = []
        sd = start_date.date() if isinstance(start_date, datetime) else start_date
        ed = end_date.date() if isinstance(end_date, datetime) else end_date
        for ev in self._get_events_for_person():
            event_date_str = ev.get("date", "")
            if not event_date_str:
                continue
            try:
                event_date = date.fromisoformat(event_date_str)
            except ValueError:
                continue
            if event_date < sd or event_date > ed:
                continue
            cal_ev = _event_to_calendar_event(ev)
            if cal_ev:
                result.append(cal_ev)
        return result
