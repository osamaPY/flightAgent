"""
Flight provider abstraction layer.

Each provider declares CAPABILITIES (see src/core/provider_registry.py) so the
search engine routes work by capability and tier, not by provider-name strings.

Base class (FlightProvider) handles:
  - Circuit breaker (3 failures → 15 min disable)
  - Exponential backoff retry
  - Cached health checks (15 min TTL, no HTTP on every call)
  - pre_call_ok()/record_call() hooks for metered (paid) providers

Providers (registered in provider_registry.py):
  Ryanair            — official API, free, live, VERIFICATION+DISCOVERY
  GoogleScraper      — fast-flights Protobuf, free, all airlines, both tiers
  Google Multi-Mode  — 3 search modes, free, wider coverage, both tiers
  Ryanair Calendar   — open cheapestPerDay surface, free, DISCOVERY only
  Duffel             — GDS, paid/bookable, VERIFICATION only (budget-gated)

Endpoint reality (probed 2026-07): Ryanair's public API is open (calendar,
route graph, airports). Wizz / easyJet / Vueling / Transavia / Kiwi are walled
(403 / Access Denied / deprecated) — their fares reach us via the Google
aggregator, not via direct readers. Add a new source by registering one spec.
"""

import time
import random
from abc import ABC, abstractmethod
from typing import List, Optional, Any

from fast_flights import FlightQuery, Passengers, create_query, get_flights

