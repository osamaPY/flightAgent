# Codebase Guide

Current snapshot: 57 files, 37 Python files, 8,787 Python lines.

Last updated: 2026-07-04

## File Map

```text
flight_optimizer/
  README.md
  main.py                         CLI + provider waterfall + booking_mode
  telegram_bot.py                 v7 "one card" Telegram UX: hub, panel, results, admin
  flight_api_server.py            FastAPI local API
  requirements.txt
  start.bat / start_api.bat

  src/core/
    search_request.py             ParticipantGroup and SearchRequest
    scoring.py                    Flight, MeetupResult, GroupMeetupResult, ranking
    storage.py                    SQLite schema, migrations, groups, searches, admin
    smart_search.py               5 smart layers
    cost_utils.py                 bag costs, transfer costs, sanity helpers
    providers.py                  provider base and concrete providers
    provider_factory.py           provider builder, health cache, Duffel budget
    airports.py                   airport universe and destination helpers
    config.py                     env config and date windows
    timezone_utils.py             timezone helpers
    logger.py                     rotating logging
    notifier.py                   Telegram notifications

  src/clients/
    ryanair_client.py
    google_scraper.py
    duffel_client.py
    weather_client.py
    routestack_client.py          inactive/legacy hotel client

  src/scrapers/
    multi_google.py
    base.py
    engine.py

  src/utils/
    compat.py                     compatibility shim

  scripts/
    nightly_surface.py
    canary.py
    dashboard.py
    ical_export.py
    backup_db.py
    kick_vps.py

  tests/
    test_apis.py

  docs/
    *.md
```

Largest files by live line count:

| File | Lines | Purpose |
|---|---:|---|
| `telegram_bot.py` | 1670 | Main product UX |
| `src/core/storage.py` | 1240 | SQLite persistence and admin queries |
| `main.py` | 861 | Search engine and CLI |
| `src/core/scoring.py` | 553 | Models and ranking |
| `flight_api_server.py` | 480 | REST API |

## Core Models

`SearchRequest` is the current input model:

- `participants`: list of `ParticipantGroup(label, origins)`.
- `depart_earliest`, `depart_latest`.
- `min_nights`, `max_nights`.
- `destination_universe`: `schengen`, `europe`, or `anywhere`.
- `luggage`: `none`, `carryon_10kg`, or `checked_23kg`.
- `include_transfers`.
- `direct_only` / `max_stops`.

`Flight` represents one participant's round trip. Result models combine flights
for two-person legacy searches or group searches.

## Primary Flows

### Group Setup (v7)

```text
Home -> "New group"
  -> group name (typed)
  -> creator airports (city names or IATA; multi-airport cities get a
     toggle picker via bot_ui.resolve_airports)
  -> Storage.create_group + Storage.join_group
  -> invite link + Telegram share button
Friends tap the link -> asked for their airports -> in the group;
owner gets a "joined" ping.
```

### Search (v7)

```text
Group Hub -> "Search now" (defaults) or "Custom" settings panel
  panel: dates / nights / luggage / transfers / flights / scope
         all pre-filled, tap-to-change, LAUNCH always 1 tap
  -> SearchRequest
  -> Storage.create_search
  -> booking_mode(..., search_request=req) in a thread
  -> live progress edits the requester's card (sync callback +
     run_coroutine_threadsafe)
  -> Storage.save_group_result
  -> completion card + every group member gets a "results ready" ping
```

UI rendering helpers (escaping, airport resolution, result cards,
progress bars, panel text) are pure functions in `src/core/bot_ui.py`,
tested offline in `tests/test_bot_ui.py`.

### Results

```text
/results_<group_id>
  -> latest search for group
  -> Storage.get_search_results
  -> city dedup for display
  -> 4 cards per page
  -> city detail callback
```

### Admin

```text
/admin
  -> owner check via TELEGRAM_CHAT_ID
  -> stats, users, groups, searches, recent results
```

## Common Commands

```bash
python telegram_bot.py
python main.py
python main.py booking-mode
python main.py health
python main.py inspect-db
python main.py selftest
python flight_api_server.py
python scripts/dashboard.py
python scripts/backup_db.py
```

## Debugging

Provider health:

```bash
python main.py health
curl http://127.0.0.1:8000/health
```

Inspect DB:

```bash
python main.py inspect-db
sqlite3 data/flights.db "SELECT id, destination, grand_total, search_id FROM results ORDER BY grand_total LIMIT 10"
sqlite3 data/flights.db "SELECT id, group_id, status, result_count FROM searches ORDER BY created_at DESC LIMIT 10"
```

Raw flight query:

```bash
python -c "from src.core.provider_factory import build_providers; from src.core.storage import Storage; from main import get_best_flight; s=Storage(); p=build_providers(); f=get_best_flight(s,['BGY'],'VIE','2026-07-25','2026-07-27',p); print(f)"
```
