# Roadmap

Last updated: 2026-07-04

## Done

Core search:

- Provider cleanup to four active provider classes.
- Collect-all-minimum provider waterfall.
- Shared `ThreadPoolExecutor`.
- Provider health caching.
- Circuit breaker/backoff behavior in provider base.
- Sanity-band filtering for obvious price outliers.
- Provider consensus with deduped quote counting.
- Leg combiner fallback with freshness cutoff.
- Cheapest-first destination ordering.
- Flexible dates with min/max-night enforcement.
- City-level result deduplication.
- Cost model with luggage and transfers.
- Arrival timezone normalization via hardcoded European UTC offsets, wired into scoring.

Telegram UX:

- Group creation.
- Invite links and join flow.
- Member airport collection.
- 6-step search wizard.
- Quick search defaults.
- Live progress/ETA updates.
- Paginated result cards.
- City detail drilldown.
- Per-person fairness bars.
- Live Verify button for saved deals.
- Paid-price reporting flow.
- Owner-only admin dashboard.
- Invite-only gate option.

Persistence/API:

- SQLite WAL storage.
- Users, groups, group members, searches, results, share links.
- Append-only fare observations.
- Verification event history.
- User-reported paid-price reports.
- Search/result API endpoints.
- Result verification and fare-intelligence API endpoints.
- Share link endpoints and HTML view.
- Admin storage methods.
- DB repair and cleanup helpers.
- Backup, canary, dashboard, iCal scripts.

## Current TODO

| Item | Why |
|---|---|
| Make Duffel call recording enforce around actual API calls | Budget helpers exist; confirm every paid call records usage |
| Add HTTP fixtures and parser snapshot tests | Protect scrapers from silent upstream changes |
| Add ruff/mypy/pre-commit | Catch regressions in the larger bot/storage files |
| Upgrade timezone normalization to full OurAirports dataset | Replace the hardcoded European UTC-offset stopgap for global/DST-accurate arrival-gap correctness |
| Different-day arrival handling | Long routes and overnight arrivals need clearer logic |
| Pareto frontier output | Show "cheapest", "fairest", and "fastest" alternatives, not only one ranking |
| API auth hardening | `JWT_SECRET` exists but current share/group reads are mostly open/local |
| Booking-timing intelligence | Turn fare observations into stronger wait/book recommendations |

## Ideas

- Web dashboard for group results.
- Price monitoring/alerts per saved group.
- Amadeus or another free/cheap fifth provider if it proves reliable.
- Public holiday and school holiday calendars.
- Ground transport between nearby destination cities.
- Better airport database validation during airport entry.

## Fixed Issues From Earlier Iterations

- Dead/hanging providers removed.
- Slow provider timeout added.
- Excess Telegram progress spam reduced.
- Insecure admin auto-claim replaced by owner checks.
- Weekend-only search replaced by configurable date ranges.
- Hotels removed from the active scoring model.
- 10 kg carry-on and transfer costs made visible.
- External dashboard no longer required for normal use.
