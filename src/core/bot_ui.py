"""Pure, testable UI helpers for the Telegram bot (v7).

Everything here is string-in / string-out or plain-data - NO telegram imports,
no Storage, no network. That keeps the whole presentation layer unit-testable
offline (tests/test_bot_ui.py) while telegram_bot.py stays thin glue.

All rendered text is Telegram HTML (parse_mode='HTML'); every user-sourced
string must pass through esc() exactly once, at render time.
"""

from __future__ import annotations

import html
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from src.core.airports import CANDIDATE_DESTINATIONS, Airport


# ---------------------------------------------------------------------------
# Escaping
# ---------------------------------------------------------------------------

def esc(s) -> str:
    """HTML-escape any user-sourced string for parse_mode='HTML'."""
    return html.escape(str(s if s is not None else ""), quote=False)


# ---------------------------------------------------------------------------
# Airport resolution - friends type "milan", not "BGY"
# ---------------------------------------------------------------------------

_IATA_SET = {a.iata for a in CANDIDATE_DESTINATIONS}

# city (lowercase) -> [Airport, ...]
_CITY_INDEX: Dict[str, List[Airport]] = {}
for _a in CANDIDATE_DESTINATIONS:
    _CITY_INDEX.setdefault(_a.city.lower(), []).append(_a)


def resolve_airports(text: str) -> Tuple[List[str], Dict[str, List[Airport]], List[str]]:
    """Parse free-typed airport input: IATA codes AND city names, mixed.

    "BGY, MXP"          -> (["BGY", "MXP"], {}, [])
    "milan"             -> ([], {"Milan": [BGY, MXP, LIN]}, [])   # multi-airport city
    "riga"              -> (["RIX"], {}, [])                       # single-airport city
    "milan, RIX, xyzzy" -> (["RIX"], {"Milan": [...]}, ["XYZZY"])

    Returns:
        resolved:    IATA codes ready to use (explicit codes + unambiguous cities)
        suggestions: multi-airport cities needing a pick/confirm (display name -> airports)
        unknown:     tokens we couldn't understand (may still be valid IATA
                     codes outside our database - caller decides)
    """
    resolved: List[str] = []
    suggestions: Dict[str, List[Airport]] = {}
    unknown: List[str] = []

    for token in (t.strip() for t in text.replace(";", ",").split(",")):
        if not token:
            continue
        up = token.upper()
        low = token.lower()

        if len(up) == 3 and up.isalpha() and up in _IATA_SET:
            if up not in resolved:
                resolved.append(up)
        elif low in _CITY_INDEX:
            airports = _CITY_INDEX[low]
            if len(airports) == 1:
                if airports[0].iata not in resolved:
                    resolved.append(airports[0].iata)
            else:
                suggestions[airports[0].city] = airports
        elif len(up) == 3 and up.isalpha():
            # Plausible IATA outside our DB - pass through as unknown;
            # caller may accept it with a warning (current v6 behavior).
            unknown.append(up)
        else:
            unknown.append(token)

    return resolved, suggestions, unknown


def airport_label(iata: str) -> str:
    """'BGY' -> 'BGY (Milan Bergamo)' when known, else the raw code."""
    a = next((x for x in CANDIDATE_DESTINATIONS if x.iata == iata), None)
    return f"{iata} ({a.name})" if a else iata


def city_of(iata: str) -> str:
    a = next((x for x in CANDIDATE_DESTINATIONS if x.iata == iata), None)
    return a.city if a else iata


def flag_of(iata: str) -> str:
    a = next((x for x in CANDIDATE_DESTINATIONS if x.iata == iata), None)
    return a.flag if a else "\U0001f4cd"


def country_of(iata: str) -> str:
    a = next((x for x in CANDIDATE_DESTINATIONS if x.iata == iata), None)
    return a.country if a else ""


# ---------------------------------------------------------------------------
# Small formatting atoms
# ---------------------------------------------------------------------------

def eur(v) -> str:
    try:
        return f"\u20ac{float(v):,.0f}"
    except (TypeError, ValueError):
        return "\u20ac?"


