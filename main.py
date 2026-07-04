import argparse
import sys
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Any, Dict, Tuple

# Polyfill imghdr for Python 3.13+ (required by undetected-chromedriver)
import src.utils.compat  # noqa: F401

# Global cancellation flag for long-running searches
SEARCH_STOP_EVENT = threading.Event()

from src.core.config import Config, DATE_WINDOWS
from src.core.airports import get_destinations, expand_nearby_airports
from src.core.scoring import score_meetup, rank_results, MeetupResult, Flight
from src.core.storage import Storage
from src.core.notifier import Notifier
from src.core.logger import log_info, log_error
from src.core.provider_factory import build_providers
from src.core.providers import FlightProvider
from src.core.smart_search import (
    calendar_pre_scan,
    build_round_trip_from_legs,
    flexible_date_search,
    provider_consensus,
    sort_destinations_by_cheapness,
)

import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

# ---------------------------------------------------------------------------
# v5: Shared thread pool — one pool for the entire scan, not 2,700 of them.
# ---------------------------------------------------------------------------
_SHARED_POOL: ThreadPoolExecutor | None = None
_SHARED_POOL_SIZE = 16

def _get_shared_pool() -> ThreadPoolExecutor:
    global _SHARED_POOL
    if _SHARED_POOL is None:
        _SHARED_POOL = ThreadPoolExecutor(max_workers=_SHARED_POOL_SIZE)
    return _SHARED_POOL

def _cleanup_shared_pool():
    global _SHARED_POOL
    if _SHARED_POOL:
        _SHARED_POOL.shutdown(wait=False, cancel_futures=True)
        _SHARED_POOL = None

# Per-provider timeout (seconds) — no provider can block longer than this.
PROVIDER_TIMEOUT = 12


@dataclass
class SearchRunSummary:
    mode: str
    stopped: bool = False
    results: List[MeetupResult] = field(default_factory=list)
    new_top3: List[Any] = field(default_factory=list)


def _top_key(row: Any) -> tuple:
    return (row[0], row[2], row[3])


def _top_score(row: Any) -> float:
    return float(row[1] or 0) + float(row[9] or 0)


def _find_new_top3(previous_top: List[Any], current_top: List[Any]) -> List[Any]:
    previous = {_top_key(row): _top_score(row) for row in previous_top}
    new_entries = []
    for row in current_top[:3]:
        key = _top_key(row)
        if key not in previous or _top_score(row) < previous[key]:
            new_entries.append(row)
    return new_entries

def exact_date_pairs(window) -> List[tuple]:
    """Generate (out_date, ret_date) pairs within a DateWindow.

    v5: Skip dates before today — protects against midnight rollover
    during long scans querying yesterday's flights.
    """
    pairs = []
    today = datetime.now().strftime("%Y-%m-%d")
    start = datetime.strptime(window.depart_earliest, "%Y-%m-%d")
    end = datetime.strptime(window.depart_latest, "%Y-%m-%d")
    current = start
    while current <= end:
        out_str = current.strftime("%Y-%m-%d")
        if out_str >= today:  # v5: skip past dates
            for nights in range(window.min_nights, window.max_nights + 1):
                ret = current + timedelta(days=nights)
                pairs.append((out_str, ret.strftime("%Y-%m-%d")))
        current += timedelta(days=1)
    return pairs

