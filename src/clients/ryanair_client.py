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
                
                response = requests.get(url, params=params, headers=self.headers, timeout=15)
                
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
                    flights.append(Flight(
                        origin=origin,
                        destination=outbound['arrivalAirport']['iataCode'],
                        price=outbound['price']['value'],
                        outbound_date=outbound['departureDate'].split('T')[0],
                        return_date="",
                        stops=0,
                        arrival_time=outbound['arrivalDate'].replace('T', ' ')[:16],
                        source="ryanair"
                    ))
                return flights
        
        return []

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
            source="ryanair"
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