def nights_of(out: str, ret: str) -> int:
    try:
        return (datetime.strptime(ret, "%Y-%m-%d")
                - datetime.strptime(out, "%Y-%m-%d")).days
    except Exception:
        return 0


def fmt_date(d: str) -> str:
    """'2026-08-01' -> 'Aug 1' (compact, human; Windows-safe strftime)."""
    try:
        dt = datetime.strptime(d, "%Y-%m-%d")
        return f"{dt.strftime('%b')} {dt.day}"
    except Exception:
        return d


def fmt_day(d: str) -> str:
    """'2026-08-01' -> 'Fri Aug 1' (weekday-aware; Windows-safe)."""
    try:
        dt = datetime.strptime(d, "%Y-%m-%d")
        return f"{dt.strftime('%a')} {dt.strftime('%b')} {dt.day}"
    except Exception:
        return d


def fmt_datetime(s: str) -> str:
    """'2026-08-07 14:30' -> 'Fri Aug 7, 14:30' (Windows-safe)."""
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M")
        return f"{dt.strftime('%a')} {dt.strftime('%b')} {dt.day}, {dt.strftime('%H:%M')}"
    except Exception:
        return s


def _fmt_dur(minutes: float) -> str:
    m = int(round(minutes))
    h, mm = divmod(m, 60)
    return f"{h}h{mm:02d}m" if h else f"{mm}m"


def journey_duration(dep_local: str, dep_iata: str,
                     arr_local: str, arr_iata: str) -> str:
    """Total travel time from origin departure to destination arrival, made
    timezone-correct with the airport offset map. Empty string if we can't be
    sure (unknown timezone or unparseable times). For a connecting flight this
    total includes the waiting/layover time."""
    try:
        from src.core.timezone_utils import AIRPORT_UTC_OFFSET
        do = AIRPORT_UTC_OFFSET.get((dep_iata or "").upper())
        ao = AIRPORT_UTC_OFFSET.get((arr_iata or "").upper())
        if do is None or ao is None:
            return ""
        d = datetime.strptime(dep_local[:16], "%Y-%m-%d %H:%M") - timedelta(hours=do)
        a = datetime.strptime(arr_local[:16], "%Y-%m-%d %H:%M") - timedelta(hours=ao)
        mins = (a - d).total_seconds() / 60.0
        if mins <= 0 or mins > 60 * 48:
            return ""
        return _fmt_dur(mins)
    except Exception:
        return ""


def fmt_arrivals(participants: List[dict]) -> List[str]:
    """Landing coordination: who lands when (all at the same destination, so
    same timezone), each person's gap after the first, and the total spread."""
    rows = []
    for p in participants:
        t = p.get("arrival_time") or ""
        try:
            dt = datetime.strptime(t[:16], "%Y-%m-%d %H:%M")
        except Exception:
            continue
        rows.append((dt, p.get("label", "?")))
    if len(rows) < 2:
        return []
    rows.sort(key=lambda x: x[0])
    first = rows[0][0]
    out = ["", "\U0001f6ec <b>Landing times</b> (same airport)"]
    for dt, who in rows:
        gap = (dt - first).total_seconds() / 60.0
        when = f"{dt.strftime('%a')} {dt.strftime('%b')} {dt.day}, {dt.strftime('%H:%M')}"
        tail = "" if gap < 1 else f" (+{_fmt_dur(gap)} after the first)"
        out.append(f"• {esc(who)} - {when}{tail}")
    spread = (rows[-1][0] - first).total_seconds() / 60.0
    if spread < 1:
        out.append("Everyone lands together.")
    else:
        out.append(f"Whole group lands within {_fmt_dur(spread)}.")
    return out


def progress_bar(pct: int, width: int = 12) -> str:
    pct = max(0, min(100, int(pct)))
    filled = int(width * pct / 100)
    return "\u2593" * filled + "\u2591" * (width - filled)


