import argparse
import sys
import os
import threading
from datetime import datetime, timedelta
from typing import List, Optional, Any

# Global cancellation flag for long-running searches
SEARCH_STOP_EVENT = threading.Event()

from src.core.config import Config, DATE_WINDOWS
from src.core.airports import get_destinations
from src.core.scoring import score_meetup, rank_results, MeetupResult, Flight
from src.core.storage import Storage
from src.core.notifier import Notifier
from src.core.logger import log_info, log_error
from src.core.providers import (
    RyanairProvider, TravelpayoutsProvider, SerpApiProvider, 
    RapidApiProvider, FlightApiProvider, KiwiRapidApiProvider, 
    DuffelProvider, BookingComProvider, FlightProvider
)

import concurrent.futures
from concurrent.futures import ThreadPoolExecutor

def get_best_flight(origins: List[str], destination: str, out_from: str, out_to: str, in_from: str, in_to: str, providers: List[FlightProvider], skip_slow: bool = False) -> Optional[Flight]:
    """Tries providers in order of speed/cost and returns the cheapest found."""
    best: Optional[Flight] = None
    
    # Priority 1: Fast/Cheap Providers
    fast_providers = [p for p in providers if p.name() in ["Ryanair", "Travelpayouts", "Duffel", "Booking.com (RapidAPI)"]]
    # Priority 2: Slow/Robust Providers (Verify/Fallback)
    slow_providers = [p for p in providers if p.name() not in ["Ryanair", "Travelpayouts", "Duffel", "Booking.com (RapidAPI)"]]

    for origin in origins:
        if origin == destination:
            continue
            
        # Check fast providers first
        for p in fast_providers:
            if not p.is_healthy():
                continue
            try:
                # No delay needed for fast providers (Ryanair/Travelpayouts)
                fare = p.search_round_trip(origin, destination, out_from, out_to, in_from, in_to)
                if fare and (not best or fare.price < best.price):
                    best = fare
            except Exception as e:
                log_error(f"Error in {p.name()} search: {e}")
                continue
        
        # Early Exit: If we found a Ryanair flight under 60 EUR, it's unlikely others beat it by much
        if best and best.price < 60.0 and best.source == "ryanair":
            return best

    # If no flight found or price is high, try slow providers as fallback
    if not skip_slow and (not best or best.price > 100.0):
        for origin in origins:
            if origin == destination:
                continue
                
            for p in slow_providers:
                if not p.is_healthy():
                    continue
                try:
                    import time
                    time.sleep(0.5) # Respect rate limits for heavy APIs
                    fare = p.search_round_trip(origin, destination, out_from, out_to, in_from, in_to)
                    if fare and (not best or fare.price < best.price):
                        best = fare
                except Exception as e:
                    # Silently skip SerpApi budget errors if they somehow bypass is_healthy
                    if "budget exhausted" not in str(e):
                        log_error(f"Error in {p.name()} fallback: {e}")
                    continue
    return best