def get_best_flight(
    storage: Storage,
    origins: List[str],
    destination: str,
    out_date: str,
    ret_date: str,
    providers: List[FlightProvider],
) -> Optional[Flight]:
    """Query ALL healthy providers in parallel. Collect every result. Return the CHEAPEST.

    This replaces the old greedy 3-tier waterfall. The old approach took the first
    provider that responded — even if a slower provider had a 50% cheaper fare.

    Now we:
      1. Fire every healthy provider simultaneously (one ThreadPoolExecutor)
      2. Each future has a hard PROVIDER_TIMEOUT cap
      3. Collect ALL successful results
      4. Return the one with the lowest price
      5. Save every quote to the provider matrix (for consensus/voting)

    This guarantees we find the best deal among our provider set, not the fastest.
    """
    if not providers:
        return None

    best: Optional[Flight] = None
    all_results: List[Flight] = []

    def _query_one(p: FlightProvider, origin: str) -> Optional[Flight]:
        if SEARCH_STOP_EVENT.is_set():
            return None

        # SQLite cache first
        cached = storage.get_cached_flight(
            p.name(), origin, destination, out_date, ret_date,
        )
        if cached:
            log_info(f"CACHE [{p.name()}] {origin}->{destination} EUR{cached.price:.0f}")
            storage.save_provider_quote(p.name(), cached)
            return cached

        try:
            # Metered (paid) providers gate themselves on budget — skip when spent.
            # (Was a hardcoded `if p.name() == "Duffel"` check; now capability-driven.)
            if not p.pre_call_ok():
                log_info(f"[{p.name()}] SKIP — budget exhausted")
                return None

            # Providers that expose one-way legs feed the leg combiner (Layer 2).
            if p.capabilities.has_one_way:
                for leg in p.search_one_way(origin, destination, out_date):
                    storage.save_flight_leg(p.name(), leg)
                for leg in p.search_one_way(destination, origin, ret_date):
                    storage.save_flight_leg(p.name(), leg)

            res = p.search_round_trip(
                origin, destination,
                out_date, out_date,
                ret_date, ret_date,
            )

            # Record a billable call for budget tracking (no-op for free providers).
            if res:
                p.record_call()

            if res and (res.outbound_date != out_date or res.return_date != ret_date):
                log_info(
                    f"[{p.name()}] date mismatch {origin}->{destination}: "
                    f"{res.outbound_date}/{res.return_date} (wanted {out_date}/{ret_date})"
                )
                return None

            if res and res.price > 0:
                storage.set_cached_flight(p.name(), res)
                storage.save_provider_quote(p.name(), res)
                storage.save_flight_leg(p.name(), Flight(
                    origin=res.origin,
                    destination=res.destination,
                    price=res.price,
                    outbound_date=res.outbound_date,
                    return_date="",
                    stops=res.stops,
                    arrival_time=res.arrival_time,
                    source=res.source,
                ))

            return res
        except Exception as exc:
            log_error(f"[{p.name()}] {origin}->{destination}: {exc}")
            return None

    # --- Fire all providers in the SHARED pool (v5: reuse, don't create) ---
    pool = _get_shared_pool()
    future_map: Dict[concurrent.futures.Future, Tuple[FlightProvider, str]] = {}
    for origin in origins:
        if origin == destination:
            continue
        for p in providers:
            future_map[pool.submit(_query_one, p, origin)] = (p, origin)

        for future in concurrent.futures.as_completed(future_map):
            if SEARCH_STOP_EVENT.is_set():
                break
            provider, origin = future_map[future]
            try:
                fare = future.result(timeout=PROVIDER_TIMEOUT)
            except FutureTimeout:
                log_error(f"[{provider.name()}] TIMEOUT {origin}->{destination}")
                continue
            except Exception as exc:
                log_error(f"[{provider.name()}] {origin}->{destination}: {exc}")
                continue

            if fare and fare.price > 0:
                all_results.append(fare)
                if not best or fare.price < best.price:
                    best = fare

    if all_results:
        prices = [f.price for f in all_results]
        log_info(
            f"{destination}: {len(all_results)} quotes from "
            f"{len(set(f.source for f in all_results))} providers, "
            f"best EUR{min(prices):.0f} (range EUR{min(prices):.0f}-EUR{max(prices):.0f})"
        )

    return best

