# Flight Meet Agent — Build Spec (€0)

<aside>
🎯

A near-€0 personal agent that finds the cheapest European city where two people (Milan + Riga) can both fly round-trip, meet, and return home. Includes a critical review of the plan and all copy-paste prompts for Zencoder / Cursor.

</aside>

## 1. The plan in one line

**Ryanair-first free monitor → Travelpayouts broad discovery → SerpApi top-result verification → Telegram alerts.** No AI guessing of prices; AI only summarizes/ranks/explains.

- **Person A** — Milan: `BGY`, `MXP`, `LIN`
- **Person B** — Latvia: `RIX`
- **Goal** — minimize *combined* round-trip cost to a shared meeting city on shared dates.

---

## 2. Critical review (what's weak, what's unrealistic)

The plan is solid and correctly scaled. But here are the real weak points to build around — don't skip these, they're where it breaks in practice.

### ⚠️ Data-source reality

- **Travelpayouts / Aviasales is CACHED, not live.** It returns cheapest *known* fares (often month-level, sometimes days old). Great for **discovery**, useless as final truth. Always mark its prices as approximate and re-verify.
- **Ryanair public endpoints are unofficial + personal-use only.** They can change or rate-limit without notice. Keep volume low, add retries, a real `User-Agent`, and caching. Terms allow private non-commercial use only — keep it personal.
- **SerpApi free tier is a limited trial (~100 searches), not a renewing free tier.** Use it *only* to verify the top 5–10 finalists. Add a hard monthly call-budget guard in code so you never get surprise-billed.
- **Skyscanner API is partner-only** — cut it from automation entirely. Use it only manually in a browser before booking.

### ⚠️ Logic gaps to close

- **Shared dates are the hard constraint.** Both people must be in the same city on the same days. Search *date windows*, not single dates, and only keep destinations where both round trips overlap on the same range.
- **Force EUR currency everywhere** so totals are comparable.
- **Arrival-gap matters more than a fancy comfort score.** For v1, only track: direct vs stops, and how far apart the two arrivals are (in local time). Drop layover/baggage/airport-distance penalties for now.
- **Baggage warning.** Ryanair's headline fare excludes bags — always append "verify baggage" to alerts.

### ✅ Verdict

The architecture is right and near-€0 is realistic. The three-scan split (discovery / monitoring / verification) is the key idea that keeps it cheap. Biggest risks are **cached-data accuracy** and **unofficial-endpoint fragility** — both handled by the mandatory manual final check.

---

## 3. Final architecture (3 layers)

| Layer | Source | Frequency | Cost | Job |
| --- | --- | --- | --- | --- |
| Monitoring | Ryanair public fares (BGY, MXP, LIN, RIX) | every 6–12h | €0 | Track the 20–40 best candidate cities |
| Discovery | Travelpayouts / Aviasales free API | weekly | €0 | Find new cheap cities Ryanair misses (Wizz/easyJet/airBaltic) |
| Verification | SerpApi Google Flights | on demand, top 5–10 only | free trial | Confirm finalists before you look manually |
| Final check | Google Flights / Skyscanner in browser | before booking | €0 | Confirm price, bags, times, booking link |

**Alerts:** Telegram bot (free). **Schedule:** GitHub Actions cron (free). **Storage:** SQLite or CSV in the repo (free).

---

## 4. Repo structure

```
flight-meet-agent/
  main.py                 # orchestrates discovery + monitoring + ranking + alerts
  config.py               # airports, date windows, target price, budgets
  airports.py             # candidate destination list (start ~30, not all Europe)
  ryanair_client.py       # free Ryanair fare endpoints (monitoring)
  travelpayouts_client.py # cached broad discovery
  serpapi_client.py       # top-result verification, budget-guarded
  scoring.py              # combined price + simple stops/arrival-gap ranking
  notifier.py             # Telegram alerts
  storage.py              # SQLite/CSV persistence + price-drop detection
  requirements.txt
  .env.example
  README.md
  .github/workflows/flight-check.yml
```

---

## 5. Copy-paste prompts for Zencoder / Cursor

<aside>
💡

Paste these one at a time, in order. Let each step run and check the file it produced before moving on. Every prompt tells the AI to keep it simple — no FastAPI, React, or Postgres.

</aside>

### 5.0 — Master context (paste FIRST, once)

```
You are helping me build a small PERSONAL, non-commercial Python project called "flight-meet-agent".

Goal: find the cheapest European city where two people can both fly ROUND-TRIP on the same date window, meet, and return home.
- Person A origins: BGY, MXP, LIN (Milan)
- Person B origin: RIX (Riga)
- Combined cost = A round trip + B round trip. Rank ascending.

Hard rules:
- NEVER invent or estimate prices with an LLM. All prices come from data sources.
- Keep it simple: pure Python, no FastAPI, no React, no Postgres. Use SQLite/CSV.
- All prices in EUR.
- Data sources: Ryanair public fares (monitoring, free), Travelpayouts/Aviasales (cached discovery, free), SerpApi Google Flights (verification only, limited).
- Treat Ryanair/Travelpayouts endpoints as UNOFFICIAL and fragile: add timeouts, retries, a realistic User-Agent, and caching.
- Add a hard monthly API-call budget guard for SerpApi so I never overspend.
- Every output must include a "verify manually before booking" warning.

Confirm you understand, then wait for my next message before writing code.
```

