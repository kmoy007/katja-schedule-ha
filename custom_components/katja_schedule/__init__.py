"""Katja Schedule — Home Assistant integration.

Polls a schedule app's /api/data endpoint and creates:
  - Calendar entities per family member (auto-discovered or configured)
  - Sensor entities (pending review count, next flight, last sync)
  - WebSocket commands for drive time / flight status recheck
"""
from __future__ import annotations

import logging

import httpx
import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_API_TOKEN, CONF_API_URL, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import KatjaScheduleCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["calendar", "sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Katja Schedule from a config entry."""
    registry = er.async_get(hass)
    # Remove entities from old, deleted config entries.
    orphans = [
        e for e in registry.entities.values()
        if e.platform == DOMAIN and e.config_entry_id != entry.entry_id
    ]
    for e in orphans:
        _LOGGER.info("Removing orphaned entity %s from old config entry", e.entity_id)
        registry.async_remove(e.entity_id)

    # v0.12.0: per-person calendar entities were collapsed into a single
    # `Schedule` calendar with unique_id ending in `_all`. Sweep any older
    # per-person entries (unique_id `ks_<hash>_<slug>` where slug != "all"
    # and platform is calendar) so the registry doesn't accumulate stale
    # rows.
    legacy_calendars = [
        e for e in registry.entities.values()
        if e.platform == DOMAIN
        and e.config_entry_id == entry.entry_id
        and e.domain == "calendar"
        and not (e.unique_id or "").endswith("_all")
    ]
    for e in legacy_calendars:
        _LOGGER.info("Removing legacy per-person calendar %s", e.entity_id)
        registry.async_remove(e.entity_id)

    coordinator = KatjaScheduleCoordinator(
        hass,
        api_url=entry.data[CONF_API_URL],
        api_token=entry.data[CONF_API_TOKEN],
        scan_interval=entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Register WebSocket commands for drive/flight recheck
    _register_ws_commands(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


# ====================== WebSocket commands ======================

_ws_registered = False


def _get_api_config(hass: HomeAssistant) -> tuple[str, str]:
    """Get the API URL + token from the first config entry."""
    entries = hass.data.get(DOMAIN, {})
    for coordinator in entries.values():
        return coordinator._api_url, coordinator._api_token
    raise ValueError("No katja_schedule config entry found")


def _register_ws_commands(hass: HomeAssistant) -> None:
    global _ws_registered
    if _ws_registered:
        return
    _ws_registered = True

    @websocket_api.websocket_command({
        vol.Required("type"): "katja_schedule/refresh_drive",
        # Either ({origin, destination}) OR ({event: {what, where}}).
        # The backend parses the drive row when given an event, so the
        # card doesn't have to ship its own regex (which drifted from
        # the web parser; see bug-20260509-150030).
        vol.Optional("origin"): str,
        vol.Optional("destination"): str,
        vol.Optional("event"): dict,
        vol.Optional("arrival_time"): str,
        vol.Optional("departure_time"): str,
    })
    @websocket_api.async_response
    async def ws_refresh_drive(hass, connection, msg):
        try:
            api_url, api_token = _get_api_config(hass)
        except ValueError as e:
            connection.send_error(msg["id"], "not_configured", str(e))
            return

        # Forward whichever shape the card sent. The backend accepts
        # either {origin, destination} (legacy) or {event: {what, where}}
        # (current). Optional time params let the card opt into
        # arrive-by convergence (web default since 2026-05-05).
        body: dict = {}
        if msg.get("origin"):
            body["origin"] = msg["origin"]
        if msg.get("destination"):
            body["destination"] = msg["destination"]
        if msg.get("event"):
            body["event"] = msg["event"]
        if msg.get("arrival_time"):
            body["arrival_time"] = msg["arrival_time"]
        if msg.get("departure_time"):
            body["departure_time"] = msg["departure_time"]

        def _call():
            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    f"{api_url}/api/actions/refresh-drive",
                    headers={"Authorization": f"Bearer {api_token}",
                             "Content-Type": "application/json"},
                    json=body,
                )
                return resp.json()

        try:
            result = await hass.async_add_executor_job(_call)
            connection.send_result(msg["id"], result)
        except Exception as e:
            connection.send_error(msg["id"], "api_error", str(e))

    @websocket_api.websocket_command({
        vol.Required("type"): "katja_schedule/refresh_flight",
        vol.Required("flight_number"): str,
        vol.Required("date"): str,
        vol.Optional("origin"): str,
        vol.Optional("destination"): str,
    })
    @websocket_api.async_response
    async def ws_refresh_flight(hass, connection, msg):
        try:
            api_url, api_token = _get_api_config(hass)
        except ValueError as e:
            connection.send_error(msg["id"], "not_configured", str(e))
            return

        body = {"flight_number": msg["flight_number"], "date": msg["date"]}
        if msg.get("origin"):
            body["origin"] = msg["origin"]
        if msg.get("destination"):
            body["destination"] = msg["destination"]

        def _call():
            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    f"{api_url}/api/actions/refresh-flight",
                    headers={"Authorization": f"Bearer {api_token}",
                             "Content-Type": "application/json"},
                    json=body,
                )
                return resp.json()

        try:
            result = await hass.async_add_executor_job(_call)
            connection.send_result(msg["id"], result)
        except Exception as e:
            connection.send_error(msg["id"], "api_error", str(e))

    @websocket_api.websocket_command({
        vol.Required("type"): "katja_schedule/agent_action",
        vol.Required("message"): str,
    })
    @websocket_api.async_response
    async def ws_agent_action(hass, connection, msg):
        """Send a message to the schedule app's chat agent and return the response."""
        try:
            api_url, api_token = _get_api_config(hass)
        except ValueError as e:
            connection.send_error(msg["id"], "not_configured", str(e))
            return

        def _call():
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    f"{api_url}/api/chat",
                    headers={"Authorization": f"Bearer {api_token}",
                             "Content-Type": "application/json"},
                    json={"message": msg["message"], "history": []},
                )
                return resp.json()

        try:
            result = await hass.async_add_executor_job(_call)
            connection.send_result(msg["id"], result)
        except Exception as e:
            connection.send_error(msg["id"], "api_error", str(e))

    @websocket_api.websocket_command({
        vol.Required("type"): "katja_schedule/skip_week",
        vol.Required("event_id"): str,
    })
    @websocket_api.async_response
    async def ws_skip_week(hass, connection, msg):
        """Skip this occurrence for the week — same idempotent rewrite the
        web app's ⚠️ Skip-this-week button does, but reachable from the card
        without needing a browser session."""
        try:
            api_url, api_token = _get_api_config(hass)
        except ValueError as e:
            connection.send_error(msg["id"], "not_configured", str(e))
            return

        def _call():
            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    f"{api_url}/api/actions/skip-week/{msg['event_id']}",
                    headers={"Authorization": f"Bearer {api_token}"},
                )
                return resp.json()

        try:
            result = await hass.async_add_executor_job(_call)
            connection.send_result(msg["id"], result)
        except Exception as e:
            connection.send_error(msg["id"], "api_error", str(e))

    @websocket_api.websocket_command({
        vol.Required("type"): "katja_schedule/list_pending_proposals",
    })
    @websocket_api.async_response
    async def ws_list_pending_proposals(hass, connection, msg):
        """Return the schedule app's queue of pending agent proposals so
        the card can fold them into its event list (REVIEW badges in
        parity with the web schedule, fr-2026-05-07-d). The endpoint is
        token-authed; the card never sees the bearer."""
        try:
            api_url, api_token = _get_api_config(hass)
        except ValueError as e:
            connection.send_error(msg["id"], "not_configured", str(e))
            return

        def _call():
            with httpx.Client(timeout=10) as client:
                resp = client.get(
                    f"{api_url}/api/data/pending-proposals",
                    headers={"Authorization": f"Bearer {api_token}"},
                )
                return resp.json()

        try:
            result = await hass.async_add_executor_job(_call)
            connection.send_result(msg["id"], result)
        except Exception as e:
            connection.send_error(msg["id"], "api_error", str(e))

    websocket_api.async_register_command(hass, ws_refresh_drive)
    websocket_api.async_register_command(hass, ws_refresh_flight)
    websocket_api.async_register_command(hass, ws_agent_action)
    websocket_api.async_register_command(hass, ws_skip_week)
    websocket_api.async_register_command(hass, ws_list_pending_proposals)