def conf_icon(label: str) -> str:
    return {
        "HIGH": "\U0001f7e2", "MEDIUM": "\U0001f7e1",
        "SINGLE_SOURCE": "\U0001f535", "SINGLE": "\U0001f535",
        "LOW": "\u26aa",
    }.get(label or "", "\u26aa")


def gf_link(origin: str, dest: str, out: str, ret: str) -> str:
    return (f"https://www.google.com/travel/flights?q=Flights%20from%20"
            f"{origin}%20to%20{dest}%20on%20{out}%20through%20{ret}")


# ---------------------------------------------------------------------------
# Search settings panel
# ---------------------------------------------------------------------------

LUGGAGE_LABELS = {
    "carryon_10kg": "10kg cabin bag",
    "checked_23kg": "23kg checked bag",
    "none": "personal item only",
}
SCOPE_LABELS = {
    "europe": "Anywhere in Europe",
    "schengen": "Schengen countries only",
    "anywhere": "All cities we cover",
}


def default_search_config() -> dict:
    """Smart defaults: next month, 2-4 nights, 10kg, transfers, any, Europe."""
    today = datetime.now()
    return {
        "start": (today + timedelta(days=14)).strftime("%Y-%m-%d"),
        "end": (today + timedelta(days=42)).strftime("%Y-%m-%d"),
        "min_n": 2, "max_n": 4,
        "luggage": "carryon_10kg",
        "transfers": True,
        "direct": False,
        "scope": "europe",
    }


def nights_label(cfg: dict) -> str:
    mn, mx = cfg.get("min_n", 2), cfg.get("max_n", 4)
    return f"{mn} night{'s' if mn != 1 else ''}" if mn == mx else f"{mn}-{mx} nights"