def monitor_mode(storage: Storage, notifier: Notifier, providers: List[FlightProvider], progress_callback=None) -> None:
    """Monitoring loop."""
    SEARCH_STOP_EVENT.clear()
    log_info("--- MONITOR MODE ---")
    
    active_providers = [p for p in providers if p.is_healthy()]
    tp = next((p for p in active_providers if p.name() == "Travelpayouts"), None)
    
    # Step 1: Pre-filter destinations
    all_destinations = get_destinations(exclude_iatas=[])
    valid_destinations = []
    
    if tp:
        log_info("Discovery: Filtering...")
        try:
            milan_routes = set()
            for org in Config.ORIGINS_A:
                milan_routes.update([f.destination for f in tp.client.get_cheapest_by_origin(org)])
            
            riga_routes = set([f.destination for f in tp.client.get_cheapest_by_origin(Config.ORIGINS_B[0])])
            common_routes = milan_routes.intersection(riga_routes)
            
            if not common_routes:
                log_info("Fallback: Full Scan")
                valid_destinations = all_destinations
            else:
                valid_destinations = [d for d in all_destinations if d.iata in common_routes or d.iata in Config.ORIGINS_A or d.iata in Config.ORIGINS_B]
                log_info(f"Filtered to {len(valid_destinations)} cities.")
        except Exception as e:
            log_error(f"Smart Discovery failed: {e}")
            valid_destinations = all_destinations
    else:
        valid_destinations = all_destinations

    all_results: List[MeetupResult] = []
    total_steps = len(valid_destinations)
    
    def process_window(dest_iata, window, skip_slow: bool = True):
        if SEARCH_STOP_EVENT.is_set(): return None
        
        out_from = window.depart_earliest
        out_to = window.depart_latest
        in_from = (datetime.strptime(out_from, "%Y-%m-%d") + timedelta(days=window.min_nights)).strftime("%Y-%m-%d")
        in_to = (datetime.strptime(out_from, "%Y-%m-%d") + timedelta(days=window.max_nights)).strftime("%Y-%m-%d")

        # Smart Skip: Don't re-search the same thing on the same day
        if storage.is_searched_today(dest_iata, out_from, in_from):
            return None

        # Search for A and B in parallel
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = None
            future_b = None
            
            if dest_iata not in Config.ORIGINS_A:
                future_a = executor.submit(get_best_flight, Config.ORIGINS_A, dest_iata, out_from, out_to, in_from, in_to, active_providers, skip_slow=skip_slow)
            
            if dest_iata not in Config.ORIGINS_B:
                future_b = executor.submit(get_best_flight, Config.ORIGINS_B, dest_iata, out_from, out_to, in_from, in_to, active_providers, skip_slow=skip_slow)
            
            best_a = Flight(origin=dest_iata, destination=dest_iata, price=0.0, outbound_date=out_from, return_date=out_from, stops=0, arrival_time=f"{out_from} 00:00", source="internal") if dest_iata in Config.ORIGINS_A else (future_a.result() if future_a else None)
            best_b = Flight(origin=dest_iata, destination=dest_iata, price=0.0, outbound_date=out_from, return_date=out_from, stops=0, arrival_time=f"{out_from} 00:00", source="internal") if dest_iata in Config.ORIGINS_B else (future_b.result() if future_b else None)

        if best_a and best_b:
            return score_meetup(best_a, best_b)
        return None

    for i, dest in enumerate(valid_destinations):
        if SEARCH_STOP_EVENT.is_set(): break
        if progress_callback: progress_callback(i + 1, total_steps, dest.city)
        log_info(f"Scanning {dest.iata} ({dest.city})...")

        # Parallelize DATE_WINDOWS for this city - SKIP SLOW during monitor
        with ThreadPoolExecutor(max_workers=4) as window_executor:
            futures = [window_executor.submit(process_window, dest.iata, window, True) for window in DATE_WINDOWS]
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                if res:
                    all_results.append(res)
                    if storage.is_price_drop(dest.iata, res.total_price, Config.TARGET_PRICE_EUR):
                        notifier.send_message(notifier.format_alert(res))
                    log_info(f"  Found trip: €{res.total_price:.2f} (Me: {res.a_origin}, Her: {res.b_origin}) on {res.outbound_date}")

    if all_results:
        ranked = rank_results(all_results)
        storage.save_results(ranked)
        print_results_table(ranked, "Today's Best Meetup Deals")
    
    log_info("Scan Finished.")

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
        
        best_a = get_best_flight([a_origin], dest_iata, out_date, out_date, ret_date, ret_date, providers, skip_slow=False)
        best_b = get_best_flight([b_origin], dest_iata, out_date, out_date, ret_date, ret_date, providers, skip_slow=False)

        if best_a and best_b:
            res = score_meetup(best_a, best_b)
            if res:
                storage.save_results([res])
                log_info(f"Verified: €{res.total_price:.2f}")
                notifier.send_message(f"Verified Found!\n{notifier.format_alert(res)}")
        else:
            log_error(f"Failed for {dest_iata}")

def print_results_table(results: List[MeetupResult], title: str) -> None:
    print(f"\n--- {title} ---")
    print(f"{'Dest':<25} | {'Total':<8} | {'Me':<8} | {'Her':<8} | {'Fair'}")
    print("-" * 75)
    seen = set()
    count = 0
    for res in results:
        key = (res.destination, res.outbound_date)
        if key in seen: continue
        seen.add(key)
        
        fairness_label = "Good" if res.fairness_penalty < 15 else "Fair" if res.fairness_penalty < 30 else "Poor"
        dest_display = f"{res.dest_city}"
        
        print(f"{dest_display:<25} | €{res.total_price:<6.2f} | €{res.a_price:<6.2f} | €{res.b_price:<6.2f} | {fairness_label}")
        count += 1
        if count >= 10: break
    print("-" * 75)

