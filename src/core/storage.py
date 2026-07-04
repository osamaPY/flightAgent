import sqlite3
import csv
import os
from datetime import datetime
from typing import List, Optional, Tuple, Any
from contextlib import contextmanager


def _coerce_arrival_time(value: Any, fallback_date: str) -> Any:
    if isinstance(value, (str, int, float, bytes, type(None))):
        return value

    date_part = getattr(value, "date", None)
    time_part = getattr(value, "time", None)
    if isinstance(date_part, (tuple, list)) and len(date_part) >= 3 and isinstance(time_part, (tuple, list)) and len(time_part) >= 2:
        yyyy, mm, dd = date_part[:3]
        hh, minute = time_part[:2]
        return f"{int(yyyy):04d}-{int(mm):02d}-{int(dd):02d} {int(hh):02d}:{int(minute):02d}"

    return str(value) if value is not None else f"{fallback_date} 00:00"


class Storage:
    """
    Persistence layer using SQLite for flight results, price history, and API budget.
    """
    def __init__(self, db_path: str = os.path.join("data", "flights.db")):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _get_connection(self):
        """Context manager for SQLite connections."""
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Initializes the database schema if it doesn't exist."""
        # Ensure data directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Enable WAL mode for high concurrency
            cursor.execute("PRAGMA journal_mode=WAL;")
            
            # Results table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME,
                    destination TEXT,
                    a_origin TEXT,
                    a_price REAL,
                    b_origin TEXT,
                    b_price REAL,
                    total_price REAL,
                    outbound_date TEXT,
                    return_date TEXT,
                    a_stops INTEGER,
                    b_stops INTEGER,
                    arrival_gap_hours REAL,
                    source TEXT,
                    is_approximate INTEGER,
                    fairness_penalty REAL DEFAULT 0,
                    hotel_name TEXT,
                    hotel_price REAL
                )
            """)
            
            # Migration: Ensure new columns exist (v3-v5)
            cursor.execute("PRAGMA table_info(results)")
            columns = [info[1] for info in cursor.fetchall()]
            migrations = [
                ('fairness_penalty', 'REAL DEFAULT 0'),
                ('hotel_name', 'TEXT'),
                ('hotel_price', 'REAL'),
                # v5.0 columns
                ('grand_total', 'REAL DEFAULT 0'),
                ('transfer_cost', 'REAL DEFAULT 0'),
                ('bag_cost', 'REAL DEFAULT 0'),
                ('hotel_total', 'REAL DEFAULT 0'),
                ('flight_airlines', "TEXT DEFAULT ''"),
                ('flight_numbers', "TEXT DEFAULT ''"),
                ('confidence_label', "TEXT DEFAULT ''"),
                ('deal_percentile', 'REAL DEFAULT 0'),
                ('scan_id', "TEXT DEFAULT ''"),
                ('nights', 'INTEGER DEFAULT 2'),
            ]
            for col_name, col_type in migrations:
                if col_name not in columns:
                    cursor.execute(
                        f"ALTER TABLE results ADD COLUMN {col_name} {col_type}"
                    )

            # --- v5.0 Performance Indexes ---
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_results_total
                ON results(total_price, fairness_penalty)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_results_outbound
                ON results(outbound_date)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_results_dest_date
                ON results(destination, outbound_date, return_date)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_results_timestamp
                ON results(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_results_scan
                ON results(scan_id)
            """)
            # NOTE: idx_cache_lookup and idx_legs_lookup are created further
            # down, right after their api_cache / flight_legs tables — a fresh
            # DB has no such tables yet at this point.

            # --- v5.0 Schema version tracking ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    description TEXT
                )
            """)
            cursor.execute(
                "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
                (5, "v5.0: grand_total, transfers, bags, hotels, indexes, scan_id"),
            )

            # Price History table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    destination TEXT PRIMARY KEY,
                    min_total REAL,
                    last_updated DATETIME
                )
            """)

            # API Budget table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS api_budget (
                    month TEXT PRIMARY KEY,
                    serpapi_calls INTEGER DEFAULT 0
                )
            """)
            
            # Global API Cache table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS api_cache (
                    provider TEXT,
                    origin TEXT,
                    destination TEXT,
                    outbound_date TEXT,
                    return_date TEXT,
                    price REAL,
                    stops INTEGER,
                    arrival_time TEXT,
                    timestamp DATETIME,
                    PRIMARY KEY (provider, origin, destination, outbound_date, return_date)
                )
            """)

            # One-way legs discovered during searches. These are useful even
            # when a complete meetup cannot be scored yet.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS flight_legs (
                    provider TEXT,
                    origin TEXT,
                    destination TEXT,
                    depart_date TEXT,
                    price REAL,
                    stops INTEGER,
                    arrival_time TEXT,
                    timestamp DATETIME,
                    PRIMARY KEY (provider, origin, destination, depart_date)
                )
            """)

            # Indexes for the two tables just created above.
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_cache_lookup
                ON api_cache(provider, origin, destination, outbound_date, return_date, timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_legs_lookup
                ON flight_legs(origin, destination, depart_date, timestamp)
            """)

            # Provider voting / price matrix for exact route-date pairs.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS provider_quotes (
                    provider TEXT,
                    origin TEXT,
                    destination TEXT,
                    outbound_date TEXT,
                    return_date TEXT,
                    price REAL,
                    stops INTEGER,
                    arrival_time TEXT,
                    timestamp DATETIME,
                    PRIMARY KEY (provider, origin, destination, outbound_date, return_date)
                )
            """)

            # Append-only fare warehouse. Unlike api_cache/provider_quotes,
            # this keeps every observation so local analytics get smarter over
            # time instead of only remembering the latest quote.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS price_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    provider TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    outbound_date TEXT NOT NULL,
                    return_date TEXT DEFAULT '',
                    price REAL NOT NULL,
                    currency TEXT DEFAULT 'EUR',
                    stops INTEGER DEFAULT 0,
                    airline TEXT DEFAULT '',
                    flight_number TEXT DEFAULT '',
                    source_context TEXT DEFAULT '',
                    is_live INTEGER DEFAULT 0,
                    is_bookable INTEGER DEFAULT 0
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS verification_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    result_id INTEGER NOT NULL,
                    verified_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL,
                    old_total REAL DEFAULT 0,
                    new_total REAL DEFAULT 0,
                    old_grand_total REAL DEFAULT 0,
                    new_grand_total REAL DEFAULT 0,
                    delta REAL DEFAULT 0,
                    confidence_label TEXT DEFAULT '',
                    details_json TEXT DEFAULT '{}'
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS paid_price_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    result_id INTEGER,
                    search_id TEXT DEFAULT '',
                    telegram_id TEXT DEFAULT '',
                    destination TEXT NOT NULL,
                    outbound_date TEXT NOT NULL,
                    return_date TEXT NOT NULL,
                    reported_total REAL NOT NULL,
                    currency TEXT DEFAULT 'EUR',
                    notes TEXT DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ── v6: Multi-user tables ──

            # Telegram users
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id TEXT UNIQUE NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    display_name TEXT,
                    is_admin INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_active DATETIME
                )
            """)

            # Search groups (2-4 people who want to meet up)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS groups_table (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_by TEXT NOT NULL REFERENCES users(telegram_id),
                    invite_code TEXT UNIQUE NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Group members (each person's origin airports)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS group_members (
                    group_id TEXT NOT NULL REFERENCES groups_table(id),
                    telegram_id TEXT NOT NULL REFERENCES users(telegram_id),
                    label TEXT NOT NULL,
                    origins_json TEXT NOT NULL DEFAULT '[]',
                    joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (group_id, telegram_id)
                )
            """)

            # Searches (each search run for a group)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS searches (
                    id TEXT PRIMARY KEY,
                    group_id TEXT NOT NULL REFERENCES groups_table(id),
                    status TEXT NOT NULL DEFAULT 'draft',
                    participants_json TEXT NOT NULL DEFAULT '[]',
                    destinations_json TEXT NOT NULL DEFAULT '[]',
                    depart_earliest TEXT NOT NULL DEFAULT '',
                    depart_latest TEXT NOT NULL DEFAULT '',
                    min_nights INTEGER DEFAULT 2,
                    max_nights INTEGER DEFAULT 4,
                    max_price REAL,
                    schengen_only INTEGER DEFAULT 1,
                    progress_total INTEGER DEFAULT 0,
                    progress_current INTEGER DEFAULT 0,
                    progress_message TEXT DEFAULT '',
                    result_count INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    started_at DATETIME,
                    completed_at DATETIME
                )
            """)

            # Share links for public result viewing
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS share_links (
                    id TEXT PRIMARY KEY,
                    search_id TEXT NOT NULL REFERENCES searches(id),
                    created_by TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME,
                    is_active INTEGER DEFAULT 1
                )
            """)

            # ── v6 schema version ──
            cursor.execute("""
                INSERT OR REPLACE INTO schema_version (version, description)
                VALUES (?, ?)
            """, (6, "v6: users, groups, searches, share_links, N-person support"))

            # ── v6: Add search_id and participants_json to results ──
            cursor.execute("PRAGMA table_info(results)")
            columns = [info[1] for info in cursor.fetchall()]
            if 'search_id' not in columns:
                cursor.execute("ALTER TABLE results ADD COLUMN search_id TEXT DEFAULT ''")
            if 'participants_json' not in columns:
                cursor.execute("ALTER TABLE results ADD COLUMN participants_json TEXT DEFAULT ''")

            # ── v6 indexes ──
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_results_search_id
                ON results(search_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_searches_group
                ON searches(group_id, created_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_group_members_group
                ON group_members(group_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_share_links_search
                ON share_links(search_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_price_obs_route
                ON price_observations(origin, destination, outbound_date, return_date, observed_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_price_obs_dest
                ON price_observations(destination, observed_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_verification_result
                ON verification_events(result_id, verified_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_paid_reports_result
                ON paid_price_reports(result_id, created_at)
            """)

            cursor.execute("PRAGMA table_info(searches)")
            search_cols = [info[1] for info in cursor.fetchall()]
            search_migrations = [
                ("luggage", "TEXT DEFAULT 'carryon_10kg'"),
                ("include_transfers", "INTEGER DEFAULT 1"),
                ("direct_only", "INTEGER DEFAULT 0"),
                ("destination_universe", "TEXT DEFAULT 'europe'"),
                ("max_stops", "INTEGER DEFAULT 2"),
            ]
            for col_name, col_type in search_migrations:
                if col_name not in search_cols:
                    cursor.execute(
                        f"ALTER TABLE searches ADD COLUMN {col_name} {col_type}"
                    )

            conn.commit()

    def clear_results(self) -> None:
        """Clears all results and price history for a fresh start."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM results")
            cursor.execute("DELETE FROM price_history")
            conn.commit()
            print("Database results cleared.")
    def save_results(self, results: List[Any]) -> None:
        now = datetime.now()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for res in results:
                # v5.1: Dedup-at-save — skip if a cheaper deal exists for this IATA.
                existing_min = cursor.execute(
                    "SELECT MIN(total_price + fairness_penalty) FROM results WHERE destination = ?",
                    (res.destination,)
                ).fetchone()[0]
                new_score = res.total_price + getattr(res, 'fairness_penalty', 0)
                if existing_min is not None and new_score >= existing_min:
                    continue  # Already have a better or equal deal for this airport

                # Insert into full results log (v5.1: hotels removed)
                cursor.execute("""
                    INSERT INTO results (
                        timestamp, destination, a_origin, a_price, b_origin, b_price,
                        total_price, outbound_date, return_date, a_stops, b_stops,
                        arrival_gap_hours, source, is_approximate, fairness_penalty,
                        grand_total, transfer_cost, bag_cost,
                        flight_airlines, flight_numbers, confidence_label,
                        deal_percentile, scan_id, nights
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?, ?, ?)
                """, (
                    now, res.destination, res.a_origin, res.a_price, res.b_origin, res.b_price,
                    res.total_price, res.outbound_date, res.return_date, res.a_stops, res.b_stops,
                    res.arrival_gap_hours, res.source, 1 if res.is_approximate else 0, res.fairness_penalty,
                    getattr(res, 'grand_total', res.total_price),
                    getattr(res, 'transfer_cost', 0),
                    getattr(res, 'bag_cost', 0),
                    getattr(res, 'flight_airlines', ''),
                    getattr(res, 'flight_numbers', ''),
                    getattr(res, 'confidence_label', ''),
                    getattr(res, 'deal_percentile', 0),
                    getattr(res, 'scan_id', ''),
                    getattr(res, 'nights', 2),
                ))
                
                # Update all-time best price for this destination
                cursor.execute("""
                    INSERT INTO price_history (destination, min_total, last_updated)
                    VALUES (?, ?, ?)
                    ON CONFLICT(destination) DO UPDATE SET
                        min_total = MIN(min_total, excluded.min_total),
                        last_updated = excluded.last_updated
                """, (res.destination, res.total_price, now))
            conn.commit()

    def save_result(self, result: Any) -> None:
        """Save a single meetup result."""
        if not result:
            return
        self.save_results([result])

    def get_previous_best(self, destination: str) -> float:
        """Retrieves the all-time minimum total price for a destination."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT min_total FROM price_history WHERE destination = ?", (destination,))
            row = cursor.fetchone()
            return row[0] if row else float('inf')

    def get_all_time_top(self, limit: int = 3) -> List[Any]:
        """Returns unique all-time best meetup results ordered by price plus fairness."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT destination, total_price, outbound_date, return_date,
                       a_origin, a_price, b_origin, b_price, arrival_gap_hours,
                       fairness_penalty, source, a_stops, b_stops
                FROM results
                ORDER BY (total_price + fairness_penalty) ASC, arrival_gap_hours ASC
            """)
            rows = cursor.fetchall()

        seen = set()
        top = []
        for row in rows:
            key = (row[0], row[2], row[3])
            if key in seen:
                continue
            seen.add(key)
            top.append(row)
            if len(top) >= limit:
                break
        return top

    def delete_short_stays(self, min_nights: int = 2) -> int:
        """Delete results with fewer than min_nights nights. Returns count of deleted rows."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM results
                WHERE (julianday(return_date) - julianday(outbound_date)) < ?
            """, (min_nights,))
            count = cursor.fetchone()[0]
            if count > 0:
                cursor.execute("""
                    DELETE FROM results
                    WHERE (julianday(return_date) - julianday(outbound_date)) < ?
                """, (min_nights,))
                conn.commit()
            return count

    def purge_city_duplicates(self, airport_list=None) -> int:
        """v5.1: Keep only the CHEAPEST deal per city. Delete all other rows.

        Uses the provided airport list to map IATA codes to city names.
        Two airports in the same city (WAW + WMI = Warsaw) are deduped together.
        Returns count of deleted rows.
        """
        if airport_list is None:
            from src.core.airports import CANDIDATE_DESTINATIONS as airport_list
        iata_to_city = {a.iata: a.city for a in airport_list}

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, destination, total_price, fairness_penalty, outbound_date, return_date
                FROM results ORDER BY (total_price + fairness_penalty) ASC
            """)
            rows = cursor.fetchall()

            kept = set()  # city names we've already kept
            deleted = 0
            for row in rows:
                row_id, dest_iata, price, penalty, out_d, ret_d = row
                city = iata_to_city.get(dest_iata, dest_iata)
                if city in kept:
                    cursor.execute("DELETE FROM results WHERE id = ?", (row_id,))
                    deleted += 1
                else:
                    kept.add(city)

            if deleted > 0:
                conn.commit()
            return deleted

    def repair_cost_gaps(self) -> dict:
        """v5.1: Fill missing bag_cost, transfer_cost, and grand_total for existing rows.

        Rows saved before the 10kg carry-on feature have zeros for these columns.
        Uses flight_airlines column (e.g. "FR/BT") to compute bag costs per person
        and IATA codes to compute transfer costs. Returns a repair report.
        """
        from src.core.cost_utils import get_transfer_cost, get_bag_cost

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, destination, a_origin, b_origin,
                       total_price, bag_cost, transfer_cost, grand_total,
                       flight_airlines
                FROM results
                WHERE grand_total IS NULL OR grand_total = 0
                   OR bag_cost IS NULL OR bag_cost = 0
                   OR transfer_cost IS NULL OR transfer_cost = 0
            """)
            rows = cursor.fetchall()

        report = {"scanned": len(rows), "repaired": 0, "details": []}

        for row in rows:
            rid, dest, a_org, b_org, total, old_bag, old_xfer, old_grand, airlines = row
            airlines_str = str(airlines or "")

            # Compute transfer costs
            a_xfer, _ = get_transfer_cost(a_org)
            b_xfer, _ = get_transfer_cost(b_org)
            d_xfer, _ = get_transfer_cost(dest)
            transfer_total = round(a_xfer + b_xfer + d_xfer * 2, 2)

            # Compute 10 kg carry-on bag costs from airline codes
            a_airline = airlines_str.split("/")[0].strip() if "/" in airlines_str else airlines_str.strip()
            b_airline = airlines_str.split("/")[1].strip() if "/" in airlines_str else ""
            a_bag, a_inc, _ = get_bag_cost(a_airline) if a_airline else (24, False, "estimated")
            b_bag, b_inc, _ = get_bag_cost(b_airline) if b_airline else (24, False, "estimated")
            bag_total = round((0 if a_inc else a_bag) + (0 if b_inc else b_bag), 2)

            # Grand total
            grand_total = round(float(total or 0) + transfer_total + bag_total, 2)

            # Only update if something actually changed
            old_bag_v = float(old_bag or 0)
            old_xfer_v = float(old_xfer or 0)
            old_grand_v = float(old_grand or 0)
            if (abs(old_bag_v - bag_total) > 0.01 or
                abs(old_xfer_v - transfer_total) > 0.01 or
                abs(old_grand_v - grand_total) > 0.01):

                with self._get_connection() as conn:
                    conn.execute("""
                        UPDATE results
                        SET bag_cost = ?, transfer_cost = ?, grand_total = ?
                        WHERE id = ?
                    """, (bag_total, transfer_total, grand_total, rid))
                    conn.commit()
                report["repaired"] += 1
                report["details"].append(
                    f"  {dest}: flights EUR {float(total):.0f} + bags EUR {bag_total} + xfer EUR {transfer_total} = grand EUR {grand_total}"
                )

        return report

    def is_price_drop(self, destination: str, new_total: float, target_price: float) -> bool:
        """Returns True if the new price is lower than the previous best and within target."""
        prev_best = self.get_previous_best(destination)
        return new_total < prev_best and new_total <= target_price

    def get_serpapi_usage(self) -> int:
        """Returns the number of SerpApi calls made in the current month."""
        month = datetime.now().strftime("%Y-%m")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT serpapi_calls FROM api_budget WHERE month = ?", (month,))
            row = cursor.fetchone()
            return row[0] if row else 0

    def increment_serpapi_usage(self) -> None:
        """Increments the monthly SerpApi call counter."""
        month = datetime.now().strftime("%Y-%m")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO api_budget (month, serpapi_calls)
                VALUES (?, 1)
                ON CONFLICT(month) DO UPDATE SET serpapi_calls = serpapi_calls + 1
            """, (month,))
            conn.commit()

    def is_searched_today(self, destination: str, outbound: str, return_date: str) -> bool:
        """Checks if a search for this destination and date was already performed in the last 18 hours."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # We check 18 hours to allow for "same day" logic but prevent overlap
            cursor.execute("""
                SELECT COUNT(*) FROM results 
                WHERE destination = ? 
                AND outbound_date = ? 
                AND return_date = ?
                AND timestamp > datetime('now', '-18 hours')
            """, (destination, outbound, return_date))
            return cursor.fetchone()[0] > 0

    def export_csv(self, path: str = os.path.join("data", "results.csv")) -> None:
        """Exports all results to a CSV file for manual analysis."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM results ORDER BY timestamp DESC")
            columns = [description[0] for description in cursor.description]
            try:
                with open(path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(columns)
                    writer.writerows(cursor.fetchall())
            except IOError as e:
                print(f"Error: Failed to export CSV: {e}")

    def get_stats(self) -> dict:
        """Returns statistics and top results from the database."""
        stats = {}
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Total results
            cursor.execute("SELECT COUNT(*) FROM results")
            stats['total_results'] = cursor.fetchone()[0]
            
            # Last scan timestamp
            cursor.execute("SELECT MAX(timestamp) FROM results")
            stats['last_scan'] = cursor.fetchone()[0]
            
            # Providers used
            cursor.execute("SELECT DISTINCT source FROM results")
            stats['providers'] = [row[0] for row in cursor.fetchall()]
            
            # Top 20 overall
            cursor.execute("""
                SELECT destination, total_price, outbound_date, return_date, a_price, b_price, source, fairness_penalty, a_stops, b_stops, arrival_gap_hours
                FROM results
                ORDER BY (total_price + fairness_penalty) ASC
                LIMIT 20
            """)
            stats['top_20_overall'] = cursor.fetchall()

            # Top 20 holiday (Jul 15 - Aug 12)
            cursor.execute("""
                SELECT destination, total_price, outbound_date, return_date, a_price, b_price, source, fairness_penalty, a_stops, b_stops, arrival_gap_hours
                FROM results
                WHERE outbound_date >= '2026-07-15' AND outbound_date <= '2026-08-12'
                ORDER BY (total_price + fairness_penalty) ASC
                LIMIT 20
            """)
            stats['top_20_july'] = cursor.fetchall()
            
        return stats

    def get_cached_flight(self, provider: str, origin: str, destination: str, outbound: str, ret: str) -> Optional[Any]:
        """Returns a cached flight object if queried within the last 3 hours, else None."""
        from src.core.scoring import Flight
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT price, stops, arrival_time 
                    FROM api_cache 
                    WHERE provider = ? AND origin = ? AND destination = ? AND outbound_date = ? AND return_date = ?
                    AND timestamp > datetime('now', '-3 hours')
                """, (provider, origin, destination, outbound, ret))
                row = cursor.fetchone()
                if row:
                    return Flight(
                        origin=origin,
                        destination=destination,
                        price=row[0],
                        outbound_date=outbound,
                        return_date=ret,
                        stops=row[1],
                        arrival_time=row[2],
                        source=provider
                    )
        except sqlite3.OperationalError:
            pass
        return None

    def set_cached_flight(self, provider: str, flight: Any) -> None:
        """Saves a flight result into the API cache."""
        if not flight:
            return
        now = datetime.now()
        arrival_time = _coerce_arrival_time(flight.arrival_time, flight.outbound_date)
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO api_cache (provider, origin, destination, outbound_date, return_date, price, stops, arrival_time, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(provider, origin, destination, outbound_date, return_date) DO UPDATE SET
                        price = excluded.price,
                        stops = excluded.stops,
                        arrival_time = excluded.arrival_time,
                        timestamp = excluded.timestamp
                """, (provider, flight.origin, flight.destination, flight.outbound_date, flight.return_date, flight.price, flight.stops, arrival_time, now))
                conn.commit()
        except (sqlite3.OperationalError, sqlite3.ProgrammingError):
            # Ignore cache write errors to prevent crashing the thread pool
            pass
        self.save_price_observation(provider, flight, "api_cache", is_live=True)

    def save_provider_quote(self, provider: str, flight: Any) -> None:
        """Stores each provider's route/date quote for price-matrix analysis."""
        if not flight:
            return
        now = datetime.now()
        arrival_time = _coerce_arrival_time(flight.arrival_time, flight.outbound_date)
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO provider_quotes (
                        provider, origin, destination, outbound_date, return_date,
                        price, stops, arrival_time, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(provider, origin, destination, outbound_date, return_date)
                    DO UPDATE SET
                        price = excluded.price,
                        stops = excluded.stops,
                        arrival_time = excluded.arrival_time,
                        timestamp = excluded.timestamp
                """, (
                    provider, flight.origin, flight.destination, flight.outbound_date,
                    flight.return_date, flight.price, flight.stops, arrival_time, now
                ))
                conn.commit()
        except (sqlite3.OperationalError, sqlite3.ProgrammingError):
            pass
        self.save_price_observation(provider, flight, "provider_quote")

    def save_flight_leg(self, provider: str, flight: Any) -> None:
        """Stores a one-way leg, even when no complete meetup exists yet."""
        if not flight:
            return
        now = datetime.now()
        arrival_time = _coerce_arrival_time(flight.arrival_time, flight.outbound_date)
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO flight_legs (
                        provider, origin, destination, depart_date, price,
                        stops, arrival_time, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(provider, origin, destination, depart_date)
                    DO UPDATE SET
                        price = MIN(price, excluded.price),
                        stops = excluded.stops,
                        arrival_time = excluded.arrival_time,
                        timestamp = excluded.timestamp
                """, (
                    provider, flight.origin, flight.destination, flight.outbound_date,
                    flight.price, flight.stops, arrival_time, now
                ))
                conn.commit()
        except (sqlite3.OperationalError, sqlite3.ProgrammingError):
            pass
        self.save_price_observation(provider, flight, "flight_leg")

    def save_price_observation(
        self,
        provider: str,
        flight: Any,
        source_context: str = "",
        is_live: bool = False,
        is_bookable: bool = False,
    ) -> None:
        """Append a fare observation to the local price warehouse."""
        if not flight or not getattr(flight, "price", 0):
            return
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO price_observations (
                        provider, origin, destination, outbound_date, return_date,
                        price, currency, stops, airline, flight_number,
                        source_context, is_live, is_bookable
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    provider,
                    getattr(flight, "origin", ""),
                    getattr(flight, "destination", ""),
                    getattr(flight, "outbound_date", ""),
                    getattr(flight, "return_date", "") or "",
                    float(getattr(flight, "price", 0) or 0),
                    getattr(flight, "currency", "EUR") or "EUR",
                    int(getattr(flight, "stops", 0) or 0),
                    getattr(flight, "airline", "") or "",
                    getattr(flight, "flight_number", "") or "",
                    source_context,
                    1 if is_live else 0,
                    1 if is_bookable else 0,
                ))
                conn.commit()
        except (sqlite3.OperationalError, sqlite3.ProgrammingError):
            pass

    def get_price_observation_stats(
        self,
        origin: str = "",
        destination: str = "",
        days: int = 180,
    ) -> dict:
        """Local fare-history stats for route/destination analytics."""
        clauses = ["observed_at > datetime('now', ?)"]
        params = [f"-{int(days)} days"]
        if origin:
            clauses.append("origin = ?")
            params.append(origin)
        if destination:
            clauses.append("destination = ?")
            params.append(destination)
        where = " AND ".join(clauses)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT price
                FROM price_observations
                WHERE {where} AND price > 0
                ORDER BY price ASC
            """, params)
            prices = [float(r[0]) for r in cursor.fetchall()]
            cursor.execute(f"""
                SELECT provider, COUNT(*), MIN(price), AVG(price)
                FROM price_observations
                WHERE {where} AND price > 0
                GROUP BY provider
                ORDER BY COUNT(*) DESC
            """, params)
            providers = [
                {
                    "provider": r[0],
                    "count": r[1],
                    "min_price": round(float(r[2]), 2),
                    "avg_price": round(float(r[3]), 2),
                }
                for r in cursor.fetchall()
            ]

        if not prices:
            return {
                "count": 0,
                "min": None,
                "median": None,
                "p25": None,
                "p75": None,
                "providers": providers,
            }

        def pct(p: float) -> float:
            idx = int(round((len(prices) - 1) * p))
            return round(prices[max(0, min(idx, len(prices) - 1))], 2)

        return {
            "count": len(prices),
            "min": round(prices[0], 2),
            "median": pct(0.50),
            "p25": pct(0.25),
            "p75": pct(0.75),
            "providers": providers,
        }

    def save_verification_event(self, result_id: int, event: dict) -> None:
        """Persist a live verification result."""
        import json
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO verification_events (
                    result_id, status, old_total, new_total,
                    old_grand_total, new_grand_total, delta,
                    confidence_label, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                result_id,
                event.get("status", "unknown"),
                float(event.get("old_total", 0) or 0),
                float(event.get("new_total", 0) or 0),
                float(event.get("old_grand_total", 0) or 0),
                float(event.get("new_grand_total", 0) or 0),
                float(event.get("delta", 0) or 0),
                event.get("confidence_label", ""),
                json.dumps(event.get("details", {})),
            ))
            conn.commit()

    def get_latest_verification(self, result_id: int) -> Optional[dict]:
        """Return the latest verification event for a result."""
        import json
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, result_id, verified_at, status, old_total, new_total,
                       old_grand_total, new_grand_total, delta,
                       confidence_label, details_json
                FROM verification_events
                WHERE result_id = ?
                ORDER BY verified_at DESC
                LIMIT 1
            """, (result_id,))
            row = cursor.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cursor.description]
            data = dict(zip(cols, row))
            try:
                data["details"] = json.loads(data.pop("details_json") or "{}")
            except Exception:
                data["details"] = {}
            return data

    def save_paid_price_report(
        self,
        result_id: Optional[int],
        search_id: str,
        telegram_id: str,
        destination: str,
        outbound_date: str,
        return_date: str,
        reported_total: float,
        notes: str = "",
        currency: str = "EUR",
    ) -> None:
        """Store user-reported real paid totals."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO paid_price_reports (
                    result_id, search_id, telegram_id, destination,
                    outbound_date, return_date, reported_total, currency, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                result_id,
                search_id,
                telegram_id,
                destination,
                outbound_date,
                return_date,
                float(reported_total),
                currency,
                notes,
            ))
            conn.commit()

    # ═══════════════════════════════════════════════════════════════════
    # v6: Multi-user / group / search methods
    # ═══════════════════════════════════════════════════════════════════

    def upsert_user(self, telegram_id: str, username: str = "", first_name: str = "") -> dict:
        """Register or update a Telegram user. Returns user dict."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (telegram_id, username, first_name, display_name, last_active)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    username = COALESCE(excluded.username, username),
                    first_name = COALESCE(excluded.first_name, first_name),
                    last_active = excluded.last_active
            """, (telegram_id, username, first_name, first_name or username, now))
            conn.commit()
            cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            row = cursor.fetchone()
            cols = [d[0] for d in cursor.description]
            return dict(zip(cols, row)) if row else {}

    def get_user(self, telegram_id: str) -> Optional[dict]:
        """Get a user by Telegram ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            row = cursor.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cursor.description]
            return dict(zip(cols, row))

    # ── Groups ──

    def create_group(self, name: str, created_by_telegram_id: str) -> dict:
        """Create a new search group. Returns group dict with invite_code."""
        import secrets
        invite_code = secrets.token_urlsafe(8)[:10]
        import uuid
        group_id = uuid.uuid4().hex[:12]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO groups_table (id, name, created_by, invite_code)
                VALUES (?, ?, ?, ?)
            """, (group_id, name, created_by_telegram_id, invite_code))
            conn.commit()
        return {"id": group_id, "name": name, "invite_code": invite_code, "created_by": created_by_telegram_id}

    def get_group(self, group_id: str) -> Optional[dict]:
        """Get a group by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM groups_table WHERE id = ? AND is_active = 1", (group_id,))
            row = cursor.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cursor.description]
            return dict(zip(cols, row))

    def get_group_by_invite(self, invite_code: str) -> Optional[dict]:
        """Find a group by its invite code."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM groups_table WHERE invite_code = ? AND is_active = 1", (invite_code,))
            row = cursor.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cursor.description]
            return dict(zip(cols, row))

    def list_user_groups(self, telegram_id: str) -> list:
        """List all groups a user belongs to."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT g.*, gm.label, gm.origins_json
                FROM groups_table g
                JOIN group_members gm ON g.id = gm.group_id
                WHERE gm.telegram_id = ? AND g.is_active = 1
                ORDER BY g.created_at DESC
            """, (telegram_id,))
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, row)) for row in rows]

    # ── Group Members ──

    def join_group(self, group_id: str, telegram_id: str, label: str, origins: List[str]) -> bool:
        """Add a member to a group with their origin airports. Returns True if new."""
        import json
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Check if already a member
            cursor.execute(
                "SELECT 1 FROM group_members WHERE group_id = ? AND telegram_id = ?",
                (group_id, telegram_id),
            )
            if cursor.fetchone():
                # Update origins
                cursor.execute(
                    "UPDATE group_members SET origins_json = ?, label = ? WHERE group_id = ? AND telegram_id = ?",
                    (json.dumps(origins), label, group_id, telegram_id),
                )
                conn.commit()
                return False
            cursor.execute(
                "INSERT INTO group_members (group_id, telegram_id, label, origins_json) VALUES (?, ?, ?, ?)",
                (group_id, telegram_id, label, json.dumps(origins)),
            )
            conn.commit()
            return True

    def get_group_members(self, group_id: str) -> list:
        """Get all members of a group with their origins."""
        import json
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT gm.telegram_id, gm.label, gm.origins_json, u.username, u.first_name
                FROM group_members gm
                LEFT JOIN users u ON gm.telegram_id = u.telegram_id
                WHERE gm.group_id = ?
                ORDER BY gm.joined_at ASC
            """, (group_id,))
            rows = cursor.fetchall()
            members = []
            for row in rows:
                tid, label, origins_json, username, first_name = row
                members.append({
                    "telegram_id": tid,
                    "label": label,
                    "origins": json.loads(origins_json) if origins_json else [],
                    "username": username or first_name or tid,
                })
            return members

    def leave_group(self, group_id: str, telegram_id: str) -> bool:
        """Remove a member from a group."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM group_members WHERE group_id = ? AND telegram_id = ?",
                (group_id, telegram_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    # ── Searches ──

    def create_search(self, group_id: str, search_request) -> str:
        """Create a new search record. Returns search_id."""
        import json
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO searches (
                    id, group_id, status, participants_json, destinations_json,
                    depart_earliest, depart_latest, min_nights, max_nights,
                    max_price, schengen_only, luggage, include_transfers,
                    direct_only, destination_universe, max_stops
                ) VALUES (?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                search_request.id, group_id,
                json.dumps([p.to_dict() for p in search_request.participants]),
                json.dumps(search_request.destinations),
                search_request.depart_earliest, search_request.depart_latest,
                search_request.min_nights, search_request.max_nights,
                search_request.max_price,
                1 if search_request.schengen_only else 0,
                getattr(search_request, "luggage", "carryon_10kg"),
                1 if getattr(search_request, "include_transfers", True) else 0,
                1 if getattr(search_request, "direct_only", False) else 0,
                getattr(search_request, "destination_universe", "europe"),
                getattr(search_request, "max_stops", 2),
            ))
            conn.commit()
        return search_request.id

    def get_search(self, search_id: str) -> Optional[dict]:
        """Get a search by ID."""
        import json
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM searches WHERE id = ?", (search_id,))
            row = cursor.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cursor.description]
            d = dict(zip(cols, row))
            d['participants_json'] = json.loads(d.get('participants_json', '[]'))
            d['destinations_json'] = json.loads(d.get('destinations_json', '[]'))
            return d

    def list_searches_by_group(self, group_id: str, limit: int = 20) -> list:
        """List searches for a group, most recent first."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, group_id, status, depart_earliest, depart_latest,
                       min_nights, max_nights, progress_total, progress_current,
                       progress_message, result_count, created_at, completed_at,
                       luggage, include_transfers, direct_only,
                       destination_universe, max_stops
                FROM searches
                WHERE group_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (group_id, limit))
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, row)) for row in rows]

    def update_search_status(self, search_id: str, status: str,
                              progress_current: int = 0, progress_total: int = 0,
                              progress_message: str = "") -> None:
        """Update search progress."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            updates = ["status = ?"]
            params = [status]
            if progress_current:
                updates.append("progress_current = ?")
                params.append(progress_current)
            if progress_total:
                updates.append("progress_total = ?")
                params.append(progress_total)
            if progress_message:
                updates.append("progress_message = ?")
                params.append(progress_message)
            if status == 'running':
                updates.append("started_at = COALESCE(started_at, ?)")
                params.append(now)
            if status in ('completed', 'failed', 'cancelled'):
                updates.append("completed_at = ?")
                params.append(now)
            params.append(search_id)
            cursor.execute(
                f"UPDATE searches SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            conn.commit()

    def save_group_result(self, search_id: str, result) -> None:
        """Save a GroupMeetupResult to the database."""
        import json
        now = datetime.now()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO results (
                    timestamp, destination, search_id, participants_json,
                    a_origin, a_price, b_origin, b_price,
                    total_price, outbound_date, return_date,
                    a_stops, b_stops, arrival_gap_hours,
                    source, is_approximate, fairness_penalty,
                    grand_total, transfer_cost, bag_cost,
                    flight_airlines, flight_numbers, confidence_label,
                    deal_percentile, scan_id, nights
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now, result.destination, search_id,
                json.dumps([p.to_dict() for p in result.participants]),
                result.a_origin, result.a_price, result.b_origin, result.b_price,
                result.total_price, result.outbound_date, result.return_date,
                result.a_stops, result.b_stops, result.arrival_gap_hours,
                result.source, 1 if result.is_approximate else 0,
                result.fairness_penalty,
                result.grand_total, result.transfer_cost, result.bag_cost,
                result.flight_airlines, result.flight_numbers,
                result.confidence_label,
                result.deal_percentile, result.scan_id, result.nights,
            ))
            conn.commit()

    def update_search_result_count(self, search_id: str) -> None:
        """Update the cached result count for a search."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE searches SET result_count = (SELECT COUNT(*) FROM results WHERE search_id = ?) WHERE id = ?",
                (search_id, search_id),
            )
            conn.commit()

    def get_search_results(self, search_id: str) -> list:
        """Get all results for a search, best deals first."""
        import json
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, destination, outbound_date, return_date,
                       total_price, grand_total, transfer_cost, bag_cost,
                       flight_airlines, flight_numbers, confidence_label,
                       fairness_penalty, participants_json, nights,
                       arrival_gap_hours, source, is_approximate, search_id
                FROM results
                WHERE search_id = ?
                ORDER BY (COALESCE(grand_total, total_price) + COALESCE(fairness_penalty, 0)) ASC
            """, (search_id,))
            rows = cursor.fetchall()
            results = []
            for row in rows:
                d = {
                    "id": row[0], "destination": row[1], "outbound_date": row[2],
                    "return_date": row[3], "total_price": row[4], "grand_total": row[5],
                    "transfer_cost": row[6], "bag_cost": row[7],
                    "flight_airlines": row[8], "flight_numbers": row[9],
                    "confidence_label": row[10], "fairness_penalty": row[11],
                    "participants": json.loads(row[12]) if row[12] else [],
                    "nights": row[13], "arrival_gap_hours": row[14],
                    "source": row[15], "is_approximate": row[16],
                    "search_id": row[17],
                }
                latest = self.get_latest_verification(row[0])
                if latest:
                    d["verification"] = latest
                results.append(d)
            return results

    def get_result(self, result_id: int) -> Optional[dict]:
        """Get one result by database ID."""
        import json
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, destination, search_id, outbound_date, return_date,
                       total_price, grand_total, transfer_cost, bag_cost,
                       flight_airlines, flight_numbers, confidence_label,
                       fairness_penalty, participants_json, nights,
                       arrival_gap_hours, source, is_approximate
                FROM results
                WHERE id = ?
            """, (result_id,))
            row = cursor.fetchone()
            if not row:
                return None
            d = {
                "id": row[0], "destination": row[1], "search_id": row[2],
                "outbound_date": row[3], "return_date": row[4],
                "total_price": row[5], "grand_total": row[6],
                "transfer_cost": row[7], "bag_cost": row[8],
                "flight_airlines": row[9], "flight_numbers": row[10],
                "confidence_label": row[11], "fairness_penalty": row[12],
                "participants": json.loads(row[13]) if row[13] else [],
                "nights": row[14], "arrival_gap_hours": row[15],
                "source": row[16], "is_approximate": row[17],
            }
            latest = self.get_latest_verification(result_id)
            if latest:
                d["verification"] = latest
            return d

    # ── Share Links ──

    def create_share_link(self, search_id: str, created_by: str) -> str:
        """Create a share link for a search. Returns the token."""
        import secrets
        token = secrets.token_urlsafe(16)[:20]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO share_links (id, search_id, created_by, expires_at)
                VALUES (?, ?, ?, datetime('now', '+30 days'))
            """, (token, search_id, created_by))
            conn.commit()
        return token

    def get_share_link(self, token: str) -> Optional[dict]:
        """Get a share link by token."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM share_links
                WHERE id = ? AND is_active = 1 AND expires_at > datetime('now')
            """, (token,))
            row = cursor.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cursor.description]
            return dict(zip(cols, row))

    def get_shared_results(self, token: str) -> Optional[dict]:
        """Get search + results for a share link."""
        link = self.get_share_link(token)
        if not link:
            return None
        search = self.get_search(link['search_id'])
        if not search:
            return None
        results = self.get_search_results(link['search_id'])
        return {"search": search, "results": results}

    # ═══════════════════════════════════════════════════════════════════
    # v6.2: Admin methods — full system visibility for the owner
    # ═══════════════════════════════════════════════════════════════════

    def admin_all_users(self) -> list:
        """List every registered user with stats."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT u.telegram_id, u.username, u.first_name, u.is_admin,
                       u.created_at, u.last_active,
                       (SELECT COUNT(*) FROM group_members gm WHERE gm.telegram_id = u.telegram_id) as group_count,
                       (SELECT COUNT(*) FROM searches s JOIN group_members gm2 ON s.group_id = gm2.group_id WHERE gm2.telegram_id = u.telegram_id) as search_count
                FROM users u
                ORDER BY u.last_active DESC NULLS LAST
            """)
            rows = cursor.fetchall()
            cols = ['telegram_id','username','first_name','is_admin','created_at','last_active','group_count','search_count']
            return [dict(zip(cols, r)) for r in rows]

    def admin_all_groups(self) -> list:
        """List every group with member details."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT g.id, g.name, g.created_by, g.created_at, g.is_active,
                       (SELECT COUNT(*) FROM group_members WHERE group_id = g.id) as member_count,
                       (SELECT COUNT(*) FROM searches WHERE group_id = g.id) as search_count
                FROM groups_table g
                ORDER BY g.created_at DESC
            """)
            rows = cursor.fetchall()
            cols = ['id','name','created_by','created_at','is_active','member_count','search_count']
            groups = []
            for r in rows:
                d = dict(zip(cols, r))
                d['members'] = self.get_group_members(d['id'])
                groups.append(d)
            return groups

    def admin_all_searches(self, limit: int = 50) -> list:
        """List all searches across all users, most recent first."""
        import json
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.id, s.group_id, g.name as group_name, s.status,
                       s.depart_earliest, s.depart_latest,
                       s.min_nights, s.max_nights,
                       s.participants_json, s.destinations_json,
                       s.progress_total, s.progress_current, s.progress_message,
                       s.result_count, s.created_at, s.started_at, s.completed_at
                FROM searches s
                LEFT JOIN groups_table g ON s.group_id = g.id
                ORDER BY s.created_at DESC
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            results = []
            for r in rows:
                d = dict(zip(cols, r))
                d['participants_json'] = json.loads(d.get('participants_json','[]'))
                d['destinations_json'] = json.loads(d.get('destinations_json','[]'))
                results.append(d)
            return results

    def admin_recent_results(self, limit: int = 100) -> list:
        """All results across all searches, most recent first."""
        import json
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT r.id, r.destination, r.search_id, r.total_price,
                       r.grand_total, r.outbound_date, r.return_date,
                       r.participants_json, r.flight_airlines, r.flight_numbers,
                       r.confidence_label, r.bag_cost, r.transfer_cost,
                       r.timestamp, r.source, r.is_approximate, r.fairness_penalty,
                       r.nights
                FROM results r
                ORDER BY r.timestamp DESC
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, r)) for r in rows]

    def admin_stats(self) -> dict:
        """Full system stats for the admin dashboard."""
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM users")
            total_users = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM users WHERE last_active > datetime('now','-24 hours')")
            active_24h = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM groups_table WHERE is_active = 1")
            total_groups = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM searches")
            total_searches = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM searches WHERE status = 'running'")
            running = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM searches WHERE status = 'completed'")
            completed = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM results")
            total_results = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM results WHERE timestamp > datetime('now','-24 hours')")
            results_24h = c.fetchone()[0]
            c.execute("SELECT COUNT(DISTINCT destination) FROM results WHERE timestamp > datetime('now','-30 days')")
            cities_30d = c.fetchone()[0]
            c.execute("""
                SELECT destination, COUNT(*) as cnt, MIN(total_price) as cheapest
                FROM results
                WHERE timestamp > datetime('now','-30 days')
                GROUP BY destination
                ORDER BY cnt DESC LIMIT 5
            """)
            top_destinations = [{'destination': r[0], 'count': r[1], 'cheapest': r[2]} for r in c.fetchall()]

        return {
            'total_users': total_users,
            'active_24h': active_24h,
            'total_groups': total_groups,
            'total_searches': total_searches,
            'running': running,
            'completed': completed,
            'total_results': total_results,
            'results_24h': results_24h,
            'cities_30d': cities_30d,
            'top_destinations': top_destinations,
        }

    def get_quote_stats(self, origin: str, destination: str, outbound: str, ret: str) -> dict:
        """Summarizes provider voting for a route/date pair."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT provider, price
                FROM provider_quotes
                WHERE origin = ? AND destination = ? AND outbound_date = ? AND return_date = ?
                  AND price > 0
            """, (origin, destination, outbound, ret))
            rows = cursor.fetchall()

        prices = [float(row[1]) for row in rows]
        if not prices:
            return {"provider_count": 0, "cheapest": None, "spread": None, "confidence": 0}
        spread = max(prices) - min(prices)
        confidence = min(100, 45 + (len(prices) * 20))
        if len(prices) > 1 and spread <= 30:
            confidence = min(100, confidence + 15)
        return {
            "provider_count": len(prices),
            "cheapest": min(prices),
            "spread": round(spread, 2),
            "confidence": confidence,
        }