def fmt_settings_panel(group_name: str, member_count: int, cfg: dict) -> str:
    """The one-card search setup: all settings visible, launch always 1 tap."""
    rule = "\u2500" * 18
    members = f"{member_count} member{'s' if member_count != 1 else ''}"
    transfers = "included" if cfg.get("transfers", True) else "flights only"
    flights = "direct only" if cfg.get("direct") else "any (cheapest)"
    lines = [
        f"\U0001f50d <b>Search - {esc(group_name)}</b>",
        f"\U0001f465 {members} \u00b7 everything below is tap-to-change",
        rule,
        f"\U0001f4c5 <b>Dates</b>  {esc(cfg.get('start', '?'))} \u2192 {esc(cfg.get('end', '?'))}",
        f"\U0001f319 <b>Nights</b>  {nights_label(cfg)}",
        f"\U0001f9f3 <b>Luggage</b>  {LUGGAGE_LABELS.get(cfg.get('luggage'), '?')}",
        f"\U0001f686 <b>Transfers</b>  {transfers}",
        f"\u2708\ufe0f <b>Flights</b>  {flights}",
        f"\U0001f30d <b>Where</b>  {SCOPE_LABELS.get(cfg.get('scope'), '?')}",
        rule,
        "Ready when you are - hit Launch \U0001f680",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Results - compact ranked list + per-city detail
# ---------------------------------------------------------------------------

def _grand(r: dict) -> float:
    return float(r.get("grand_total", 0) or r.get("total_price", 0) or 0)


def _source_label(value: str) -> str:
    value = str(value or "").replace("_", " ").replace("+", " + ").strip()
    if not value:
        return "source unknown"
    names = {
        "ryanair": "Ryanair",
        "ryanair calendar": "Ryanair calendar",
        "google": "Google Flights",
        "google scraper": "Google Flights",
        "google multimode": "Google Flights",
        "google calendar": "Google calendar",
        "amadeus": "Amadeus",
        "duffel": "Duffel",
    }
    return names.get(value.lower(), value)


def _stops_label(stops) -> str:
    try:
        n = int(stops or 0)
    except Exception:
        n = 0
    return "direct" if n == 0 else f"{n} stop{'s' if n != 1 else ''}"


def _person_total(p: dict) -> float:
    return (
        float(p.get("price", 0) or 0)
        + float(p.get("bag_cost", 0) or 0)
        + float(p.get("transfer_cost", 0) or 0)
    )


def _people_count(r: dict) -> int:
    parts = r.get("participants") or []
    return len(parts) or int(r.get("people_count", 0) or 0)


def _per_person(r: dict) -> float:
    """Average all-in cost per traveller."""
    n = _people_count(r)
    return _grand(r) / n if n else _grand(r)


def _connection_note(participants: List[dict]) -> str:
    """'all direct' / '1 with a stop' summary across the whole group."""
    if not participants:
        return ""
    stopped = sum(1 for p in participants if int(p.get("stops", 0) or 0) > 0)
    if stopped == 0:
        return "all direct"
    if stopped == len(participants):
        return "all have a stop"
    return f"{stopped} with a stop"


def _fairness(spread: float) -> str:
    if spread < 15:
        return "✅ very even"
    if spread < 50:
        return "⚖️ a bit uneven"
    return "⚠️ uneven - one person pays a lot more"


def _receipt_row(label: str, amount, width: int = 22) -> str:
    """One monospace receipt line: label left, amount right (space padded)."""
    money = eur(amount)
    pad = max(1, width - len(label) - len(money))
    return f"{label}{' ' * pad}{money}"


CONF_TEXT = {
    "HIGH": "price confirmed by multiple sources",
    "MEDIUM": "sources disagree a little - verify before booking",
    "SINGLE_SOURCE": "seen at one source only - verify before booking",
    "SINGLE": "seen at one source only - verify before booking",
    "LOW": "weak signal - verify before booking",
}


def fmt_results_list(group_name: str, deals: List[dict],
                     page: int = 0, per_page: int = 5) -> Tuple[str, int, int]:
    """Ranked city list: a rich but scannable block per deal.

    Returns (text, clamped_page, total_pages).
    """
    if not deals:
        return (f"\U0001f3c6 <b>{esc(group_name)}</b>\n\nNo deals yet.", 0, 1)

    total_pages = max(1, (len(deals) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = deals[page * per_page:(page + 1) * per_page]

    medals = {1: "\U0001f947", 2: "\U0001f948", 3: "\U0001f949"}
    lines = [
        f"\U0001f3c6 <b>Best meetups - {esc(group_name)}</b>",
        f"{len(deals)} cities ranked by all-in group cost \u00b7 "
        f"tap one for the full breakdown",
        "",
    ]
    for i, r in enumerate(chunk):
        rank = page * per_page + i + 1
        badge = medals.get(rank, f"{rank}.")
        dest = r.get("destination", "?")
        city = r.get("dest_city") or city_of(dest)
        flag = r.get("dest_flag") or flag_of(dest)
        out, ret = r.get("outbound_date", "?"), r.get("return_date", "?")
        n = nights_of(out, ret)
        grand = _grand(r)
        total = float(r.get("total_price", 0) or 0)
        bag = float(r.get("bag_cost", 0) or 0)
        xfer = float(r.get("transfer_cost", 0) or 0)
        participants = r.get("participants", []) or []
        pp = _per_person(r)
        per_person = " · ".join(
            f"{esc(p.get('label', '?'))} {eur(_person_total(p))}"
            for p in participants[:3]
        )
        if len(participants) > 3:
            per_person += f" · +{len(participants) - 3} more"
        source = _source_label(r.get("source") or (
            participants[0].get("source") if participants else ""
        ))
        conn = _connection_note(participants)
        via = f"via {esc(source)}" + (f" · {conn}" if conn else "")
        lines.append(
            f"{badge} {flag} <b>{esc(city)}</b> - <b>{eur(grand)} all-in</b>"
            f" \u00b7 ~{eur(pp)}pp\n"
            f"   \U0001f4c5 {fmt_date(out)}\u2192{fmt_date(ret)} \u00b7 {n}n"
            f" \u00b7 {conf_icon(r.get('confidence_label'))}\n"
            f"   \U0001f9fe flights {eur(total)} · bags {eur(bag)}"
            f" · transfers {eur(xfer)}\n"
            f"   \U0001f465 {per_person or 'per-person data unavailable'}\n"
            f"   ✈️ {via}"
        )
    if total_pages > 1:
        lines += ["", f"page {page + 1}/{total_pages}"]
    return "\n".join(lines), page, total_pages


def fmt_result_detail(r: dict, rank: Optional[int] = None) -> str:
    """Full receipt for one deal: everything known, per person, structured."""
    dest = r.get("destination", "?")
    city = r.get("dest_city") or city_of(dest)
    flag = r.get("dest_flag") or flag_of(dest)
    country = r.get("dest_country") or country_of(dest)
    out, ret = r.get("outbound_date", "?"), r.get("return_date", "?")
    n = nights_of(out, ret)
    total = float(r.get("total_price", 0) or 0)
    grand = _grand(r)
    bag = float(r.get("bag_cost", 0) or 0)
    xfer = float(r.get("transfer_cost", 0) or 0)
    participants = r.get("participants", []) or []
    people = _people_count(r)
    pp = _per_person(r)
    source = _source_label(r.get("source") or (
        participants[0].get("source") if participants else ""
    ))
    airlines = esc(r.get("flight_airlines", "") or "")
    flight_numbers = esc(r.get("flight_numbers", "") or "")
    arrival_gap = float(r.get("arrival_gap_hours", 0) or 0)
    origins = ", ".join(esc(p.get("origin", "?")) for p in participants)

    where = f"{flag} <b>{esc(city)}</b>"
    if country:
        where += f", {esc(country)}"
    head = (f"#{rank}  " + where) if rank else where

    lines = [
        head,
        f"\U0001f4c5 {fmt_day(out)} → {fmt_day(ret)}"
        f" · {n} night{'s' if n != 1 else ''}",
    ]
    who_line = f"\U0001f465 {people} traveller{'s' if people != 1 else ''}"
    if origins:
        who_line += f" from {origins}"
    lines.append(who_line)
    lines.append(f"\U0001f6ec Airport: <b>{esc(dest)}</b>"
                 f" · \U0001f50e via <b>{esc(source)}</b>")
    if airlines:
        lines.append(f"\u2708\ufe0f Airlines: {airlines}")
    if flight_numbers:
        lines.append(f"\U0001f3ab Flights: {flight_numbers}")
    if r.get("is_approximate"):
        lines.append("\u26a0\ufe0f Calendar/estimated fare - verify before booking")

    receipt = [
        _receipt_row("Flights", total),
        _receipt_row("Bags", bag),
        _receipt_row("Transfers", xfer),
        "─" * 22,
        _receipt_row("All-in total", grand),
    ]
    if people:
        receipt.append(_receipt_row(f"Per person (x{people})", pp))
    lines += [
        "",
        "\U0001f9fe <b>Group receipt</b>",
        "<pre>" + "\n".join(receipt) + "</pre>",
    ]
    per_night = pp / n if n else 0
    if per_night:
        lines.append(f"That is about {eur(per_night)} per person, per night.")

    if participants:
        person_totals = [_person_total(p) for p in participants]
        pool = sum(person_totals) or 1.0
        spread = (max(person_totals) - min(person_totals)) if person_totals else 0
        cheapest = min(range(len(participants)), key=lambda i: person_totals[i])
        priciest = max(range(len(participants)), key=lambda i: person_totals[i])
        lines += ["", "\U0001f3ab <b>Per-person tickets</b>"]
        for idx, p in enumerate(participants):
            price = float(p.get("price", 0) or 0)
            person_bag = float(p.get("bag_cost", 0) or 0)
            person_xfer = float(p.get("transfer_cost", 0) or 0)
            person_total = person_totals[idx]
            share = int(round(person_total / pool * 100))
            who = esc(p.get("label", "?"))
            origin = esc(p.get("origin", "?"))
            airline = esc(p.get("airline", "") or "")
            flight_no = esc(p.get("flight_number", "") or "")
            psource = esc(_source_label(p.get("source") or r.get("source") or ""))
            stops_txt = _stops_label(p.get("stops", 0))
            journey = journey_duration(p.get("departure_time", "") or "",
                                       p.get("origin", ""), p.get("arrival_time", "") or "",
                                       dest)
            if journey:
                stops_txt += f" · {journey} total"
            layover = esc(p.get("layover", "") or "")
            arrival = esc(p.get("arrival_time", "") or "")
            bag_note = "included" if p.get("bag_included") else eur(person_bag)
            route_link = p.get("deep_link") or gf_link(p.get("origin", ""), dest, out, ret)
            tag = ""
            if len(participants) > 1 and idx == cheapest:
                tag = " \U0001f4b8 cheapest"
            elif len(participants) > 1 and idx == priciest:
                tag = " \U0001f4b0 pays most"
            meta = [origin, stops_txt, f"via {psource}"]
            if airline:
                meta.append(f"airline {airline}")
            if flight_no:
                meta.append(f"flight {flight_no}")
            lines.append(
                f"• <b>{who}</b> - <b>{eur(person_total)}</b>"
                f" ({share}% of total){tag}\n"
                f"  fare {eur(price)} · bag {bag_note} · transfer {eur(person_xfer)}\n"
                f"  {' · '.join(meta)}"
            )
            if layover:
                lines.append(f"  connection: {layover}")
            elif int(p.get("stops", 0) or 0) > 0:
                lines.append("  has a stop - check the connection when booking")
            if arrival:
                lines.append(f"  arrives {esc(fmt_datetime(arrival))}")
            lines.append(f"  <a href=\"{route_link}\">Open ticket search</a>")
        lines.append(f"\n\u2696\ufe0f Fairness: {_fairness(spread)} (spread {eur(spread)})")
        arrivals_block = fmt_arrivals(participants)
        if arrivals_block:
            lines += arrivals_block
        elif arrival_gap > 0:
            lines.append(
                f"\U0001f552 Whole group lands within {arrival_gap:.1f}h of each other")

    conf = r.get("confidence_label", "")
    if conf:
        lines += ["", f"{conf_icon(conf)} {CONF_TEXT.get(conf, esc(conf))}"]

    ver = r.get("verification")
    if ver:
        status = str(ver.get("status", "?")).replace("_", " ")
        new_g = float(ver.get("new_grand_total") or 0)
        ts = str(ver.get("verified_at", ""))[:16]
        vline = f"\U0001f50e last check: {esc(status)}"
        if new_g:
            vline += f" at {eur(new_g)}"
        if ts:
            vline += f" ({esc(ts)})"
        lines.append(vline)

    lines += ["", "<i>Always verify the final checkout price before booking.</i>"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Progress card
# ---------------------------------------------------------------------------

def fmt_progress(group_name: str, pct: int, city: str,
                 elapsed_s: float, found: Optional[int] = None,
                 current: Optional[int] = None,
                 total: Optional[int] = None) -> str:
    eta = ""
    if 0 < pct < 100 and elapsed_s > 5:
        rem = elapsed_s / (pct / 100.0) - elapsed_s
        if rem < 90:
            eta = f" \u00b7 ~{int(rem)}s left"
        elif rem < 5400:
            eta = f" \u00b7 ~{int(rem / 60)}min left"
        else:
            eta = f" \u00b7 ~{rem / 3600:.1f}h left"
    found_line = f"\n\U0001f3c6 {found} deal{'s' if found != 1 else ''} so far" \
        if found else ""
    step_line = ""
    if current is not None and total:
        step_line = f"\n{max(0, int(current))}/{max(1, int(total))} checks"
    return (
        f"\U0001f50e <b>Searching - {esc(group_name)}</b>\n\n"
        f"{progress_bar(pct)}  {pct}%{eta}{step_line}\n"
        f"\U0001f4cd now checking: {esc(city or '…')}{found_line}\n\n"
        f"<i>You can close the chat - I'll ping everyone when it's done.</i>"
    )

