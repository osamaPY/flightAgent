"""Timezone utilities for arrival-time math.

v6: When origins span timezones (London UTC+0, Riga UTC+2, Istanbul UTC+3),
    naive wall-clock subtraction on arrival times is wrong. A 10:00 arrival
    in London and a 12:00 arrival in Riga are literally simultaneous (10:00 UTC
    = 12:00 EET), but naive subtraction shows a 2-hour gap.

This module provides timezone offsets for common European airports and a
UTC-normalized arrival gap computation. For a full worldwide dataset, load
the OurAirports CSV (see docs/ROADMAP.md item 3-2).
"""

import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple

# Timezone offset map for common European airports (hours from UTC).
# Positive = ahead of UTC (EET = +2, CET = +1).
# This is a stopgap — the full OurAirports dataset has timezone per airport.
AIRPORT_UTC_OFFSET: Dict[str, float] = {
    # UK (UTC+0 winter, +1 summer — using summer DST)
    "LHR": 1.0, "LGW": 1.0, "STN": 1.0, "LTN": 1.0, "LCY": 1.0,
    "MAN": 1.0, "EDI": 1.0, "BHX": 1.0, "BRS": 1.0, "GLA": 1.0,

    # Ireland (UTC+1 summer)
    "DUB": 1.0, "ORK": 1.0, "SNN": 1.0,

    # Portugal (UTC+1 summer)
    "LIS": 1.0, "OPO": 1.0, "FAO": 1.0, "FNC": 1.0,

    # Spain / France / Benelux / Germany / Italy / Switzerland / Austria (CEST = UTC+2)
    "BCN": 2.0, "MAD": 2.0, "AGP": 2.0, "PMI": 2.0, "VLC": 2.0,
    "ALC": 2.0, "SVQ": 2.0, "BIO": 2.0, "IBZ": 2.0, "MAH": 2.0,
    "CDG": 2.0, "ORY": 2.0, "BVA": 2.0, "NCE": 2.0, "LYS": 2.0,
    "MRS": 2.0, "TLS": 2.0, "SXB": 2.0, "NTE": 2.0, "BOD": 2.0,
    "AMS": 2.0, "EIN": 2.0, "RTM": 2.0,
    "BRU": 2.0, "CRL": 2.0, "LGG": 2.0,
    "FRA": 2.0, "MUC": 2.0, "BER": 2.0, "DUS": 2.0, "HAM": 2.0,
    "STR": 2.0, "CGN": 2.0, "NUE": 2.0, "HAJ": 2.0, "LEJ": 2.0,
    "BGY": 2.0, "MXP": 2.0, "LIN": 2.0, "FCO": 2.0, "CIA": 2.0,
    "VCE": 2.0, "TSF": 2.0, "BLQ": 2.0, "NAP": 2.0, "CTA": 2.0,
    "PMO": 2.0, "TRN": 2.0, "BRI": 2.0,
    "ZRH": 2.0, "GVA": 2.0, "BSL": 2.0,
    "VIE": 2.0, "SZG": 2.0,

    # Nordics (CEST = UTC+2)
    "CPH": 2.0, "BLL": 2.0, "AAL": 2.0,
    "ARN": 2.0, "GOT": 2.0, "MMX": 2.0,
    "OSL": 2.0, "TRD": 2.0, "BGO": 2.0, "SVG": 2.0,
    "HEL": 3.0,  # EEST = UTC+3

    # Baltics (EEST = UTC+3)
    "RIX": 3.0, "VNO": 3.0, "TLL": 3.0,

    # Poland / Czech / Slovakia / Hungary / Croatia / Slovenia (CEST = UTC+2)
    "WAW": 2.0, "WMI": 2.0, "KRK": 2.0, "GDN": 2.0, "KTW": 2.0, "WRO": 2.0,
    "PRG": 2.0,
    "BTS": 2.0,
    "BUD": 2.0,
    "ZAG": 2.0, "SPU": 2.0, "DBV": 2.0,
    "LJU": 2.0,

    # Romania / Bulgaria / Greece / Cyprus (EEST = UTC+3)
    "OTP": 3.0, "CLJ": 3.0, "TSR": 3.0, "IAS": 3.0,
    # Moldova (EEST = UTC+3)
    "KIV": 3.0, "BZY": 3.0,
    "SOF": 3.0, "VAR": 3.0,
    "ATH": 3.0, "SKG": 3.0, "HER": 3.0, "RHO": 3.0, "CHQ": 3.0,
    "LCA": 3.0, "PFO": 3.0,

    # Turkey (UTC+3 year-round)
    "IST": 3.0, "SAW": 3.0, "AYT": 3.0, "ADB": 3.0, "ESB": 3.0,

    # Malta (CEST = UTC+2)
    "MLA": 2.0,

    # Iceland (UTC+0 year-round)
    "KEF": 0.0,
}


def get_utc_offset(iata: str) -> float:
    """Get UTC offset in hours for an airport. Default 2.0 (CET/CEST)."""
    return AIRPORT_UTC_OFFSET.get(iata.upper(), 2.0)


def normalize_to_utc(arrival_time_str: str, iata: str) -> Optional[datetime]:
    """Convert a local arrival time string to UTC datetime.

    Args:
        arrival_time_str: "YYYY-MM-DD HH:MM" in airport local time
        iata: Airport IATA code for timezone lookup

    Returns:
        UTC datetime, or None if parsing fails
    """
    try:
        local_dt = datetime.strptime(arrival_time_str, "%Y-%m-%d %H:%M")
        offset_hours = get_utc_offset(iata)
        utc_dt = local_dt - timedelta(hours=offset_hours)
        return utc_dt
    except (ValueError, TypeError):
        return None


def compute_arrival_spread(arrivals: list) -> Tuple[float, str]:
    """Compute timezone-correct arrival spread across participants.

    Args:
        arrivals: List of (arrival_time_str, origin_iata) tuples

    Returns:
        (spread_hours, warning_string)
        spread_hours = max_utc - min_utc (timezone-corrected)
        warning_string = "" or description of timezone issues
    """
    utc_times = []
    timezone_issues = []
    offsets_seen = set()

    for arrival_str, iata in arrivals:
        utc = normalize_to_utc(arrival_str, iata)
        if utc:
            utc_times.append(utc)
            offset = get_utc_offset(iata)
            offsets_seen.add(offset)

    if len(utc_times) < 2:
        return (0.0, "")

    utc_times.sort()
    spread = abs((utc_times[-1] - utc_times[0]).total_seconds()) / 3600.0

    warning = ""
    if len(offsets_seen) > 1:
        warning = f"⏰ {len(offsets_seen)} timezones — times shown in local, gap is UTC-corrected"

    return (round(spread, 2), warning)
