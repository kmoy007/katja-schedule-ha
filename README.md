# Katja Schedule — Home Assistant Integration

Custom integration that connects Home Assistant to the [Katja Schedule](https://katja-schedule.onrender.com) family logistics app.

## What it creates

**Calendar entities** (one per family member):
- `calendar.katja_schedule_katja`
- `calendar.katja_schedule_ken`
- `calendar.katja_schedule_caleb`
- `calendar.katja_schedule_sam`
- `calendar.katja_schedule_shared`

**Sensor entities:**
- `sensor.katja_schedule_pending_review` — count of events needing review
- `sensor.katja_schedule_next_flight` — next tracked flight status
- `sensor.katja_schedule_last_sync` — last calendar sync timestamp

## Installation

1. In HACS: Settings → Custom Repositories → paste this repo URL → Category: Integration
2. Install "Katja Schedule" from HACS
3. Restart Home Assistant
4. Settings → Integrations → Add → "Katja Schedule"
5. Enter the API URL and bearer token

## Week Planner Card configuration

```yaml
type: custom:week-planner-card
days: 14
startingDay: today
calendars:
  - entity: calendar.katja_schedule_katja
    color: '#FF6B6B'
  - entity: calendar.katja_schedule_ken
    color: '#4ECDC4'
  - entity: calendar.katja_schedule_caleb
    color: '#45B7D1'
  - entity: calendar.katja_schedule_sam
    color: '#96CEB4'
  - entity: calendar.katja_schedule_shared
    color: '#FFEAA7'
```

## Requirements

- `API_DATA_TOKEN` must be configured on the schedule app (Render env var)
- The same token is entered during HA integration setup
