# Complete Guide

Last updated: 2026-07-05

## The Problem

A group of people want to meet somewhere in Europe. Each person may have
multiple nearby departure airports. The useful question is not "what is the
cheapest flight for one person?" but:

> Which destination is cheapest and fairest for everyone, on dates that work?

The app automates that search across destinations, date pairs, providers,
luggage assumptions, and airport transfer costs.

## The Current Product

The current product is a Telegram bot (v7):

1. Create a group.
2. Add your friends: either enter their airports yourself with Add a friend
   (handy when you already know where they fly from), or send a one-tap invite
   link so they join and enter their own.
3. Airports accept city names like "milan", not just codes.
4. Tap Find flights for a one-tap search with smart defaults, or Pick dates /
   options first to tune dates, nights, luggage, direct-only, and region.
5. The bot scans destinations and dates; live progress updates in place.
6. Review the ranked city list and tap a city for the full breakdown.
7. Optionally ask the AI concierge which city to pick and what to do there.
8. Tap Verify before booking to re-check the exact saved itinerary live.
9. Report what you actually paid after booking so the local dataset improves.

Everyone in the group is notified when results are ready, not just the person
who started the search. The original Milan + Riga summer search is still
available as a default, but it is no longer the only supported shape.

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

The bot exposes these as a single settings panel with smart defaults (next
month, 2-4 nights, 10kg cabin, transfers included, any flights, Europe).
Launch is always one tap; tap any row to change it first:

- travel window,
- nights,
- luggage,
- airport transfers,
- direct vs any flights,
- Europe / Schengen / everywhere.

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

Providers are declared with capability tags in a registry and split into two
tiers: discovery (broad, cheap, calendar-first) and verification (live,
bookable). The live set:

- Ryanair (both tiers),
- Ryanair Calendar (discovery only, whole-month fare surface),
- Internal Google Scraper (both tiers),
- Google Multi-Mode (both tiers),
- Duffel (verification only, paid) when enabled and budget-safe.

Guest searches are free-provider-only. Owner searches can use Duffel if the
token and daily budget allow it. Adding a source is one registry entry. See
[PROVIDERS.md](PROVIDERS.md).

## Ranking

Results are ranked by all-in cost plus penalties. The all-in cost can include:

- flight prices,
- luggage fees,
- transfer costs.

Additional ranking factors include fairness and confidence.

Fairness reflects spread between participant prices. Confidence reflects whether
more than one independent source supports the quote.

## Results UX

The bot shows a compact ranked list (top three get medals), one line per city
with the all-in group price, nights, and a confidence icon. Tapping a city
opens a detail card:

- cheapest all-in total, plus flight total and bag/transfer add-ons,
- per-person prices with fairness bars,
- date range and night count,
- booking links per participant,
- confidence label,
- Verify and Paid actions,
- other date options for the same city.

The results screen also offers optional AI buttons (see below).

## AI Concierge

When a DeepSeek key is configured, two optional buttons appear:

- "Which should we pick?" reads the real ranked deals and recommends one city
  with a short, human reason. It is given only the computed numbers and told not
  to invent prices.
- "Things to do" gives a quick trip idea for a city, sized to the nights.

Both are optional and fail quietly: if the key is missing or the API is down,
the buttons simply do nothing and the rest of the bot is unaffected. The LLM
never touches pricing or the search itself.

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
- The AI concierge is optional and for guidance only; it never sets prices.
- Some legacy env variables and clients remain in the repo but are not active providers.
