from abc import ABC, abstractmethod
from typing import List, Optional, Any
from src.core.scoring import Flight
from src.clients.ryanair_client import RyanairClient
from src.clients.travelpayouts_client import TravelpayoutsClient
from src.clients.serpapi_client import SerpApiClient
from src.clients.rapidapi_client import RapidApiClient
from src.clients.flightapi_client import FlightApiClient
from src.clients.kiwi_rapidapi_client import KiwiRapidApiClient
from src.clients.duffel_client import DuffelClient
from src.clients.booking_com_client import BookingComClient
from src.core.config import Config

class FlightProvider(ABC):
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def search_round_trip(self, origin: str, destination: str, out_from: str, out_to: str, in_from: str, in_to: str) -> Optional[Flight]:
        pass

    @abstractmethod
    def is_healthy(self) -> bool:
        pass

class RyanairProvider(FlightProvider):
    def __init__(self):
        self.client = RyanairClient(debug=False)
    
    def name(self) -> str:
        return "Ryanair"

    def search_round_trip(self, origin: str, destination: str, out_from: str, out_to: str, in_from: str, in_to: str) -> Optional[Flight]:
        try:
            return self.client.round_trip_fare(origin, destination, out_from, out_to, in_from, in_to)
        except Exception:
            return None

    def is_healthy(self) -> bool:
        import requests
        try:
            res = requests.get("https://services-api.ryanair.com/farfnd/3/oneWayFares", timeout=5)
            return res.status_code in [200, 400]
        except:
            return False

class TravelpayoutsProvider(FlightProvider):
    def __init__(self, token: str):
        self.client = TravelpayoutsClient(token)
    
    def name(self) -> str:
        return "Travelpayouts"

    def search_round_trip(self, origin: str, destination: str, out_from: str, out_to: str, in_from: str, in_to: str) -> Optional[Flight]:
        try:
            fares = self.client.get_cheapest_by_origin(origin)
            matches = [f for f in fares if f.destination == destination and f.outbound_date == out_from]
            if matches:
                best = min(matches, key=lambda x: x.price)
                if best.return_date:
                    return best
            return None
        except Exception:
            return None

    def is_healthy(self) -> bool:
        import requests
        if not self.client.token: return False
        try:
            res = requests.get(f"https://api.travelpayouts.com/v2/prices/latest?token={self.client.token}", timeout=5)
            return res.status_code in [200, 401]
        except:
            return False

class SerpApiProvider(FlightProvider):
    def __init__(self, api_key: str, storage: Any):
        self.client = SerpApiClient(api_key, storage)
    
    def name(self) -> str:
        return "GoogleFlights (SerpApi)"

    def search_round_trip(self, origin: str, destination: str, out_from: str, out_to: str, in_from: str, in_to: str) -> Optional[Flight]:
        try:
            return self.client.verify_round_trip(origin, destination, out_from, in_from)
        except Exception:
            return None

    def is_healthy(self) -> bool:
        return bool(self.client.api_key) and self.client.storage.get_serpapi_usage() < Config.SERPAPI_MONTHLY_BUDGET

class RapidApiProvider(FlightProvider):
    def __init__(self, api_key: str):
        self.client = RapidApiClient(api_key)
    
    def name(self) -> str:
        return "SkyScrapper (RapidAPI)"

    def search_round_trip(self, origin: str, destination: str, out_from: str, out_to: str, in_from: str, in_to: str) -> Optional[Flight]:
        try:
            fares = self.client.search_flights(origin, destination, out_from, in_from)
            if fares:
                return min(fares, key=lambda x: x.price)
            return None
        except Exception:
            return None

    def is_healthy(self) -> bool:
        return bool(self.client.api_key)

class DuffelProvider(FlightProvider):
    def __init__(self, token: str):
        self.client = DuffelClient(token)
    
    def name(self) -> str:
        return "Duffel"

    def search_round_trip(self, origin: str, destination: str, out_from: str, out_to: str, in_from: str, in_to: str) -> Optional[Flight]:
        try:
            fares = self.client.search_round_trip(origin, destination, out_from, in_from)
            if fares:
                return fares[0]
            return None
        except Exception:
            return None

    def is_healthy(self) -> bool:
        import requests
        if not self.client.token: return False
        try:
            # Simple check to see if token is valid
            res = requests.get("https://api.duffel.com/air/airlines", headers=self.client.headers, timeout=5)
            return res.status_code == 200
        except:
            return False

class FlightApiProvider(FlightProvider):
    def __init__(self, api_key: str):
        self.client = FlightApiClient(api_key)
    
    def name(self) -> str:
        return "FlightAPI.io"

    def search_round_trip(self, origin: str, destination: str, out_from: str, out_to: str, in_from: str, in_to: str) -> Optional[Flight]:
        try:
            fares = self.client.search_round_trip(origin, destination, out_from, in_from)
            if fares:
                return min(fares, key=lambda x: x.price)
            return None
        except Exception:
            return None

    def is_healthy(self) -> bool:
        return bool(self.client.api_key)

class KiwiRapidApiProvider(FlightProvider):
    def __init__(self, api_key: str):
        self.client = KiwiRapidApiClient(api_key)
    
    def name(self) -> str:
        return "Kiwi (RapidAPI)"

    def search_round_trip(self, origin: str, destination: str, out_from: str, out_to: str, in_from: str, in_to: str) -> Optional[Flight]:
        try:
            fares = self.client.search_round_trip(origin, destination, out_from, in_from)
            if fares:
                return min(fares, key=lambda x: x.price)
            return None
        except Exception:
            return None

    def is_healthy(self) -> bool:
        return bool(self.client.api_key)

class BookingComProvider(FlightProvider):
    def __init__(self, api_key: str):
        self.client = BookingComClient(api_key)
    
    def name(self) -> str:
        return "Booking.com (RapidAPI)"

    def search_round_trip(self, origin: str, destination: str, out_from: str, out_to: str, in_from: str, in_to: str) -> Optional[Flight]:
        try:
            fares = self.client.search_round_trip(origin, destination, out_from, in_from)
            if fares:
                return min(fares, key=lambda x: x.price)
            return None
        except Exception:
            return None

    def is_healthy(self) -> bool:
        return bool(self.client.api_key)
