"""Offline tests for the provider registry, route-graph pruning, and the
calendar discovery pre-scan. No HTTP — everything network-shaped is faked.

Run:  python -m pytest tests/test_registry.py -q
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import src.utils.compat  # noqa

from src.core import provider_registry as reg
from src.core import route_graph as rg_mod
from src.core.route_graph import RouteGraph
from src.core.scoring import Flight


# ---------------------------------------------------------------------------
# Registry invariants
# ---------------------------------------------------------------------------

def test_registry_keys_unique():
    keys = [c.key for c in reg.all_capabilities()]
    assert len(keys) == len(set(keys)), f"duplicate registry keys: {keys}"


def test_registry_tiers_valid():
    for c in reg.all_capabilities():
        assert c.tiers, f"{c.key}: empty tiers"
        assert c.tiers <= {reg.DISCOVERY, reg.VERIFICATION}, f"{c.key}: bad tier"


def test_paid_providers_never_serve_discovery():
    """A broad discovery scan must never cost money."""
    for c in reg.all_capabilities():
        if c.cost == "paid":
            assert reg.DISCOVERY not in c.tiers, f"{c.key} is paid AND discovery"


def test_duffel_is_metered_verification_only():
    duffel = next(c for c in reg.all_capabilities() if c.key == "duffel")
    assert duffel.metered
    assert duffel.bookable
    assert duffel.tiers == frozenset({reg.VERIFICATION})


def test_discovery_tier_has_calendar_capability():
    disc = [c for c in reg.all_capabilities() if reg.DISCOVERY in c.tiers]
    assert any(c.has_calendar for c in disc), "no calendar source in discovery"


def test_build_verification_free_matches_legacy_set():
    """Guest (free, exact-date) set == the pre-refactor hardcoded trio."""
    names = [p.name() for p in reg.build_providers(tier=reg.VERIFICATION, include_paid=False)]
    assert names == ["Ryanair", "Internal Google Scraper", "Google Multi-Mode"]


def test_build_discovery_includes_calendar_excludes_paid():
    names = [p.name() for p in reg.build_discovery_providers()]
    assert "Ryanair Calendar" in names
    assert "Duffel" not in names


def test_all_instantiated_providers_expose_capability_hooks():
    for p in reg.build_providers(tier=None, include_paid=False):
        assert p.capabilities.key != "generic", f"{p.name()} missing CAPABILITIES"
        assert p.pre_call_ok() is True          # free providers never gate
        p.record_call()                          # no-op, must not raise


# ---------------------------------------------------------------------------
# Route graph
# ---------------------------------------------------------------------------

class _FakeGraph(RouteGraph):
    """RouteGraph with a canned _fetch — no HTTP, temp cache file."""

    def __init__(self, cache_file, responses):
        self._responses = responses            # origin -> list[str] | None
        super().__init__(cache_file=cache_file)

    def _fetch(self, origin):
        return self._responses.get(origin)


def test_route_graph_flies_true_false(tmp_path):
    g = _FakeGraph(str(tmp_path / "rg.json"), {"BGY": ["VIE", "RIX"]})
    assert g.flies("BGY", "VIE") is True
    assert g.flies("BGY", "XYZ") is False       # provably absent -> prunable
    assert g.flies("bgy", "vie") is True        # case-insensitive


def test_route_graph_fail_open(tmp_path):
    g = _FakeGraph(str(tmp_path / "rg.json"), {})  # every fetch fails
    assert g.flies("BGY", "VIE") is None        # unknown -> never prune


def test_route_graph_persists_to_disk(tmp_path):
    cache = str(tmp_path / "rg.json")
    g1 = _FakeGraph(cache, {"RIX": ["BCN"]})
    assert g1.flies("RIX", "BCN") is True
    # New instance whose fetch always fails must serve from the disk cache:
    g2 = _FakeGraph(cache, {})
    assert g2.flies("RIX", "BCN") is True


def test_provider_prunes_only_on_proven_absence(tmp_path, monkeypatch):
    from src.core.providers import RyanairProvider

    fake = _FakeGraph(str(tmp_path / "rg.json"), {"BGY": ["VIE"]})
    monkeypatch.setattr(rg_mod, "_GRAPH", fake)

    assert RyanairProvider._route_pruned("BGY", "XYZ") is True    # proven absent
    assert RyanairProvider._route_pruned("BGY", "VIE") is False   # exists
    assert RyanairProvider._route_pruned("ZZZ", "VIE") is False   # unknown -> open


# ---------------------------------------------------------------------------
# Discovery pre-scan
# ---------------------------------------------------------------------------

class _FakeCalendarClient:
    def __init__(self):
        self.calls = []

    def cheapest_per_day(self, origin, dest, date_from, date_to):
        self.calls.append((origin, dest))
        return [
            Flight(
                origin=origin, destination=dest, price=19.99,
                outbound_date=date_from, return_date="", stops=0,
                arrival_time=f"{date_from} 12:00", source="ryanair_calendar",
                airline="FR", is_approximate=True,
            )
        ]


def test_discovery_prescan_saves_legs_for_confirmed_routes(tmp_path):
    from src.core.smart_search import discovery_prescan
    from src.core.storage import Storage

    storage = Storage(db_path=str(tmp_path / "test.db"))
    graph = _FakeGraph(str(tmp_path / "rg.json"), {"BGY": ["VIE", "BUD"]})
    client = _FakeCalendarClient()

    saved = discovery_prescan(
        storage, ["BGY", "ZZZ"], ["VIE", "BUD", "XYZ"],
        "2026-08-01", "2026-08-31",
        _client=client, _graph=graph,
    )

    # Only confirmed routes called: BGY->VIE, BGY->BUD.
    # ZZZ (unknown graph) and XYZ (not served) are skipped.
    assert sorted(client.calls) == [("BGY", "BUD"), ("BGY", "VIE")]
    assert saved == 2

    with storage._get_connection() as conn:
        rows = conn.cursor().execute(
            "SELECT origin, destination, price FROM flight_legs ORDER BY destination"
        ).fetchall()
    assert [(r[0], r[1]) for r in rows] == [("BGY", "BUD"), ("BGY", "VIE")]
    assert all(abs(r[2] - 19.99) < 0.01 for r in rows)


def test_discovery_prescan_respects_max_calls(tmp_path):
    from src.core.smart_search import discovery_prescan
    from src.core.storage import Storage

    storage = Storage(db_path=str(tmp_path / "test.db"))
    graph = _FakeGraph(str(tmp_path / "rg.json"), {"BGY": ["VIE", "BUD", "KRK"]})
    client = _FakeCalendarClient()

    discovery_prescan(
        storage, ["BGY"], ["VIE", "BUD", "KRK"],
        "2026-08-01", "2026-08-31",
        max_calls=2, _client=client, _graph=graph,
    )
    assert len(client.calls) == 2


def test_discovery_prescan_no_graph_is_noop(tmp_path):
    from src.core.smart_search import discovery_prescan
    from src.core.storage import Storage

    storage = Storage(db_path=str(tmp_path / "test.db"))
    graph = _FakeGraph(str(tmp_path / "rg.json"), {})   # graph down
    client = _FakeCalendarClient()

    saved = discovery_prescan(
        storage, ["BGY"], ["VIE"], "2026-08-01", "2026-08-31",
        _client=client, _graph=graph,
    )
    assert saved == 0
    assert client.calls == []                            # no blind HTTP