### 5.1 — Project setup

```
Create the project scaffold for flight-meet-agent with this exact structure:

flight-meet-agent/
  main.py, config.py, airports.py, ryanair_client.py, travelpayouts_client.py,
  serpapi_client.py, scoring.py, notifier.py, storage.py,
  requirements.txt, .env.example, README.md, .github/workflows/flight-check.yml

Requirements:
- Python 3.11+. Use `requests`, `python-dotenv`, and stdlib `sqlite3`/`csv` only for now.
- requirements.txt: requests, python-dotenv (and pytest for tests).
- .env.example with placeholders: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TRAVELPAYOUTS_TOKEN, SERPAPI_KEY, TARGET_PRICE_EUR, SERPAPI_MONTHLY_BUDGET.
- config.py loads env vars via dotenv and exposes typed config values with sensible defaults.
- Add a .gitignore that excludes .env, *.db, __pycache__, results.csv.
- Leave the other module files as stubs with docstrings describing their job.
Show me the tree and file contents.
```

### 5.2 — [config.py](http://config.py)

```
Flesh out config.py.

Define:
- ORIGINS_A = ["BGY", "MXP", "LIN"], ORIGIN_B = "RIX"
- DATE_WINDOWS: a list of (depart_earliest, depart_latest, min_nights, max_nights) so we search flexible trips, not single dates. Start with the next 8 weekends, 2–4 nights.
- TARGET_PRICE_EUR (from env, default 200)
- CURRENCY = "EUR"
- SERPAPI_MONTHLY_BUDGET (from env, default 90) and a helper to read/reset a monthly counter stored in SQLite.
- Load secrets from .env via python-dotenv.
Keep everything typed and documented.
```

### 5.3 — [airports.py](http://airports.py)

```
Build airports.py.

- Provide a hand-picked CANDIDATE_DESTINATIONS list of ~30 European airports likely cheap from BOTH Milan and Riga (e.g. WAW, KRK, GDN, WMI, PRG, BUD, VIE, BER, BRU, CRL, EIN, AMS, CPH, ARN, VNO, KUN, TLL, MLA, VLC, BCN, CIA, NAP, SOF, OTP, ZAG, ATH, DUB, LTN, STN, TSF).
- Exclude any origin airport from destinations.
- Add an OPTIONAL function load_europe_airports_from_ourairports() that downloads the OurAirports CSV and filters to large_airport + medium_airport with a valid IATA code, excluding closed/heliport/seaplane. Cache the CSV locally. This is for the weekly discovery scan only.
- Return simple dataclasses with iata, name, country.
```

### 5.4 — ryanair_[client.py](http://client.py)

```
Build ryanair_client.py using Ryanair's public/unofficial fare endpoints (the ones the Ryanair site/app use), free and keyless.

- Function cheapest_fares(origin, date_from, date_to) that returns cheapest one-way fares to many destinations (use Ryanair's "one-way fares" / farfnd style endpoint).
- Function round_trip_fare(origin, destination, out_from, out_to, in_from, in_to, currency="EUR") returning cheapest outbound + inbound and the total, with dates and flight numbers if available.
- Robustness: 10s timeout, 3 retries with backoff, realistic User-Agent header, graceful None on failure.
- Simple in-memory + on-disk cache (TTL ~2h) to avoid hammering the endpoint.
- Return typed dataclasses. Add a __main__ block that prints cheapest fares from BGY as a smoke test.
```

### 5.5 — travelpayouts_[client.py](http://client.py)

```
Build travelpayouts_client.py using the Travelpayouts / Aviasales Data API (free, needs TRAVELPAYOUTS_TOKEN).

- Function cheapest_by_origin(origin, currency="EUR") returning cached cheapest fares to many destinations.
- Function price_for_route(origin, destination, month) returning cheapest cached fare.
- Clearly mark all returned prices as approximate/cached (add a `source="travelpayouts_cached"` and `is_approximate=True` field).
- Timeout, retries, graceful failure. Read token from env.
- __main__ smoke test printing cheapest cached fares from RIX.
```

### 5.6 — serpapi_[client.py](http://client.py)

```
Build serpapi_client.py using SerpApi engine=google_flights (verification only).

- Function verify_round_trip(origins_csv, destination, outbound_date, return_date, currency="EUR", deep_search=False) returning the cheapest real price, airline, stops, and times.
- Support comma-separated origins like "MXP,BGY,LIN".
- BUDGET GUARD: before every call, check the monthly SerpApi counter in SQLite via storage/config; if the budget is exhausted, skip the call and return None with a logged warning. Increment the counter on each successful call.
- Timeout, retries, graceful failure, key from env.
- __main__ smoke test verifying one BGY->WAW round trip.
```

### 5.7 — [scoring.py](http://scoring.py)

