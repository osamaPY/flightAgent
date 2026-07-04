"""Capability-tagged provider registry — the single source of truth for which
flight providers exist, what each is good at, and which search tier it serves.

This is the keystone refactor. It lets us:

  * add a new airline / reader by registering ONE spec — no edits to the search
    engine, no hardcoded provider-name strings sprinkled through main.py;
  * route work by *capability* ("who has a calendar?", "who is bookable?")
    instead of by provider name;
  * express the DISCOVERY vs VERIFICATION split cleanly.

Tiers
-----
DISCOVERY    — broad, cheap, allowed to be slightly stale. Answers
               "which cities/dates are worth looking at?" across a huge space.
               Calendar endpoints, aggregators, history.
VERIFICATION — narrow, live, must be bookable. Answers "is THIS specific deal
               real right now?" Runs only on the shortlist discovery surfaced.

A provider may serve one tier or both. `build_providers(tier=...)` filters by
tier, so the current exact-date search keeps getting exactly today's providers
(tier=VERIFICATION), while a future calendar-first discovery pipeline can ask
for `build_discovery_providers()` without touching any caller.

NOTE: this module must not import `providers` at module top — provider classes
import `ProviderCapabilities` from here, so the concrete classes are imported
lazily inside `_build_registry()` to avoid a circular import.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, FrozenSet

# ---------------------------------------------------------------------------
# Tier constants
# ---------------------------------------------------------------------------

DISCOVERY = "discovery"
VERIFICATION = "verification"


# ---------------------------------------------------------------------------
# Capability tags
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderCapabilities:
    """What a provider is good at. Attached to each provider as `.capabilities`
    and referenced by the registry to route work by capability, not by name."""

    key: str                                    # stable id, e.g. "ryanair"
    label: str                                  # human name (== provider.name())
    airline: Optional[str] = None               # IATA carrier code; None = multi-airline aggregator
    region: str = "EU"                          # coverage hint: "EU" | "EU-LCC" | "GLOBAL" | ...
    cost: str = "free"                          # "free" | "paid"
    freshness: str = "live"                     # "live" | "near-live" | "cached"
    bookable: bool = False                      # produces bookable/verifiable offers (real GDS)
    has_round_trip: bool = True
    has_one_way: bool = False                   # exposes search_one_way (feeds the leg combiner)
    has_calendar: bool = False                  # cheap month-level fare surface (discovery fuel)
    tiers: FrozenSet[str] = frozenset({DISCOVERY, VERIFICATION})

    @property
    def metered(self) -> bool:
        """Paid providers whose per-call usage must be budget-gated."""
        return self.cost == "paid"

    def serves(self, tier: Optional[str]) -> bool:
        return tier is None or tier in self.tiers


# Fallback for a provider that forgot to declare capabilities (defensive default).
GENERIC_CAPABILITIES = ProviderCapabilities(key="generic", label="Generic")


@dataclass(frozen=True)
class ProviderSpec:
    """A registered provider: its capabilities, how to build it, and a runtime
    gate deciding whether it is usable right now (token present, budget left,
    feature flag on)."""

    capabilities: ProviderCapabilities
    factory: Callable[[], "object"]             # returns a FlightProvider instance
    enabled: Callable[[], bool] = lambda: True

    @property
    def key(self) -> str:
        return self.capabilities.key


# ---------------------------------------------------------------------------
# The registry (built lazily to avoid the providers <-> registry import cycle)
# ---------------------------------------------------------------------------

_REGISTRY: Optional[List[ProviderSpec]] = None


def _duffel_enabled() -> bool:
    """Duffel is paid: only usable with a token AND remaining daily budget."""
    try:
        from src.core.provider_factory import duffel_budget_ok
        return duffel_budget_ok()
    except Exception:
        return False


def _build_registry() -> List[ProviderSpec]:
    """Construct the ordered provider registry.

    Order matters only for display / stable iteration; selection is by tier
    and capability, never by position.
    """
    from src.core.config import Config
    from src.core.providers import (
        DuffelProvider,
        GoogleScraperProvider,
        MultiGoogleScraperProvider,
        RyanairCalendarProvider,
        RyanairProvider,
    )

    return [
        ProviderSpec(RyanairProvider.CAPABILITIES, RyanairProvider),
        ProviderSpec(GoogleScraperProvider.CAPABILITIES, GoogleScraperProvider),
        ProviderSpec(MultiGoogleScraperProvider.CAPABILITIES, MultiGoogleScraperProvider),
        # Discovery-only: cheap month-level Ryanair fare surface. Not returned to
        # the exact-date (VERIFICATION) search, so it is non-breaking today; a
        # future calendar-first discovery pipeline pulls it via tier=DISCOVERY.
        ProviderSpec(RyanairCalendarProvider.CAPABILITIES, RyanairCalendarProvider),
        # Paid GDS: verification voice only, budget-gated.
        ProviderSpec(
            DuffelProvider.CAPABILITIES,
            lambda: DuffelProvider(Config.DUFFEL_TOKEN),
            enabled=_duffel_enabled,
        ),
    ]


def get_registry() -> List[ProviderSpec]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY


def all_capabilities() -> List[ProviderCapabilities]:
    """Introspection helper — every registered provider's capability tags."""
    return [spec.capabilities for spec in get_registry()]


# ---------------------------------------------------------------------------
# Build helpers — the one place providers get instantiated
# ---------------------------------------------------------------------------

def build_providers(
    tier: Optional[str] = None,
    include_paid: bool = True,
    only_healthy: bool = False,
) -> List["object"]:
    """Instantiate providers matching a tier + constraints.

    Args:
        tier: DISCOVERY, VERIFICATION, or None (any tier).
        include_paid: when False, paid/metered providers are excluded (guest-safe).
        only_healthy: when True, filter through cached health checks.
    """
    out: List[object] = []
    for spec in get_registry():
        if not spec.capabilities.serves(tier):
            continue
        if spec.capabilities.metered and not include_paid:
            continue
        try:
            if not spec.enabled():
                continue
        except Exception:
            continue
        try:
            out.append(spec.factory())
        except Exception:
            # A single mis-configured provider must never sink the whole list.
            continue

    if only_healthy:
        out = [p for p in out if p.is_healthy()]
    return out


def build_verification_providers(include_paid: bool = True) -> List["object"]:
    """Live, exact-date, bookable-grade providers (today's default search set)."""
    return build_providers(tier=VERIFICATION, include_paid=include_paid)


def build_discovery_providers() -> List["object"]:
    """Broad, cheap, calendar-capable providers for shortlist discovery.

    Paid providers are always excluded from discovery — broad scans must stay
    free. Ready for a calendar-first discovery pipeline; no caller is forced to
    adopt it.
    """
    return build_providers(tier=DISCOVERY, include_paid=False)
