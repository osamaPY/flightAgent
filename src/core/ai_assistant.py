"""AI travel concierge - turns cold result data into a warm, human answer.

Two features, both powered by DeepSeek (src/clients/deepseek_client.py) and
both strictly optional (they return None if the LLM is unavailable so the bot
degrades gracefully):

  recommend_meetup(deals)  → "Which city should we pick?" - reasons over the
                             ACTUAL computed deals and recommends one, with a
                             one-line why. Hard-constrained to the given numbers
                             so it can never invent a price.

  city_vibe(city, nights)  → "What could we do there?" - a short, upbeat trip
                             idea for the destination and trip length. General
                             travel knowledge, clearly labelled as an AI idea.

Design choices that matter for a pricing product:
  * The recommender is fed a compact, factual digest of the real deals and told
    to use ONLY those figures - no fabricated fares, flights, or dates.
  * Results are cached in-process by prompt so repeated taps don't re-bill.
  * Everything is best-effort; callers treat None as "AI not available".
"""

from __future__ import annotations

import hashlib
from typing import List, Dict, Optional

from src.clients.deepseek_client import DeepSeekClient
from src.core.airports import CANDIDATE_DESTINATIONS

# prompt-hash -> response
_CACHE: Dict[str, str] = {}

_iata_meta = {a.iata: a for a in CANDIDATE_DESTINATIONS}


def _client() -> DeepSeekClient:
    return DeepSeekClient()


def available() -> bool:
    return _client().available()


def _cached(key: str) -> Optional[str]:
    return _CACHE.get(key)


def _store(key: str, value: str) -> str:
    _CACHE[key] = value
    return value


def _grand(r: dict) -> float:
    return float(r.get("grand_total", 0) or r.get("total_price", 0) or 0)


def recommend_meetup(deals: List[dict], group_name: str = "",
                     limit: int = 6) -> Optional[str]:
    """Recommend which meetup city to pick, reasoning over real deals only."""
    if not deals:
        return None
    client = _client()
    if not client.available():
        return None

    top = deals[:limit]
    # Build a compact, unambiguous digest the model must reason from.
    lines = []
    for i, r in enumerate(top, 1):
        dest = r.get("destination", "?")
        city = r.get("dest_city") or (_iata_meta.get(dest).city
                                      if dest in _iata_meta else dest)
        parts = r.get("participants", []) or []
        prices = [float(p.get("price", 0) or 0) for p in parts]
        spread = (max(prices) - min(prices)) if prices else 0
        per = ", ".join(f"{p.get('label', '?')} €{float(p.get('price', 0) or 0):.0f}"
                        for p in parts)
        try:
            from datetime import datetime
            n = (datetime.strptime(r.get("return_date", ""), "%Y-%m-%d")
                 - datetime.strptime(r.get("outbound_date", ""), "%Y-%m-%d")).days
        except Exception:
            n = 0
        lines.append(
            f"{i}. {city}: all-in €{_grand(r):.0f} for the group, "
            f"{n} nights, per-person [{per}], fairness spread €{spread:.0f}, "
            f"confidence {r.get('confidence_label', 'n/a')}"
        )
    digest = "\n".join(lines)

    key = "rec:" + hashlib.sha1(digest.encode("utf-8")).hexdigest()
    hit = _cached(key)
    if hit:
        return hit

    system = (
        "You are a concise, upbeat travel assistant helping a group of friends "
        "choose ONE city to meet in. You are given a ranked list of real, "
        "already-computed options with true all-in group costs, per-person "
        "prices, trip length, a fairness 'spread' (smaller = everyone pays "
        "similarly), and a price-confidence label. "
        "Recommend ONE option and briefly say why (cost, fairness, and a touch "
        "of destination appeal). You MAY mention a strong runner-up in one line. "
        "STRICT RULES: use ONLY the numbers provided - never invent prices, "
        "flights, airlines, or dates. Keep it under 90 words. No markdown "
        "headers. Warm and human, like texting a friend."
    )
    user = (f"Group: {group_name or 'our group'}\n\nOptions:\n{digest}\n\n"
            "Which should we pick, and why?")
    out = client.chat(system, user, max_tokens=260, temperature=0.6)
    return _store(key, out) if out else None


_BOT_GUIDE = (
    "You are the friendly in-app help assistant inside a Telegram bot called "
    "Flight Meetup. What the bot does: a group of friends each live in a "
    "different city, and it finds the cheapest European city for them all to "
    "fly to and meet, counting the real cost - flights + bag fees + the "
    "train/bus from the airport into town. "
    "How people use it: 'Make a group', then 'Add a friend' (type their name "
    "and home airport yourself) or 'Invite a friend' (send a link they tap to "
    "join). Then 'Find flights' runs a search with sensible defaults, or 'Pick "
    "dates / options first' lets them choose the dates, number of nights, "
    "luggage, direct-only vs cheapest, and which region. 'See results' shows "
    "cities ranked cheapest-first; tapping a city shows what each person pays "
    "and a button to check the live price before booking. "
    "It only covers destinations in Europe (not other continents yet). "
    "Answer the person like a patient, non-technical friend: simple words, "
    "warm, and SHORT (under 80 words). No markdown headers. If they ask for "
    "something the bot cannot do, say so kindly and suggest the closest thing "
    "it can do. Point them to the exact button to tap when it helps."
)


def ask(question: str, group_context: str = "") -> Optional[str]:
    """Free-text help: answer a user's question about using the bot or their
    trip, in plain simple language. Best-effort; None if the LLM is off."""
    question = (question or "").strip()
    if not question:
        return None
    client = _client()
    if not client.available():
        return None
    user = question
    if group_context:
        user += f"\n\n(their current group: {group_context})"
    out = client.chat(_BOT_GUIDE, user, max_tokens=300, temperature=0.5)
    return out or None


def city_vibe(city: str, country: str = "", nights: int = 3,
              month: str = "") -> Optional[str]:
    """A short, fun 'what to do there' idea for the trip length."""
    client = _client()
    if not client.available():
        return None

    key = "vibe:" + hashlib.sha1(
        f"{city}|{country}|{nights}|{month}".encode("utf-8")).hexdigest()
    hit = _cached(key)
    if hit:
        return hit

    system = (
        "You are a friendly local-in-the-know giving a group of friends a quick "
        "taste of a city for a short trip. Give 3-4 punchy bullet ideas "
        "(neighbourhoods, a food thing, a view/landmark, an evening vibe). "
        "Keep the WHOLE reply under 80 words. Use simple '•' bullets, no "
        "markdown headers. This is inspiration, not booking advice; don't "
        "mention prices or flights."
    )
    where = f"{city}, {country}" if country else city
    when = f" in {month}" if month else ""
    user = f"A group of friends is spending {nights} nights in {where}{when}. Ideas?"
    out = client.chat(system, user, max_tokens=220, temperature=0.85)
    return _store(key, out) if out else None