```
Build scoring.py.

- Input: for a destination, Person A's cheapest round trip and Person B's cheapest round trip (with dates, stops, arrival times).
- combined_total = A.total + B.total (both EUR).
- Only keep destinations where A and B can be there on the SAME date window (overlapping meeting days >= min_nights).
- Simple ranking key: primarily combined_total; light tiebreakers: fewer total stops, smaller arrival-time gap (convert to local time).
- Return a sorted list of result dataclasses with: destination, a_price, b_price, total, dates, airlines/source, stops, arrival_gap_hours, is_approximate, and a fixed warning string "Verify manually before booking (check baggage, times, booking link)."
- Do NOT add layover/baggage/airport-distance penalties yet.
```

### 5.8 — [notifier.py](http://notifier.py)

```
Build notifier.py for Telegram (free bot).

- send_message(text) using TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID via the Bot API sendMessage endpoint.
- format_alert(result) producing a clean message, e.g.:
  "✈️ Cheap meetup found\nWarsaw — €132 total\nYou: BGY→WAW→BGY €48 (direct)\nHer: RIX→WAW→RIX €84 (direct)\nDates: 15–17 Aug\nSource: Ryanair (verify baggage)\n⚠️ Verify manually on Google Flights/Skyscanner before booking."
- Timeout, retries, graceful failure if Telegram is unreachable.
- __main__ sends a test message.
```

### 5.9 — [storage.py](http://storage.py)

```
Build storage.py using SQLite (and a CSV export helper).

- Tables: results (all scans with timestamp), price_history (destination + combined_total over time), api_budget (month, serpapi_calls).
- save_results(results), export_csv(path), get_previous_best(destination).
- is_price_drop(destination, new_total): True if new_total is below the previous best AND below TARGET_PRICE_EUR — used to trigger alerts and avoid spamming.
- Helpers for the SerpApi monthly budget counter (get/increment/reset-by-month).
- Create tables on first run.
```

### 5.10 — [main.py](http://main.py) (orchestration)

```
Build main.py to tie everything together.

Modes via CLI arg:
- `python main.py monitor`  -> for each CANDIDATE_DESTINATIONS: get Person A round trip (ryanair_client across BGY/MXP/LIN) and Person B round trip (RIX) over DATE_WINDOWS; score; save; alert on price drops below TARGET.
- `python main.py discover` -> weekly: use travelpayouts_client (and optionally OurAirports list) to propose NEW cheap candidate cities from both origins; print them so I can add to airports.py.
- `python main.py verify`   -> take top 5–10 saved results and confirm with serpapi_client (budget-guarded); update stored prices.

Always: print a clean top-10 table, export results.csv, and never send duplicate alerts for the same best price. Wrap each destination in try/except so one failure doesn't kill the run.
```

### 5.11 — GitHub Actions cron

```
Create .github/workflows/flight-check.yml.

- Schedule: run `monitor` every 12 hours (two cron entries or every 6h if I want).
- Add a weekly schedule that also runs `discover`.
- Steps: checkout, setup-python 3.11, pip install -r requirements.txt, run `python main.py monitor`.
- Read all secrets from GitHub Actions secrets (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TRAVELPAYOUTS_TOKEN, SERPAPI_KEY, TARGET_PRICE_EUR) and pass as env.
- Commit the updated SQLite db / results.csv back to the repo after each run (or upload as an artifact) so price history persists.
- Add workflow_dispatch so I can trigger it manually.
```

### 5.12 — README

```
Write README.md covering:
- What the project does and the 3-layer architecture (monitoring/discovery/verification + manual final check).
- Setup: create a Telegram bot with @BotFather, get chat id, get a free Travelpayouts token, optional SerpApi key.
- Filling .env from .env.example.
- Running locally: monitor / discover / verify modes.
- Deploying the GitHub Actions cron + where to put secrets.
- Clear disclaimer: personal, non-commercial use; prices are indicative; always verify manually before booking; unofficial endpoints may break.
```

### 5.13 — Testing & debugging

```
Add a tests/ folder with pytest tests:
- Unit tests for scoring.py (combined total, date-overlap filtering, ranking order) using fake fare objects.
- Tests for storage.py (save, price-drop detection, budget counter) against an in-memory SQLite db.
- Mock all network calls (requests) in client tests so tests run offline.
Also add a `python main.py selftest` command that runs each client's smoke test with clear PASS/FAIL output and prints which data sources are reachable and which env vars are missing.
```

---

## 6. Build order (do it in this sequence)

1. 5.0 master context → 5.1 setup → 5.2 config
2. 5.3 airports → 5.4 Ryanair client (get real fares printing first!)
3. 5.7 scoring → 5.9 storage → 5.10 main `monitor` mode → run locally
4. 5.8 Telegram → wire alerts
5. 5.5 Travelpayouts (`discover`) → 5.6 SerpApi (`verify`)
6. 5.11 GitHub Actions → 5.12 README → 5.13 tests

<aside>
⚠️

Golden rule: get **real Ryanair prices printing in your terminal** before building anything else. If the data layer works, the rest is easy. If it doesn't, nothing above it matters.

</aside>