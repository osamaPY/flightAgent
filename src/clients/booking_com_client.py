import requests
import json
import time
from typing import List, Optional, Dict, Any
from src.core.scoring import Flight
from src.core.logger import log_info, log_error

class BookingComClient:
    """
    Client for Booking.com API via RapidAPI (DataCrawler).
    """
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.host = "booking-com15.p.rapidapi.com"
        self.base_url = f"https://{self.host}/api/v1/flights"
        self.headers = {
            "x-rapidapi-key": self.api_key,
            "x-rapidapi-host": self.host,
            "Content-Type": "application/json"
        }

    def search_round_trip(self, origin: str, destination: str, out_date: str, ret_date: str) -> List[Flight]:
        """
        Searches for the minimum price for a round trip.
        """
        if not self.api_key:
            return []

        url = f"{self.base_url}/getMinPriceMultiStops"
        
        legs = [
            {"fromId": f"{origin}.AIRPORT", "toId": f"{destination}.AIRPORT", "date": out_date},
            {"fromId": f"{destination}.AIRPORT", "toId": f"{origin}.AIRPORT", "date": ret_date}
        ]
        
        params = {
            "legs": json.dumps(legs),
            "cabinClass": "ECONOMY",
            "currency_code": "EUR"
        }

        try:
            time.sleep(1.0)
            response = requests.get(url, headers=self.headers, params=params, timeout=20)
            
            if response.status_code == 429:
                log_error("Booking.com API: 429 Too Many Requests. Skipping.")
                return []
            if response.status_code == 403:
                log_error("Booking.com API: 403 Forbidden. Check subscription.")
                return []
                
            response.raise_for_status()
            data = response.json()
            
            # The structure for getMinPriceMultiStops usually returns a summary or list of results
            # Based on the endpoint name, we expect a price-focused response
            results = data.get("data", [])
            if not results:
                # Try fallback: maybe it's not a list but a single object
                if data.get("data"):
                    results = [data.get("data")]
            
            flights = []
            for res in results:
                price = res.get("minPrice", 0) or res.get("price", 0)
                if not price: continue
                
                flights.append(Flight(
                    origin=origin,
                    destination=destination,
                    price=float(price),
                    outbound_date=out_date,
                    return_date=ret_date,
                    stops=0, # This endpoint doesn't specify stops clearly
                    arrival_time=f"{out_date} 23:59", # Approximation
                    source="booking-com-rapidapi"
                ))
            
            return flights
        except Exception as e:
            log_error(f"Booking.com API error: {e}")
            return []

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    key = os.getenv("RAPIDAPI_KEY")
    client = BookingComClient(key)
    print(f"Testing Booking.com search with key: {key[:5]}...")
    res = client.search_round_trip("BGY", "WAW", "2026-09-18", "2026-09-21")
    if res:
        print(f"Success! Price: €{res[0].price}")
    else:
        print("No results found.")
