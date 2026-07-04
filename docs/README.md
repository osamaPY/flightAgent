# Documentation Hub

Current project snapshot: 57 files, 37 Python files, 8,787 Python lines.

Last updated: 2026-07-04

## Documents

| Document | Contents |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Current topology, data flow, storage, API, and bot architecture |
| [CODEBASE_GUIDE.md](CODEBASE_GUIDE.md) | File map, models, commands, and debugging notes |
| [COMPLETE_GUIDE.md](COMPLETE_GUIDE.md) | End-to-end explanation of the system |
| [PROVIDERS.md](PROVIDERS.md) | Active provider list, Duffel safety, consensus, bags, and transfers |
| [SMART_LAYERS.md](SMART_LAYERS.md) | The 5 search layers and how searches are ordered/scored |
| [SETUP.md](SETUP.md) | Install, environment variables, bot setup, and run modes |
| [ROADMAP.md](ROADMAP.md) | Completed work and remaining TODOs |
| [ENTERPRISE.md](ENTERPRISE.md) | Future scale architecture |
| [FABLE5_CHECKLIST.md](FABLE5_CHECKLIST.md) | Recommendation/status tracker |

## System At A Glance

```text
telegram_bot.py v6.2
  group creation, invite links, 6-step search wizard, results, admin

main.py
  provider waterfall, booking_mode, CLI, legacy/default search support

flight_api_server.py
  REST endpoints for health, search, scraper matrix, groups, searches, shares

src/core
  SearchRequest, scoring, storage, smart layers, provider factory, costs

SQLite WAL
  results, cache, legs, quotes, users, groups, members, searches, share links
```

## Current Behavioral Truths

- The bot is the primary product surface.
- Searches are no longer hardcoded to two people or Milan + Riga.
- The default Milan + Riga summer search remains for CLI/backward compatibility.
- The result cost model is configurable: luggage and transfers can be included or skipped.
- Duffel is paid and protected: owner searches may use it, guests use free providers.
- Admin visibility is owner-only and based on `TELEGRAM_CHAT_ID`.
- Sharing exists through API share endpoints, but the Telegram bot is still the main sharing experience.
