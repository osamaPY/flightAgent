# Provider System

Last updated: 2026-07-05

## Provider Registry And Tiers

`src/core/provider_registry.py` is the single source of truth for which
providers exist, what each is good at, and which search tier it serves. Every
provider declares `CAPABILITIES` (a `ProviderCapabilities`): `airline`,
`region`, `cost`, `freshness`, `bookable`, `has_calendar`, `has_one_way`, and
`tiers`. The search engine routes work by capability - never by provider-name
strings.

Two tiers express the discovery/verification split:

| Tier | Job | Freshness | Providers |
|---|---|---|---|
| `DISCOVERY` | Broad, cheap "which cities/dates are worth looking at?" | May be slightly stale | Ryanair, Ryanair Calendar, Google, Google Multi-Mode |
| `VERIFICATION` | Narrow, live "is THIS deal real right now?" | Must be live/bookable | Ryanair, Google, Google Multi-Mode, Duffel |

Adding a source is one `ProviderSpec` in the registry - no edits to `main.py` or
the search engine. Build helpers: `build_verification_providers()` (today's
default exact-date set), `build_discovery_providers()` (free calendar-capable
set, paid providers always excluded).

Metered (paid) providers gate themselves via `pre_call_ok()` / `record_call()`
on the provider base class, so budget logic no longer lives as name-string
checks inside `get_best_flight`.

## Active Providers

| Provider class | Source | Cost | Tiers | Used for |
|---|---|---|---|---|
| `RyanairProvider` | Ryanair public JSON endpoints | Free | Both | Direct LCC prices, one-way legs, exact-date round trips |
| `RyanairCalendarProvider` | Ryanair `cheapestPerDay` calendar | Free | Discovery | Whole-month fare surface in ~1 call/route (approximate) |
| `GoogleScraperProvider` | `fast-flights` Google Flights Protobuf | Free | Both | Broad airline coverage (aggregator breadth) |
| `MultiGoogleScraperProvider` | Google Flights queried in direct/all/calendar modes | Free | Both | Wider search coverage and backup signal |
| `DuffelProvider` | Duffel GDS API | Paid | Verification | Independent bookable GDS offers and confidence |

## Direct-Airline Coverage Reality (probed 2026-07-05)

Direct airline readers were probed for key-free availability. Only Ryanair's
public API answers cleanly (calendar, route graph `/api/views/locate/.../routes`,
active-airports list - all HTTP 200 JSON). The rest are walled and would need
CAPTCHA/proxy evasion, which is out of scope:

| Carrier / source | Result |
|---|---|
| Ryanair | Open - calendar, routes, airports all 200 JSON |
| Wizz Air | 403 (Cloudflare) |
| easyJet | 403 Access Denied (Akamai) |
| Vueling | Host not resolvable / walled |
| Transavia | 500 (needs official API key) |
| Kiwi (skypicker) | 404 (endpoint deprecated; Tequila needs a key) |

Consequence: every non-Ryanair airline's **fares** reach us via the Google
aggregator, not via direct readers. The registry makes adding a source trivial
the moment a consenting endpoint (or an Amadeus/other API key) becomes available.

## Duffel Safety

Duffel is paid, so v6 added a safety layer:

- Guest searches use `build_guest_providers()` and do not include Duffel.
- Owner searches may use Duffel through `build_providers()` / `build_owner_providers()`.
- Duffel is only added when `DUFFEL_TOKEN` is set and `DUFFEL_DAILY_BUDGET` remains.
- Budget helpers track calls per local day: `duffel_budget_remaining`,
  `duffel_budget_used_today`, `record_duffel_call`, and `duffel_budget_ok`.

Set `DUFFEL_DAILY_BUDGET=0` to effectively disable Duffel.

## Health And Reliability

All providers inherit from `FlightProvider`, which supplies:

- failure tracking,
- circuit breaker behavior,
- health status/reason fields,
- retry/backoff wrapper hooks.

`provider_factory.py` adds a 15-minute health cache so Telegram commands do not
perform live HTTP checks every time.

## Provider Consensus

The ranking system prefers confirmed prices. Quotes are deduplicated by airline
and near-identical price before being counted, so Google showing the same
Ryanair fare is not treated as an independent second source.

Confidence labels:

| Label | Meaning |
|---|---|
| `HIGH` | Multiple independent sources agree closely |
| `MEDIUM` | Multiple sources exist but disagree more |
| `SINGLE` / `SINGLE_SOURCE` | One source only; verify before booking |
| `LOW` | Weak/stale/fallback signal |

## Luggage Costing

Default search mode is `carryon_10kg`.

Known examples:

| Airline | Code | 10 kg carry-on round trip |
|---|---|---|
| Ryanair | FR | EUR 40 |
| Wizz Air | W6 | EUR 36 |
| easyJet | U2 | EUR 14 |
| Norwegian | DY | EUR 22 |
| airBaltic | BT | EUR 24 |
| Vueling | VY | EUR 22 |
| Eurowings | EW | EUR 16 |
| Lufthansa / Air France / KLM / BA | LH / AF / KL / BA | EUR 0 assumed included |

The bot also exposes `none` and `checked_23kg` modes through the search wizard.

## Transfer Costing

`cost_utils.py` contains transfer costs for many airports and renders
human-readable airport-to-city method/cost details. Search requests can include
or exclude transfers.

Destination transfer costs are multiplied by the number of travelers because
everyone needs destination airport-city transport.

## Removed Or Inactive Providers

Older docs and `.env.example` still mention several providers that are no
longer active in the provider factory. Examples include SerpApi, Travelpayouts,
RapidAPI/Kiwi, Aviationstack, SearchAPI, Amadeus placeholders, and dead airline
scrapers. They are not part of the live provider list unless explicitly
re-enabled in code.
