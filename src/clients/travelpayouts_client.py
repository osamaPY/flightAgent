import requests
import time
from typing import List, Optional, Dict, Any
from src.core.scoring import Flight
from src.core.config import Config

class TravelpayoutsClient:
    """
    Client for Travelpayouts / Aviasales Data API.
    Provides cached flight discovery data.
    """
    def __init__(self, token: str):
        self.token = token
        self.base_url = "https://api.travelpayouts.com/v2/prices/latest"
        self.headers = {
            "X-Access-Token": token,
            "Accept-Encoding": "gzip, deflate"
        }

    def _request(self, params: Dict[str, Any], retries: int = 3) -> Optional[Dict[str, Any]]:
        """Handles API requests with basic retry logic."""
        for i in range(retries):
            try:
                response = requests.get(self.base_url, params=params, headers=self.headers, timeout=10)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as e:
                wait = (2 ** i)
                if i < retries - 1:
                    time.sleep(wait)
        return None

    def get_cheapest_by_origin(self, origin: str, currency: str = "EUR") -> List[Flight]:
        """
        Retrieves cached cheapest fares from a specific origin.
        Results are marked as approximate.
        """
        params = {
            "origin": origin,
            "currency": currency,
            "period_type": "year",
            "page": 1,
            "limit": 100,
            "show_to_affiliates": "true",
            "sorting": "price"
        }
        
        data = self._request(params)
        if not data or not data.get('success') or not data.get('data'):
            return []

        flights = []
        for item in data['data']:
            try:
                # Safe extraction with defaults
                dest = item.get('destination')
                value = item.get('value')
                dep_at = item.get('departure_at')
                
                if not dest or not value or not dep_at:
                    continue

                flights.append(Flight(
                    origin=origin,
                    destination=dest,
                    price=float(value),
                    outbound_date=dep_at.split('T')[0],
                    return_date=item.get('return_at', '').split('T')[0] if item.get('return_at') else "",
                    stops=int(item.get('number_of_changes', 0)),
                    arrival_time=dep_at.replace('T', ' ')[:16],
                    source="travelpayouts_cached",
                    is_approximate=True
                ))
            except (KeyError, ValueError, TypeError):
                continue
        return flights

if __name__ == "__main__":
    token = Config.TRAVELPAYOUTS_TOKEN
    if not token:
        print("TRAVELPAYOUTS_TOKEN not found in .env. Skipping smoke test.")
    else:
        client = TravelpayoutsClient(token)
        print("Smoke test: Finding cheapest cached fares from RIX...")
        fares = client.get_cheapest_by_origin("RIX")
        if fares:
            print(f"Found {len(fares)} cached fares. Cheapest: €{fares[0].price} to {fares[0].destination}")
        else:
            print("No fares found or API error (Check token).")
