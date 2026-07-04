"""v5: iCal export — generate .ics calendar file for a chosen deal.

Usage: python scripts/ical_export.py <result_id>
Saves to data/flight_meetup.ics — importable into Google Calendar, Apple Calendar, Outlook.
"""

import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import src.utils.compat  # noqa

from src.core.storage import Storage
from src.core.airports import CANDIDATE_DESTINATIONS


ICAL_TEMPLATE = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Flight Meet Agent//flight_optimizer//EN
CALSCALE:GREGORIAN
METHOD:PUBLISH
BEGIN:VEVENT
DTSTART;VALUE=DATE:{dtstart}
DTEND;VALUE=DATE:{dtend}
SUMMARY:{summary}
DESCRIPTION:{description}
LOCATION:{location}
TRANSP:OPAQUE
END:VEVENT
END:VCALENDAR"""


def _city(iata: str) -> str:
    for a in CANDIDATE_DESTINATIONS:
        if a.iata == iata:
            return f"{a.city}, {a.country}"
    return iata


def _fmt_date(date_str: str) -> str:
    """2026-07-25 → 20260725"""
    return date_str.replace("-", "")


def export_deal(result_id: int, output_path: str = "data/flight_meetup.ics"):
    storage = Storage()
    with storage._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT destination, total_price, outbound_date, return_date,
                   a_origin, a_price, b_origin, b_price,
                   flight_airlines, flight_numbers, grand_total,
                   hotel_name, hotel_price, confidence_label
            FROM results WHERE id = ?
        """, (result_id,))
        row = cursor.fetchone()

    if not row:
        print(f"No result found with id={result_id}")
        return

    (dest, total, out, ret, a_org, a_p, b_org, b_p,
     airlines, flight_nos, grand, h_name, h_price, conf) = row

    dest_name = _city(dest)
    out_dt = datetime.strptime(out, "%Y-%m-%d")
    ret_dt = datetime.strptime(ret, "%Y-%m-%d")
    nights = (ret_dt - out_dt).days

    summary = f"Flight Meet: {dest_name}"
    description = (
        f"Flight Meetup in {dest_name}\\n\\n"
        f"Dates: {out} → {ret} ({nights} nights)\\n"
        f"Person A ({a_org}): EUR {a_p:.0f}\\n"
        f"Person B ({b_org}): EUR {b_p:.0f}\\n"
        f"Total flights: EUR {total:.0f}\\n"
        f"Grand total: EUR {grand or total:.0f}\\n"
        f"Airlines: {airlines or 'various'}\\n"
        f"Confidence: {conf or 'N/A'}\\n"
    )
    if h_name:
        description += f"Hotel: {h_name} (~EUR {h_price:.0f}/night)\\n"

    ical = ICAL_TEMPLATE.format(
        dtstart=_fmt_date(out),
        dtend=_fmt_date((ret_dt + timedelta(days=1)).strftime("%Y-%m-%d")),
        summary=summary,
        description=description,
        location=f"{dest} — {dest_name}",
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ical)
    print(f"iCal saved to {output_path}")
    print(f"  {summary}")
    print(f"  {out} → {ret}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Show latest deal
        storage = Storage()
        with storage._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM results ORDER BY timestamp DESC LIMIT 1"
            )
            row = cursor.fetchone()
        if row:
            print(f"Latest result ID: {row[0]}")
            print(f"Usage: python scripts/ical_export.py {row[0]}")
        else:
            print("No results. Run a search first.")
    else:
        export_deal(int(sys.argv[1]))
