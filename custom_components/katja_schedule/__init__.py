"""Katja Schedule — Home Assistant integration.

Polls a schedule app's /api/data endpoint and creates:
  - Calendar entities per family member (auto-discovered or configured)
  - Sensor entities (pending review count, next flight, last sync)
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_API_TOKEN, CONF_API_URL, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import KatjaScheduleCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["calendar", "sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Katja Schedule from a config entry."""
    # Clean up ALL orphaned katja_schedule entities from any previous
    # config entry (deleted installs, old unique_id formats, etc.).
    registry = er.async_get(hass)
    orphans = [
        e for e in registry.entities.values()
        if e.platform == DOMAIN and e.config_entry_id != entry.entry_id
    ]
    for e in orphans:
        _LOGGER.info("Removing orphaned entity %s from old config entry", e.entity_id)
        registry.async_remove(e.entity_id)

    coordinator = KatjaScheduleCoordinator(
        hass,
        api_url=entry.data[CONF_API_URL],
        api_token=entry.data[CONF_API_TOKEN],
        scan_interval=entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