def monitor_mode(storage: Storage, notifier: Notifier, providers: List[FlightProvider], progress_callback=None) -> SearchRunSummary:
    """Monitoring loop."""
    SEARCH_STOP_EVENT.clear()
    log_info("--- MONITOR MODE ---")
    
    all_results = []
    previous_top3 = storage.get_all_time_top(3)
    valid_destinations = get_destinations(exclude_iatas=[])

    def process_window(dest_iata, window, skip_slow):
        if SEARCH_STOP_EVENT.is_set():
            return None

        out_from = window.depart_earliest
        out_to = window.depart_latest
        in_from = (datetime.strptime(out_from, "%Y-%m-%d") + timedelta(days=window.min_nights)).strftime("%Y-%m-%d")
        in_to = (datetime.strptime(out_from, "%Y-%m-%d") + timedelta(days=window.max_nights)).strftime("%Y-%m-%d")

        best_a = get_best_flight(storage, Config.ORIGINS_A, dest_iata, out_from, in_from, providers)
        best_b = get_best_flight(storage, Config.ORIGINS_B, dest_iata, out_from, in_from, providers)

        if best_a and best_b:
            return score_meetup(best_a, best_b)
        return None

    # Boosted parallel workers for local PC
    total_steps = len(valid_destinations)
    
    # Increase workers to 50 for much faster local scanning
    with ThreadPoolExecutor(max_workers=50) as executor:
        for i, dest in enumerate(valid_destinations):
            if SEARCH_STOP_EVENT.is_set(): break
            if progress_callback: progress_callback(i + 1, total_steps, dest.city)
            
            # Focused windows only
            futures = [executor.submit(process_window, dest.iata, window, False) for window in DATE_WINDOWS]
            for future in concurrent.futures.as_completed(futures):
                try:
                    res = future.result()
                    if res:
                        storage.save_result(res)
                        all_results.append(res)
                        log_info(f"  MATCH: {dest.city} €{res.total_price:.2f}")
                except Exception as e:
                    log_error(f"Worker Error: {e}")

    if all_results:
        ranked = rank_results(all_results)
        print_results_table(ranked, "Today's Best Meetup Deals")
    
    stopped = SEARCH_STOP_EVENT.is_set()
    current_top3 = storage.get_all_time_top(3)
    summary = SearchRunSummary(
        mode="Search",
        stopped=stopped,
        results=rank_results(all_results) if all_results else [],
        new_top3=_find_new_top3(previous_top3, current_top3),
    )
    log_info("Scan Stopped." if stopped else "Scan Finished.")
    return summary

