import sqlite3
import csv
import os
from datetime import datetime
from typing import List, Optional, Tuple, Any
from contextlib import contextmanager

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
        conn = sqlite3.connect(self.db_path)
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
                    fairness_penalty REAL DEFAULT 0
                )
            """)
            
            # Migration: Ensure fairness_penalty exists in results
            cursor.execute("PRAGMA table_info(results)")
            columns = [info[1] for info in cursor.fetchall()]
            if 'fairness_penalty' not in columns:
                print("Migrating database: adding fairness_penalty column...")
                cursor.execute("ALTER TABLE results ADD COLUMN fairness_penalty REAL DEFAULT 0")

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
                # Insert into full results log
                cursor.execute("""
                    INSERT INTO results (
                        timestamp, destination, a_origin, a_price, b_origin, b_price, 
                        total_price, outbound_date, return_date, a_stops, b_stops, 
                        arrival_gap_hours, source, is_approximate, fairness_penalty
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    now, res.destination, res.a_origin, res.a_price, res.b_origin, res.b_price,
                    res.total_price, res.outbound_date, res.return_date, res.a_stops, res.b_stops,
                    res.arrival_gap_hours, res.source, 1 if res.is_approximate else 0, res.fairness_penalty
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

    def get_previous_best(self, destination: str) -> float:
        """Retrieves the all-time minimum total price for a destination."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT min_total FROM price_history WHERE destination = ?", (destination,))
            row = cursor.fetchone()
            return row[0] if row else float('inf')

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
