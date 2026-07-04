# Setup And Configuration

Last updated: 2026-07-04

## Prerequisites

- Python 3.11+
- Telegram bot token from BotFather if using the bot
- Optional Duffel token for paid GDS quotes

SQLite is built in; the app creates `data/flights.db` automatically.

## Install

```bash
pip install -r requirements.txt
copy .env.example .env
```

On Unix-like shells, use `cp .env.example .env`.

## Important Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot only | Token from BotFather |
| `TELEGRAM_CHAT_ID` | Owner/admin | Telegram user ID treated as owner |
| `REQUIRE_INVITE_CODE` | Optional | `1` makes the bot invite-only |
| `DUFFEL_TOKEN` | Optional | Enables paid Duffel provider for owner searches |
| `DUFFEL_DAILY_BUDGET` | Optional | Daily Duffel safety cap, default 50 |
| `TARGET_PRICE_EUR` | Optional | Price threshold used by older CLI flows |
| `MAX_API_CALLS_PER_RUN` | Optional | Safety cap for full scans |
| `JWT_SECRET` | Future/API auth | Present in config, not central to current bot UX |

`ADMIN_SECRET` remains in the environment template, but current owner checks are
based on `TELEGRAM_CHAT_ID` in `telegram_bot.py`.

## Run The Bot

```bash
python telegram_bot.py
```

Recommended first flow:

1. Send `/start`.
2. Tap create group, or send `/newgroup`.
3. Enter group name, size, and your airports.
4. Share the generated invite link.
5. Start `/newsearch <group_id>` after members join.
6. View `/results_<group_id>`.

If `REQUIRE_INVITE_CODE=1`, only invited users can use the bot.

## Run CLI

```bash
python main.py
python main.py booking-mode
python main.py health
python main.py inspect-db
python main.py selftest
```

CLI flows are still useful for debugging and for the original default search.

## Run API

```bash
python flight_api_server.py
```

Open `http://127.0.0.1:8000`.

Useful endpoints:

```bash
curl http://127.0.0.1:8000/health
curl "http://127.0.0.1:8000/search?origin=BGY&destination=VIE&out=2026-07-25&return=2026-07-27"
curl "http://127.0.0.1:8000/groups/<group_id>"
curl "http://127.0.0.1:8000/searches/<search_id>/results"
```

## Operational Scripts

```bash
python scripts/nightly_surface.py
python scripts/canary.py
python scripts/dashboard.py
python scripts/ical_export.py 5
python scripts/backup_db.py
python scripts/kick_vps.py
```

## Clean Slate

To clear search results:

```bash
python -c "from src.core.storage import Storage; s=Storage(); s.clear_results()"
```

This does not necessarily remove all users/groups/search metadata. For a total
database reset, stop the app and remove `data/flights.db` and its WAL/SHM files.
