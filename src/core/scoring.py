from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

@dataclass
class Flight:
    origin: str
    destination: str
    price: float
    outbound_date: str
    return_date: str
    stops: int
    arrival_time: str  # Format: "YYYY-MM-DD HH:MM"
    source: str
    is_approximate: bool = False

from src.core.airports import CANDIDATE_DESTINATIONS, Airport

@dataclass
class MeetupResult:
    destination: str
    a_origin: str
    a_price: float
    b_origin: str
    b_price: float
    total_price: float
    outbound_date: str
    return_date: str
    a_stops: int
    b_stops: int
    arrival_gap_hours: float
    source: str
    is_approximate: bool
    dest_city: str = ""
    dest_country: str = ""
    dest_flag: str = ""
    fairness_penalty: float = 0.0
    warning: str = "Verify manually."

def generate_booking_link(origin: str, dest: str, outbound: str, return_date: str) -> str:
    """Generates a Google Flights booking link."""
    return f"https://www.google.com/travel/flights?q=Flights%20from%20{origin}%20to%20{dest}%20on%20{outbound}%20through%20{return_date}"

def score_meetup(a_flight: Flight, b_flight: Flight) -> Optional[MeetupResult]:
    # Hard constraint: same dates
    if a_flight.outbound_date != b_flight.outbound_date or a_flight.return_date != b_flight.return_date:
        return None
    
    # Calculate arrival gap in hours
    try:
        a_arrival = datetime.strptime(a_flight.arrival_time, "%Y-%m-%d %H:%M")
        b_arrival = datetime.strptime(b_flight.arrival_time, "%Y-%m-%d %H:%M")
        arrival_gap = abs((a_arrival - b_arrival).total_seconds()) / 3600.0
    except ValueError:
        arrival_gap = 0.0

    # Lookup airport metadata
    dest_info = next((a for a in CANDIDATE_DESTINATIONS if a.iata == a_flight.destination), None)
    
    # Fairness logic: penalize large price differences
    # We want both to pay a similar amount.
    price_diff = abs(a_flight.price - b_flight.price)
    
    # Heavier penalty for large differences to prioritize fair deals
    if price_diff > 100:
        fairness_penalty = price_diff * 0.8
    elif price_diff > 50:
        fairness_penalty = price_diff * 0.5
    else:
        fairness_penalty = price_diff * 0.2

    return MeetupResult(
        destination=a_flight.destination,
        a_origin=a_flight.origin,
        a_price=a_flight.price,
        b_origin=b_flight.origin,
        b_price=b_flight.price,
        total_price=a_flight.price + b_flight.price,
        outbound_date=a_flight.outbound_date,
        return_date=a_flight.return_date,
        a_stops=a_flight.stops,
        b_stops=b_flight.stops,
        arrival_gap_hours=round(arrival_gap, 2),
        source=f"{a_flight.source}+{b_flight.source}",
        is_approximate=a_flight.is_approximate or b_flight.is_approximate,
        dest_city=dest_info.city if dest_info else "",
        dest_country=dest_info.country if dest_info else "",
        dest_flag="",
        fairness_penalty=round(fairness_penalty, 2)
    )

def rank_results(results: List[MeetupResult]) -> List[MeetupResult]:
    # Sort by total_price + fairness_penalty primarily, then arrival gap, then stops
    return sorted(results, key=lambda x: (x.total_price + x.fairness_penalty, x.arrival_gap_hours, x.a_stops + x.b_stops))
