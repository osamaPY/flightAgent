import requests
import time
from typing import List, Optional, Dict, Any
from src.core.scoring import Flight
from src.core.config import Config

class RapidApiClient:
    """
    Client for Sky Scrapper API via RapidAPI.
    Used for broad flight searches and discovery.
    """
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.host = "sky-scrapper.p.rapidapi.com"
        self.base_url = f"https://{self.host}/api/v1/flights"
        self.headers = {
            "x-rapidapi-key": self.api_key,
            "x-rapidapi-host": self.host
        }

    def _request(self, url: str, params: Dict[str, Any], retries: int = 3) -> Optional[Dict[str, Any]]:
        for i in range(retries):
            try:
                # Minimal delay between RapidAPI calls
                if i > 0:
                    time.sleep(2.0 * i)
                else:
                    time.sleep(0.5)
                
                response = requests.get(url, headers=self.headers, params=params, timeout=20)
                
                if response.status_code == 429:
                    wait = 5 * (i + 1)
                    time.sleep(wait)
                    continue
                    
                if response.status_code == 403:
                    return None
                    
                response.raise_for_status()
                return response.json()
            except Exception as e:
                if i == retries - 1:
                    # print(f"RapidAPI Request failed: {e}")
                    pass
        return None

    def search_flights(self, origin: str, destination: str, date: str, return_date: str = None) -> List[Flight]:
        """
        Searches for flights between two points on specific dates using v2 endpoint.
        """
        if not self.api_key:
            return []

        # Try v2 first, then v1
        endpoints = [
            f"https://{self.host}/api/v2/flights/searchFlights",
            f"https://{self.host}/api/v1/flights/searchFlights"
        ]
        
        params = {
            "originSkyId": origin,
            "destinationSkyId": destination,
            "date": date,
            "currency": "EUR"
        }
        if return_date:
            params["returnDate"] = return_date

        for url in endpoints:
            data = self._request(url, params)
            if not data:
                continue
                
            flights = []
            results = data.get("data", {}).get("itineraries") or data.get("data", {}).get("results")
            if results:
                for itin in results:
                    price = itin.get("price", {}).get("raw", 0)
                    leg = itin.get("legs", [{}])[0]
                    flights.append(Flight(
                        origin=origin,
                        destination=destination,
                        price=float(price),
                        outbound_date=date,
                        return_date=return_date or "",
                        stops=len(leg.get("segments", [])) - 1 if leg.get("segments") else 0,
                        arrival_time=leg.get("arrival", "").replace("T", " ")[:16],
                        source="sky-scrapper-rapidapi"
                    ))
            if flights:
                return flights
        return []

    def search_everywhere(self, origin: str) -> List[str]:
        """
        Uses searchFlightEverywhereDetails to discover where you can go from an origin.
        """
        if not self.api_key:
            return []

        endpoints = [
            f"https://{self.host}/api/v1/flights/searchFlightEverywhereDetails",
            f"https://{self.host}/api/v1/flights/searchFlightEverywhere",
            f"https://{self.host}/api/v2/flights/searchFlightEverywhere"
        ]
        
        params = {
            "originSkyId": origin,
            "oneWay": "false",
            "currency": "EUR"
        }

        for url in endpoints:
            try:
                response = requests.get(url, headers=self.headers, params=params, timeout=20)
                if response.status_code == 403:
                    continue
                response.raise_for_status()
                data = response.json()
                
                destinations = []
                results = data.get("data", {}).get("results") or data.get("data") or []
                if isinstance(results, list):
                    for res in results:
                        # Parsing logic varies between v1 and v2
                        if isinstance(res, dict):
                            dest = (res.get("content", {}).get("location", {}).get("displayCode") or 
                                    res.get("Meta", {}).get("CountryId") or 
                                    res.get("destination", {}).get("displayCode"))
                            if dest:
                                destinations.append(dest)
                if destinations:
                    return destinations
            except Exception:
                pass
        return []

if __name__ == "__main__":
    from config import Config
    client = RapidApiClient(Config.RAPIDAPI_KEY)
    if not Config.RAPIDAPI_KEY:
        print("RAPIDAPI_KEY not found. Skipping smoke test.")
    else:
        print("Smoke test: Searching BGY -> RIX...")
        # Note: We need SkyId, which might be different from IATA but often they are same
        res = client.search_flights("BGY", "RIX", "2026-09-18", "2026-09-21")
        if res:
            print(f"Success: Found {len(res)} flights. Best: €{res[0].price}")
        else:
            print("No flights found. Check if SkyId matches IATA.")