def verify_mode(storage: Storage, notifier: Notifier, providers: List[FlightProvider]) -> None:
    """Re-verifies."""
    log_info("\n--- VERIFY MODE ---")
    
    with storage._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT destination, a_origin, b_origin, outbound_date, return_date
            FROM results 
            WHERE timestamp > datetime('now', '-24 hours')
            ORDER BY (total_price + fairness_penalty) ASC
            LIMIT 5
        """)
        rows = cursor.fetchall()

    if not rows:
        log_info("No results to verify.")
        return

    log_info(f"Verifying {len(rows)} candidates...")
    
    for dest_iata, a_origin, b_origin, out_date, ret_date in rows:
        log_info(f"Checking {dest_iata} ({out_date})...")
        
        best_a = get_best_flight(storage, [a_origin], dest_iata, out_date, ret_date, providers)
        best_b = get_best_flight(storage, [b_origin], dest_iata, out_date, ret_date, providers)

        if best_a and best_b:
            res = score_meetup(best_a, best_b)
            if res:
                storage.save_results([res])
                log_info(f"Verified: €{res.total_price:.2f}")
                notifier.send_message(f"Verified Found!\n{notifier.format_alert(res)}")
        else:
            log_error(f"Failed for {dest_iata}")

def print_results_table(results: list, title: str, limit: int = 20) -> None:
    """v6: Render results table — handles both 2-person and N-person results."""
    print(f"\n{'='*60}")
    print(f" [ TOP {title.upper()} ] ")
    print(f"{'='*60}")

    from src.core.airports import CANDIDATE_DESTINATIONS
    iata_to_city = {a.iata: a.city for a in CANDIDATE_DESTINATIONS}
    seen = set()
    count = 0
    for res in results:
        city = res.dest_city or iata_to_city.get(res.destination, res.destination)
        if city in seen:
            continue
        seen.add(city)

        count += 1
        fairness = getattr(res, 'fairness_penalty', 0) or 0
        fairness_label = "Balanced" if fairness < 15 else "Fair" if fairness < 30 else "Lopsided"
        flag = getattr(res, 'dest_flag', '📍')
        nights_val = getattr(res, 'nights', 0)
        dest_display = f"{flag} {res.dest_city} ({res.destination})"
        nights_str = f"🌙 {nights_val} night{'s' if nights_val != 1 else ''}"

        grand = getattr(res, 'grand_total', 0) or res.total_price
        bag = getattr(res, 'bag_cost', 0) or 0
        xfer = getattr(res, 'transfer_cost', 0) or 0

        print(f"\n[RANK #{count}] {dest_display}")
        print(f"💰 Flights EUR {res.total_price:.0f}  |  💎 All-in EUR {grand:.0f}  |  {nights_str}")
        print(f"📅 {res.outbound_date} → {res.return_date}")
        print(f"⚖️ {fairness_label}")

        # v6: Render per-person lines (works for both legacy and N-person)
        if hasattr(res, 'participants') and res.participants:
            for p in res.participants:
                print(f"  {p.label}: {p.origin} ↔ {res.destination}  EUR {p.price:.0f}  "
                      f"({p.stops} stop{'s' if p.stops != 1 else ''})  {p.airline}")
        else:
            print(f"  🅰️: {res.a_origin} ↔ {res.destination}  EUR {res.a_price:.0f}  ({res.a_stops} stops)")
            print(f"  🅱️: {res.b_origin} ↔ {res.destination}  EUR {res.b_price:.0f}  ({res.b_stops} stops)")

        if bag > 0:
            print(f"🧳 10kg bags: EUR {bag:.0f}")
        if xfer > 0:
            print(f"🚆 Transfers: EUR {xfer:.0f}")

        conf = getattr(res, 'confidence_label', '')
        if conf:
            print(f"🎯 Confidence: {conf}")
        print(f"Source: {res.source} | Gap: {res.arrival_gap_hours}h")
        print(f"{'-'*60}")

        if count >= limit:
            break

    if count == 0:
        print("No results found.")
    print(f"{'='*60}\n")

def inspect_db(storage: Storage) -> None:
    """Prints database statistics and top results."""
    stats = storage.get_stats()
    print("\n" + "="*60)
    print(" [ DATABASE INSPECTION ] ")
    print("="*60)
    print(f"Total results: {stats['total_results']}")
    print(f"Last scan:     {stats['last_scan']}")
    print(f"Providers:     {', '.join(stats['providers'])}")
    
    from src.core.airports import CANDIDATE_DESTINATIONS
    
    def row_to_res(row):
        dest_iata, total, out, ret, a_p, b_p, src, fair, a_s, b_s, gap = row
        dest_info = next((a for a in CANDIDATE_DESTINATIONS if a.iata == dest_iata), None)
        try:
            n = (datetime.strptime(ret, "%Y-%m-%d") - datetime.strptime(out, "%Y-%m-%d")).days
        except Exception:
            n = 2
        return MeetupResult(
            destination=dest_iata,
            total_price=total,
            outbound_date=out,
            return_date=ret,
            a_price=a_p,
            b_price=b_p,
            source=src,
            fairness_penalty=fair,
            a_stops=a_s,
            b_stops=b_s,
            arrival_gap_hours=gap,
            a_origin="Me",
            b_origin="Her",
            dest_city=dest_info.city if dest_info else "Unknown",
            dest_flag=dest_info.flag if dest_info else "📍",
            is_approximate=False,
            nights=n,
        )

    print("\n--- [ TOP 10 OVERALL ] ---")
    overall_res = [row_to_res(r) for r in stats['top_20_overall'][:10]]
    print_results_table(overall_res, "Overall Leaderboard", limit=10)

    print("\n--- [ TOP 10 HOLIDAY (JUL-AUG) ] ---")
    if not stats['top_20_july']:
        print("No results found for these dates yet.")
    else:
        july_res = [row_to_res(r) for r in stats['top_20_july'][:10]]
        print_results_table(july_res, "Holiday Leaderboard", limit=10)
    print("="*60)

def booking_mode(
    storage: Storage,
    notifier: Notifier,
    providers: List[FlightProvider],
    progress_callback=None,
    search_request=None,  # v6: SearchRequest from src.core.search_request
) -> SearchRunSummary:
    """v6: Parameterized meetup search — any group size (2-4), any origins, any dates.

    When search_request is None, falls back to the legacy Milan+Riga summer holiday
    search for backward compatibility.
    """
    from src.core.search_request import SearchRequest, ParticipantGroup
    from src.core.scoring import score_group_meetup

    # ── Resolve search request ──
    if search_request is None:
        search_request = SearchRequest.default_two_person()

    req = search_request
    has_search_record = storage.get_search(req.id) is not None
    member_origins = [p.origins for p in req.participants]
    labels = [p.label for p in req.participants]
    all_home_iatas = set(req.all_origins)

    mode_label = f"{req.people_count}-person search: {req.depart_earliest} → {req.depart_latest} ({req.min_nights}-{req.max_nights} nights)"
    log_info(f"\n--- {mode_label} ---")
    log_info(f"Participants: {', '.join(f'{p.label} ({p.origins})' for p in req.participants)}")

    previous_top3 = storage.get_all_time_top(3)

    # ── Generate date windows from search request ──
    date_windows_raw = req.date_windows()
    date_windows = []
    for dw in date_windows_raw:
        from src.core.config import DateWindow
        date_windows.append(DateWindow(
            depart_earliest=dw["depart_earliest"],
            depart_latest=dw["depart_latest"],
            min_nights=dw.get("min_nights", req.min_nights),
            max_nights=dw.get("max_nights", req.max_nights),
        ))
    log_info(f"Date windows: {len(date_windows)} chunks, {req.min_nights}-{req.max_nights} nights")

    # ── SMART LAYER 5: Cheapest-first destination ordering ──
    exclude_set = list(all_home_iatas)
    all_destinations = get_destinations(
        exclude_iatas=exclude_set,
        universe=req.destination_universe,
    )

    # ── Calendar-first discovery pre-scan (free, bounded, best-effort) ──
    # Refreshes the flight_legs price surface from Ryanair's month-level
    # calendar for confirmed routes, so the cheapest-first ordering below
    # runs on fresh data instead of possibly-stale history.
    try:
        from src.core.smart_search import discovery_prescan
        discovery_prescan(
            storage, req.all_origins,
            [d.iata for d in all_destinations],
            req.depart_earliest, req.depart_latest,
        )
    except Exception as exc:
        log_error(f"Discovery pre-scan skipped: {exc}")

    all_destinations = sort_destinations_by_cheapness(
        all_destinations, storage, origins=req.all_origins,
    )
    log_info(
        f"Layer 5 - Smart ordering: {len(all_destinations)} destinations "
        f"sorted cheapest-first"
    )

    # ── API Protection ──
    MAX_API_CALLS = Config.MAX_API_CALLS_PER_RUN
    current_calls = 0

    # ── Country round-robin spread ──
    by_country = {}
    for d in all_destinations:
        if d.country not in by_country:
            by_country[d.country] = []
        by_country[d.country].append(d)

    spread_list = []
    max_per_country = 3
    for i in range(max_per_country):
        for country in sorted(by_country.keys()):
            if i < len(by_country[country]):
                spread_list.append(by_country[country][i])

    log_info(f"Targeting {len(spread_list)} destinations across {len(by_country)} countries")

    # ── Expand to nearby airports (with dynamic exclusions) ──
    all_results = []
    expanded_targets = []
    seen_targets = set()
    for city_dest in spread_list:
        for airport in expand_nearby_airports(city_dest, exclude_iatas=all_home_iatas):
            if airport.iata in seen_targets:
                continue
            seen_targets.add(airport.iata)
            expanded_targets.append((city_dest, airport))

    exact_pairs_by_window = [(window, exact_date_pairs(window)) for window in date_windows]
    total_steps = sum(len(pairs) for _, pairs in exact_pairs_by_window) * len(expanded_targets)
    step = 0

    for window, date_pairs in exact_pairs_by_window:
        log_info(f"Scanning window {window.depart_earliest} to {window.depart_latest}...")
        for out_from, in_from in date_pairs:
            for city_dest, dest in expanded_targets:
                if SEARCH_STOP_EVENT.is_set():
                    break
                step += 1
                if progress_callback:
                    progress_callback(step, total_steps, f"{city_dest.city} {out_from}")
                if current_calls >= MAX_API_CALLS:
                    break

                # ── SMART LAYER 4: Flexible date search (N people) ──
                active = [p for p in providers if p.is_healthy()]
                meetup_candidates = flexible_date_search(
                    storage,
                    member_origins,
                    dest.iata, out_from, in_from,
                    active, get_best_flight,
                    min_nights=window.min_nights,
                    max_nights=window.max_nights,
                    participant_labels=labels,
                    luggage=req.luggage,
                    include_transfers=req.include_transfers,
                    max_stops=req.effective_max_stops,
                )
                current_calls += req.people_count * len(active)

                for res in meetup_candidates:
                    res.dest_city = city_dest.city
                    res.dest_country = city_dest.country

                    # ── SMART LAYER 3: Provider consensus (per participant) ──
                    conf_labels = []
                    for p in res.participants:
                        consensus = provider_consensus(
                            storage, p.origin, dest.iata,
                            res.outbound_date, res.return_date,
                        )
                        conf_labels.append(consensus['label'])

                    # Use worst confidence as overall
                    if "LOW" in conf_labels or "" in conf_labels:
                        res.confidence_label = "LOW"
                    elif "SINGLE" in conf_labels:
                        res.confidence_label = "SINGLE_SOURCE"
                    elif "MEDIUM" in conf_labels:
                        res.confidence_label = "MEDIUM"
                    else:
                        res.confidence_label = "HIGH"

                    res.source = " + ".join(
                        f"{p.origin}:{cl}" for p, cl in zip(res.participants, conf_labels)
                    )

                    if has_search_record:
                        storage.save_group_result(req.id, res)
                        storage.update_search_result_count(req.id)
                    else:
                        storage.save_result(res)
                    all_results.append(res)
                    log_info(
                        f"  MATCH: {city_dest.city} EUR {res.grand_total:.0f} all-in "
                        f"({res.total_price:.0f} flights) on {res.outbound_date} "
                        f"[{res.confidence_label}]"
                    )

                # ── SMART LAYER 2: Leg-based round-trip combiner (N people) ──
                if not meetup_candidates:
                    leg_flights = []
                    for origins in member_origins:
                        leg = build_round_trip_from_legs(
                            storage, origins, dest.iata, out_from, in_from,
                        )
                        if leg:
                            leg_flights.append(leg)
                    if len(leg_flights) == req.people_count and len(leg_flights) >= 2:
                        res = score_group_meetup(
                            leg_flights, labels, storage=storage,
                            luggage=req.luggage,
                            include_transfers=req.include_transfers,
                        )
                        if res:
                            res.dest_city = city_dest.city
                            res.dest_country = city_dest.country
                            res.source = f"LEG_COMBO:{res.source}"
                            res.confidence_label = "LOW"
                            if has_search_record:
                                storage.save_group_result(req.id, res)
                                storage.update_search_result_count(req.id)
                            else:
                                storage.save_result(res)
                            all_results.append(res)
                            log_info(
                                f"  LEG-COMBO: {city_dest.city} EUR "
                                f"{res.grand_total:.0f} all-in on {res.outbound_date}"
                            )

            if SEARCH_STOP_EVENT.is_set() or current_calls >= MAX_API_CALLS:
                break
        if SEARCH_STOP_EVENT.is_set():
            break
        if current_calls >= MAX_API_CALLS:
            log_info(f"Reached MAX_API_CALLS_PER_RUN ({MAX_API_CALLS}). Stopping.")
            break

    if all_results:
        ranked = rank_results(all_results)
        print_results_table(ranked, f"TOP DEALS ({mode_label})", limit=20)
        purged = storage.purge_city_duplicates()
        if purged > 0:
            log_info(f"🧹 Cleaned {purged} duplicate city entries from database")
    else:
        log_info("No new matches found.")

    stopped = SEARCH_STOP_EVENT.is_set()
    current_top3 = storage.get_all_time_top(3)
    return SearchRunSummary(
        mode=mode_label,
        stopped=stopped,
        results=rank_results(all_results) if all_results else [],
        new_top3=_find_new_top3(previous_top3, current_top3),
    )

def export_leaderboard(storage: Storage) -> None:
    """v5.1: Exports the holiday leaderboard for July 1 - Aug 12."""
    path = os.path.join("data", "leaderboard_end_july.csv")
    with storage._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT destination, total_price, a_origin, a_price, b_origin, b_price,
                   outbound_date, return_date, source, fairness_penalty, a_stops, b_stops, arrival_gap_hours
            FROM results
            WHERE outbound_date >= '2026-07-15' AND outbound_date <= '2026-08-12'
            ORDER BY (total_price + fairness_penalty) ASC
        """)
        rows = cursor.fetchall()

    if not rows:
        print("No results found for late July to export.")
        return

    import csv
    from src.core.airports import CANDIDATE_DESTINATIONS

    headers = [
        "Rank", "City", "IATA", "Total Price", "My Route", "My Price", "My Stops",
        "Her Route", "Her Price", "Her Stops", "Outbound", "Return", "Source", "Fairness", "Arrival Gap (h)", "Warning"
    ]

    try:
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for i, row in enumerate(rows):
                dest_iata, total, a_org, a_p, b_org, b_p, out, ret, src, fair, a_s, b_s, gap = row
                dest_info = next((a for a in CANDIDATE_DESTINATIONS if a.iata == dest_iata), None)
                city = dest_info.city if dest_info else "Unknown"

                writer.writerow([
                    i+1, city, dest_iata, f"EUR {total:.2f}", f"{a_org}->{dest_iata}", f"EUR {a_p:.2f}", a_s,
                    f"{b_org}->{dest_iata}", f"EUR {b_p:.2f}", b_s,
                    out, ret, src, fair, f"{gap}h", "Verify manually"
                ])
        print(f"Exported detailed leaderboard to {path}")
    except Exception as e:
        print(f"Export failed: {e}")

