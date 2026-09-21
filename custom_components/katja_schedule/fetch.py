"""Conditional fetch of the /api/data snapshot.

Kept free of `homeassistant.*` imports (like `review_count.py`) so the
main repo's unit tests can import it standalone with a fake HTTP client.

Why: the coordinator polls /api/data every 5 minutes. Until 2026-09-21
every poll pulled the full snapshot (1.35 MB raw) whether or not
anything had changed — 288 × 1.35 MB/day, a third of the app's metered
bandwidth. The server now sends an ETag that ignores its heartbeat
fields (`last_sync`, `last_cron`), so a poll where nothing else moved
answers 304 with no body. On a 304 we keep the cached snapshot and
refresh just the heartbeat fields from /api/data/status (~2 KB), so the
"last sync" sensor keeps ticking.

Failure modes stay loud (INV-4.1): a non-2xx on the main fetch raises
from `raise_for_status()` exactly as before, and the coordinator turns
it into `UpdateFailed`. Only the heartbeat top-up is best-effort — a
stale-but-present `last_sync` beats failing the whole poll over a
2 KB side request.
"""
from __future__ import annotations

from typing import Any

# Fields refreshed from /api/data/status after a 304. Everything else in
# the cached snapshot is, by construction of the server's ETag, unchanged.
HEARTBEAT_KEYS: tuple[str, ...] = ("last_sync", "last_cron", "build_version")


class SnapshotFetcher:
    """Remembers the last ETag + body so each poll can be a conditional GET.

    `client` is any object with `.get(url, headers=...)` returning a
    response with `.status_code`, `.headers`, `.json()` and
    `.raise_for_status()` — an `httpx.Client` in production, a fake in
    tests.
    """

    def __init__(self, api_url: str, api_token: str) -> None:
        self.api_url = api_url.rstrip("/")
        self._token = api_token
        self.etag: str | None = None
        self.cached: dict[str, Any] | None = None
        self.last_status: int | None = None

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def fetch(self, client: Any) -> dict[str, Any]:
        headers = self._auth()
        if self.etag and self.cached is not None:
            headers["If-None-Match"] = self.etag
        resp = client.get(f"{self.api_url}/api/data", headers=headers)
        self.last_status = resp.status_code

        if resp.status_code == 304 and self.cached is not None:
            data = dict(self.cached)
            self._refresh_heartbeat(client, data)
            self.cached = data
            return data

        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("ok"):
            self.etag = resp.headers.get("ETag") or None
            self.cached = data
        else:
            # Don't send a stale validator on the next poll if the body
            # was an error envelope — force a full fetch instead.
            self.etag = None
            self.cached = None
        return data

    def _refresh_heartbeat(self, client: Any, data: dict[str, Any]) -> None:
        try:
            st = client.get(f"{self.api_url}/api/data/status", headers=self._auth())
            st.raise_for_status()
            body = st.json()
        except Exception:  # noqa: BLE001 — best-effort top-up
            return
        if not isinstance(body, dict) or not body.get("ok"):
            return
        for key in HEARTBEAT_KEYS:
            if key in body:
                data[key] = body[key]
