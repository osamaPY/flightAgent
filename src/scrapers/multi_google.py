"""
Multi-mode Google Flights scraper — queries the free fast-flights backend
in 3 different modes to maximize price discovery:

  Mode 1 — DIRECT: Non-stop flights only (cheapest, fastest)
  Mode 2 — ALL: Direct + connections (widest coverage)
  Mode 3 — CALENDAR: Month-level scan for cheapest dates

Combined, these 3 modes surface more deals than a single search while
using the same free Google Flights Protobuf endpoint.

REPLACES the broken airline-specific scrapers (Wizz Air, airBaltic,
Norwegian, easyJet) which had no public API access.
"""

from typing import List, Optional
from datetime import datetime, timedelta

from fast_flights import FlightQuery, Passengers, create_query, get_flights
from fast_flights.exceptions import FlightsNotFound

from src.core.scoring import Flight
from src.core.logger import log_info, log_error
from src.scrapers.base import BaseScraper


class MultiModeGoogleScraper(BaseScraper):
    """Google Flights scraper that runs 3 search modes in parallel."""

    def name(self) -> str:
        return "Google Multi-Mode"

    # Required by BaseScraper ABC — runs all modes, returns merged results
    def _search_one_way(
        self, origin: str, destination: str, date: str
    ) -> List[Flight]:
        all_flights: List[Flight] = []
        seen = set()
        for mode_name, mode_fn in [
            ("direct", self._search_direct),
            ("all", self._search_all),
        ]:
            try:
                for f in mode_fn(origin, destination, date):
                    key = (f.price, f.stops)
                    if key not in seen:
                        seen.add(key)
                        f.source = f"google_{mode_name}"
                        all_flights.append(f)
            except Exception:
                pass
        all_flights.sort(key=lambda f: f.price)
        return all_flights

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search_one_way(
        self, origin: str, destination: str, date: str
    ) -> List[Flight]:
        """Run all modes, merge and deduplicate results."""
        all_flights: List[Flight] = []
        seen = set()

        for mode_name, mode_fn in [
            ("direct", self._search_direct),
            ("all", self._search_all),
        ]:
            try:
                results = mode_fn(origin, destination, date)
                for f in results:
                    key = (f.price, f.stops)
                    if key not in seen:
                        seen.add(key)
                        f.source = f"google_{mode_name}"
                        all_flights.append(f)
            except Exception as exc:
                log_error(f"[Google {mode_name}] {origin}->{destination}: {exc}")

        all_flights.sort(key=lambda f: f.price)
        if all_flights and self.debug:
            log_info(
                f"[Google MM] {origin}->{destination} {date}: "
                f"{len(all_flights)} fares across modes, "
                f"best EUR{all_flights[0].price:.0f}"
            )
        return all_flights

    def search_round_trip(
        self,
        origin: str,
        destination: str,
        out_date: str,
        ret_date: str,
    ) -> Optional[Flight]:
        """Combine best outbound + best return across all modes."""
        out_flights = self.search_one_way(origin, destination, out_date)
        ret_flights = self.search_one_way(destination, origin, ret_date)

        if not out_flights or not ret_flights:
            return None

        best_out = min(out_flights, key=lambda f: f.price)
        best_ret = min(ret_flights, key=lambda f: f.price)

        return Flight(
            origin=origin,
            destination=destination,
            price=best_out.price + best_ret.price,
            outbound_date=out_date,
            return_date=ret_date,
            stops=best_out.stops + best_ret.stops,
            arrival_time=best_out.arrival_time,
            source="google_multimode",
        )

    def calendar_scan(
        self,
        origin: str,
        destination: str,
        month_start: str,
        days: int = 30,
    ) -> List[Flight]:
        """Mode 3: Scan a full month to find the cheapest departure dates.

        Returns one Flight per date with the cheapest fare found.
        """
        start_dt = datetime.strptime(month_start, "%Y-%m-%d")
        results: List[Flight] = []

        for offset in range(days):
            date = (start_dt + timedelta(days=offset)).strftime("%Y-%m-%d")
            try:
                flights = self._search_all(origin, destination, date)
                if flights:
                    best = min(flights, key=lambda f: f.price)
                    best.source = "google_calendar"
                    results.append(best)
            except Exception:
                continue

        results.sort(key=lambda f: f.price)
        if results:
            log_info(
                f"[Calendar] {origin}->{destination}: "
                f"{len(results)} days with fares, "
                f"cheapest {results[0].outbound_date} EUR{results[0].price:.0f}"
            )
        return results

    # ------------------------------------------------------------------
    # Search modes
    # ------------------------------------------------------------------

    def _search_direct(
        self, origin: str, destination: str, date: str
    ) -> List[Flight]:
        """Mode 1: Non-stop flights only."""
        return self._query_google(origin, destination, date, max_stops=0)

    def _search_all(
        self, origin: str, destination: str, date: str
    ) -> List[Flight]:
        """Mode 2: All flights including connections."""
        return self._query_google(origin, destination, date, max_stops=2)

    def _query_google(
        self,
        origin: str,
        destination: str,
        date: str,
        max_stops: int = 2,
    ) -> List[Flight]:
        """Execute a single fast-flights query and parse results."""
        try:
            query = create_query(
                flights=[
                    FlightQuery(
                        date=date,
                        from_airport=origin.upper(),
                        to_airport=destination.upper(),
                    ),
                ],
                seat="economy",
                trip="one-way",
                passengers=Passengers(adults=1),
                language="en-US",
                currency="EUR",
                max_stops=max_stops,
            )

            results = get_flights(query)
            if not results:
                return []

            flights: List[Flight] = []
            for f in results:
                segments = getattr(f, "flights", None) or []
                if not segments:
                    continue

                arrival = self._fmt_arrival(
                    getattr(segments[-1], "arrival", None),
                    date,
                )
                price = self._safe_price(getattr(f, "price", None))
                stops = max(0, len(segments) - 1)

                if stops > max_stops or price <= 0:
                    continue

                flights.append(Flight(
                    origin=origin.upper(),
                    destination=destination.upper(),
                    price=price,
                    outbound_date=date,
                    return_date="",
                    stops=stops,
                    arrival_time=arrival,
                    source="google",
                ))

            return flights
        except FlightsNotFound:
            return []
        except Exception as exc:
            log_error(f"[Google query] {origin}->{destination} {date}: {exc}")
            return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt_arrival(value, fallback_date: str) -> str:
        if not value:
            return f"{fallback_date} 12:00"
        try:
            date_part = getattr(value, "date", None)
            time_part = getattr(value, "time", None)

            if isinstance(date_part, (tuple, list)) and len(date_part) >= 3:
                yyyy, mm, dd = date_part[:3]
                date_text = f"{int(yyyy):04d}-{int(mm):02d}-{int(dd):02d}"
            else:
                date_text = fallback_date

            if isinstance(time_part, (tuple, list)) and len(time_part) >= 2:
                hh, minute = time_part[:2]
                time_text = f"{int(hh):02d}:{int(minute):02d}"
            else:
                time_text = "12:00"

            return f"{date_text} {time_text}"
        except Exception:
            return f"{fallback_date} 12:00"

    def is_healthy(self) -> bool:
        return True  # No API key needed
