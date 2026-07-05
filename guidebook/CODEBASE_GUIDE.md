# Codebase Guide

Current snapshot: ~46 Python files, ~10,900 Python lines, 5 offline test files.

Last updated: 2026-07-05

## File Map

```text
flight_optimizer/
  README.md
  main.py                         CLI + provider waterfall + booking_mode
  telegram_bot.py                 v7 "one card" Telegram UX: simple group screen,
                                  guided setup, results, AI ask-a-question helper, admin
  flight_api_server.py            FastAPI local API
  requirements.txt
  start.bat / start_api.bat

  src/core/
    search_request.py             ParticipantGroup and SearchRequest
    scoring.py                    Flight, MeetupResult, GroupMeetupResult, ranking
    storage.py                    SQLite schema, migrations, groups, searches, admin
    smart_search.py               5 smart layers + calendar-first discovery pre-scan
    provider_registry.py          capability-tagged registry + discovery/verification tiers
    providers.py                  provider base and concrete providers (incl. Ryanair Calendar)
    provider_factory.py           registry-backed builders, health cache, Duffel budget
    route_graph.py                Ryanair route-graph pruning (cached, fail-open)
    cost_utils.py                 bag costs, transfer costs, sanity helpers
    ai_assistant.py               DeepSeek concierge (recommend a city, things to do)
    bot_ui.py                     pure, tested UI/render helpers (no telegram imports)
    airports.py                   airport universe and destination helpers
    config.py                     env config and date windows
    timezone_utils.py             timezone helpers
    logger.py                     rotating logging
    notifier.py                   Telegram notifications (used by CLI)

  src/clients/
    ryanair_client.py
    google_scraper.py
    duffel_client.py
    deepseek_client.py            OpenAI-compatible LLM client (fail-soft)
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
    test_bot_ui.py                pure UI-helper tests
    test_registry.py              registry invariants, route graph, discovery pre-scan
    test_ai_assistant.py          AI prompt-building with a mocked client
    test_apis.py                  provider health

  docs/                           internal notes (not published)
  guidebook/                      public docs shipped on GitHub
```

Largest files by live line count (approx):

| File | Lines | Purpose |
|---|---:|---|
| `src/core/storage.py` | ~1560 | SQLite persistence and admin queries |
| `telegram_bot.py` | ~1440 | Main product UX (v7) |
| `main.py` | ~880 | Search engine and CLI |
| `src/core/scoring.py` | ~550 | Models and ranking |
| `flight_api_server.py` | ~525 | REST API |

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
Group screen -> "Find flights" (one-tap smart defaults) or
                "Pick dates / options first" (guided 6-question setup)
  settings: dates / nights / luggage / transfers / flights / scope
            all pre-filled, tap-to-change, LAUNCH always 1 tap
  (a "Ask a question" AI helper answers how-to questions in plain words)
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
Results button (or /results_<group_id>)
  -> latest search for group
  -> Storage.get_search_results
  -> city dedup for display
  -> compact ranked list (medals for top 3), paginated
  -> tap a city -> detail card (per-person, fairness, links, Verify/Paid)
  -> optional AI: "Which should we pick?" / "Things to do"
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
python -m pytest -q          # 44 offline tests, no network needed
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
