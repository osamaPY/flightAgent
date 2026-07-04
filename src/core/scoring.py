from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class Flight:
    origin: str
    destination: str
    price: float
    outbound_date: str
    return_date: str
    stops: int
    arrival_time: str  # "YYYY-MM-DD HH:MM"
    source: str
    is_approximate: bool = False
    # --- v5.0+ fields ---
    airline: str = ""               # IATA airline code e.g. "FR", "LH"
    flight_number: str = ""         # e.g. "FR1234"
    departure_time: str = ""        # "YYYY-MM-DD HH:MM" — for duration calc
    currency: str = "EUR"           # ISO 4217
    deep_link: str = ""             # Direct booking URL
    cabin_bag_included: bool = False  # True = cabin bag in fare
    offer_expires_at: str = ""      # ISO timestamp when quote becomes stale


@dataclass
class ParticipantFlight:
    """One person's flight within a group meetup result."""
    label: str = ""                 # "You", "Alice", etc.
    origin: str = ""                # IATA
    price: float = 0.0
    stops: int = 0
    airline: str = ""
    flight_number: str = ""
    deep_link: str = ""
    arrival_time: str = ""
    source: str = ""
    transfer_cost: float = 0.0      # airport → city RT for this person
    bag_cost: float = 0.0           # 10kg carry-on for this person
    bag_included: bool = False
    is_approximate: bool = False

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "origin": self.origin,
            "price": self.price,
            "stops": self.stops,
            "airline": self.airline,
            "flight_number": self.flight_number,
            "deep_link": self.deep_link,
            "arrival_time": self.arrival_time,
            "source": self.source,
            "transfer_cost": self.transfer_cost,
            "bag_cost": self.bag_cost,
            "bag_included": self.bag_included,
        }


from src.core.airports import CANDIDATE_DESTINATIONS, Airport


@dataclass
class MeetupResult:
    """v5 legacy: two-person meetup result. Kept for backward compatibility.

    New code should use GroupMeetupResult for 2-4 people.
    """
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
    nights: int = 0
    fairness_penalty: float = 0.0
    warning: str = "Verify manually."
    # --- v5.1: true cost (flights + transfers + 10 kg bag) ---
    transfer_cost: float = 0.0
    bag_cost: float = 0.0
    grand_total: float = 0.0
    flight_airlines: str = ""
    flight_numbers: str = ""
    confidence_label: str = ""
    deal_percentile: float = 0.0
    scan_id: str = ""

    def to_group_result(self) -> "GroupMeetupResult":
        """Convert legacy 2-person result to the new group format."""
        return GroupMeetupResult(
            destination=self.destination,
            outbound_date=self.outbound_date,
            return_date=self.return_date,
            participants=[
                ParticipantFlight(
                    label="🅰️ Person A", origin=self.a_origin,
                    price=self.a_price, stops=self.a_stops,
                    arrival_time="", source=self.source,
                ),
                ParticipantFlight(
                    label="🅱️ Person B", origin=self.b_origin,
                    price=self.b_price, stops=self.b_stops,
                    arrival_time="", source=self.source,
                ),
            ],
            total_price=self.total_price,
            grand_total=self.grand_total,
            transfer_cost=self.transfer_cost,
            bag_cost=self.bag_cost,
            dest_city=self.dest_city,
            dest_country=self.dest_country,
            dest_flag=self.dest_flag,
            nights=self.nights,
            fairness_penalty=self.fairness_penalty,
            source=self.source,
            is_approximate=self.is_approximate,
            flight_airlines=self.flight_airlines,
            flight_numbers=self.flight_numbers,
            confidence_label=self.confidence_label,
            deal_percentile=self.deal_percentile,
            scan_id=self.scan_id,
        )


