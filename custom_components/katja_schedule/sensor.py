"""Sensor entities — pending review count, next flight, last sync."""
from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_API_URL, DOMAIN, stable_id
from .coordinator import KatjaScheduleCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KatjaScheduleCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        PendingReviewSensor(coordinator, entry),
        NextFlightSensor(coordinator, entry),
        LastSyncSensor(coordinator, entry),
    ], update_before_add=True)


class PendingReviewSensor(CoordinatorEntity, SensorEntity):
    """Count of events pending review (new + changed + orphan + conflict)."""

    def __init__(self, coordinator: KatjaScheduleCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._attr_unique_id = stable_id(entry.data.get(CONF_API_URL, ""), "pending_review")
        self._attr_name = "Schedule — Pending Review"
        self._attr_icon = "mdi:clipboard-check-outline"

    @property
    def native_value(self) -> int:
        if not self.coordinator.data:
            return 0
        events = self.coordinator.data.get("overlay", {}).get("manual_events", [])
        return sum(1 for e in events
                   if e.get("status") in ("new", "changed", "orphan", "conflict"))

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        events = self.coordinator.data.get("overlay", {}).get("manual_events", [])
        counts = {"new": 0, "changed": 0, "orphan": 0, "conflict": 0}
        for e in events:
            s = e.get("status", "")
            if s in counts:
                counts[s] += 1
        return counts


class NextFlightSensor(CoordinatorEntity, SensorEntity):
    """Status of the next tracked flight."""

    def __init__(self, coordinator: KatjaScheduleCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._attr_unique_id = stable_id(entry.data.get(CONF_API_URL, ""), "next_flight")
        self._attr_name = "Schedule — Next Flight"
        self._attr_icon = "mdi:airplane"

    def _find_flight(self) -> dict | None:
        if not self.coordinator.data:
            return None
        events = self.coordinator.data.get("overlay", {}).get("manual_events", [])
        for e in events:
            if e.get("flight"):
                return e
        return None

    @property
    def native_value(self) -> str | None:
        ev = self._find_flight()
        if not ev:
            return "No flights"
        flight = ev["flight"]
        return f"{flight.get('number', '?')} — {ev.get('where', 'checking')}"

    @property
    def extra_state_attributes(self) -> dict:
        ev = self._find_flight()
        if not ev:
            return {}
        flight = ev["flight"]
        return {
            "flight_number": flight.get("number", ""),
            "date": flight.get("date", ""),
            "origin": flight.get("origin", ""),
            "destination": flight.get("destination", ""),
            "event_what": ev.get("what", ""),
            "event_where": ev.get("where", ""),
        }


class LastSyncSensor(CoordinatorEntity, SensorEntity):
    """Timestamp of the last successful calendar sync."""

    def __init__(self, coordinator: KatjaScheduleCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._attr_unique_id = stable_id(entry.data.get(CONF_API_URL, ""), "last_sync")
        self._attr_name = "Schedule — Last Sync"
        self._attr_icon = "mdi:sync"
        self._attr_device_class = "timestamp"

    @property
    def native_value(self) -> datetime | None:
        if not self.coordinator.data:
            return None
        last_sync = self.coordinator.data.get("last_sync")
        if not last_sync:
            return None
        synced_at = last_sync.get("synced_at")
        if not synced_at:
            return None
        try:
            return datetime.fromisoformat(synced_at)
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        last_sync = self.coordinator.data.get("last_sync") or {}
        bv = self.coordinator.data.get("build_version") or {}
        return {
            "event_count": last_sync.get("event_count", 0),
            "calendar_count": len(last_sync.get("calendars", [])),
            "build_sha": bv.get("short_sha", ""),
        }
