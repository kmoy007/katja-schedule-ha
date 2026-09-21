"""DataUpdateCoordinator for Katja Schedule — polls the /api/data endpoint.

Polls are conditional GETs (see fetch.py): the server's ETag ignores its
5-minute heartbeat fields, so an unchanged schedule answers 304 with no
body and we keep the cached snapshot, topping up `last_sync` /
`last_cron` / `build_version` from the 2 KB /api/data/status. Cut the
integration's share of the app's egress from ~59 MB/day to a few MB
(2026-09-21 bandwidth investigation).
"""
from __future__ import annotations

import logging
from datetime import timedelta

import httpx
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .fetch import SnapshotFetcher

_LOGGER = logging.getLogger(__name__)


def _sync_fetch(fetcher: SnapshotFetcher) -> dict:
    """Blocking HTTP fetch — run via async_add_executor_job to avoid
    SSL cert loading on the event loop."""
    with httpx.Client(timeout=30) as client:
        return fetcher.fetch(client)


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
        self._fetcher = SnapshotFetcher(self._api_url, api_token)

    async def _async_update_data(self) -> dict:
        try:
            data = await self.hass.async_add_executor_job(
                _sync_fetch, self._fetcher,
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
