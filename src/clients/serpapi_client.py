import requests
import time
from typing import Optional, Dict, Any
from src.core.scoring import Flight
from src.core.storage import Storage
from src.core.config import Config

class SerpApiClient:
    """
    Client for SerpApi Google Flights engine.
    Used for final verification of top candidates.
    """
    def __init__(self, api_key: str, storage: Storage):
        self.api_key = api_key
        self.storage = storage
        self.base_url = "https://serpapi.com/search.json"
        self.monthly_budget = Config.SERPAPI_MONTHLY_BUDGET

    def verify_round_trip(self, origins: str, destination: str, out_date: str, ret_date: str, currency: str = "EUR") -> Optional[Flight]:
        """
        Verifies a round trip using Google Flights.
        Includes a hard budget guard to prevent unexpected costs.
        """
        # Budget guard check
        current_usage = self.storage.get_serpapi_usage()
        if current_usage >= self.monthly_budget:
            print(f"⚠️ SerpApi budget exhausted ({current_usage}/{self.monthly_budget}). Skipping verification.")
            return None

        params = {
            "engine": "google_flights",
            "departure_id": origins,
            "arrival_id": destination,
            "outbound_date": out_date,
            "return_date": ret_date,
            "currency": currency,
            "hl": "en",
            "api_key": self.api_key,
            "type": "1"  # Round trip
        }

        try:
            response = requests.get(self.base_url, params=params, timeout=20)
            if response.status_code == 401:
                return None
            
            response.raise_for_status()
            data = response.json()
            
            if "error" in data:
                return None
            
            # Increment usage on successful API call
            self.storage.increment_serpapi_usage()

            # Attempt to extract from best_flights or other_flights
            flights_data = data.get("best_flights") or data.get("other_flights")
            if flights_data:
                best = flights_data[0]
                return Flight(
                    origin=origins,
                    destination=destination,
                    price=float(best["price"]),
                    outbound_date=out_date,
                    return_date=ret_date,
                    stops=len(best.get("flights", [])) - 1,
                    arrival_time=best["flights"][0].get("arrival_airport", {}).get("time", ""),
                    source="serpapi_google_flights"
                )
        except requests.RequestException as e:
            # print(f"SerpApi request failed: {e}")
            pass
            
        return None

if __name__ == "__main__":
    s = Storage()
    client = SerpApiClient(Config.SERPAPI_KEY, s)
    if not Config.SERPAPI_KEY:
        print("SERPAPI_KEY not found. Skipping smoke test.")
    else:
        print("Smoke test: Verifying BGY,MXP,LIN -> WAW...")
        res = client.verify_round_trip("MXP,BGY,LIN", "WAW", "2026-09-18", "2026-09-21")
        if res:
            print(f"Verified Price: €{res.price}")
        else:
            print("Verification failed or budget reached.")
