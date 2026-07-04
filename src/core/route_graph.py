"""Ryanair route graph — which routes actually exist.

Open endpoint (probed 2026-07-05, HTTP 200 JSON, no key needed):

    https://www.ryanair.com/api/views/locate/searchWidget/routes/en/airport/{IATA}

Purpose: PRUNE wasted provider calls. `RyanairProvider` and
`RyanairCalendarProvider` skip HTTP instantly when the graph proves Ryanair
does not fly origin->dest. Google-based providers still cover those routes, so
pruning costs zero coverage — it only removes guaranteed-empty calls.

Semantics are deliberately three-valued and FAIL-OPEN:

    flies(o, d) -> True    graph fetched, route exists
                   False   graph fetched, route provably absent  (safe to prune)
                   None    graph unavailable                     (never prune)

Cache: data/route_graph.json — 7-day TTL per origin, thread-safe, with a
short negative-TTL so a failing endpoint is not hammered inside one run.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Dict, List, Optional, Set

import requests

from src.core.logger import log_info, log_error

ROUTES_URL = "https://www.ryanair.com/api/views/locate/searchWidget/routes/en/airport/{origin}"
CACHE_FILE = os.path.join("data", "route_graph.json")
CACHE_TTL = 7 * 24 * 3600          # routes change on schedule seasons, not hourly
FAILURE_TTL = 600                  # don't re-hit a failing endpoint for 10 min

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


class RouteGraph:
    """Per-origin sets of Ryanair-served destination IATAs, disk-cached."""

    def __init__(self, cache_file: str = CACHE_FILE):
        self._cache_file = cache_file
        self._lock = threading.Lock()
        # origin -> {"destinations": [..], "fetched_at": epoch}
        self._cache: Dict[str, Dict] = {}
        # origin -> epoch of last failed fetch (in-memory only)
        self._failures: Dict[str, float] = {}
        self._load()

    # -- persistence ---------------------------------------------------------

    def _load(self) -> None:
        try:
            if os.path.exists(self._cache_file):
                with open(self._cache_file, "r") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._cache = data
        except (json.JSONDecodeError, IOError):
            self._cache = {}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._cache_file) or ".", exist_ok=True)
            with open(self._cache_file, "w") as f:
                json.dump(self._cache, f)
        except IOError as exc:
            log_error(f"RouteGraph: cache save failed: {exc}")

    # -- fetching -------------------------------------------------------------

    def _fetch(self, origin: str) -> Optional[List[str]]:
        """One HTTP call: every destination Ryanair serves from `origin`.
        Returns None on any failure (fail-open upstream)."""
        try:
            r = requests.get(
                ROUTES_URL.format(origin=origin), headers=_HEADERS, timeout=10,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            if not isinstance(data, list):
                return None
            dests = []
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                code = (entry.get("arrivalAirport") or {}).get("code", "")
                if code:
                    dests.append(code)
            return dests or None
        except Exception:
            return None

    # -- public API -----------------------------------------------------------

    def destinations(self, origin: str) -> Optional[Set[str]]:
        """Set of IATAs Ryanair serves from `origin`, or None if unknown."""
        origin = origin.upper().strip()
        now = time.time()

        with self._lock:
            entry = self._cache.get(origin)
            if entry and (now - entry.get("fetched_at", 0)) < CACHE_TTL:
                return set(entry.get("destinations", []))
            if (now - self._failures.get(origin, 0)) < FAILURE_TTL:
                return None  # recently failed — don't hammer

        # Fetch outside the lock (a racing duplicate fetch is harmless).
        dests = self._fetch(origin)

        with self._lock:
            if dests is None:
                self._failures[origin] = now
                # Stale cache beats nothing:
                entry = self._cache.get(origin)
                if entry:
                    return set(entry.get("destinations", []))
                return None
            self._cache[origin] = {"destinations": sorted(dests), "fetched_at": now}
            self._failures.pop(origin, None)
            self._save()
        log_info(f"RouteGraph: {origin} serves {len(dests)} destinations (cached 7d)")
        return set(dests)

    def flies(self, origin: str, dest: str) -> Optional[bool]:
        """Three-valued: True / False (provably absent) / None (unknown)."""
        dests = self.destinations(origin)
        if dests is None:
            return None
        return dest.upper().strip() in dests


# ---------------------------------------------------------------------------
# Module-level singleton — providers share one graph (and one disk cache)
# ---------------------------------------------------------------------------

_GRAPH: Optional[RouteGraph] = None
_GRAPH_LOCK = threading.Lock()


def get_route_graph() -> RouteGraph:
    global _GRAPH
    if _GRAPH is None:
        with _GRAPH_LOCK:
            if _GRAPH is None:
                _GRAPH = RouteGraph()
    return _GRAPH
