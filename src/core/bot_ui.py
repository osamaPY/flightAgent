"""Pure, testable UI helpers for the Telegram bot (v7).

Everything here is string-in / string-out or plain-data — NO telegram imports,
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
# Airport resolution — friends type "milan", not "BGY"
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
                     codes outside our database — caller decides)
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
            # Plausible IATA outside our DB — pass through as unknown;
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


# ---------------------------------------------------------------------------
# Small formatting atoms
# ---------------------------------------------------------------------------

def eur(v) -> str:
    try:
        return f"€{float(v):,.0f}"
    except (TypeError, ValueError):
        return "€?"


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


def progress_bar(pct: int, width: int = 12) -> str:
    pct = max(0, min(100, int(pct)))
    filled = int(width * pct / 100)
    return "▓" * filled + "░" * (width - filled)


def conf_icon(label: str) -> str:
    return {
        "HIGH": "\U0001f7e2", "MEDIUM": "\U0001f7e1",
        "SINGLE_SOURCE": "\U0001f535", "SINGLE": "\U0001f535",
        "LOW": "⚪",
    }.get(label or "", "⚪")


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
    "europe": "Europe",
    "schengen": "Schengen only",
    "anywhere": "Everywhere",
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
    return f"{mn} night{'s' if mn != 1 else ''}" if mn == mx else f"{mn}–{mx} nights"


def fmt_settings_panel(group_name: str, member_count: int, cfg: dict) -> str:
    """The one-card search setup: all settings visible, launch always 1 tap."""
    return (
        f"\U0001f50d <b>Search — {esc(group_name)}</b>\n"
        f"\U0001f465 {member_count} member{'s' if member_count != 1 else ''}"
        f" · everything below is tap-to-change\n"
        f"──────────────────\n"
        f"\U0001f4c5 <b>Dates</b>  {esc(cfg.get('start', '?'))} → {esc(cfg.get('end', '?'))}\n"
        f"\U0001f319 <b>Nights</b>  {nights_label(cfg)}\n"
        f"\U0001f9f3 <b>Luggage</b>  {LUGGAGE_LABELS.get(cfg.get('luggage'), '?')}\n"
        f"\U0001f686 <b>Transfers</b>  {'included' if cfg.get('transfers', True) else 'flights only'}\n"
        f"✈️ <b>Flights</b>  {'direct only' if cfg.get('direct') else 'any (cheapest)'}\n"
        f"\U0001f30d <b>Where</b>  {SCOPE_LABELS.get(cfg.get('scope'), '?')}\n"
        f"──────────────────\n"
        f"Ready when you are — hit Launch \U0001f680"
    )


# ---------------------------------------------------------------------------
# Results — compact ranked list + per-city detail
# ---------------------------------------------------------------------------

def _grand(r: dict) -> float:
    return float(r.get("grand_total", 0) or r.get("total_price", 0) or 0)


def fmt_results_list(group_name: str, deals: List[dict],
                     page: int = 0, per_page: int = 8) -> Tuple[str, int, int]:
    """Compact ranked city list, one line per deal.

    Returns (text, clamped_page, total_pages).
    """
    if not deals:
        return (f"\U0001f3c6 <b>{esc(group_name)}</b>\n\nNo deals yet.", 0, 1)

    total_pages = max(1, (len(deals) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = deals[page * per_page:(page + 1) * per_page]

    medals = {1: "\U0001f947", 2: "\U0001f948", 3: "\U0001f949"}
    lines = [
        f"\U0001f3c6 <b>Best meetups — {esc(group_name)}</b>",
        f"{len(deals)} cities · all-in per group · tap a city for details",
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
        lines.append(
            f"{badge} {flag} <b>{esc(city)}</b> — <b>{eur(_grand(r))}</b>"
            f" · {n}n · {conf_icon(r.get('confidence_label'))}"
        )
    if total_pages > 1:
        lines += ["", f"page {page + 1}/{total_pages}"]
    return "\n".join(lines), page, total_pages


def fmt_result_detail(r: dict, rank: Optional[int] = None) -> str:
    """Full card for one deal: costs, per-person fairness, dates, links."""
    dest = r.get("destination", "?")
    city = r.get("dest_city") or city_of(dest)
    flag = r.get("dest_flag") or flag_of(dest)
    out, ret = r.get("outbound_date", "?"), r.get("return_date", "?")
    n = nights_of(out, ret)
    total = float(r.get("total_price", 0) or 0)
    grand = _grand(r)
    bag = float(r.get("bag_cost", 0) or 0)
    xfer = float(r.get("transfer_cost", 0) or 0)
    participants = r.get("participants", []) or []

    head = f"{flag} <b>{esc(city)}</b>"
    if rank:
        head = f"#{rank}  " + head

    lines = [
        head,
        f"\U0001f4c5 {esc(out)} → {esc(ret)} · {n} night{'s' if n != 1 else ''}",
        "",
        f"\U0001f4b0 Flights {eur(total)}",
    ]
    if bag > 0:
        lines.append(f"\U0001f9f3 Bags +{eur(bag)}")
    if xfer > 0:
        lines.append(f"\U0001f686 Transfers +{eur(xfer)}")
    lines.append(f"\U0001f48e <b>All-in {eur(grand)}</b>")

    if participants:
        prices = [float(p.get("price", 0) or 0) for p in participants]
        mx = max(prices) if prices and max(prices) > 0 else 1.0
        spread = (max(prices) - min(prices)) if prices else 0
        lines.append("")
        for p in participants:
            price = float(p.get("price", 0) or 0)
            bar = "▓" * max(1, int(price / mx * 8))
            who = esc(p.get("label", "?"))
            origin = esc(p.get("origin", "?"))
            airline = esc(p.get("airline", "") or "")
            suffix = f" · {airline}" if airline else ""
            lines.append(f"{who} · {origin} · {eur(price)}{suffix}\n{bar}")
        fair = ("✅ very fair" if spread < 15
                else ("⚖️ ok" if spread < 50 else "⚠️ uneven"))
        lines.append(f"spread {eur(spread)} — {fair}")

    conf = r.get("confidence_label", "")
    if conf:
        conf_txt = {
            "HIGH": "price confirmed by multiple sources",
            "MEDIUM": "sources disagree a little — verify",
            "SINGLE_SOURCE": "one source only — verify before booking",
            "SINGLE": "one source only — verify before booking",
            "LOW": "weak signal — verify before booking",
        }.get(conf, conf)
        lines += ["", f"{conf_icon(conf)} {conf_txt}"]

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

    if participants:
        links = " · ".join(
            f"<a href=\"{gf_link(p.get('origin', ''), dest, out, ret)}\">"
            f"{esc(p.get('label', '?'))}</a>"
            for p in participants
        )
        lines += ["", f"\U0001f4e4 Book: {links}"]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Progress card
# ---------------------------------------------------------------------------

def fmt_progress(group_name: str, pct: int, city: str,
                 elapsed_s: float, found: Optional[int] = None) -> str:
    eta = ""
    if 0 < pct < 100 and elapsed_s > 5:
        rem = elapsed_s / (pct / 100.0) - elapsed_s
        if rem < 90:
            eta = f" · ~{int(rem)}s left"
        elif rem < 5400:
            eta = f" · ~{int(rem / 60)}min left"
        else:
            eta = f" · ~{rem / 3600:.1f}h left"
    found_line = f"\n\U0001f3c6 {found} deal{'s' if found != 1 else ''} so far" \
        if found else ""
    return (
        f"\U0001f50e <b>Searching — {esc(group_name)}</b>\n\n"
        f"{progress_bar(pct)}  {pct}%{eta}\n"
        f"\U0001f4cd now checking: {esc(city or '…')}{found_line}\n\n"
        f"<i>You can close the chat — I'll ping everyone when it's done.</i>"
    )