def show_latest_results(storage: Storage) -> None:
    print("\n--- Latest Deals ---")
    from src.core.airports import CANDIDATE_DESTINATIONS
    with storage._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT destination, total_price, outbound_date, return_date, 
                   a_price, b_price, fairness_penalty
            FROM results 
            WHERE timestamp > datetime('now', '-7 days')
            ORDER BY (total_price + fairness_penalty) ASC
        """)
        rows = cursor.fetchall()
        
    if not rows:
        print("No results.")
        return

    print(f"{'Dest':<25} | {'Total':<8} | {'Me':<8} | {'Her':<8} | {'Fair'}")
    print("-" * 75)
    seen = set()
    count = 0
    for row in rows:
        dest_iata, total, out, ret, a_p, b_p, fairness = row
        key = (dest_iata, out)
        if key in seen: continue
        seen.add(key)
        
        # Lookup metadata
        dest_info = next((a for a in CANDIDATE_DESTINATIONS if a.iata == dest_iata), None)
        dest_display = f"{dest_info.city if dest_info else dest_iata}"
        fairness_label = "Good" if fairness < 15 else "Fair" if fairness < 30 else "Poor"
        
        print(f"{dest_display:<25} | €{total:<6.2f} | €{a_p:<6.2f} | €{b_p:<6.2f} | {fairness_label}")
        count += 1
        if count >= 15: break
    print("-" * 75)
    print("\nVerify manually before booking.")

def discover_mode(providers: List[FlightProvider]) -> None:
    """Discovery mode using Travelpayouts specifically if available."""
    print("\n--- Running DISCOVER Mode ---")
    tp = next((p for p in providers if isinstance(p, TravelpayoutsProvider)), None)
    if not tp or not tp.is_healthy():
        print("Travelpayouts provider is not available or healthy. Cannot run discovery.")
        return

    print("Fetching cached price data from Travelpayouts...")
    milan_dest = set()
    for origin in Config.ORIGINS_A:
        fares = tp.client.get_cheapest_by_origin(origin)
        milan_dest.update([f.destination for f in fares])
    
    riga_dest = set()
    for origin in Config.ORIGINS_B:
        fares = tp.client.get_cheapest_by_origin(origin)
        riga_dest.update([f.destination for f in fares])
    
    common = milan_dest.intersection(riga_dest)
    from airports import CANDIDATE_DESTINATIONS
    existing = {a.iata for a in CANDIDATE_DESTINATIONS}
    new_candidates = common - existing
    
    if new_candidates:
        print(f"\nFound {len(new_candidates)} potential new meetup locations:")
        for iata in sorted(new_candidates):
            print(f"- {iata}")
        print("\nYou can add these to airports.py if you want to track them.")
    else:
        print("No new shared destinations found.")
    print("\nVerify manually before booking.")

def test_providers(providers: List[FlightProvider]) -> None:
    print("\n--- Provider Health Check ---")
    for p in providers:
        status = "HEALTHY" if p.is_healthy() else "UNAVAILABLE/ERROR"
        print(f"{p.name():<25}: {status}")
    print("\nVerify manually before booking.")

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
        
    print("\nVerify manually before booking.")

def show_menu():
    print("\n" + "="*25)
    print(" Flight Meet")
    print("="*25)
    print("1. Search")
    print("2. Verify")
    print("3. History")
    print("4. Discover")
    print("5. Health")
    print("6. Selftest")
    print("7. Notify Test")
    print("8. Clear")
    print("0. Exit")
    return input("\nChoice: ")

def main() -> None:
    storage = Storage()
    notifier = Notifier(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_ID)
    
    # Initialize providers
    providers = [
        RyanairProvider(),
        TravelpayoutsProvider(Config.TRAVELPAYOUTS_TOKEN),
        SerpApiProvider(Config.SERPAPI_KEY, storage),
        RapidApiProvider(Config.RAPIDAPI_KEY),
        FlightApiProvider(Config.FLIGHTAPI_KEY),
        KiwiRapidApiProvider(Config.RAPIDAPI_KEY),
        DuffelProvider(Config.DUFFEL_TOKEN),
        BookingComProvider(Config.RAPIDAPI_KEY)
    ]

    parser = argparse.ArgumentParser(description="Flight Meet Agent")
    parser.add_argument("command", nargs="?", help="Command: monitor, results, discover, health, selftest, clear")
    args = parser.parse_args()

    cmd = args.command
    if not cmd:
        while True:
            choice = show_menu()
            if choice == "1": monitor_mode(storage, notifier, providers)
            elif choice == "2": verify_mode(storage, notifier, providers)
            elif choice == "3": show_latest_results(storage)
            elif choice == "4": discover_mode(providers)
            elif choice == "5": test_providers(providers)
            elif choice == "6": selftest(storage, notifier, providers)
            elif choice == "7": 
                notifier.send_message("Test message from Flight Meet Agent")
                print("Test message sent.")
            elif choice == "8": storage.clear_results()
            elif choice == "0": break
            else: print("Invalid choice.")
    else:
        if cmd in ["monitor", "search"]: monitor_mode(storage, notifier, providers)
        elif cmd == "verify": verify_mode(storage, notifier, providers)
        elif cmd in ["results", "history"]: show_latest_results(storage)
        elif cmd == "discover": discover_mode(providers)
        elif cmd in ["health", "test"]: test_providers(providers)
        elif cmd == "selftest": selftest(storage, notifier, providers)
        elif cmd == "telegram-test": notifier.send_message("Direct test message")
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
