# Troubleshooting And Issues We Hit

Last updated: 2026-07-05

A plain record of the real problems that came up while building and deploying
this, what caused them, and how they were resolved. If you run into something
odd, check here first.

## No results / "0 deals" on a cloud server (the big one)

**Symptom:** the bot runs fine on a laptop and finds deals, but the same bot on
an AWS/VPS server returns "0 deals" every time, and searches take a long time
before giving up.

**Cause:** flight data sources block datacenter IP addresses. Google Flights
(via `fast-flights`) and most airline sites sit behind Cloudflare/Akamai and
return nothing (or 403) when the request comes from an AWS/GCP/Azure IP. The
bot itself reaches Telegram fine (that is not blocked), so the bot looks
healthy while every price lookup quietly comes back empty. It then grinds
through the full destination sweep making calls that all fail, which is why it
is both slow and empty.

**Fixes / what to do:**
- Lean on API-based sources that do not care about the IP: Ryanair's public
  JSON API (usually not blocked) and Travelpayouts (`TRAVELPAYOUTS_TOKEN`,
  free). These work from a server.
- Confirm what your server can reach with the diagnostic in the deploy notes
  (a tiny script that calls Ryanair and Travelpayouts directly).
- If you want full Google-level breadth on a server, either call a scraping/SERP
  API (paid, e.g. SerpAPI) from the server, put a residential proxy in front of
  the scrapers, or host on a machine with a residential IP (a home mini-PC or
  Raspberry Pi running the same `deploy/setup.sh`).
- The engine now logs provider health at the start of each search, so
  `journalctl -u flight-bot -f` shows exactly which sources are reachable.

## Settings panel repeated many times / "Message is too long"

**Symptom:** opening the search setup showed the same panel pasted about 18
times, and tapping a setting (like Dates) did nothing.

**Cause:** a Python gotcha. The divider line was written as
`f"...text\n" f"─" * 18`. Implicit string-literal concatenation binds
tighter than `*`, so it repeated the whole preceding block 18 times. The
message blew past Telegram's 4096-character limit, the edit failed, and the
date picker never opened.

**Fix:** rebuilt the panel from a joined list (no adjacent-literal trap), added
a length guard in the render helper so no card can ever exceed the limit, and
registered an error handler so a bad screen cannot crash a handler. Covered by
a regression test.

## Stop button did nothing during "warming up"

**Symptom:** pressing Stop while the card said "warming up 0%" had no effect.

**Cause:** the calendar discovery pre-scan runs before the main loop and never
checked the stop flag, so it finished on its own before anything looked at the
stop signal.

**Fix:** the pre-scan now polls the stop signal and aborts immediately, the
launch guards the pre-scan on the stop flag, and the Stop button gives instant
"stopping" feedback.

## Progress card looked frozen

**Symptom:** the progress card sat on the first city and did not visibly move.

**Cause:** updates only fired on a percentage change, which barely moves on a
large sweep, so it looked stuck.

**Fix:** progress updates on a short time interval too, and the card shows an
exact check count (for example `7/500 checks`) so large searches visibly
advance.

## One person's search wiped what the group saw

**Symptom:** a friend ran a search that found nothing, and then everyone in the
group saw "no deals," even though an earlier run had found cities.

**Cause:** the results screen always loaded the single most recent search.

**Fix:** it now shows the newest search that actually produced deals (a running
search still shows its own live state), so an empty or failed run no longer
hides the group's good results. Groups are otherwise fully isolated: every
search is keyed by its group and its results by that search's id, so groups
never see each other's data.

## Amadeus was removed as a free option

**Symptom:** setup docs used to suggest Amadeus for free coverage.

**Cause:** Amadeus discontinued its free Self-Service test tier in 2026, so it
is no longer a no-cost source.

**Fix:** removed Amadeus from the setup, README, and providers guide.
Travelpayouts is the recommended free, server-friendly source now. The dormant
Amadeus provider code remains but nothing points people at it.

## Search felt slow / "brute force"

**Symptom:** searches, especially with the widest region, took a long time.

**Cause:** the sweep covers a large destination set (a couple hundred cities)
across date pairs and providers. On a small server, and especially when a
source is timing out, that adds up. On a blocked server it is worst of all
because every call fails slowly.

**Status:** the primary cause on a server is the IP blocking above; fix that
first. Bounded scan size and per-source timeouts are the next tuning lever once
sources are reachable.

## "Conflict" errors in the logs

**Symptom:** the logs show a Telegram `Conflict` error.

**Cause:** two copies of the bot are polling with the same token (for example,
one on your laptop and one on the server).

**Fix:** run only one instance. If you deploy to the server, stop the local one.
The service retries on its own once the other copy stops.

## Coverage is Europe only

The destination list covers European cities. Origins or destinations outside
Europe (for example Moldova as a meeting city, or Iran) are not in the set, so
"all cities we cover" still means Europe. This is a data-coverage limit, not a
bug. The scope options are Europe, Schengen only, or all covered cities.
