"""Config flow — user enters API URL + bearer token, we validate."""
from __future__ import annotations

import logging

import httpx
import voluptuous as vol
from homeassistant import config_entries

from .const import (
    CONF_API_TOKEN,
    CONF_API_URL,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_API_URL): str,
    vol.Required(CONF_API_TOKEN): str,
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

            def _validate(u, t):
                with httpx.Client(timeout=15) as c:
                    return c.get(f"{u}/api/data/status",
                                 headers={"Authorization": f"Bearer {t}"})

            try:
                resp = await self.hass.async_add_executor_job(_validate, url, token)
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
                user_input[CONF_API_URL] = url
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
