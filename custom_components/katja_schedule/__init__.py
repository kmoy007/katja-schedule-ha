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
        vol.Required("type"): "katja_schedule/list_review_inbox",
    })
    @websocket_api.async_response
    async def ws_list_review_inbox(hass, connection, msg):
        """Unified review inbox (groups + recurring_batches) the card's
        review modal renders to mirror the web /review page. The card
        polls this when the user taps the pending pill; it's heavier
        than list_pending_proposals (involves rendering the payload)
        so we keep it modal-driven, not part of the schedule render."""
        try:
            api_url, api_token = _get_api_config(hass)
        except ValueError as e:
            connection.send_error(msg["id"], "not_configured", str(e))
            return
        def _call():
            with httpx.Client(timeout=15) as client:
                resp = client.get(
                    f"{api_url}/api/data/review-inbox",
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

    # ----- Review-queue WS commands (fr-2026-05-11-b) ---------------
    # Each command is a thin pass-through to a /api/actions/* bearer
    # endpoint on the Flask app. The drift-prevention test in the main
    # app's tests/ suite walks both surfaces and fails CI when a new
    # web review route lands without a matching command here. Bodies
    # are intentionally similar so a refactor (e.g. extracting a
    # `_post_with_token` helper) can collapse them later.
    def _build_review_action_command(*, ws_type: str, http_path_tmpl: str,
                                       msg_schema: dict | None = None,
                                       body_keys: tuple[str, ...] = ()):
        """Factory: returns an async websocket handler that POSTs to
        `http_path_tmpl` (a `.format()`-style string fed by msg keys it
        names) with an optional JSON body assembled from msg keys named
        in `body_keys`. Keeps every command's wiring identical so the
        drift-prevention test only needs to check that a command for
        each route exists."""
        schema = {
            vol.Required("type"): ws_type,
            **(msg_schema or {}),
        }
        @websocket_api.websocket_command(schema)
        @websocket_api.async_response
        async def _handler(hass, connection, msg):
            try:
                api_url, api_token = _get_api_config(hass)
            except ValueError as e:
                connection.send_error(msg["id"], "not_configured", str(e))
                return
            path = http_path_tmpl.format(**{
                k: msg.get(k, "") for k in msg if k not in ("type", "id")
            })
            body = {k: msg[k] for k in body_keys if k in msg}
            def _call():
                with httpx.Client(timeout=15) as client:
                    resp = client.post(
                        f"{api_url}{path}",
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
        return _handler

    ws_accept_event = _build_review_action_command(
        ws_type="katja_schedule/accept_event",
        http_path_tmpl="/api/actions/events/accept/{event_id}",
        msg_schema={vol.Required("event_id"): str})
    ws_hide_event = _build_review_action_command(
        ws_type="katja_schedule/hide_event",
        http_path_tmpl="/api/actions/events/hide/{event_id}",
        msg_schema={vol.Required("event_id"): str})
    ws_unhide_event = _build_review_action_command(
        ws_type="katja_schedule/unhide_event",
        http_path_tmpl="/api/actions/events/unhide/{event_id}",
        msg_schema={vol.Required("event_id"): str})
    ws_accept_all_new = _build_review_action_command(
        ws_type="katja_schedule/accept_all_new",
        http_path_tmpl="/api/actions/events/accept-all-new")
    ws_hide_all_new = _build_review_action_command(
        ws_type="katja_schedule/hide_all_new",
        http_path_tmpl="/api/actions/events/hide-all-new")
    ws_accept_all_changed = _build_review_action_command(
        ws_type="katja_schedule/accept_all_changed",
        http_path_tmpl="/api/actions/events/accept-all-changed")
    ws_accept_batch = _build_review_action_command(
        ws_type="katja_schedule/accept_batch",
        http_path_tmpl="/api/actions/events/accept-batch",
        msg_schema={vol.Required("event_ids"): [str]},
        body_keys=("event_ids",))
    ws_hide_batch = _build_review_action_command(
        ws_type="katja_schedule/hide_batch",
        http_path_tmpl="/api/actions/events/hide-batch",
        msg_schema={vol.Required("event_ids"): [str]},
        body_keys=("event_ids",))
    ws_unhide_all = _build_review_action_command(
        ws_type="katja_schedule/unhide_all",
        http_path_tmpl="/api/actions/events/unhide-all")
    ws_apply_proposal = _build_review_action_command(
        ws_type="katja_schedule/apply_proposal",
        http_path_tmpl="/api/actions/review/proposed/{pe_id}/apply",
        msg_schema={vol.Required("pe_id"): str})
    ws_reject_proposal = _build_review_action_command(
        ws_type="katja_schedule/reject_proposal",
        http_path_tmpl="/api/actions/review/proposed/{pe_id}/reject",
        msg_schema={vol.Required("pe_id"): str})
    ws_apply_proposals_batch = _build_review_action_command(
        ws_type="katja_schedule/apply_proposals_batch",
        http_path_tmpl="/api/actions/review/proposed/apply-batch",
        msg_schema={vol.Required("proposal_ids"): [str]},
        body_keys=("proposal_ids",))
    ws_reject_proposals_batch = _build_review_action_command(
        ws_type="katja_schedule/reject_proposals_batch",
        http_path_tmpl="/api/actions/review/proposed/reject-batch",
        msg_schema={vol.Required("proposal_ids"): [str]},
        body_keys=("proposal_ids",))

    websocket_api.async_register_command(hass, ws_refresh_drive)
    websocket_api.async_register_command(hass, ws_refresh_flight)
    websocket_api.async_register_command(hass, ws_agent_action)
    websocket_api.async_register_command(hass, ws_skip_week)
    websocket_api.async_register_command(hass, ws_list_pending_proposals)
    websocket_api.async_register_command(hass, ws_list_review_inbox)
    for _cmd in (
        ws_accept_event, ws_hide_event, ws_unhide_event,
        ws_accept_all_new, ws_hide_all_new, ws_accept_all_changed,
        ws_accept_batch, ws_hide_batch, ws_unhide_all,
        ws_apply_proposal, ws_reject_proposal,
        ws_apply_proposals_batch, ws_reject_proposals_batch,
    ):
        websocket_api.async_register_command(hass, _cmd)
