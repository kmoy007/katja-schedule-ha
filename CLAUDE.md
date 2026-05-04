# CLAUDE.md — Agent Rules for Katja Schedule HA Integration

This is the Home Assistant custom integration for the Katja Schedule app.
It must stay aligned with the main web app at `kmoy007/katja-schedule`.

## Alignment Rule

- **This integration must match the web app's capabilities.** When the web app adds features (new data fields, new API endpoints, new event types), update this integration in the same session.
- Check the main app's `CLAUDE.md` and `project_architecture.md` (in the Claude memory) for the full architecture and conventions.
- The web app is deployed at https://katja-schedule.onrender.com — use the `/api/data` endpoints to verify data shapes.

## Key Conventions

- **All dates are Pacific time (America/Los_Angeles).** The `time_parser.py` handles the schedule's time formats.
- **Unique IDs must be stable** — based on `stable_id(api_url, slug)`, not config entry ID. Prevents entity registry corruption.
- **Auto-clean orphaned entities** on startup from previous installs.
- **HTTP calls on the executor thread** — use `hass.async_add_executor_job()`, never `httpx.AsyncClient` directly (causes SSL blocking on HA event loop).
- **WebSocket commands** proxy API calls so the bearer token stays in HA's encrypted config, never in card YAML.

## Versioning

- **Bump `manifest.json` version** on every change.
- **Create a GitHub release with a version tag** (`git tag vX.Y.Z && git push origin --tags && gh release create vX.Y.Z`) so HACS detects updates.
- **Version must be semver** and monotonically increasing.

## Testing

- Test changes against the live API at `https://katja-schedule.onrender.com/api/data/status` with the bearer token.
- The main app repo has the `API_DATA_TOKEN` in the local environment.

## Files

- `__init__.py` — Entry point, entity cleanup, WebSocket command registration
- `coordinator.py` — DataUpdateCoordinator, polls `/api/data`
- `calendar.py` — Calendar entities per family member, auto-discovered
- `sensor.py` — Pending review, next flight, last sync sensors
- `config_flow.py` — Setup UI, API validation, member auto-discovery
- `time_parser.py` — Ported from the web app's `ical_feed.py`
- `const.py` — Constants, `stable_id()` helper
