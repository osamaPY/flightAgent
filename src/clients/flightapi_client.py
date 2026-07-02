import requests
from typing import List, Optional
from src.core.scoring import Flight

class FlightApiClient:
    """
    Client for flightapi.io.
    """
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.flightapi.io"

    def search_round_trip(self, origin: str, destination: str, date: str, return_date: str) -> List[Flight]:
        """
        Searches for round trip flights.
        """
        if not self.api_key:
            return []

        # Try multiple variants of parameters (query params vs path, case sensitivity)
        variants = [
            # Case 1: All uppercase (Standard)
            f"{self.base_url}/roundtrip/{self.api_key}/{origin}/{destination}/{date}/{return_date}/1/0/0/Economy/EUR",
            # Case 2: economy lowercase
            f"{self.base_url}/roundtrip/{self.api_key}/{origin}/{destination}/{date}/{return_date}/1/0/0/economy/EUR",
            # Case 3: Query parameters instead of path (Legacy or alternate)
            f"{self.base_url}/roundtrip?token={self.api_key}&from={origin}&to={destination}&date1={date}&date2={return_date}&adults=1&children=0&infants=0&cabin=Economy&currency=EUR"
        ]

        for url in variants:
            try:
                response = requests.get(url, timeout=20)
                if response.status_code != 200:
                    # Mute logs for standard failures
                    continue
                response.raise_for_status()
                data = response.json()
                
                flights = []
                # Handle both 'itineraries' and 'trips' keys
                itins = data.get("itineraries") or data.get("trips") or []
                if itins:
                    for itin in itins:
                        # Parsing logic can be complex; using a safe approach
                        try:
                            price_data = itin.get("pricingOptions", [{}])[0].get("price", {})
                            amount = price_data.get("amount") or price_data.get("value") or 0
                            flights.append(Flight(
                                origin=origin,
                                destination=destination,
                                price=float(amount),
                                outbound_date=date,
                                return_date=return_date,
                                stops=0,
                                arrival_time=date + " 12:00",
                                source="flightapi_io"
                            ))
                        except:
                            continue
                if flights:
                    return flights
            except Exception:
                pass
        return []
