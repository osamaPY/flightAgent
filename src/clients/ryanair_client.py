import requests
import time
import json
import os
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from src.core.scoring import Flight

# Global cache to persist across instances
_MEM_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_FILE = os.path.join("data", "ryanair_cache.json")

class RyanairClient:
    """
    Client for interacting with Ryanair's public fare endpoints.
    Includes caching and robust retry logic.
    """
    def __init__(self, debug: bool = True):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }
        self.ttl = 3600 * 2  # 2 hours
        self.debug = debug
        # v5: Connection pooling — reuse TCP connections for 20-50% latency reduction
        self._session = requests.Session()
        self._session.headers.update(self.headers)
        self._load_disk_cache()

    def _load_disk_cache(self) -> None:
        """Loads cache from disk into memory."""
        global _MEM_CACHE
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r') as f:
                    _MEM_CACHE = json.load(f)
            except (json.JSONDecodeError, IOError):
                _MEM_CACHE = {}

    def _save_disk_cache(self) -> None:
        """Saves current memory cache to disk."""
        try:
            with open(CACHE_FILE, 'w') as f:
                json.dump(_MEM_CACHE, f)
        except IOError as e:
            if self.debug: print(f"Warning: Failed to save Ryanair cache: {e}")

    def _get_cache(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieves item from cache if it hasn't expired."""
        if key in _MEM_CACHE:
            entry = _MEM_CACHE[key]
            if time.time() - entry['timestamp'] < self.ttl:
                return entry['data']
        return None

    def _set_cache(self, key: str, data: Dict[str, Any]) -> None:
        """Sets item in cache and persists to disk."""
        # Do not cache empty fares
        if not data or not data.get('fares'):
            return
            
        _MEM_CACHE[key] = {
            'timestamp': time.time(),
            'data': data
        }
        self._save_disk_cache()

    def _request(self, url: str, params: Dict[str, Any], retries: int = 3) -> Optional[Dict[str, Any]]:
        """Handles HTTP requests with caching and exponential backoff retries."""
        cache_key = f"{url}?{json.dumps(params, sort_keys=True)}"
        cached_data = self._get_cache(cache_key)
        if cached_data:
            if self.debug: print(f"DEBUG: Returning CACHED data for {url}")
            return cached_data

        for i in range(retries):
            try:
                if self.debug: 
                    print(f"DEBUG: Calling {url}")
                    print(f"DEBUG: Params: {params}")
                
                response = self._session.get(url, params=params, timeout=15)
                
                if self.debug:
                    print(f"DEBUG: Status Code: {response.status_code}")
                
                response.raise_for_status()
                data = response.json()
                
                if self.debug:
                    print(f"DEBUG: JSON Keys: {list(data.keys()) if data else 'None'}")
                    if 'fares' in data:
                        print(f"DEBUG: Fare Count: {len(data['fares'])}")
                
                if data and data.get('fares'):
                    self._set_cache(cache_key, data)
                return data
            except Exception as e:
                wait = (2 ** i)
                if self.debug: print(f"Ryanair API error: {e}. Retrying in {wait}s...")
                if i < retries - 1:
                    time.sleep(wait)
        return None

    def cheapest_fares(self, origin: str, date_from: str, date_to: str, destination: str) -> List[Flight]:
        """
        Returns a list of cheapest one-way flights from origin to a SPECIFIC destination.
        Note: Broad search with 'ANY' is no longer supported by Ryanair public endpoints.
        """
        if destination == "ANY":
            if self.debug: print("DEBUG: 'ANY' destination is not supported. Skipping search.")
            return []

        # Primary endpoint
        endpoints = [
            "https://services-api.ryanair.com/farfnd/3/oneWayFares",
            "https://www.ryanair.com/api/farfnd/v4/oneWayFares"
        ]
        
        params = {
            "departureAirportIataCode": origin,
            "arrivalAirportIataCode": destination,
            "outboundDepartureDateFrom": date_from,
            "outboundDepartureDateTo": date_to,
            "currency": "EUR",
            "language": "en",
            "market": "en-gb",
            "limit": 100
        }
        
        for url in endpoints:
            data = self._request(url, params)
            if data and data.get('fares'):
                flights = []
                for f in data['fares']:
                    outbound = f['outbound']
                    dep_dt = outbound['departureDate']
                    arr_dt = outbound['arrivalDate']
                    flights.append(Flight(
                        origin=origin,
                        destination=outbound['arrivalAirport']['iataCode'],
                        price=outbound['price']['value'],
                        outbound_date=dep_dt.split('T')[0],
                        return_date="",
                        stops=0,
                        arrival_time=arr_dt.replace('T', ' ')[:16],
                        departure_time=dep_dt.replace('T', ' ')[:16],
                        source="ryanair",
                        airline="FR",
                        flight_number=outbound.get('flightNumber', ''),
                        currency=outbound['price'].get('currencyCode', 'EUR'),
                        deep_link=f"https://www.ryanair.com/en/trip/flights/select?adults=1&"
                                  f"originIata={origin}&destinationIata={outbound['arrivalAirport']['iataCode']}"
                                  f"&dateOut={dep_dt.split('T')[0]}",
                        cabin_bag_included=False,
                    ))
                return flights
        
        return []

    # ------------------------------------------------------------------
    # v5: Calendar & surface-building endpoints
    # ------------------------------------------------------------------

    def cheapest_per_day(
        self, origin: str, destination: str,
        date_from: str, date_to: str,
    ) -> List[Flight]:
        """Ryanair cheapest-per-day calendar — one call per route-month.

        Returns one Flight per date with the cheapest fare.
        Foundation of the nightly price surface.
        """
        url = (
            f"https://services-api.ryanair.com/farfnd/3/oneWayFares/"
            f"{origin}/{destination}/cheapestPerDay"
        )
        params = {"outboundDateFrom": date_from, "outboundDateTo": date_to, "currency": "EUR"}
        data = self._request(url, params)
        if not data:
            return []
        flights = []
        # Real response: {"outbound": {"fares": [{"day": "2026-07-01",
        #   "price": {"value": 16.99, ...}, "unavailable": false, ...}]}}
        fares_list = data.get("outbound", {}).get("fares", [])
        if not fares_list:
            fares_list = data if isinstance(data, list) else []
        for entry in fares_list:
            if not isinstance(entry, dict):
                continue
            # Skip unavailable/sold-out days
            if entry.get("unavailable") or entry.get("soldOut"):
                continue
            try:
                price_raw = entry.get("price", {})
                price = price_raw.get("value") if isinstance(price_raw, dict) else entry.get("price", 0)
                if price is None or float(price) <= 0:
                    continue
                # "day" is the date field in calendar responses
                dep_date = (entry.get("day") or entry.get("departureDate") or "")[:10]
                if not dep_date:
                    continue
                flights.append(Flight(
                    origin=origin, destination=destination,
                    price=float(price), outbound_date=dep_date,
                    return_date="", stops=0,
                    arrival_time=f"{dep_date} 12:00",
                    departure_time=f"{dep_date} 06:00",
                    source="ryanair_calendar", airline="FR",
                    currency="EUR", is_approximate=True,
                    cabin_bag_included=False,
                    deep_link=f"https://www.ryanair.com/en/trip/flights/select?"
                              f"originIata={origin}&destinationIata={destination}&dateOut={dep_date}",
                ))
            except (ValueError, TypeError, KeyError):
                continue
        return flights

    def cheapest_from_airport(
        self, origin: str, date_from: str, date_to: str,
    ) -> List[Flight]:
        """v5: All destinations from one airport in one call.

        One request returns cheapest fares to every destination Ryanair
        flies from origin. Builds the entire outbound price surface.
        """
        url = (
            f"https://services-api.ryanair.com/farfnd/3/oneWayFares/"
            f"{origin}/cheapestPerDate"
        )
        params = {
            "outboundDateFrom": date_from, "outboundDateTo": date_to,
            "currency": "EUR", "language": "en", "limit": 200,
        }
        data = self._request(url, params)
        if not data:
            return []
        flights = []
        items = data if isinstance(data, list) else data.get("fares", [])
        for entry in items:
            if not isinstance(entry, dict):
                continue
            try:
                outbound = entry.get("outbound", entry)
                arr = outbound.get("arrivalAirport", {})
                dest = arr.get("iataCode", "") if isinstance(arr, dict) else ""
                price_raw = outbound.get("price", {})
                price = price_raw.get("value") if isinstance(price_raw, dict) else outbound.get("price", 0)
                dep_date = outbound.get("departureDate", "")[:10]
                if not dest or not price or not dep_date:
                    continue
                flights.append(Flight(
                    origin=origin, destination=dest, price=float(price),
                    outbound_date=dep_date, return_date="", stops=0,
                    arrival_time=outbound.get("arrivalDate", "").replace("T", " ")[:16],
                    departure_time=outbound.get("departureDate", "").replace("T", " ")[:16],
                    source="ryanair_airport_sweep", airline="FR",
                    currency="EUR", is_approximate=True, cabin_bag_included=False,
                ))
            except (ValueError, TypeError, KeyError):
                continue
        return flights

    def round_trip_fare(self, origin: str, destination: str, out_from: str, out_to: str, in_from: str, in_to: str) -> Optional[Flight]:
        """
        Combines two cheapest one-way flights to form a round trip.
        """
        out_fares = self.cheapest_fares(origin, out_from, out_to, destination=destination)
        in_fares = self.cheapest_fares(destination, in_from, in_to, destination=origin)
        
        if not out_fares or not in_fares:
            return None
            
        best_out = min(out_fares, key=lambda x: x.price)
        best_in = min(in_fares, key=lambda x: x.price)
        
        return Flight(
            origin=origin,
            destination=destination,
            price=best_out.price + best_in.price,
            outbound_date=best_out.outbound_date,
            return_date=best_in.outbound_date,
            stops=0,
            arrival_time=best_out.arrival_time,
            departure_time=best_out.departure_time,
            source="ryanair",
            airline="FR",
            flight_number=best_out.flight_number,
            currency="EUR",
            deep_link=best_out.deep_link,
            cabin_bag_included=False,
        )

if __name__ == "__main__":
    client = RyanairClient(debug=True)
    today = datetime.now()
    # Smoke test range: next 7 to 60 days
    date_from = (today + timedelta(days=7)).strftime("%Y-%m-%d")
    date_to = (today + timedelta(days=60)).strftime("%Y-%m-%d")
    
    print(f"--- Ryanair Smoke Test ---")
    test_routes = [("BGY", "CRL"), ("RIX", "STN"), ("STN", "DUB")]
    for origin, dest in test_routes:
        print(f"\nTesting Route: {origin} -> {dest}")
        fares = client.cheapest_fares(origin, date_from, date_to, destination=dest)
        if fares:
            print(f"SUCCESS: Found {len(fares)} fares. Example: {fares[0].destination} for €{fares[0].price}")
        else:
            print(f"FAILED: No fares found for {origin} -> {dest}")
    
    print("\nVerify manually before booking.")
