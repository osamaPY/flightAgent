# Smart Search Layers

File: `src/core/smart_search.py`

Last updated: 2026-07-05

The app searches a very large space: participants x origins x destinations x
date pairs x providers. The smart layers keep that search useful, cheaper first,
and less noisy.

## Overview

```text
SearchRequest
  |
  v
L5 Cheapest-first destination ordering
  |
  v
L1 Calendar/history pre-scan
  |
  v
Date windows and exact date pairs
  |
  v
L4 Flexible date variants
  |
  v
Provider waterfall for each participant
  |
  +--> L3 provider consensus
  +--> L2 fresh one-way leg combiner fallback
  |
  v
score_group_meetup / rank_results
```

## L5: Cheapest-First Ordering

Historical `flight_legs` and cached price data are used to put promising
destinations earlier. Unknown destinations are not discarded; they sit in the
middle so a run can still discover new cheap cities.

This matters because long searches may be stopped early. The first 25-50% of a
run should still contain useful destinations.

## L1: Calendar Pre-Scan

Calendar and history data provide a rough map of cheap routes. Ryanair calendar
data is also used by `scripts/nightly_surface.py` to pre-build a price surface.

Since 2026-07-05, `booking_mode` also runs a **live discovery pre-scan**
(`discovery_prescan`) before L5 ordering: for every origin→candidate route the
Ryanair route graph confirms, one `cheapestPerDay` call pulls a whole month of
fares into `flight_legs`. Bounded (max calls, time budget, free provider only,
best-effort), so L5 orders destinations by *fresh* prices, not only history.

## Route-Graph Pruning

`src/core/route_graph.py` caches Ryanair's open route graph (7-day TTL,
fail-open). `RyanairProvider` and `RyanairCalendarProvider` skip HTTP instantly
when a route is provably not flown (e.g. BGY→JFK answers in ~0.2 ms instead of
a wasted network call). Unknown graph → never prune. Google providers are
unaffected, so coverage is unchanged - only guaranteed-empty calls are removed.

## L4: Flexible Dates

For a requested date pair, the engine can try:

- exact dates,
- outbound -1 day,
- outbound +1 day,
- return -1 day,
- return +1 day.

Every variant must still satisfy the request's `min_nights` and `max_nights`.
That prevents flexible date shifts from leaking 1-night or too-long trips.

## Provider Waterfall

`get_best_flight()` checks cache, fans out healthy providers in a shared
`ThreadPoolExecutor`, waits with timeout protection, saves quotes/legs/cache,
and returns the cheapest result rather than the first result.

## L3: Provider Consensus

Provider quotes are collapsed by same airline and near-same price before
confidence is assigned. This avoids counting one fare relayed through multiple
surfaces as multiple independent confirmations.

Confidence affects ranking through penalties: confirmed prices can outrank a
slightly cheaper single-source quote.

## L2: Leg Combiner

If round-trip providers do not return a result, fresh one-way legs can be paired
into an approximate round trip. The freshness cutoff prevents stale legs from
creating phantom deals.

Leg-combined results are advisory and should be verified before booking.

## Current Search Range

The code no longer has one fixed range. The range comes from `SearchRequest`.

Defaults and presets include:

- backward-compatible summer search: 2026-07-15 to 2026-08-12,
- bot quick picks: this weekend, next 2 weeks, next month, summer 2026, custom,
- night options surfaced in Telegram: fixed 2/3/4/5 nights or flexible 2-4 / 3-7.

Destination universe is also configurable: Europe, Schengen, or everywhere.
