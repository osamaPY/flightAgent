from typing import List, Optional
from fast_flights import FlightQuery, Passengers, create_query, get_flights
from fast_flights.exceptions import FlightsNotFound
from src.core.scoring import Flight
from src.core.logger import log_error


def _format_simple_datetime(value, fallback_date: str) -> str:
    """Return the app's required YYYY-MM-DD HH:MM string for fast-flights values."""
    if not value:
        return f"{fallback_date} 00:00"

    date_part = getattr(value, "date", None)
    time_part = getattr(value, "time", None)

    if isinstance(date_part, (tuple, list)) and len(date_part) >= 3:
        yyyy, mm, dd = date_part[:3]
        date_text = f"{int(yyyy):04d}-{int(mm):02d}-{int(dd):02d}"
    else:
        date_text = fallback_date

    if isinstance(time_part, (tuple, list)) and len(time_part) >= 2:
        hh, minute = time_part[:2]
        time_text = f"{int(hh):02d}:{int(minute):02d}"
    elif isinstance(time_part, str) and time_part:
        time_text = time_part
    else:
        raw = str(value)
        return raw if raw and raw != "None" else f"{date_text} 00:00"

    return f"{date_text} {time_text}"


def _coerce_price(value) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace("€", "").replace("EUR", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

class GoogleScraperClient:
    """Our own internal scraper using fast-flights (Google Flights Protobuf)"""
    
    def search_flights(self, origin: str, destination: str, date: str) -> List[Flight]:
        try:
            query = create_query(
                flights=[
                    FlightQuery(
                        date=date,
                        from_airport=origin,
                        to_airport=destination,
                    ),
                ],
                seat="economy",
                trip="one-way",
                passengers=Passengers(adults=1),
                language="en-US",
            )
            
            result = get_flights(query)

            if not result:
                return []

            flights = []
            for f in result:
                segments = getattr(f, "flights", None) or []
                if not segments:
                    continue

                arrival_time = _format_simple_datetime(
                    getattr(segments[-1], "arrival", None),
                    date,
                )
                price_val = _coerce_price(getattr(f, "price", None))

                if price_val <= 0:
                    continue

                # Extract airline + flight info from first segment
                first_seg = segments[0]
                airline = (
                    getattr(first_seg, "airline", "")
                    or getattr(first_seg, "airlineCode", "")
                    or ""
                )
                flight_no = (
                    getattr(first_seg, "flightNumber", "")
                    or getattr(first_seg, "flight_number", "")
                    or ""
                )
                dep_time = _format_simple_datetime(
                    getattr(first_seg, "departure", None), date,
                )

                flights.append(Flight(
                    origin=origin,
                    destination=destination,
                    price=float(price_val),
                    outbound_date=date,
                    return_date=date,
                    stops=max(0, len(segments) - 1),
                    arrival_time=arrival_time,
                    departure_time=dep_time,
                    source="google_scraper",
                    airline=str(airline),
                    flight_number=str(flight_no),
                    currency="EUR",
                    deep_link=(
                        f"https://www.google.com/travel/flights?q="
                        f"Flights%20from%20{origin}%20to%20{destination}%20on%20{date}"
                    ),
                ))
            return flights
        except FlightsNotFound:
            return []
        except (AttributeError, IndexError, TypeError) as e:
            text = str(e)
            quiet_no_result_errors = [
                "'NoneType' object has no attribute 'text'",
                "'NoneType' object is not subscriptable",
                "list index out of range",
            ]
            if isinstance(e, IndexError) or any(msg in text for msg in quiet_no_result_errors):
                pass
            else:
                log_error(f"GoogleScraper Error ({origin}->{destination}): {e}")
            return []
        except Exception as e:
            log_error(f"GoogleScraper Error ({origin}->{destination}): {e}")
            return []

    def search_round_trip(self, origin: str, destination: str, outbound: str, ret: str) -> Optional[Flight]:
        """Convenience to match our scoring logic"""
        out_flights = self.search_flights(origin, destination, outbound)
        if not out_flights: return None
        
        in_flights = self.search_flights(destination, origin, ret)
        if not in_flights: return None
        
        # Best cheapest combo
        best_out = min(out_flights, key=lambda x: x.price if x.price > 0 else 9999)
        best_in = min(in_flights, key=lambda x: x.price if x.price > 0 else 9999)
        
        return Flight(
            origin=origin,
            destination=destination,
            price=best_out.price + best_in.price,
            outbound_date=outbound,
            return_date=ret,
            stops=best_out.stops + best_in.stops,
            arrival_time=best_out.arrival_time,
            departure_time=best_out.departure_time,
            source="google_scraper",
            airline=best_out.airline,
            flight_number=best_out.flight_number,
            currency="EUR",
            deep_link=best_out.deep_link,
        )
