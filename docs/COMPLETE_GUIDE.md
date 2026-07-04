# Complete Guide

Last updated: 2026-07-04

## The Problem

A group of people want to meet somewhere in Europe. Each person may have
multiple nearby departure airports. The useful question is not "what is the
cheapest flight for one person?" but:

> Which destination is cheapest and fairest for everyone, on dates that work?

The app automates that search across destinations, date pairs, providers,
luggage assumptions, and airport transfer costs.

## The Current Product

The current product is a Telegram bot:

1. Create a group.
2. Invite friends.
3. Everyone enters origin airports.
4. Configure a search with buttons.
5. Let the bot scan destinations and dates.
6. Review ranked city cards and drill into details.
7. Tap Verify before booking to re-check the exact saved itinerary live.
8. Report what you actually paid after booking so the local dataset improves.

The original Milan + Riga summer search is still available as a default, but it
is no longer the only supported shape.

## Search Configuration

Every modern search is represented by `SearchRequest`.

Important fields:

- participants and their origin airport lists,
- date range,
- min/max nights,
- destination universe,
- luggage setting,
- transfer setting,
- direct-only/stop setting.

The Telegram wizard exposes these as six steps:

1. travel window,
2. nights,
3. luggage,
4. airport transfers,
5. direct vs any flights,
6. Europe/Schengen/everywhere.

## How A Search Runs

```text
SearchRequest
  -> date windows
  -> candidate destinations
  -> cheapest-first ordering
  -> date pairs and flexible variants
  -> cheapest flight for every participant
  -> group meetup score
  -> provider confidence
  -> save result
  -> rank and display
```

For each participant, the engine tries all their origin airports and active
providers, then keeps the cheapest viable flight. For a group, those participant
flights are combined into one destination/date result.

## Providers

The live provider factory uses:

- Ryanair,
- Internal Google Scraper,
- Google Multi-Mode,
- Duffel when enabled and budget-safe.

Guest searches are free-provider-only. Owner searches can use Duffel if the
token and daily budget allow it.

## Ranking

Results are ranked by all-in cost plus penalties. The all-in cost can include:

- flight prices,
- luggage fees,
- transfer costs.

Additional ranking factors include fairness and confidence.

Fairness reflects spread between participant prices. Confidence reflects whether
more than one independent source supports the quote.

## Results UX

The bot displays:

- 4 result cards per page,
- cheapest all-in total,
- flight total,
- bag and transfer add-ons when present,
- per-person prices and fairness bars,
- date range and night count,
- booking links per participant,
- confidence label.

Tapping a city opens a detail view with all matching date options for that city.
Each card and city-detail option has Verify and Paid actions.

## Storage

The app uses SQLite WAL. It stores both operational data and user-facing group
data:

- provider caches and quote history,
- one-way legs,
- meetup results,
- users,
- groups,
- group members,
- searches,
- share links,
- append-only fare observations,
- verification events,
- paid-price reports.

This lets the bot show old results, share results, inspect admin stats, and
resume with reusable groups.

## API

The FastAPI server is a secondary interface. It exposes health checks, direct
flight searches, scraper matrix calls, group/search/result reads, and public
share views.
It also exposes live result verification, paid-price reporting, and local
fare-intelligence endpoints.

Use it for debugging or integrating with other local tools. The Telegram bot is
the primary UX.

## Admin

The owner is the Telegram user whose ID matches `TELEGRAM_CHAT_ID`.

Owner-only `/admin` shows:

- user count and active users,
- group count,
- searches by status,
- result count,
- discovered city count,
- top destinations,
- drilldowns for users, groups, searches, and recent results.

Non-owners receive an owner-only rejection.

## Operational Tools

- `scripts/nightly_surface.py`: pre-compute route price surfaces.
- `scripts/canary.py`: daily provider smoke check.
- `scripts/dashboard.py`: static HTML dashboard from SQLite.
- `scripts/ical_export.py`: export a deal to `.ics`.
- `scripts/backup_db.py`: rotating DB backups.
- `scripts/kick_vps.py`: clear a competing Telegram bot session.

## Main Caveats

- Prices must still be verified before booking.
- Google scraping depends on `fast-flights` and can break if Google changes internals.
- Duffel is paid and should remain budget-limited.
- Some legacy env variables and clients remain in the repo but are not active providers.
