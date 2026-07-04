"""
Smart multi-layer search engine - maximizes deal discovery by:

Layer 1 - CALENDAR PRE-SCAN
  Uses Ryanair's month-level fare data to identify the cheapest travel dates
  BEFORE exact-date searching. This avoids wasting time on expensive dates.

Layer 2 - ONE-WAY COMBINER
  Stores every one-way leg discovered. Builds round-trips from the cheapest
  outbound + cheapest return, even if they're from different airlines.
  This can be 30-50% cheaper than airline-enforced round-trips.

Layer 3 - PROVIDER CONSENSUS VOTING
  When 2+ providers agree on a price within EUR 20, confidence is HIGH.
  When only 1 provider has data, flag as "verify manually."

Layer 4 - FLEXIBLE DATE SCORING
  Allows +/- 1 day flexibility. If arriving a day earlier or leaving a day
  later drops the price by >20%, that deal is surfaced.

Layer 5 - SMART DESTINATION ORDERING
  Sorts destinations by historical cheapness so the best deals are found
  first, even if the search is interrupted.
"""

import time
import concurrent.futures
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict

from src.core.scoring import Flight, MeetupResult, score_meetup, rank_results
from src.core.storage import Storage
from src.core.config import Config
from src.core.logger import log_info, log_error


