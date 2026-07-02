import requests
import time
from typing import List, Optional, Dict, Any
from src.core.scoring import Flight
from src.core.config import Config

class KiwiRapidApiClient:
    """
    Client for Kiwi-Com Cheap Flights API via RapidAPI.
    Provides extra coverage using Kiwi's extensive network.
    """
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.host = "kiwi-com-cheap-flights.p.rapidapi.com"
        self.base_url = f"https://{self.host}/round-trip"
        self.headers = {
            "x-rapidapi-key": self.api_key,
            "x-rapidapi-host": self.host,
            "Content-Type": "application/json"
        }

    def search_round_trip(self, origin: str, destination: str, out_date: str, ret_date: str) -> List[Flight]:
        """
        Searches for round trip flights using Kiwi RapidAPI.
        """
        if not self.api_key:
            return []

        time.sleep(0.5) # Minimal RapidAPI delay
        # Kiwi RapidAPI (emir12) usually follows a specific param structure
        # source/destination format: Airport:XXX or City:xxx_xx
        params = {
            "source": f"Airport:{origin}",
            "destination": f"Airport:{destination}",
            "currency": "EUR",
            "locale": "en",
            "adults": "1",
            "children": "0",
            "infants": "0",
            "cabinClass": "ECONOMY",
            "sortBy": "PRICE",
            "sortOrder": "ASC",
            "limit": "10",
            # Dates: Some versions use date_from, some use specific formats.
            # Based on common Kiwi wrappers, we'll try to find the right keys.
            "outbound": out_date, # Testing if it accepts YYYY-MM-DD
            "inbound": ret_date
        }

        try:
            response = requests.get(self.base_url, headers=self.headers, params=params, timeout=20)
            if response.status_code == 403:
                return []
            
            response.raise_for_status()
            data = response.json()
            
            flights = []
            results = data.get("data", [])
            if isinstance(results, list):
                for item in results:
                    price = item.get("price", 0)
                    flights.append(Flight(
                        origin=origin,
                        destination=destination,
                        price=float(price),
                        outbound_date=out_date,
                        return_date=ret_date,
                        stops=0, # Simplified
                        arrival_time=f"{out_date} 12:00",
                        source="kiwi-rapidapi"
                    ))
            return flights
        except Exception:
            return []

if __name__ == "__main__":
    key = "586a14ffbbmsh6b33d20e0f405c7p15473ejsnda8eff5e60a6"
    client = KiwiRapidApiClient(key)
    print("Smoke test: Searching BGY -> RIX...")
    res = client.search_round_trip("BGY", "RIX", "2026-09-18", "2026-09-21")
    if res:
        print(f"Success: Found {len(res)} flights. Best: €{res[0].price}")
    else:
        print("No flights found.")
