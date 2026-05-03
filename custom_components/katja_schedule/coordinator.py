"""DataUpdateCoordinator for Katja Schedule — polls the /api/data endpoint."""
from __future__ import annotations

import logging
from datetime import timedelta

import httpx
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _sync_fetch(api_url: str, api_token: str) -> dict:
    """Blocking HTTP fetch — run via async_add_executor_job to avoid
    SSL cert loading on the event loop."""
    headers = {"Authorization": f"Bearer {api_token}"}
    with httpx.Client(timeout=30) as client:
        resp = client.get(f"{api_url}/api/data", headers=headers)
        resp.raise_for_status()
    return resp.json()


class KatjaScheduleCoordinator(DataUpdateCoordinator):
    """Fetch the full app snapshot from the schedule API."""

    def __init__(
        self,
        hass: HomeAssistant,
        api_url: str,
        api_token: str,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self._api_url = api_url.rstrip("/")
        self._api_token = api_token

    async def _async_update_data(self) -> dict:
        try:
            data = await self.hass.async_add_executor_job(
                _sync_fetch, self._api_url, self._api_token,
            )
        except httpx.HTTPStatusError as exc:
            raise UpdateFailed(
                f"HTTP {exc.response.status_code} from schedule API"
            ) from exc
        except Exception as exc:
            raise UpdateFailed(f"Failed to reach schedule API: {exc}") from exc

        if not data.get("ok"):
            raise UpdateFailed(f"API returned error: {data.get('error', 'unknown')}")
        return data
