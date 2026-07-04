# Architecture

Current snapshot: v6.2 Telegram UX, parameterized `SearchRequest`, 52 files,
37 Python files, 7,639 Python lines.

Last updated: 2026-07-04

## Purpose

The app finds the best meetup city for a group whose members fly from different
airports. It searches many destinations and date combinations, combines each
member's cheapest viable flights, then ranks results by true cost and fairness.

The original Milan area + Riga summer holiday scenario is still available as a
default, but current code supports arbitrary groups, dates, origin airports, and
destination scopes.

## Topology

```text
Telegram users
  |
  v
telegram_bot.py
  - group creation and invite links
  - join flow and airport collection
  - 6-step search wizard
  - progress updates and ETA
  - result cards, pagination, city detail
  - live Verify and paid-price reporting
  - owner-only admin dashboard
  |
  v
SearchRequest
  participants, dates, nights, luggage, transfers, stops, scope
  |
  v
booking_mode() in main.py
  |
  +--> provider waterfall: Ryanair, Google, Google Multi-Mode, Duffel when allowed
  +--> smart_search.py: 5 layers
  +--> scoring.py: group meetup scoring and ranking
  +--> cost_utils.py: bag, transfer, and sanity helpers
  |
  v
storage.py / SQLite WAL
  cache, legs, provider quotes, users, groups, searches, results, share links
  price observations, verification events, paid-price reports
```

Secondary entry points:

- `main.py`: CLI menu, health checks, booking mode, DB inspection, export.
- `flight_api_server.py`: FastAPI endpoints for search, scraper matrix, group/search/result/share reads.
- `scripts/`: nightly surface, canary, dashboard, iCal export, backups, VPS bot kick.

## Cost Model

For each participant, the system chooses the cheapest flight from their allowed
origin airports to the destination. Group results aggregate those participant
flights.

All-in cost can include:

- flight tickets,
- airline-specific luggage fees,
- origin airport transfers,
- destination airport transfers.

Searches can also be configured as flight-only by disabling transfers, and
personal-item-only by selecting luggage `none`.

Default luggage remains `carryon_10kg`. Known full-service airlines are treated
as included; unknown airlines use a conservative estimate.

## Smart Layers

The search engine uses five layers:

| Layer | Role |
|---|---|
| L1 Calendar pre-scan | Historical/cached price surface |
| L2 Leg combiner | Fallback round trips from fresh one-way legs |
| L3 Provider consensus | Confidence labels after quote deduplication |
| L4 Flexible dates | Exact and shifted dates, bounded by min/max nights |
| L5 Cheapest-first ordering | Searches historically cheaper destinations earlier |

See [SMART_LAYERS.md](SMART_LAYERS.md).

## Providers

Active provider classes:

- `RyanairProvider`
- `GoogleScraperProvider`
- `MultiGoogleScraperProvider`
- `DuffelProvider`

`provider_factory.py` exposes:

- `build_providers(storage=None, include_duffel=True)`
- `build_guest_providers()` for free-only guest searches
- `build_owner_providers()` for owner searches with Duffel if budget allows
- cached health helpers
- Duffel daily budget tracking

## Telegram Bot

`telegram_bot.py` (v7) is the main UX. Pure rendering helpers live in
`src/core/bot_ui.py` and are offline-tested in `tests/test_bot_ui.py`.

v7 design — "one card that navigates like an app":

- The UI is a single message per chat; every tap edits it in place
  (no message spam). Screens: Home → Group Hub → Search Panel →
  Progress → Results → City Detail, with Back everywhere.
- Search setup is a settings panel with smart defaults (next month,
  2–4 nights, 10kg, transfers, any flights, Europe) — launch is 1 tap;
  tap any row to change it. The old 6-step linear wizard is gone.
- Airport entry accepts city names ("milan" → BGY/MXP/LIN picker) as
  well as IATA codes, via `bot_ui.resolve_airports()`.
- Live progress edits the requester's own card via a sync callback +
  `asyncio.run_coroutine_threadsafe` (v6's async callback was never
  awaited and targeted the owner's chat).
- Group-aware notifications: owner is pinged on joins; every member is
  pinged when results are ready.
- All text is HTML with escaping on user content; `/` command menu is
  registered at startup via `set_my_commands`.
- Old inline buttons (`res_`, `ver_`, `paid_`, `wizpick_`, …) and
  `/results_<id>`-style commands still route.

Major entry points: `/start` (home + deep-link joins), `/help`,
`/status`, `/stop`, `/admin` (owner), plus legacy command aliases.

## Storage

SQLite runs in WAL mode. Current tables:

| Table | Purpose |
|---|---|
| `results` | Meetup results, including `search_id` and `participants_json` |
| `schema_version` | Migration record |
| `price_history` | Historical destination prices |
| `api_budget` | API/budget tracking |
| `api_cache` | Round-trip cache |
| `flight_legs` | One-way legs for pre-scan and leg combiner |
| `provider_quotes` | Raw provider quote matrix |
| `users` | Telegram users |
| `groups_table` | Meetup groups and invite codes |
| `group_members` | Members and their origin airports |
| `searches` | Search metadata, progress, and counts |
| `share_links` | Public read-only result links |
| `price_observations` | Append-only local fare warehouse |
| `verification_events` | Live re-check history for saved deals |
| `paid_price_reports` | User-reported real booked totals |

Important storage methods:

- `create_group`, `join_group`, `leave_group`, `get_group_members`
- `create_search`, `update_search_status`, `get_search_results`
- `save_group_result`, `update_search_result_count`
- `create_share_link`, `get_shared_results`
- `save_price_observation`, `get_price_observation_stats`
- `save_verification_event`, `get_latest_verification`
- `save_paid_price_report`
- `admin_all_users`, `admin_all_groups`, `admin_all_searches`, `admin_stats`
- `delete_short_stays`, `purge_city_duplicates`, `repair_cost_gaps`

## API

FastAPI endpoints include:

- `/health`
- `/leg`, `/search`, `/matrix`
- `/scrape/health`, `/scrape/leg`, `/scrape/search`, `/scrape/matrix`
- `/groups/{group_id}`
- `/groups/{group_id}/searches`
- `/searches/{search_id}/results`
- `/results/{result_id}/verify`
- `/results/{result_id}/paid-price`
- `/intelligence/fares`
- `/searches/{search_id}/share`
- `/share/{token}`
- `/share/{token}/html`

## Known Architecture Notes

- Search execution is still synchronous provider code run through threads.
- The Telegram bot runs searches in background tasks using `asyncio.to_thread`.
- `SearchRequest` is the source of truth for new configurable searches.
- Some legacy environment variables and clients remain in code for compatibility/reference.