@dataclass
class GroupMeetupResult:
    """v6: N-person meetup result (2-4 people).

    Replaces the hardcoded a_origin/a_price/b_origin/b_price with a flexible
    participants list. All per-person costs (flight, transfer, bag) are tracked
    individually so the UI can show a full breakdown.
    """
    destination: str
    outbound_date: str
    return_date: str
    participants: List[ParticipantFlight] = field(default_factory=list)
    total_price: float = 0.0          # sum of all flight prices
    grand_total: float = 0.0          # flights + all transfers + all bags
    transfer_cost: float = 0.0        # total transfer cost (all people)
    bag_cost: float = 0.0             # total bag cost (all people)
    dest_city: str = ""
    dest_country: str = ""
    dest_flag: str = ""
    nights: int = 0
    fairness_penalty: float = 0.0
    arrival_gap_hours: float = 0.0    # max gap between any two arrivals
    source: str = ""
    is_approximate: bool = False
    flight_airlines: str = ""
    flight_numbers: str = ""
    confidence_label: str = ""
    deal_percentile: float = 0.0
    scan_id: str = ""

    @property
    def people_count(self) -> int:
        return len(self.participants)

    def to_dict(self) -> dict:
        return {
            "destination": self.destination,
            "outbound_date": self.outbound_date,
            "return_date": self.return_date,
            "participants": [p.to_dict() for p in self.participants],
            "total_price": self.total_price,
            "grand_total": self.grand_total,
            "transfer_cost": self.transfer_cost,
            "bag_cost": self.bag_cost,
            "dest_city": self.dest_city,
            "dest_country": self.dest_country,
            "dest_flag": self.dest_flag,
            "nights": self.nights,
            "fairness_penalty": self.fairness_penalty,
            "arrival_gap_hours": self.arrival_gap_hours,
            "source": self.source,
            "is_approximate": self.is_approximate,
            "flight_airlines": self.flight_airlines,
            "flight_numbers": self.flight_numbers,
            "confidence_label": self.confidence_label,
            "deal_percentile": self.deal_percentile,
            "people_count": self.people_count,
        }

    # ── backward compat properties ──

    @property
    def a_origin(self) -> str:
        return self.participants[0].origin if len(self.participants) > 0 else ""

    @property
    def a_price(self) -> float:
        return self.participants[0].price if len(self.participants) > 0 else 0.0

    @property
    def b_origin(self) -> str:
        return self.participants[1].origin if len(self.participants) > 1 else ""

    @property
    def b_price(self) -> float:
        return self.participants[1].price if len(self.participants) > 1 else 0.0

    @property
    def a_stops(self) -> int:
        return self.participants[0].stops if len(self.participants) > 0 else 0

    @property
    def b_stops(self) -> int:
        return self.participants[1].stops if len(self.participants) > 1 else 0


def generate_booking_link(origin: str, dest: str, outbound: str, return_date: str) -> str:
    """Generates a Google Flights booking link."""
    return f"https://www.google.com/travel/flights?q=Flights%20from%20{origin}%20to%20{dest}%20on%20{outbound}%20through%20{return_date}"


# ═══════════════════════════════════════════════════════════════════════════
# v6: N-person scoring (new — use this for 2-4 people)
# ═══════════════════════════════════════════════════════════════════════════

