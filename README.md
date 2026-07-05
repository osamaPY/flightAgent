# Flight Meetup Optimizer

A Telegram bot that works out where a group of friends should meet up when everyone's flying in from a different city.

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![tests](https://github.com/osamaPY/flight-meetup-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/osamaPY/flight-meetup-agent/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

The hard part of planning a trip with friends spread across Europe isn't finding a cheap flight. It's that "cheap" is different for everyone, and the price you see online isn't what you actually pay once you add a bag and the train from the airport into town. So instead of five people opening twenty tabs each, this scans destinations and dates and ranks cities by what the whole group really pays, door to door.

It started as a two-person "where do we meet, Milan or Riga?" script and grew into a proper multi-user bot.

## How it works

Make a group in the bot and share the invite link. People join and say which airports they can fly from - you can type "milan" or "riga", the codes aren't required. Hit search, and it goes through destinations across Europe, finds each person's cheapest realistic round trip, adds the bag fee for that airline and the airport-to-city transfer, and sends back a ranked list of cities with the cost broken down per person. Everyone in the group gets a message when it's finished, not just whoever started it.

There's also an AI button (DeepSeek): it reads the actual results and tells you which city to go for and why, and can suggest a few things to do in the one you're leaning towards.

Roughly what a result looks like in chat:

```
Best meetups - Weekend Crew
3 cities · all-in per group · tap a city for details

1. 🇦🇹 Vienna - €142 · 3n · confirmed
2. 🇭🇺 Budapest - €158 · 3n · one source
3. 🇵🇹 Porto - €171 · 3n · confirmed

        [ Which should we pick? ]
```

Tap that button and the LLM comes back with something like: *"Vienna. It's the cheapest at €142 and you both pay close to the same (€60 vs €40), so it's fair. Budapest's a good shout if you want louder nightlife."*

## Running it

```bash
git clone https://github.com/osamaPY/flight-meetup-agent.git
cd flight-meetup-agent
pip install -r requirements.txt
cp .env.example .env
python telegram_bot.py
```

You need a `TELEGRAM_BOT_TOKEN` (from [@BotFather](https://t.me/BotFather)) and your own `TELEGRAM_CHAT_ID` in `.env`. The rest is optional: `DEEPSEEK_API_KEY` turns on the AI features, `DUFFEL_TOKEN` adds a paid GDS source. Without either, it still runs fine on the free Ryanair and Google data.

```bash
python -m pytest -q         # tests, no network needed
python main.py health       # check which providers are up
python flight_api_server.py # optional REST API on :8000
```

To run it 24/7 on a server (AWS free-tier or any Linux VPS), there's a one-command setup in [deploy/](deploy/README.md): clone the repo, run `bash deploy/setup.sh`, add your token, and a `systemd` service keeps it alive across crashes and reboots.

## How it's built

The stack is Python: `python-telegram-bot` for the bot, SQLite (WAL) for storage, `fast-flights` for Google Flights data, Ryanair's public API, Travelpayouts (a free flight-data API that keeps working from a server IP), an optional Duffel GDS source, DeepSeek for the LLM bits, and a small FastAPI server on the side for debugging.

A few decisions worth explaining:

**Searching is split in two.** Scanning the whole map cheaply and confirming one specific deal are different jobs, so they use different sources. Discovery pulls Ryanair's month-at-a-time calendar (one request covers ~31 days of fares) to decide which cities are even worth looking at; verification then checks the shortlist live. It's a lot fewer calls than pricing every date individually.

**Providers are registered, not hardcoded.** Each one declares what it can do - which airline, free or paid, has a calendar, can be booked, which tier it belongs to - and the search engine picks by those tags instead of checking provider names in `if` statements. Adding a source is one entry in `provider_registry.py`.

**It skips routes that don't exist.** Ryanair publishes its route map, so before firing a request for, say, Bergamo→New York, it checks the cached graph and skips it instantly. If the graph is unavailable it just doesn't skip anything, so it can never hide a route that's actually there.

**The price is meant to be honest.** Bag fees are per-airline, airport transfers are included, and when only one source has a fare it says so rather than pretending it's confirmed. There's a verify step to re-check a deal live before you book, because a confidently wrong price is worse than no price.

**The AI is kept on a short leash.** The recommendation is given only the numbers already computed and told not to invent fares - it's choosing between real options, not making up prices. There's also an "Ask a question" helper so a non-technical user can type something like "how do I add my friend?" and get a plain answer. Every AI call is optional and fails quietly, so the bot never breaks if DeepSeek is down or no key is set.

There are 65 tests that run offline (no network, no API key) covering the registry, the route-graph fallback behaviour, the discovery scan, the bot's rendering helpers, manual-member handling, the Travelpayouts client, and the AI prompt-building with a mocked client. They run in CI on every push.

Full docs are in [guidebook/](guidebook/): [setup](guidebook/SETUP.md), [architecture](guidebook/ARCHITECTURE.md), [providers](guidebook/PROVIDERS.md), [search layers](guidebook/SMART_LAYERS.md), a [codebase tour](guidebook/CODEBASE_GUIDE.md), and [troubleshooting](guidebook/TROUBLESHOOTING.md). To run it 24/7 on a server, see [deploy/](deploy/README.md).

## Layout

```
telegram_bot.py            the bot (main thing people use)
main.py                    search engine + CLI
flight_api_server.py       FastAPI server
src/core/                  registry, search, scoring, route graph, AI, storage, UI helpers
src/clients/               ryanair, google, duffel, deepseek
scripts/                   nightly price surface, canary, backups, dashboard
tests/                     offline tests
guidebook/                 setup and architecture docs
```

## A few honest caveats

It only covers European destinations for now. It reads public and consenting endpoints - Ryanair's open API, Google Flights via `fast-flights`, optionally Duffel - and deliberately doesn't scrape the airlines that wall themselves off, so most non-Ryanair fares come through Google rather than a direct source. Prices move constantly, so always confirm on the airline's own checkout before booking. It's a personal project, not affiliated with any airline.

## License

[MIT](LICENSE) © 2026 Oussama El Mir ([osamaPY](https://github.com/osamaPY))