def calendar_pre_scan(
    storage: Storage,
    origins: List[str],
) -> Dict[str, float]:
    """Layer 1: Scan each origin's cheapest routes using stored one-way legs.

    Returns a dict of {destination_iata: cheapest_seen_price} used to
    prioritize destination ordering.
    """
    price_map: Dict[str, float] = {}
    three_months_ago = (datetime.now() - timedelta(days=90)).isoformat()

    try:
        with storage._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT destination, MIN(price)
                FROM flight_legs
                WHERE timestamp > ?
                  AND price > 0
                GROUP BY destination
            """, (three_months_ago,))
            for dest_iata, min_price in cursor.fetchall():
                price_map[dest_iata] = float(min_price)
    except Exception:
        pass

    if price_map:
        log_info(
            f"Calendar pre-scan: {len(price_map)} destinations "
            f"with cached prices (range EUR "
            f"{min(price_map.values()):.0f}-{max(price_map.values()):.0f})"
        )
    return price_map


def discovery_prescan(
    storage: Storage,
    origins: List[str],
    destination_iatas: List[str],
    date_from: str,
    date_to: str,
    max_calls: int = 100,
    max_workers: int = 8,
    time_budget_s: float = 60.0,
    should_stop=None,
    _client=None,
    _graph=None,
) -> int:
    """Layer 1 (live): calendar-first discovery pre-scan.

    Before a big scan, pull Ryanair's month-level `cheapestPerDay` surface for
    every (origin -> candidate) route that PROVABLY EXISTS (route graph), and
    save the resulting one-way legs into `flight_legs`. One HTTP call yields a
    whole month of fares, so ~N calls refresh the entire outbound price
    surface - after which Layer 5 (cheapest-first ordering) and Layer 2 (leg
    combiner) run on fresh data instead of possibly-stale history.

    Strictly best-effort and bounded:
      * only routes the route graph confirms (unknown graph -> origin skipped;
        a blind calendar call on a non-route is a wasted HTTP);
      * at most `max_calls` HTTP calls, `time_budget_s` seconds wall-clock;
      * free provider only (Ryanair) - a broad scan must never cost money;
      * any failure degrades to "no pre-scan", never to a broken search;
      * `should_stop()` (optional) is polled so a user Stop aborts promptly.

    Returns the number of legs saved.

    `_client` / `_graph` are injection points for offline tests.
    """
    def _stopped() -> bool:
        try:
            return bool(should_stop and should_stop())
        except Exception:
            return False

    if _stopped():
        return 0
    from src.clients.ryanair_client import RyanairClient
    from src.core.route_graph import get_route_graph

    graph = _graph if _graph is not None else get_route_graph()
    client = _client if _client is not None else RyanairClient(debug=False)

    # -- Build the confirmed-route worklist ---------------------------------
    routes: List[Tuple[str, str]] = []
    for origin in origins:
        served = None
        try:
            served = graph.destinations(origin)
        except Exception:
            served = None
        if not served:
            continue  # graph unknown for this origin - don't guess
        for dest in destination_iatas:
            if dest in served and dest != origin:
                routes.append((origin, dest))
    routes = routes[:max_calls]
    if not routes:
        return 0

    started = time.time()
    log_info(
        f"Discovery pre-scan: {len(routes)} confirmed routes, "
        f"window {date_from}..{date_to}"
    )

    # -- Fetch calendars in parallel; collect flights, save on this thread ---
    def _fetch(route: Tuple[str, str]) -> list:
        # A queued task becomes an instant no-op once time is up or the user
        # pressed Stop, so the pool drains fast instead of running every route.
        if _stopped() or (time.time() - started) > time_budget_s:
            return []
        origin, dest = route
        try:
            return client.cheapest_per_day(origin, dest, date_from, date_to)
        except Exception:
            return []

    saved = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        for flights in pool.map(_fetch, routes):
            if _stopped():
                break
            for leg in flights:
                try:
                    storage.save_flight_leg("Ryanair Calendar", leg)
                    saved += 1
                except Exception:
                    continue

    log_info(
        f"Discovery pre-scan: {saved} fresh legs saved "
        f"in {time.time() - started:.1f}s"
    )
    return saved


def build_round_trip_from_legs(
    storage: Storage,
    origins: List[str],
    destination: str,
    out_date: str,
    ret_date: str,
) -> Optional[Flight]:
    """Layer 2: Assemble the cheapest round-trip from any combination of
    stored one-way legs - possibly across different airlines.

    This can beat airline-enforced round-trips by 30-50% because you
    can fly Ryanair out and Wizz back, or any other combination.
    """
    best_out: Optional[Flight] = None
    best_ret: Optional[Flight] = None

    try:
        with storage._get_connection() as conn:
            cursor = conn.cursor()

            # Cheapest outbound from any origin to destination on out_date
            # v5: Require leg freshness - legs older than 48h for near-term
            # dates are stale and produce phantom deals. Mark as approximate.
            placeholders = ",".join("?" for _ in origins)
            cursor.execute(f"""
                SELECT origin, destination, depart_date, price, stops,
                       arrival_time, provider
                FROM flight_legs
                WHERE origin IN ({placeholders})
                  AND destination = ?
                  AND depart_date = ?
                  AND price > 0
                  AND timestamp > datetime('now', '-48 hours')
                ORDER BY price ASC
                LIMIT 1
            """, (*origins, destination, out_date))
            row = cursor.fetchone()
            if row:
                best_out = Flight(
                    origin=row[0], destination=row[1],
                    price=float(row[3]), outbound_date=row[2],
                    return_date="", stops=row[4] or 0,
                    arrival_time=row[5] or f"{out_date} 12:00",
                    source=f"leg:{row[6]}",
                )

            # Cheapest return on ret_date (v5: 48h freshness)
            cursor.execute(f"""
                SELECT origin, destination, depart_date, price, stops,
                       arrival_time, provider
                FROM flight_legs
                WHERE origin = ?
                  AND destination IN ({placeholders})
                  AND depart_date = ?
                  AND price > 0
                  AND timestamp > datetime('now', '-48 hours')
                ORDER BY price ASC
                LIMIT 1
            """, (destination, *origins, ret_date))
            row = cursor.fetchone()
            if row:
                best_ret = Flight(
                    origin=row[0], destination=row[1],
                    price=float(row[3]), outbound_date=row[2],
                    return_date="", stops=row[4] or 0,
                    arrival_time=row[5] or f"{ret_date} 12:00",
                    source=f"leg:{row[6]}",
                )
    except Exception as exc:
        log_error(f"Leg combiner error {destination}: {exc}")
        return None

    if not best_out or not best_ret:
        return None

    return Flight(
        origin=best_out.origin,
        destination=destination,
        price=best_out.price + best_ret.price,
        outbound_date=best_out.outbound_date,
        return_date=best_ret.return_date,
        stops=best_out.stops + best_ret.stops,
        arrival_time=best_out.arrival_time,
        source=f"{best_out.source}+{best_ret.source}",
        is_approximate=True,  # v5: leg-combined prices are advisory only
        airline=f"{getattr(best_out, 'airline', '')}+{getattr(best_ret, 'airline', '')}",
    )


def flexible_date_search(
    storage: Storage,
    member_origins: List[List[str]],
    destination_iata: str,
    out_date: str,
    ret_date: str,
    providers: List[Any],
    get_best_fn,
    min_nights: int = 2,
    max_nights: int = 4,
    participant_labels: Optional[List[str]] = None,
    luggage: str = "carryon_10kg",       # v6.1
    include_transfers: bool = True,       # v6.1
    max_stops: int = 2,                   # v6.1
) -> list:
    """Layer 4: Try the exact dates plus +/- 1 day shifts.

    v6: Supports N people (2-4). member_origins is a list of origin lists,
    one per participant. Uses score_group_meetup() for N-person scoring.

    v5.1: Filters variants to enforce min_nights ≤ stay ≤ max_nights.
    """
    from src.core.scoring import score_group_meetup

    results = []

    out_dt = datetime.strptime(out_date, "%Y-%m-%d")
    ret_dt = datetime.strptime(ret_date, "%Y-%m-%d")

    # Generate date variants: [exact, out-1, out+1, ret-1, ret+1]
    variants: List[Tuple[str, str]] = [(out_date, ret_date)]

    for offset in (-1, 1):
        v_out = (out_dt + timedelta(days=offset)).strftime("%Y-%m-%d")
        variants.append((v_out, ret_date))

    for offset in (-1, 1):
        v_ret = (ret_dt + timedelta(days=offset)).strftime("%Y-%m-%d")
        variants.append((out_date, v_ret))

    seen = set()
    for v_out, v_ret in variants:
        key = (v_out, v_ret)
        if key in seen:
            continue
        seen.add(key)

        # Enforce min/max nights
        v_out_dt = datetime.strptime(v_out, "%Y-%m-%d")
        v_ret_dt = datetime.strptime(v_ret, "%Y-%m-%d")
        nights = (v_ret_dt - v_out_dt).days
        if nights < min_nights or nights > max_nights:
            continue

        # Search flights for every participant
        all_flights = []
        for origins in member_origins:
            best = get_best_fn(storage, origins, destination_iata, v_out, v_ret, providers)
            if best:
                all_flights.append(best)

        # Must have flights for ALL participants
        if len(all_flights) == len(member_origins) and len(all_flights) >= 2:
            res = score_group_meetup(
                all_flights, participant_labels,
                nights=nights, storage=storage,
                luggage=luggage, include_transfers=include_transfers,
            )
            if res:
                results.append(res)

    return results


def provider_consensus(storage: Storage, origin: str, destination: str,
                       out_date: str, ret_date: str) -> Dict[str, Any]:
    """Layer 3: Check how many providers agree on this route-date-price.

    Returns:
        {
            "count": number of providers,
            "prices": [list of prices],
            "spread": max-min,
            "confidence": 0-100,
            "label": "HIGH" | "MEDIUM" | "LOW" | "SINGLE_SOURCE",
        }
    """
    stats = storage.get_quote_stats(origin, destination, out_date, ret_date)
    count = stats.get("provider_count", 0)
    spread = stats.get("spread")
    confidence = stats.get("confidence", 0)

    if count >= 2 and spread is not None and spread <= 20:
        label = "HIGH"
    elif count >= 2:
        label = "MEDIUM"
    elif count == 1:
        label = "SINGLE_SOURCE"
    else:
        label = "LOW"

    return {**stats, "label": label}


def sort_destinations_by_cheapness(
    destinations: List[Any],
    storage: Storage,
    origins: Optional[List[str]] = None,
) -> List[Any]:
    """Layer 5: Order destinations from historically cheapest to most
    expensive so the best deals are discovered first.

    Destinations with no historical data are placed in the middle
    (not at the end - they might be cheap, we just don't know yet).

    v6: origins parameter replaces hardcoded Config.ORIGINS_A + Config.ORIGINS_B.
    """
    if origins is None:
        from src.core.config import Config
        origins = Config.DEFAULT_ORIGINS_A + Config.DEFAULT_ORIGINS_B
    price_map = calendar_pre_scan(storage, origins)

    def _key(dest):
        iata = dest.iata if hasattr(dest, "iata") else dest
        price = price_map.get(iata, None)
        if price is None:
            return (1, 0)  # Unknown - middle priority
        return (0, price)  # Known - cheaper first

    return sorted(destinations, key=_key)