def score_group_meetup(
    flights: List[Flight],
    participant_labels: Optional[List[str]] = None,
    nights: int = 2,
    storage=None,
    luggage: str = "carryon_10kg",       # v6.1: "none"|"carryon_10kg"|"checked_23kg"
    include_transfers: bool = True,       # v6.1: False = flight-only
) -> Optional[GroupMeetupResult]:
    """Score a group meetup for 2-4 people with true cost breakdown.

    v6: Replaces the hardcoded two-person score_meetup(). Accepts any number
    of flights (one per person), computes per-person transfers and bag costs,
    and applies an N-way fairness penalty.

    Args:
        flights: One Flight per person (must have same outbound/return dates)
        participant_labels: Optional display labels (e.g. ["You", "Alice", "Bob"])
        nights: Expected trip length (auto-computed if dates available)
        storage: Optional Storage for sanity-band lookups

    Returns:
        GroupMeetupResult with full per-person cost breakdown, or None if
        flights don't match on dates or fail sanity checks.
    """
    from src.core.cost_utils import (
        get_transfer_cost, get_bag_cost, is_sane_price,
    )

    if len(flights) < 2 or len(flights) > 4:
        return None

    # ── all flights must share the same destination and dates ──
    dest = flights[0].destination
    out_date = flights[0].outbound_date
    ret_date = flights[0].return_date

    for f in flights:
        if f.destination != dest:
            return None
        if f.outbound_date != out_date or f.return_date != ret_date:
            return None

    # ── auto-compute nights ──
    try:
        out_dt = datetime.strptime(out_date, "%Y-%m-%d")
        ret_dt = datetime.strptime(ret_date, "%Y-%m-%d")
        computed_nights = (ret_dt - out_dt).days
        if nights == 2 and computed_nights != 2:
            nights = computed_nights
    except ValueError:
        pass

    # ── sanity-band check on every flight ──
    for f in flights:
        sane, _flag = is_sane_price(f.price, dest, storage)
        if not sane:
            return None

    # ── per-person costs ──
    participants = []
    total_flight = 0.0
    total_transfer = 0.0
    total_bag = 0.0
    all_airlines = []
    all_flight_nums = []
    all_sources = set()

    for i, f in enumerate(flights):
        label = (participant_labels[i] if participant_labels and i < len(participant_labels)
                 else f"Person {i+1}")

        # Transfer: origin airport → city (one-way for this person)
        if include_transfers:
            person_transfer, _method = get_transfer_cost(f.origin)
            total_transfer += person_transfer
            dest_transfer, _ = get_transfer_cost(dest)
        else:
            person_transfer = 0.0
            dest_transfer = 0.0

        # v6.1: Bag cost based on luggage preference
        if luggage == "none":
            person_bag_actual = 0.0
            bag_incl = True  # treat as included
        elif luggage == "checked_23kg":
            # 23kg checked bag ≈ 2× 10kg carry-on cost
            person_bag, bag_incl, _ = get_bag_cost(f.airline)
            person_bag_actual = 0.0 if bag_incl else (person_bag * 2)
        else:
            # carryon_10kg (default)
            person_bag, bag_incl, _ = get_bag_cost(f.airline)
            person_bag_actual = 0.0 if bag_incl else person_bag
        total_bag += person_bag_actual

        total_flight += f.price

        if f.airline:
            all_airlines.append(f.airline)
        if f.flight_number:
            all_flight_nums.append(f.flight_number)
        if f.source:
            all_sources.add(f.source)

        participants.append(ParticipantFlight(
            label=label,
            origin=f.origin,
            price=f.price,
            stops=f.stops,
            airline=f.airline,
            flight_number=f.flight_number,
            deep_link=f.deep_link,
            arrival_time=f.arrival_time,
            source=f.source,
            transfer_cost=round(person_transfer + dest_transfer, 2),
            bag_cost=person_bag_actual,
            bag_included=bag_incl,
            is_approximate=f.is_approximate,
        ))

    # ── destination transfer × N people ──
    # Already added per-person above (person_transfer + dest_transfer)

    grand_total = round(total_flight + total_transfer + total_bag, 2)

    # ── N-way fairness penalty ──
    prices = [f.price for f in flights]
    max_diff = max(prices) - min(prices)
    avg_price = total_flight / len(flights)

    if max_diff > 100:
        fairness_penalty = max_diff * 0.8
    elif max_diff > 50:
        fairness_penalty = max_diff * 0.5
    else:
        fairness_penalty = max_diff * 0.2

    # ── arrival gap (max gap between any two arrivals, timezone-corrected) ──
    from src.core.timezone_utils import compute_arrival_spread
    arrival_pairs = [(f.arrival_time, f.origin) for f in flights if f.arrival_time]
    max_gap, tz_warning = compute_arrival_spread(arrival_pairs)

    # ── destination info ──
    dest_info = next((a for a in CANDIDATE_DESTINATIONS if a.iata == dest), None)

    return GroupMeetupResult(
        destination=dest,
        outbound_date=out_date,
        return_date=ret_date,
        participants=participants,
        total_price=round(total_flight, 2),
        grand_total=grand_total,
        transfer_cost=round(total_transfer, 2),
        bag_cost=round(total_bag, 2),
        dest_city=dest_info.city if dest_info else "",
        dest_country=dest_info.country if dest_info else "",
        dest_flag=dest_info.flag if dest_info else "",
        nights=nights,
        fairness_penalty=round(fairness_penalty, 2),
        arrival_gap_hours=round(max_gap, 2),
        source="+".join(sorted(all_sources)),
        is_approximate=any(f.is_approximate for f in flights),
        flight_airlines="/".join(all_airlines),
        flight_numbers="/".join(all_flight_nums),
    )


# ═══════════════════════════════════════════════════════════════════════════
# v5 legacy: two-person scoring (kept for backward compatibility)
# ═══════════════════════════════════════════════════════════════════════════

