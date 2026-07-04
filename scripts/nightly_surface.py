"""
Nightly Price Surface Builder — "Own the surface, not the query."

Fable 5's #1 recommendation: precompute the full (origin × destination ×
holiday) cost table. One batch job at night, then user queries are
instant database reads + on-demand verification of just the deal
being acted on.

Strategy:
  Tier 1 (FREE - Ryanair calendar): cheapest_per_day for top routes
  Tier 2 (FREE - Ryanair sweep):  cheapest_from_airport MXP, BGY, RIX
  Tier 3 (PAID - Duffel):        verify top candidates only

Run this nightly via Task Scheduler or cron.

Usage: python scripts/nightly_surface.py [--max-ryanair-calls 50]
"""

import argparse
import sys
import os
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import src.utils.compat  # noqa

from src.clients.ryanair_client import RyanairClient
from src.core.storage import Storage
from src.core.logger import log_info, log_error
from src.core.config import Config
from src.core.airports import get_destinations, CANDIDATE_DESTINATIONS, SCHENGEN_COUNTRIES

# ---------------------------------------------------------------------------
# Target months — July + August 2026
# ---------------------------------------------------------------------------
DATE_RANGE_START = "2026-07-01"
DATE_RANGE_END = "2026-08-31"

# Priority routes (top 20 by historical cheapness + both origin cities)
PRIORITY_DESTINATIONS = [
    "CRL", "BVA", "VIE", "BCN", "BUD", "PRG", "WAW", "CPH", "MAD",
    "BRU", "CDG", "ORY", "LIS", "OPO", "ATH", "TSF", "VCE", "HEL",
    "ARN", "AMS", "BER", "MUC", "ZRH", "NCE", "FCO", "MLA", "LJU",
    "BTS", "KRK", "GDN", "TLL", "VNO", "RIX",
]

ORIGINS_A = ["BGY", "MXP"]
ORIGINS_B = ["RIX"]


def build_surface(max_calls: int = 50):
    """Fill the flight_legs table with calendar-level pricing.

    After this runs, build_round_trip_from_legs() + calendar_pre_scan()
    have fresh data for the full July-August window.
    """
    storage = Storage()
    ryanair = RyanairClient(debug=False)
    total_calls = 0

    log_info(f"=== NIGHTLY SURFACE BUILD {DATE_RANGE_START} → {DATE_RANGE_END} ===")

    # --- Calendar calls for priority routes (27 days per call!) ---
    # Each call covers a full month for one route.
    # 30 calls = 15 destinations × 2 origin groups × 2 months = ~60 seconds
    log_info(f"Phase 1: Route calendars ({len(PRIORITY_DESTINATIONS)} destinations)")
    for dest in PRIORITY_DESTINATIONS:
        if total_calls >= max_calls:
            break
        for origin in ORIGINS_A + ORIGINS_B:
            if total_calls >= max_calls:
                break
            if origin == dest:
                continue
            total_calls += 1
            try:
                fares = ryanair.cheapest_per_day(origin, dest, DATE_RANGE_START, DATE_RANGE_END)
                if fares:
                    log_info(f"    {origin}→{dest}: {len(fares)} dates with fares, "
                             f"best EUR {min(f.price for f in fares):.0f}")
                    for f in fares:
                        storage.save_flight_leg("ryanair_calendar", f)
                time.sleep(0.4)
            except Exception as exc:
                log_error(f"    {origin}→{dest}: {exc}")

    # --- Phase 2: Compute meetup surface from stored legs ---
    log_info("Phase 3: Computing meetup surface...")
    meetup_count = 0
    try:
        with storage._get_connection() as conn:
            cursor = conn.cursor()
            # Join Milan-area legs with Riga legs on same destination + date
            cursor.execute("""
                SELECT
                    a.destination,
                    a.origin as a_origin, a.price as a_price,
                    b.origin as b_origin, b.price as b_price,
                    a.depart_date as out_date
                FROM flight_legs a
                JOIN flight_legs b
                  ON a.destination = b.destination
                  AND a.depart_date = b.depart_date
                WHERE a.origin IN ('BGY','MXP')
                  AND b.origin = 'RIX'
                  AND a.timestamp > datetime('now', '-24 hours')
                  AND b.timestamp > datetime('now', '-24 hours')
                  AND a.price > 0 AND b.price > 0
                ORDER BY (a.price + b.price) ASC
            """)
            rows = cursor.fetchall()
            for dest, a_org, a_p, b_org, b_p, date in rows:
                meetup_count += 1
                if meetup_count <= 10:
                    log_info(f"  MEETUP: {dest} EUR {a_p+b_p:.0f} "
                             f"({a_org} EUR {a_p:.0f} + {b_org} EUR {b_p:.0f}) on {date}")
    except Exception as exc:
        log_error(f"Meetup surface compute error: {exc}")

    log_info(f"=== SURFACE COMPLETE ===")
    log_info(f"  API calls: {total_calls}/{max_calls}")
    log_info(f"  Meetup pairs found: {meetup_count}")
    log_info(f"  Data valid until: {(datetime.now() + timedelta(hours=24)).strftime('%Y-%m-%d %H:00')}")

    return total_calls, meetup_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nightly price surface builder")
    parser.add_argument("--max-ryanair-calls", type=int, default=50,
                        help="Max Ryanair API calls (default: 50, be polite)")
    args = parser.parse_args()

    start = time.time()
    calls, meetups = build_surface(max_calls=getattr(args, 'max_ryanair_calls', 50))
    elapsed = time.time() - start
    print(f"\nDone. {calls} calls, {meetups} meetup pairs, {elapsed:.0f}s")
