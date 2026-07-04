"""
Unified Scraper Engine — orchestrates all direct airline scrapers in
parallel, aggregates results, and provides a single entry point for
one-way, round-trip, and matrix searches.

This engine is designed to work ALONGSIDE the existing provider waterfall
in main.py, not replace it.  It adds coverage for airlines that don't
appear on meta-search or GDS aggregators.
"""

import concurrent.futures
from typing import Dict, List, Optional

from src.core.scoring import Flight
from src.core.logger import log_info, log_error
from src.scrapers.base import BaseScraper
from src.scrapers.multi_google import MultiModeGoogleScraper


class ScraperEngine:
    """Runs all registered scrapers in parallel and merges results.

    Usage::

        engine = ScraperEngine()
        engine.add(MultiModeGoogleScraper(debug=True))

        # One-way
        legs = engine.search_one_way("RIX", "BCN", "2026-07-25")

        # Round-trip
        rt = engine.search_round_trip("BGY", "BCN", "2026-07-25", "2026-07-28")

        # Check which scrapers are healthy
        health = engine.health_check()
    """

    def __init__(self, max_workers: int = 6):
        self._scrapers: List[BaseScraper] = []
        self._max_workers = max_workers

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def add(self, scraper: BaseScraper):
        """Register a scraper instance."""
        self._scrapers.append(scraper)

    def add_defaults(self, debug: bool = False):
        """Register built-in scraper with default settings."""
        self.add(MultiModeGoogleScraper(debug=debug, cache_ttl=3600))

    @property
    def scrapers(self) -> List[BaseScraper]:
        return list(self._scrapers)

    @property
    def healthy_scrapers(self) -> List[BaseScraper]:
        return [s for s in self._scrapers if s.is_healthy()]

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_one_way(
        self, origin: str, destination: str, date: str, timeout: int = 25,
    ) -> List[Flight]:
        """Query every healthy scraper in parallel for a one-way leg."""
        all_flights: List[Flight] = []
        errors: Dict[str, str] = {}

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self._max_workers
        ) as pool:
            future_to_scraper = {
                pool.submit(s.search_one_way, origin, destination, date): s
                for s in self.healthy_scrapers
            }
            done, _pending = concurrent.futures.wait(
                future_to_scraper, timeout=timeout,
            )
            for future in done:
                scraper = future_to_scraper[future]
                try:
                    result = future.result()
                    if result:
                        all_flights.extend(result)
                except Exception as exc:
                    errors[scraper.name()] = str(exc)

        if errors:
            log_error(f"ScraperEngine one-way errors: {errors}")

        # Sort by price, deduplicate
        return self._deduplicate(all_flights)

    def search_round_trip(
        self, origin: str, destination: str,
        out_date: str, ret_date: str, timeout: int = 30,
    ) -> Optional[Flight]:
        """Query every healthy scraper for a round-trip.

        Returns the cheapest combined round-trip OR the best one-way
        results assembled into a round-trip.
        """
        best: Optional[Flight] = None

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self._max_workers
        ) as pool:
            futures = {
                pool.submit(
                    s.search_round_trip, origin, destination, out_date, ret_date
                ): s
                for s in self.healthy_scrapers
            }
            done, _pending = concurrent.futures.wait(futures, timeout=timeout)
            for future in done:
                try:
                    result = future.result()
                    if result and result.price > 0:
                        if not best or result.price < best.price:
                            best = result
                except Exception:
                    continue

        # Fallback: build round-trip from one-way legs
        if not best:
            out_legs = self.search_one_way(origin, destination, out_date, timeout // 2)
            ret_legs = self.search_one_way(destination, origin, ret_date, timeout // 2)
            if out_legs and ret_legs:
                best_out = min(out_legs, key=lambda f: f.price)
                best_ret = min(ret_legs, key=lambda f: f.price)
                best = Flight(
                    origin=origin,
                    destination=destination,
                    price=best_out.price + best_ret.price,
                    outbound_date=out_date,
                    return_date=ret_date,
                    stops=best_out.stops + best_ret.stops,
                    arrival_time=best_out.arrival_time,
                    source=f"{best_out.source}+{best_ret.source}",
                )

        return best

    def matrix(
        self, origin: str, destination: str,
        out_date: str, ret_date: str, timeout: int = 35,
    ) -> Dict:
        """Query all scrapers and return a price matrix (best per scraper)."""
        quotes: List[Flight] = []
        errors: Dict[str, str] = {}

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self._max_workers
        ) as pool:
            future_to_scraper = {
                pool.submit(
                    s.search_round_trip, origin, destination, out_date, ret_date,
                ): s
                for s in self.healthy_scrapers
            }
            done, _pending = concurrent.futures.wait(
                future_to_scraper, timeout=timeout,
            )
            for future in done:
                scraper = future_to_scraper[future]
                try:
                    result = future.result()
                    if result and result.price > 0:
                        quotes.append(result)
                except Exception as exc:
                    errors[scraper.name()] = str(exc)

        quotes.sort(key=lambda f: f.price)
        prices = [f.price for f in quotes]
        return {
            "best": quotes[0] if quotes else None,
            "quotes": quotes,
            "provider_count": len(quotes),
            "cheapest": min(prices) if prices else None,
            "spread": round(max(prices) - min(prices), 2) if len(prices) > 1 else None,
            "errors": errors,
        }

    def health_check(self) -> Dict:
        """Return health status for every registered scraper."""
        result = {}
        for s in self._scrapers:
            try:
                ok = s.is_healthy()
            except Exception as exc:
                ok = False
                result[s.name()] = {"ok": False, "reason": str(exc)}
                continue
            result[s.name()] = {"ok": ok, "reason": "OK" if ok else "unreachable"}
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _deduplicate(flights: List[Flight]) -> List[Flight]:
        seen = set()
        unique: List[Flight] = []
        for f in sorted(flights, key=lambda x: x.price):
            key = (f.price, f.stops, f.source)
            if key not in seen:
                seen.add(key)
                unique.append(f)
        return unique


# ------------------------------------------------------------------
# Module-level convenience — engine that mirrors the CLI/API lifecycle
# ------------------------------------------------------------------

_shared_engine: Optional[ScraperEngine] = None


def get_engine(debug: bool = False) -> ScraperEngine:
    """Return a shared ScraperEngine singleton for the process."""
    global _shared_engine
    if _shared_engine is None:
        _shared_engine = ScraperEngine()
        _shared_engine.add_defaults(debug=debug)
    return _shared_engine