def score_meetup(a_flight: Flight, b_flight: Flight,
                 nights: int = 2, storage=None) -> Optional[MeetupResult]:
    """Score a meetup with true cost: flights + transfers + 10 kg carry-on.

    v5.1: Hotels removed (you check those manually). Bag cost now specifically
    models a 10 kg carry-on bag (Ryanair Priority EUR 40 RT, Wizz Priority EUR 36 RT,
    easyJet EUR 14 RT). Full-service carriers include 10 kg in the base fare.

    v6: Now delegates to score_group_meetup() internally for consistency.
    """
    result = score_group_meetup(
        flights=[a_flight, b_flight],
        participant_labels=["🅰️ Person A", "🅱️ Person B"],
        nights=nights,
        storage=storage,
    )
    if not result:
        return None

    # Convert back to legacy MeetupResult
    p = result.participants
    dest_info = next((a for a in CANDIDATE_DESTINATIONS if a.iata == result.destination), None)

    return MeetupResult(
        destination=result.destination,
        a_origin=p[0].origin,
        a_price=p[0].price,
        b_origin=p[1].origin,
        b_price=p[1].price,
        total_price=result.total_price,
        outbound_date=result.outbound_date,
        return_date=result.return_date,
        a_stops=p[0].stops,
        b_stops=p[1].stops,
        arrival_gap_hours=result.arrival_gap_hours,
        source=result.source,
        is_approximate=result.is_approximate,
        dest_city=result.dest_city,
        dest_country=result.dest_country,
        dest_flag=result.dest_flag,
        nights=result.nights,
        fairness_penalty=result.fairness_penalty,
        transfer_cost=result.transfer_cost,
        bag_cost=result.bag_cost,
        grand_total=result.grand_total,
        flight_airlines=result.flight_airlines,
        flight_numbers=result.flight_numbers,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Dedup & ranking (works for both MeetupResult and GroupMeetupResult)
# ═══════════════════════════════════════════════════════════════════════════

def _result_city(r, iata_to_city):
    """Get city name from either result type."""
    if hasattr(r, 'dest_city') and r.dest_city:
        return r.dest_city
    return iata_to_city.get(r.destination, r.destination)


def _result_score(r):
    """Get effective score from either result type."""
    base = r.grand_total if r.grand_total > 0 else r.total_price
    return base + (getattr(r, 'fairness_penalty', 0) or 0)


def dedup_by_city(results: list) -> list:
    """v6: Keep only the CHEAPEST deal per city.

    Works with both MeetupResult and GroupMeetupResult.
    """
    iata_to_city = {a.iata: a.city for a in CANDIDATE_DESTINATIONS}

    best_per_city = {}
    for r in results:
        city = _result_city(r, iata_to_city)
        score = _result_score(r)
        if city not in best_per_city or score < best_per_city[city][0]:
            best_per_city[city] = (score, r)

    return [v[1] for _, v in sorted(best_per_city.items(), key=lambda x: x[1][0])]


def rank_results(results: list, dedup_cities: bool = True) -> list:
    """v6: Sort by grand_total (true cost), confidence tier second.

    Works with both MeetupResult and GroupMeetupResult.
    """
    if dedup_cities:
        results = dedup_by_city(results)

    def _confidence_penalty(label: str) -> float:
        if not label or "HIGH" in label:
            return 0.0
        if "MEDIUM" in label:
            return 15.0
        if "SINGLE" in label:
            return 40.0
        return 80.0

    def _effective_cost(r) -> float:
        base = r.grand_total if r.grand_total > 0 else r.total_price
        return base + _confidence_penalty(getattr(r, 'confidence_label', ''))

    # Sort key: effective cost → arrival gap → total stops
    def _stops(r):
        if hasattr(r, 'participants'):
            return sum(p.stops for p in r.participants)
        return (getattr(r, 'a_stops', 0) or 0) + (getattr(r, 'b_stops', 0) or 0)

    def _gap(r):
        return getattr(r, 'arrival_gap_hours', 0) or 0

    return sorted(results, key=lambda x: (
        _effective_cost(x),
        _gap(x),
        _stops(x),
    ))


def compute_deal_percentile(destination: str, price: float, storage) -> float:
    """v5: What percentile is this deal vs. 90 days of history?

    Returns 0-100 where higher = better deal.
    """
    if not storage:
        return 0.0
    try:
        with storage._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*)
                FROM results
                WHERE destination = ?
                  AND timestamp > datetime('now', '-90 days')
            """, (destination,))
            total = cursor.fetchone()[0] or 0
            if total < 3:
                return 0.0

            cursor.execute("""
                SELECT COUNT(*)
                FROM results
                WHERE destination = ?
                  AND timestamp > datetime('now', '-90 days')
                  AND (total_price + fairness_penalty) > ?
            """, (destination, price))
            more_expensive = cursor.fetchone()[0] or 0

            return round((more_expensive / total) * 100, 1)
    except Exception:
        return 0.0