from src.core.scoring import Flight
from src.core.config import Config
from src.core.logger import log_info, log_error
from src.core.provider_registry import (
    ProviderCapabilities,
    GENERIC_CAPABILITIES,
    DISCOVERY,
    VERIFICATION,
)
from src.clients.ryanair_client import RyanairClient
from src.clients.duffel_client import DuffelClient


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class FlightProvider(ABC):
    # Each concrete provider declares its capability tags. The registry reads
    # these to route work by capability instead of by provider name.
    CAPABILITIES: ProviderCapabilities = GENERIC_CAPABILITIES

    def __init__(self):
        self._health_reason = "Unknown"
        self._consecutive_failures = 0
        self._disabled_until = 0
        self._last_health_check = 0.0
        self._last_health_result = True
        self._health_cache_ttl = 900  # 15 min

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self.CAPABILITIES

    # -- metered/paid providers override these to gate on budget --

    def pre_call_ok(self) -> bool:
        """Return False to skip this provider right now (e.g. paid budget spent).
        Free providers always return True."""
        return True

    def record_call(self) -> None:
        """Record a successful billable call. No-op for free providers."""
        return None

    # -- must override --

    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name."""

    @abstractmethod
    def search_round_trip(
        self, origin: str, destination: str,
        out_from: str, out_to: str,
        in_from: str, in_to: str,
    ) -> Optional[Flight]:
        """Return a round-trip Flight or None."""

    # -- override for live health --

    def _live_health_check(self) -> bool:
        """Override — actual HTTP health endpoint call. Called every 15 min."""
        return True

    # -- optional override --

    def search_one_way(
        self, origin: str, destination: str, date: str,
    ) -> List[Flight]:
        """One-way search. Only Ryanair + Google override this."""
        return []

    # -- base class implementation (don't override) --

    def is_healthy(self) -> bool:
        """Circuit breaker + cached health. No HTTP on every call."""
        if time.time() < self._disabled_until:
            self._health_reason = (
                f"Circuit breaker ({int(self._disabled_until - time.time())}s)"
            )
            return False
        now = time.time()
        if (now - self._last_health_check) < self._health_cache_ttl:
            return self._last_health_result
        try:
            self._last_health_result = self._live_health_check()
        except Exception:
            self._last_health_result = False
            self._health_reason = "health check exception"
        self._last_health_check = now
        return self._last_health_result

    def get_health_reason(self) -> str:
        if time.time() < self._disabled_until:
            return (
                f"Circuit breaker "
                f"({int(self._disabled_until - time.time())}s)"
            )
        return self._health_reason

    def _retry_search(self, search_fn, *args, retries=2):
        """Execute search_fn with retry + exponential backoff + circuit breaker."""
        if time.time() < self._disabled_until:
            log_error(f"[{self.name()}] Circuit breaker open. Skipping.")
            return None
        for i in range(retries + 1):
            try:
                result = search_fn(*args)
                if result:
                    self._consecutive_failures = 0
                    return result
            except Exception as e:
                self._consecutive_failures += 1
                if self._consecutive_failures >= 3:
                    self._disabled_until = time.time() + 900
                    log_error(
                        f"[{self.name()}] Circuit breaker tripped! "
                        f"15 min disable. Error: {e}"
                    )
                    return None
                if i == retries:
                    raise e
                backoff = (2 ** i) + random.random()
                log_info(
                    f"[{self.name()}] Retry in {backoff:.1f}s "
                    f"(attempt {i + 1}/{retries})"
                )
                time.sleep(backoff)
        return None


# ---------------------------------------------------------------------------
# 1. Ryanair — official public API
# ---------------------------------------------------------------------------

class RyanairProvider(FlightProvider):
    CAPABILITIES = ProviderCapabilities(
        key="ryanair",
        label="Ryanair",
        airline="FR",
        region="EU-LCC",
        cost="free",
        freshness="live",
        bookable=False,          # deep-link handoff, not a bookable offer we hold
        has_round_trip=True,
        has_one_way=True,
        has_calendar=True,       # cheapestPerDay — open, confirmed 2026-07
        tiers=frozenset({DISCOVERY, VERIFICATION}),
    )

    def __init__(self):
        super().__init__()
        self.client = RyanairClient(debug=False)

    def name(self) -> str:
        return "Ryanair"

    @staticmethod
    def _route_pruned(origin: str, dest: str) -> bool:
        """True only when the route graph PROVES Ryanair doesn't fly this route.
        Unknown graph → fail-open (never prune)."""
        try:
            from src.core.route_graph import get_route_graph
            return get_route_graph().flies(origin, dest) is False
        except Exception:
            return False

    def search_round_trip(self, origin, dest, out_from, out_to, in_from, in_to):
        if self._route_pruned(origin, dest):
            return None  # route provably absent — skip the HTTP entirely
        try:
            return self._retry_search(
                self.client.round_trip_fare,
                origin, dest, out_from, out_to, in_from, in_to,
            )
        except Exception:
            return None

    def search_one_way(self, origin, dest, date):
        if self._route_pruned(origin, dest):
            return []
        try:
            return self.client.cheapest_fares(origin, date, date, destination=dest)
        except Exception:
            return []

    def _live_health_check(self) -> bool:
        import requests
        try:
            r = requests.get(
                "https://services-api.ryanair.com/farfnd/3/oneWayFares",
                timeout=5,
            )
            if r.status_code in (200, 400):
                return True
            self._health_reason = f"HTTP {r.status_code}"
            return False
        except Exception as e:
            self._health_reason = str(e)
            return False


# ---------------------------------------------------------------------------
# 2. GoogleScraper — fast-flights Protobuf
# ---------------------------------------------------------------------------

class GoogleScraperProvider(FlightProvider):
    CAPABILITIES = ProviderCapabilities(
        key="google",
        label="Internal Google Scraper",
        airline=None,            # aggregator — every airline's prices
        region="GLOBAL",
        cost="free",
        freshness="live",
        bookable=False,
        has_round_trip=True,
        has_one_way=True,
        has_calendar=False,
        tiers=frozenset({DISCOVERY, VERIFICATION}),
    )

    def __init__(self):
        super().__init__()
        from src.clients.google_scraper import GoogleScraperClient
        self.client = GoogleScraperClient()

    def name(self) -> str:
        return "Internal Google Scraper"

    def search_round_trip(self, origin, dest, out_from, out_to, in_from, in_to):
        try:
            return self.client.search_round_trip(
                origin, dest, out_from, in_from,
            )
        except Exception as e:
            log_error(f"GoogleScraper error: {e}")
            return None

    def search_one_way(self, origin, dest, date):
        try:
            return self.client.search_flights(origin, dest, date)
        except Exception:
            return []

    def _live_health_check(self) -> bool:
        return True  # No API key — always available


# ---------------------------------------------------------------------------
# 3. Duffel — GDS
# ---------------------------------------------------------------------------

class DuffelProvider(FlightProvider):
    CAPABILITIES = ProviderCapabilities(
        key="duffel",
        label="Duffel",
        airline=None,            # GDS — multi-airline
        region="GLOBAL",
        cost="paid",             # metered — budget-gated
        freshness="live",
        bookable=True,           # real GDS offers — the verification voice
        has_round_trip=True,
        has_one_way=False,
        has_calendar=False,
        tiers=frozenset({VERIFICATION}),
    )

    def __init__(self, token: str):
        super().__init__()
        self.client = DuffelClient(token)

    def name(self) -> str:
        return "Duffel"

    # Paid provider: gate every call on the daily budget (was a name-string
    # check inside get_best_flight; now it lives with the provider).
    def pre_call_ok(self) -> bool:
        from src.core.provider_factory import duffel_under_budget
        return duffel_under_budget()

    def record_call(self) -> None:
        from src.core.provider_factory import record_duffel_call
        record_duffel_call()

    def search_round_trip(self, origin, dest, out_from, out_to, in_from, in_to):
        try:
            fares = self.client.search_round_trip(origin, dest, out_from, in_from)
            return fares[0] if fares else None
        except Exception:
            return None

    def _live_health_check(self) -> bool:
        import requests
        if not self.client.token or len(self.client.token) < 5:
            self._health_reason = "Missing token"
            return False
        try:
            r = requests.get(
                "https://api.duffel.com/air/airlines",
                headers=self.client.headers,
                timeout=5,
            )
            if r.status_code in (200, 400):
                return True
            self._health_reason = f"HTTP {r.status_code}"
            return False
        except Exception as e:
            self._health_reason = str(e)
            return False


# ---------------------------------------------------------------------------
# 4. Google Multi-Mode — same Protobuf, 3 search modes
# ---------------------------------------------------------------------------

class MultiGoogleScraperProvider(FlightProvider):
    """Queries Google Flights in direct + all + calendar modes for wider coverage."""

    CAPABILITIES = ProviderCapabilities(
        key="google_multi",
        label="Google Multi-Mode",
        airline=None,
        region="GLOBAL",
        cost="free",
        freshness="live",
        bookable=False,
        has_round_trip=True,
        has_one_way=True,
        has_calendar=True,       # exposes a calendar query mode
        tiers=frozenset({DISCOVERY, VERIFICATION}),
    )

    def __init__(self):
        super().__init__()
        from src.scrapers.multi_google import MultiModeGoogleScraper
        self._scraper = MultiModeGoogleScraper(debug=False, cache_ttl=3600)

    def name(self) -> str:
        return "Google Multi-Mode"

    def search_round_trip(self, origin, dest, out_from, out_to, in_from, in_to):
        try:
            return self._scraper.search_round_trip(
                origin, dest, out_from, in_from,
            )
        except Exception:
            return None

    def search_one_way(self, origin, dest, date):
        try:
            return self._scraper.search_one_way(origin, dest, date)
        except Exception:
            return []

    def _live_health_check(self) -> bool:
        return True  # No API key, same backend as GoogleScraper


# ---------------------------------------------------------------------------
# 5. Ryanair Calendar — DISCOVERY tier
# ---------------------------------------------------------------------------

class RyanairCalendarProvider(FlightProvider):
    """Discovery-tier provider built on Ryanair's open `cheapestPerDay` calendar.

    One HTTP call returns a whole month of cheapest fares for a route, so a
    round trip over a date *window* costs ~2 calls instead of ~1 per date pair.
    That is the 10-50x call-volume reduction that makes broad discovery cheap.

    Results are approximate (cheapest outbound day + cheapest return day within
    the window, not a confirmed paired itinerary), so this provider is tagged
    DISCOVERY only — it never feeds the exact-date verification search, and its
    Flights carry `is_approximate=True`. Verify before booking.
    """

    CAPABILITIES = ProviderCapabilities(
        key="ryanair_calendar",
        label="Ryanair Calendar",
        airline="FR",
        region="EU-LCC",
        cost="free",
        freshness="near-live",
        bookable=False,
        has_round_trip=True,
        has_one_way=True,
        has_calendar=True,
        tiers=frozenset({DISCOVERY}),
    )

    def __init__(self):
        super().__init__()
        self.client = RyanairClient(debug=False)

    def name(self) -> str:
        return "Ryanair Calendar"

    def search_one_way(self, origin, dest, date):
        """Cheapest fares per day across the month containing `date`."""
        if RyanairProvider._route_pruned(origin, dest):
            return []  # route provably absent — skip the HTTP entirely
        try:
            from datetime import datetime, timedelta
            start = datetime.strptime(date, "%Y-%m-%d")
            end = start + timedelta(days=30)
            return self.client.cheapest_per_day(
                origin, dest, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
            )
        except Exception:
            return []

    def search_round_trip(self, origin, dest, out_from, out_to, in_from, in_to):
        """Approximate round trip: cheapest outbound day in [out_from, out_to]
        paired with cheapest return day in [in_from, in_to], both from one
        calendar call each."""
        if RyanairProvider._route_pruned(origin, dest):
            return None
        try:
            outbound = self.client.cheapest_per_day(origin, dest, out_from, out_to)
            inbound = self.client.cheapest_per_day(dest, origin, in_from, in_to)
            if not outbound or not inbound:
                return None
            best_out = min(outbound, key=lambda f: f.price)
            best_in = min(inbound, key=lambda f: f.price)
            return Flight(
                origin=origin,
                destination=dest,
                price=best_out.price + best_in.price,
                outbound_date=best_out.outbound_date,
                return_date=best_in.outbound_date,
                stops=0,
                arrival_time=best_out.arrival_time,
                departure_time=getattr(best_out, "departure_time", ""),
                source="ryanair_calendar",
                airline="FR",
                currency="EUR",
                is_approximate=True,       # discovery-grade — verify before booking
                cabin_bag_included=False,
                deep_link=getattr(best_out, "deep_link", ""),
            )
        except Exception as exc:
            log_error(f"RyanairCalendar error {origin}->{dest}: {exc}")
            return None

    def _live_health_check(self) -> bool:
        import requests
        try:
            r = requests.get(
                "https://services-api.ryanair.com/farfnd/3/oneWayFares",
                timeout=5,
            )
            return r.status_code in (200, 400)
        except Exception as e:
            self._health_reason = str(e)
            return False
