# Recommendation Tracker

Last updated: 2026-07-04

This file tracks the major recommendations and whether the live code reflects
them. It replaces the older v5.1-only checklist with the current v6.2 state.

## Done

| Area | Item |
|---|---|
| Data model | Flight fields for airline, flight number, currency, deep link, luggage flags |
| Data model | `SearchRequest` and `ParticipantGroup` replace hardcoded origins/dates |
| Data model | Group search results store `search_id` and `participants_json` |
| Cost | Transfers and luggage included in all-in cost when enabled |
| Cost | 10 kg carry-on table for major airlines |
| Cost | Flight-only and personal-item-only modes available in the bot wizard |
| Correctness | Flexible dates enforce min/max nights |
| Correctness | City-level display dedup |
| Correctness | Provider quote dedup for consensus |
| Correctness | Sanity-band checks for extreme outliers |
| Correctness | Arrival timezone normalization (hardcoded European UTC offsets, wired into scoring) |
| Correctness | Leg-combiner freshness cutoff |
| Performance | Shared provider thread pool |
| Performance | Ryanair session reuse |
| Performance | Cached provider health |
| Performance | SQLite indexes for result/cache/leg/search lookup |
| UX | Telegram-first design |
| UX | Group creation, invite links, and join flow |
| UX | 6-step search wizard |
| UX | Progress updates with ETA |
| UX | Paginated result cards |
| UX | City detail drilldown |
| UX | Per-person fairness bars |
| UX | Live Verify button for saved deals |
| UX | Paid-price reporting flow |
| UX | Owner-only admin dashboard |
| Ops | Canary, backup, dashboard, and iCal scripts |
| API | Group/search/result/share endpoints |
| API | Verification and local fare-intelligence endpoints |
| Safety | Duffel guest exclusion and daily budget helpers |
| Safety | Optional invite-only bot gate |
| Intelligence | Append-only local fare observation warehouse |
| Intelligence | User-reported paid-price ground truth |

## Still TODO

| Area | Item |
|---|---|
| Tests | HTTP fixtures and parser snapshots |
| Tests | More coverage for Telegram flows and storage migrations |
| Quality | ruff, mypy, pre-commit |
| Correctness | Upgrade timezone normalization to full OurAirports dataset (global/DST-accurate) |
| Correctness | Better different-day arrival handling |
| Product | Pareto frontier result views |
| Safety | Verify Duffel call recording wraps every paid API call |
| Intelligence | Booking-timing recommendations from fare observations |

## Current Completion Summary

The project has moved from a single hardcoded two-person search tool into a
multi-user Telegram meetup planner. The remaining work is mostly hardening:
tests, persistence completeness, auth/share safety, and production-readiness.