def show_latest_results(storage: Storage) -> None:
    """Shows the most recent flight deals from the last 7 days."""
    from src.core.airports import CANDIDATE_DESTINATIONS
    with storage._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT destination, total_price, outbound_date, return_date,
                   a_price, b_price, source, fairness_penalty, a_stops, b_stops, arrival_gap_hours
            FROM results
            WHERE timestamp > datetime('now', '-7 days')
            ORDER BY (total_price + fairness_penalty) ASC
        """)
        rows = cursor.fetchall()

    if not rows:
        print("No recent results found.")
        return

    # v5.1: one per city
    results = []
    seen = set()
    iata_to_city = {a.iata: a.city for a in CANDIDATE_DESTINATIONS}
    for row in rows:
        dest_iata, total, out, ret, a_p, b_p, src, fair, a_s, b_s, gap = row
        city = iata_to_city.get(dest_iata, dest_iata)
        if city in seen: continue
        seen.add(city)

        dest_info = next((a for a in CANDIDATE_DESTINATIONS if a.iata == dest_iata), None)
        try:
            n = (datetime.strptime(ret, "%Y-%m-%d") - datetime.strptime(out, "%Y-%m-%d")).days
        except Exception:
            n = 2
        results.append(MeetupResult(
            destination=dest_iata,
            total_price=total,
            outbound_date=out,
            return_date=ret,
            a_price=a_p,
            b_price=b_p,
            source=src,
            fairness_penalty=fair,
            a_stops=a_s,
            b_stops=b_s,
            arrival_gap_hours=gap,
            a_origin="Me",
            b_origin="Her",
            dest_city=dest_info.city if dest_info else "Unknown",
            dest_flag=dest_info.flag if dest_info else "📍",
            is_approximate=False,
            nights=n,
        ))
        
    print_results_table(results, "Latest Best Deals", limit=15)

def discover_mode(providers: List[FlightProvider]) -> None:
    """Discovery — scan Ryanair routes to find new Schengen connections."""
    print("\n--- Running DISCOVER Mode ---")
    from src.core.airports import CANDIDATE_DESTINATIONS, SCHENGEN_COUNTRIES
    from src.clients.ryanair_client import RyanairClient
    rc = RyanairClient(debug=False)
    next_month = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    end_month = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")

    existing = {a.iata for a in CANDIDATE_DESTINATIONS}
    all_dests: set = set()
    # Test the top known routes to see what's active
    test_dests = ["VIE", "BCN", "BUD", "PRG", "WAW", "CPH", "BER", "FCO",
                  "MLA", "LIS", "ATH", "AMS", "BRU", "ZRH", "ARN", "HEL",
                  "OSL", "CDG", "NCE", "AGP", "PMI", "LJU", "BTS", "KRK",
                  "GDN", "TLL", "VNO", "OPO", "MAD", "STR", "HAM", "DUS"]
    for dest in test_dests:
        fares = rc.cheapest_per_day("BGY", dest, next_month, end_month)
        if fares:
            all_dests.add(dest)
            best = min(fares, key=lambda f: f.price)
            print(f"  BGY → {dest}: {len(fares)} dates, best EUR {best.price:.0f}")
    print(f"\n{len(all_dests)} active routes found from BGY.")
    missing = set(test_dests) - all_dests
    if missing:
        print(f"No flights to: {', '.join(sorted(missing))}")

def test_providers(providers: List[FlightProvider]) -> None:
    print("\n--- Provider Health Check ---")
    for p in providers:
        status = "HEALTHY" if p.is_healthy() else "UNAVAILABLE/ERROR"
        print(f"{p.name():<25}: {status}")

def selftest(storage: Storage, notifier: Notifier, providers: List[FlightProvider]) -> None:
    print("\n--- System Selftest ---")
    def check(name, condition, info=""):
        status = "PASS" if condition else "FAIL"
        print(f"{name:<20}: [{status}] {info}")
    
    check("Python 3.11+", sys.version_info >= (3, 11), sys.version.split()[0])
    try:
        storage.get_serpapi_usage()
        check("SQLite Database", True)
    except:
        check("SQLite Database", False)
    
    check("Telegram Config", bool(Config.TELEGRAM_BOT_TOKEN and Config.TELEGRAM_CHAT_ID))
    
    for p in providers:
        check(f"Provider: {p.name()}", p.is_healthy())

def show_menu():
    print("\n" + "="*25)
    print(" Flight Meet - MENU")
    print("="*25)
    print("1. Search (Monitor)")
    print("2. Verify Candidates")
    print("3. Show History")
    print("4. Booking Mode (Late July)")
    print("5. Export Leaderboard")
    print("6. Inspect Database")
    print("7. Discover New Cities")
    print("8. Health Check")
    print("9. System Selftest")
    print("0. Exit")
    return input("\nChoice: ")

def main() -> None:
    storage = Storage()
    notifier = Notifier(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_ID)
    
    providers = build_providers(storage)

    parser = argparse.ArgumentParser(description="Flight Meet Agent")
    parser.add_argument("command", nargs="?", help="Command: monitor, results, booking-mode, export-leaderboard, inspect-db, discover, health, selftest, clear")
    args = parser.parse_args()

    cmd = args.command
    if not cmd:
        while True:
            choice = show_menu()
            if choice == "1": monitor_mode(storage, notifier, providers)
            elif choice == "2": verify_mode(storage, notifier, providers)
            elif choice == "3": show_latest_results(storage)
            elif choice == "4": booking_mode(storage, notifier, providers)
            elif choice == "5": export_leaderboard(storage)
            elif choice == "6": inspect_db(storage)
            elif choice == "7": discover_mode(providers)
            elif choice == "8": test_providers(providers)
            elif choice == "9": selftest(storage, notifier, providers)
            elif choice == "0": break
            else: print("Invalid choice.")
    else:
        if cmd in ["monitor", "search"]: monitor_mode(storage, notifier, providers)
        elif cmd == "verify": verify_mode(storage, notifier, providers)
        elif cmd in ["results", "history"]: show_latest_results(storage)
        elif cmd in ["booking-mode", "july"]: booking_mode(storage, notifier, providers)
        elif cmd in ["export-leaderboard", "export"]: export_leaderboard(storage)
        elif cmd in ["inspect-db", "inspect"]: inspect_db(storage)
        elif cmd == "discover": discover_mode(providers)
        elif cmd in ["health", "test"]: test_providers(providers)
        elif cmd == "selftest": selftest(storage, notifier, providers)
        elif cmd == "clear": storage.clear_results()
        else: print(f"Unknown command: {cmd}")

    storage.export_csv()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExit.")
    except Exception as e:
        import traceback
        print(f"\nFATAL ERROR: {e}")
        traceback.print_exc()
