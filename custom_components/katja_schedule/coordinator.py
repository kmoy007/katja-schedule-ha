"""DataUpdateCoordinator for Katja Schedule — polls the /api/data endpoint."""
from __future__ import annotations

import logging
from datetime import timedelta

import httpx
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


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
        headers = {"Authorization": f"Bearer {self._api_token}"}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{self._api_url}/api/data", headers=headers,
                )
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise UpdateFailed(
                f"HTTP {exc.response.status_code} from schedule API"
            ) from exc
        except Exception as exc:
            raise UpdateFailed(f"Failed to reach schedule API: {exc}") from exc

        data = resp.json()
        if not data.get("ok"):
            raise UpdateFailed(f"API returned error: {data.get('error', 'unknown')}")
        return data
