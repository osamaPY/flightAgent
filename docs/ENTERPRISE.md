# Enterprise Architecture

This document sketches a future path if the app grows beyond a personal or
small-group Telegram bot.

Last updated: 2026-07-04

## Current Scale

Current architecture is optimized for local/small use:

- one Telegram bot process,
- one SQLite WAL database,
- threaded provider calls,
- local FastAPI server,
- optional paid Duffel provider with a simple in-process daily budget.

This is appropriate for a handful of groups, not 100,000 users.

## Target Shape

```text
Clients
  Telegram bot / Web app / API consumers
        |
        v
API gateway
  auth, rate limits, abuse controls
        |
        v
App services
  bot service, search API, result API, share API
        |
        v
Queue
  search.requests, search.progress, search.results
        |
        v
Workers
  provider waterfall, scraper jobs, nightly surfaces, canaries
        |
        v
Data layer
  Postgres, Redis, object storage, metrics
```

## Migration Steps

1. Split bot command handling from search execution.
2. Move search jobs to a durable queue.
3. Replace in-process search progress with persisted progress events.
4. Move SQLite to PostgreSQL with migrations.
5. Move API cache and circuit breaker state to Redis.
6. Add real auth and per-user/project quotas.
7. Add observability: metrics, traces, structured logs.
8. Add provider-cost controls and billing visibility.

## Future Components

| Component | Role |
|---|---|
| API Gateway | Rate limits, auth, TLS, abuse protection |
| Search API | Validates and enqueues searches |
| Bot Service | Telegram UX, no heavy search work |
| Worker Pool | Executes provider/search jobs |
| Redis | Cache, circuit state, progress pub/sub |
| PostgreSQL | Users, groups, searches, results, price history |
| Object Storage | HTML exports, artifacts, fixtures |
| Metrics Stack | Provider latency, cost, failure rates |

## Scaling Concerns

- Paid provider calls need tenant/user budgets.
- Scraping providers need strict rate limits and canary alerts.
- Search fanout can become enormous; queue limits and batching are required.
- Public share links need expiration, revocation, and access controls.
- Bot UX should remain fast while searches run asynchronously.

## Cost Direction

| Scale | Likely setup |
|---|---|
| Personal | Current local bot + SQLite |
| 10-100 users | VPS, managed Postgres optional, strict provider budgets |
| 1,000 users | Queue workers, Redis, Postgres, observability |
| 10,000+ users | Autoscaling workers, provider contracts, product-grade auth |
