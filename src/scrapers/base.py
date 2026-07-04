"""
Base scraper class — common interface, caching, retry logic, and rate
limiting shared by every direct-airline scraper.
"""

import time
import json
import os
import random
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any

import requests

from src.core.scoring import Flight
from src.core.logger import log_info, log_error


class BaseScraper(ABC):
    """Abstract base for direct-airline scrapers.

    Subclasses MUST override:
      - name()           → str
      - _search_one_way(origin, destination, date) → List[Flight]
    """

    # ---- per-subclass overrides ----

    @abstractmethod
    def name(self) -> str:
        """Human-readable scraper name, e.g. 'Wizz Air'."""

    @abstractmethod
    def _search_one_way(
        self, origin: str, destination: str, date: str
    ) -> List[Flight]:
        """Execute one API call / scrape for a one-way route on *date*."""

    # ---- shared helpers ----

    def __init__(self, cache_ttl: int = 3600, debug: bool = False):
        self.cache_ttl = cache_ttl
        self.debug = debug
        self._mem_cache: Dict[str, Dict[str, Any]] = {}
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        })
        # Polite rate-limit: min interval between calls (seconds)
        self._min_interval = 0.6
        self._last_call = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search_one_way(
        self, origin: str, destination: str, date: str
    ) -> List[Flight]:
        """Public entry point — consults cache, rate-limits, delegates
        to _search_one_way, and stores results in cache."""
        cache_key = f"{origin}|{destination}|{date}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        self._rate_limit()
        try:
            results = self._search_one_way(origin, destination, date)
        except Exception as exc:
            log_error(f"[{self.name()}] {origin}→{destination} {date}: {exc}")
            return []

        # Normalise & validate
        valid: List[Flight] = []
        for f in results:
            if f.price and f.price > 0:
                f.source = self.name()
                valid.append(f)

        self._cache_set(cache_key, valid)
        return valid

    def search_round_trip(
        self,
        origin: str,
        destination: str,
        out_date: str,
        ret_date: str,
    ) -> Optional[Flight]:
        """Combine two one-way searches into a round-trip Flight."""
        out = self.search_one_way(origin, destination, out_date)
        ret = self.search_one_way(destination, origin, ret_date)
        if not out or not ret:
            return None

        best_out = min(out, key=lambda f: f.price)
        best_ret = min(ret, key=lambda f: f.price)

        return Flight(
            origin=origin,
            destination=destination,
            price=best_out.price + best_ret.price,
            outbound_date=out_date,
            return_date=ret_date,
            stops=max(best_out.stops, 0),
            arrival_time=best_out.arrival_time,
            source=self.name(),
        )

    def is_healthy(self) -> bool:
        """Override in subclass if a health-check endpoint exists."""
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, url: str, params: dict = None, headers: dict = None,
             timeout: int = 15, retries: int = 2) -> Optional[requests.Response]:
        """GET with retry + exponential backoff."""
        merged_headers = {**self._session.headers, **(headers or {})}
        for attempt in range(retries + 1):
            try:
                resp = self._session.get(
                    url, params=params, headers=merged_headers, timeout=timeout,
                )
                if resp.status_code < 500:
                    return resp
                # 5xx → retry
                if attempt < retries:
                    time.sleep((2 ** attempt) + random.random())
            except requests.RequestException:
                if attempt < retries:
                    time.sleep((2 ** attempt) + random.random())
        return None

    def _post(self, url: str, json_data: dict = None, data: dict = None,
              headers: dict = None, timeout: int = 15, retries: int = 2
              ) -> Optional[requests.Response]:
        """POST with retry + exponential backoff."""
        merged_headers = {**self._session.headers, **(headers or {})}
        for attempt in range(retries + 1):
            try:
                resp = self._session.post(
                    url, json=json_data, data=data,
                    headers=merged_headers, timeout=timeout,
                )
                if resp.status_code < 500:
                    return resp
                if attempt < retries:
                    time.sleep((2 ** attempt) + random.random())
            except requests.RequestException:
                if attempt < retries:
                    time.sleep((2 ** attempt) + random.random())
        return None

    def _safe_price(self, raw) -> float:
        """Coerce a raw price value into a float."""
        if raw is None:
            return 0.0
        if isinstance(raw, (int, float)):
            return float(raw)
        try:
            cleaned = str(raw).replace("€", "").replace("EUR", "")
            cleaned = cleaned.replace(",", "").strip()
            return float(cleaned)
        except (ValueError, TypeError):
            return 0.0

    def _rate_limit(self):
        """Ensure at least _min_interval seconds since the last call."""
        now = time.time()
        gap = now - self._last_call
        if gap < self._min_interval:
            time.sleep(self._min_interval - gap + random.random() * 0.3)
        self._last_call = time.time()

    # ------------------------------------------------------------------
    # Simple in-memory cache
    # ------------------------------------------------------------------

    def _cache_get(self, key: str) -> Optional[List[Flight]]:
        entry = self._mem_cache.get(key)
        if entry and (time.time() - entry["ts"]) < self.cache_ttl:
            return entry["data"]
        return None

    def _cache_set(self, key: str, data: List[Flight]):
        self._mem_cache[key] = {"ts": time.time(), "data": data}
