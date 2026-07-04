"""Single source of truth for the active provider list.

SMOKE-TESTED 2026-07-04: Only the providers below returned real prices.
The broken ones were removed entirely; their client modules have been
deleted from src/clients/.

ACTIVE PROVIDERS (4):
  1. Ryanair             — Official API, 0.6s, free
  2. GoogleScraper       — fast-flights Protobuf, 1.2s, free
  3. Google Multi-Mode   — 3 search modes, free
  4. Duffel              — GDS, 1.0s, PAID (token required)

v6: DUFFEL SAFETY — Duffel is paid-per-call. Guest users (non-owner friends)
    get FREE providers only by default. Duffel has a daily budget cap with
    a kill-switch. Owner can override via DUFFEL_FOR_GUESTS=1.

v5: Health checks are cached for 15 minutes to avoid HTTP calls on every
    Telegram command. Providers create their own connection pools via
    requests.Session() where applicable.
"""

import os
import time
from datetime import datetime
from typing import List, Optional

from src.core.config import Config
from src.core.providers import (
    DuffelProvider,
    FlightProvider,
    GoogleScraperProvider,
    MultiGoogleScraperProvider,
    RyanairProvider,
)
from src.core.storage import Storage

# ---------------------------------------------------------------------------
# v5: Cached health checks — avoids HTTP on every command
# ---------------------------------------------------------------------------
_health_cache: dict = {}          # provider_name → (healthy_bool, timestamp, reason)
_HEALTH_CACHE_TTL = 900           # 15 minutes


def _cached_is_healthy(provider: FlightProvider) -> bool:
    """Check health with caching. Only does live HTTP every 15 minutes."""
    now = time.time()
    name = provider.name()
    entry = _health_cache.get(name)
    if entry and (now - entry[1]) < _HEALTH_CACHE_TTL:
        return entry[0]

    try:
        ok = provider._live_health_check()
    except Exception:
        ok = False
        provider._health_reason = "health check exception"

    _health_cache[name] = (ok, now, provider.get_health_reason())
    return ok


def _get_healthy(providers: List[FlightProvider]) -> List[FlightProvider]:
    """Filter providers using cached health checks."""
    return [p for p in providers if _cached_is_healthy(p)]


def flush_health_cache():
    """Force re-check on next call (used after circuit breaker trips)."""
    _health_cache.clear()


# ═══════════════════════════════════════════════════════════════════════════
# v6: Duffel budget tracking (PAID provider — protect the owner's wallet)
# ═══════════════════════════════════════════════════════════════════════════

_duffel_calls_today: int = 0
_duffel_date: str = ""
_duffel_daily_budget: int = int(os.getenv("DUFFEL_DAILY_BUDGET", "50"))


def _reset_duffel_budget_if_new_day():
    global _duffel_calls_today, _duffel_date
    today = datetime.now().strftime("%Y-%m-%d")
    if today != _duffel_date:
        _duffel_calls_today = 0
        _duffel_date = today


def duffel_budget_remaining() -> int:
    """How many Duffel calls are left today?"""
    _reset_duffel_budget_if_new_day()
    return max(0, _duffel_daily_budget - _duffel_calls_today)


def duffel_budget_used_today() -> int:
    _reset_duffel_budget_if_new_day()
    return _duffel_calls_today


def record_duffel_call() -> bool:
    """Record a Duffel API call. Returns True if within budget, False if exceeded."""
    global _duffel_calls_today
    _reset_duffel_budget_if_new_day()
    if _duffel_calls_today >= _duffel_daily_budget:
        return False  # Budget exceeded
    _duffel_calls_today += 1
    return True


def duffel_under_budget() -> bool:
    """Check if Duffel is still within budget (without recording a call)."""
    _reset_duffel_budget_if_new_day()
    return _duffel_calls_today < _duffel_daily_budget


def duffel_budget_ok() -> bool:
    """v6: Whether Duffel can be used right now. Checks token + budget."""
    if not Config.DUFFEL_TOKEN:
        return False
    return duffel_under_budget()


# ═══════════════════════════════════════════════════════════════════════════
# Provider builder with guest/owner modes
# ═══════════════════════════════════════════════════════════════════════════

def build_providers(
    storage: Storage | None = None,
    include_duffel: bool = True,
) -> List[FlightProvider]:
    """Build the default (exact-date) provider list.

    Delegates to the capability-tagged registry (src/core/provider_registry.py),
    requesting VERIFICATION-tier providers — i.e. exactly today's live exact-date
    search set. Discovery-only providers (e.g. Ryanair Calendar) are excluded
    here, so this stays byte-compatible with the previous hardcoded behavior.

    v6: include_duffel=False gives free-only providers (safe for guests).
    Owner gets Duffel if the token is set and budget remains (registry gate).
    """
    from src.core import provider_registry as registry
    return registry.build_verification_providers(include_paid=include_duffel)


def build_guest_providers(storage: Storage | None = None) -> List[FlightProvider]:
    """Free-only providers — safe for guest friends."""
    return build_providers(storage, include_duffel=False)


def build_owner_providers(storage: Storage | None = None) -> List[FlightProvider]:
    """All providers including Duffel (if token set and budget available)."""
    return build_providers(storage, include_duffel=True)


def build_discovery_providers(storage: Storage | None = None) -> List[FlightProvider]:
    """Broad, cheap, calendar-capable providers for shortlist discovery.

    Free-only by design (paid providers must never fan out over a broad scan).
    Ready for a calendar-first discovery pipeline; no current caller is forced
    to adopt it.
    """
    from src.core import provider_registry as registry
    return registry.build_discovery_providers()


def get_healthy_providers() -> List[FlightProvider]:
    """One-shot: build + filter healthy (with caching)."""
    providers = build_providers()
    return _get_healthy(providers)
