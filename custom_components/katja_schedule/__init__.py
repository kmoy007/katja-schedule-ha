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
    # Clean up stale entities from previous installs that used entry_id-based
    # unique_ids (pre-v0.4.0). These collide when the integration is
    # deleted and re-added.
    registry = er.async_get(hass)
    stale = [
        e for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.unique_id and e.unique_id.startswith(entry.entry_id)
    ]
    for e in stale:
        _LOGGER.info("Removing stale entity %s (old unique_id format)", e.entity_id)
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
