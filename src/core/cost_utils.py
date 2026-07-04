"""
Cost normalization utilities — makes flight prices honest by adding:
  - Airport-to-city-center transfer costs
  - 10 kg carry-on luggage costs for LCCs
  - Sanity-band validation

LCC base fares look cheap but exclude everything. The real cost of a Ryanair
EUR 29 one-way is EUR 29 + transfer + 10 kg bag = EUR 49+. This module makes
sure rankings reflect the TRUE cost, not the advertised base fare.
"""

from typing import Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# TRANSFER COSTS — airport → city center round-trip per person (EUR)
# Sources: airport official sites, Rome2Rio, verified 2026-07
# ---------------------------------------------------------------------------
TRANSFER_COST: Dict[str, Tuple[float, str]] = {
    # (round_trip_eur, method_description)
    "BGY": (12.00, "bus 1h"),
    "MXP": (26.00, "train 50m"),
    "LIN": (6.00, "metro 25m"),
    "RIX": (4.00, "bus 30m"),
    "VIE": (8.00, "CAT train 16m"),
    "BUD": (5.00, "bus 40m"),
    "PRG": (3.00, "bus 30m"),
    "WAW": (4.00, "train 25m"),
    "WMI": (8.00, "bus 45m"),
    "BER": (7.00, "train 30m"),
    "CPH": (8.00, "metro 15m"),
    "BCN": (10.00, "aerobus 35m"),
    "MAD": (8.00, "metro 45m"),
    "FRA": (10.00, "train 15m"),
    "BVA": (34.00, "bus 1h15m"),
    "ORY": (17.00, "Orlyval 30m"),
    "CDG": (21.00, "RER 50m"),
    "CRL": (34.00, "bus 1h"),
    "BRU": (9.00, "train 20m"),
    "LIS": (4.00, "metro 30m"),
    "OPO": (4.00, "metro 30m"),
    "AGP": (6.00, "bus 30m"),
    "ATH": (9.00, "metro 40m"),
    "TSF": (14.00, "bus 1h"),
    "VCE": (16.00, "bus 25m"),
    "VLC": (6.00, "metro 25m"),
    "PMI": (8.00, "bus 20m"),
    "HEL": (8.00, "train 30m"),
    "ARN": (9.00, "Arlanda Express 20m"),
    "OSL": (20.00, "Flytoget 20m"),
    "MUC": (13.00, "train 40m"),
    "ZRH": (13.00, "train 12m"),
    "AMS": (9.00, "train 20m"),
    "NCE": (6.00, "tram 30m"),
    "MRS": (8.00, "bus 25m"),
    "LYS": (12.00, "Rhonexpress 30m"),
    "HAM": (6.00, "train 25m"),
    "DUS": (6.00, "train 15m"),
    "STR": (6.00, "train 30m"),
    "NAP": (10.00, "Alibus 30m"),
    "CTA": (8.00, "bus 30m"),
    "PMO": (10.00, "train 45m"),
    "FCO": (14.00, "Leonardo Express 32m"),
    "CIA": (8.00, "bus 40m"),
    "MLA": (6.00, "bus 30m"),
    "GVA": (6.00, "train 7m"),
    "LUX": (0.00, "free transport"),
    "BTS": (4.00, "bus 20m"),
    "LJU": (6.00, "bus 30m"),
    "VNO": (3.00, "bus 20m"),
    "TLL": (4.00, "tram 20m"),
    "KRK": (4.00, "train 20m"),
    "GDN": (4.00, "bus 30m"),
    "POZ": (4.00, "bus 25m"),
    "WRO": (4.00, "bus 30m"),
}

# Default when airport not in table
DEFAULT_TRANSFER = 10.00


def get_transfer_cost(iata: str) -> Tuple[float, str]:
    """Return (round_trip_eur, method) for an airport."""
    return TRANSFER_COST.get(iata.upper(), (DEFAULT_TRANSFER, "unknown"))


