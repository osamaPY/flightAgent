import requests
import time
from typing import List, Optional, Dict, Any
from src.core.scoring import Flight
from src.core.logger import log_info, log_error

class DuffelClient:
    """
    Client for Duffel API.
    Provides high-quality, real-time flight offers.
    """
    def __init__(self, token: str):
        self.token = token
        self.base_url = "https://api.duffel.com/air/offer_requests"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Duffel-Version": "v1",
            "Content-Type": "application/json"
        }

    def search_round_trip(self, origin: str, destination: str, out_date: str, ret_date: str) -> List[Flight]:
        """
        Creates an offer request and retrieves cheapest round-trip offers.
        """
        if not self.token:
            return []

        payload = {
            "data": {
                "slices": [
                    {
                        "origin": origin,
                        "destination": destination,
                        "departure_date": out_date
                    },
                    {
                        "origin": destination,
                        "destination": origin,
                        "departure_date": ret_date
                    }
                ],
                "passengers": [{"type": "adult"}],
                "cabin_class": "economy"
            }
        }

        try:
            # Step 1: Create Offer Request
            response = requests.post(self.base_url, headers=self.headers, json=payload, timeout=20)
            response.raise_for_status()
            data = response.json()
            
            offers = data.get("data", {}).get("offers", [])
            if not offers:
                return []

            flights = []
            for offer in offers:
                total_amount = float(offer.get("total_amount", 0))
                # For round trip, Duffel usually gives a combined offer
                # We'll take the first slice for arrival time info
                first_slice = offer.get("slices", [{}])[0]
                last_segment = first_slice.get("segments", [{}])[-1]
                
                flights.append(Flight(
                    origin=origin,
                    destination=destination,
                    price=total_amount,
                    outbound_date=out_date,
                    return_date=ret_date,
                    stops=len(first_slice.get("segments", [])) - 1,
                    arrival_time=last_segment.get("arriving_at", "").replace("T", " ")[:16],
                    source="duffel"
                ))
            
            # Sort by price
            flights.sort(key=lambda x: x.price)
            return flights
        except Exception as e:
            log_error(f"Duffel API error: {e}")
            return []

if __name__ == "__main__":
    from src.core.config import Config
    client = DuffelClient(Config.DUFFEL_TOKEN)
    print("Testing Duffel search...")
    res = client.search_round_trip("BGY", "WAW", "2026-09-18", "2026-09-21")
    if res:
        print(f"Success! Cheapest: €{res[0].price}")
    else:
        print("No flights found.")
