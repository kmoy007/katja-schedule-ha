# Katja Schedule — Home Assistant Integration

Custom integration that connects Home Assistant to a family schedule app via its `/api/data` endpoints.

## What it creates

**Calendar entities** — one per family member (auto-discovered from event data or manually configured), plus a Shared calendar for group events.

**Sensor entities:**
- `sensor.katja_schedule_pending_review` — count of events needing review
- `sensor.katja_schedule_next_flight` — next tracked flight status
- `sensor.katja_schedule_last_sync` — last calendar sync timestamp

## Installation

1. In HACS: Settings → Custom Repositories → paste this repo URL → Category: Integration
2. Install from HACS
3. Restart Home Assistant
4. Settings → Integrations → Add → "Katja Schedule"
5. Enter the API URL, bearer token, and optionally family member names

Family members can be entered as a comma-separated list (e.g. "Alice, Bob, Charlie") or left blank to auto-discover from the event data.

## Requirements

- `API_DATA_TOKEN` must be configured on the schedule app
- The same token is entered during HA integration setup