# ---------------------------------------------------------------------------
# 10 KG CARRY-ON LUGGAGE COST — per-person round-trip
# LCCs: pay extra. Full-service: included in base fare.
# Prices verified July 2026 from airline websites.
# ---------------------------------------------------------------------------
AIRLINE_BAG_COST: Dict[str, Tuple[float, str]] = {
    # Airline IATA → (round_trip_10kg_bag_eur, note)
    "FR": (40.00, "Ryanair Priority (10 kg cabin bag + small bag)"),
    "W6": (36.00, "Wizz Air Priority (10 kg trolley bag)"),
    "U2": (14.00, "easyJet 10 kg cabin bag add-on"),
    "DY": (22.00, "Norwegian LowFare+ (10 kg carry-on)"),
    "BT": (24.00, "airBaltic Green Classic (10 kg carry-on)"),
    "VY": (22.00, "Vueling Optima (10 kg cabin bag)"),
    "EW": (16.00, "Eurowings SMART (10 kg carry-on)"),
}

# Full-service carriers: 10 kg carry-on ALWAYS included in base fare
BAG_INCLUDED_AIRLINES = {
    "LH", "AF", "KL", "BA", "IB", "LX", "OS", "SN", "TK",
    "AY", "SK", "TP", "LO", "AZ", "OA", "A3", "KM", "OU",
    "JU", "RO", "FB",
}


def get_bag_cost(airline_iata: str) -> Tuple[float, bool, str]:
    """Return (round_trip_10kg_bag_eur, is_included_in_base_fare, note)."""
    airline = airline_iata.upper().strip()
    if airline in BAG_INCLUDED_AIRLINES:
        return (0.0, True, "10 kg carry-on included in fare")
    info = AIRLINE_BAG_COST.get(airline)
    if info:
        return (info[0], False, info[1])
    # Unknown airline → conservative estimate (most LCCs charge for 10 kg)
    return (24.0, False, "10 kg carry-on — estimated")


# ---------------------------------------------------------------------------
# SANITY BAND — reject or flag quotes far outside historical range
# ---------------------------------------------------------------------------
def is_sane_price(price: float, destination: str, storage=None) -> Tuple[bool, str]:
    """Check if a quote is in a reasonable band for this route.

    Returns (is_sane, reason).
    Rejects: price > 5x the 90-day median (likely parsing bug).
    Flags: price > 3x median (unusual, but possible).
    """
    if price <= 0:
        return (False, "zero_or_negative")
    if price > 3000:
        return (False, "exceeds_max")
    if price < 3:
        return (False, "implausibly_low")

    # Try storage-backed check
    if storage:
        try:
            with storage._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT AVG(total_price)
                    FROM results
                    WHERE destination = ?
                      AND timestamp > datetime('now', '-90 days')
                """, (destination,))
                row = cursor.fetchone()
                if row and row[0] and row[0] > 10:
                    avg = float(row[0])
                    ratio = price / avg
                    if ratio > 5.0:
                        return (False, f"rejected: {ratio:.1f}x route avg EUR {avg:.0f}")
                    if ratio > 3.0:
                        return (True, f"flagged: {ratio:.1f}x route avg")
        except Exception:
            pass

    return (True, "ok")


# ---------------------------------------------------------------------------
# CONSENSUS DEDUP — same airline + price within EUR 1 = same source
# ---------------------------------------------------------------------------
def dedupe_quotes(quotes: list) -> list:
    """Collapse quotes that are the same airline + same price within EUR 1.

    A list of dicts with keys: provider, airline, price.
    Returns deduplicated list.
    """
    seen: set = set()
    result = []
    for q in sorted(quotes, key=lambda x: x.get("price", 0)):
        airline = q.get("airline", "").upper().strip()
        price = round(q.get("price", 0))
        key = (airline, price)
        if key not in seen:
            seen.add(key)
            result.append(q)
    return result


def true_consensus_count(quotes: list) -> int:
    """Number of truly independent sources after dedup."""
    return len(dedupe_quotes(quotes))
