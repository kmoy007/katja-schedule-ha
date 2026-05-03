"""Config flow — user enters API URL + bearer token, we validate."""
from __future__ import annotations

import logging

import httpx
import voluptuous as vol
from homeassistant import config_entries

from .const import (
    CONF_API_TOKEN,
    CONF_API_URL,
    CONF_MEMBERS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_API_URL): str,
    vol.Required(CONF_API_TOKEN): str,
    vol.Optional(CONF_MEMBERS, default=""): str,
    vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
})


class KatjaScheduleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Katja Schedule."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_API_URL].rstrip("/")
            token = user_input[CONF_API_TOKEN]
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        f"{url}/api/data/status",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                if resp.status_code == 401:
                    errors["base"] = "invalid_auth"
                elif resp.status_code == 503:
                    errors["base"] = "api_not_configured"
                elif resp.status_code != 200:
                    errors["base"] = "cannot_connect"
                else:
                    data = resp.json()
                    if not data.get("ok"):
                        errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "cannot_connect"

            if not errors:
                # Auto-discover family members from API if not provided
                members_str = user_input.get(CONF_MEMBERS, "").strip()
                if not members_str:
                    try:
                        async with httpx.AsyncClient(timeout=15) as client:
                            resp = await client.get(
                                f"{url}/api/data/events",
                                headers={"Authorization": f"Bearer {token}"},
                            )
                        if resp.status_code == 200:
                            events = resp.json().get("events", [])
                            names = set()
                            for e in events:
                                who = (e.get("who") or "").strip()
                                if who and who.lower() not in ("kids", "family", "everyone"):
                                    names.add(who)
                            if names:
                                members_str = ", ".join(sorted(names))
                    except Exception:
                        pass
                user_input[CONF_MEMBERS] = members_str

                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Family Schedule", data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
