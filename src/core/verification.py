"""Live deal verification and local fare intelligence.

This module is intentionally provider-agnostic and shared by Telegram/API.
It rechecks one saved itinerary live, records what it saw, and returns a
human-readable status instead of trusting stale search output.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from src.core.provider_factory import (
    build_guest_providers,
    build_owner_providers,
    duffel_under_budget,
    record_duffel_call,
)
from src.core.scoring import Flight, score_group_meetup
from src.core.storage import Storage


VERIFY_TIMEOUT_SECONDS = 18


def _search_live_one(
    storage: Storage,
    providers: list,
    origin: str,
    destination: str,
    out_date: str,
    ret_date: str,
) -> Optional[Flight]:
    """Query providers directly for one exact route/date, bypassing cache."""
    best: Optional[Flight] = None
    for provider in providers:
        if not provider.is_healthy():
            continue
        try:
            if provider.name() == "Duffel" and not duffel_under_budget():
                continue

            result = provider.search_round_trip(
                origin, destination, out_date, out_date, ret_date, ret_date
            )
            if provider.name() == "Duffel" and result:
                record_duffel_call()

            if not result or result.price <= 0:
                continue
            if result.outbound_date != out_date or result.return_date != ret_date:
                continue

            storage.save_provider_quote(provider.name(), result)
            storage.save_price_observation(
                provider.name(),
                result,
                "live_verify",
                is_live=True,
                is_bookable=provider.name() == "Duffel",
            )
            if best is None or result.price < best.price:
                best = result
        except Exception:
            continue
    return best


def verify_result(
    storage: Storage,
    result_id: int,
    include_duffel: bool = False,
) -> Dict[str, Any]:
    """Live re-verify a saved meetup result.

    Args:
        storage: app storage.
        result_id: row ID from `results`.
        include_duffel: owner-only; lets verification use paid Duffel.
    """
    saved = storage.get_result(result_id)
    if not saved:
        return {"ok": False, "status": "missing", "message": "Result not found."}

    search = storage.get_search(saved.get("search_id", "")) if saved.get("search_id") else None
    luggage = (search or {}).get("luggage", "carryon_10kg")
    include_transfers = bool((search or {}).get("include_transfers", 1))

    providers = (
        build_owner_providers(storage)
        if include_duffel else
        build_guest_providers(storage)
    )

    destination = saved["destination"]
    out_date = saved["outbound_date"]
    ret_date = saved["return_date"]
    participants = saved.get("participants", [])
    if len(participants) < 2:
        return {
            "ok": False,
            "status": "unverifiable",
            "message": "Result has no participant breakdown.",
        }

    live_flights: List[Flight] = []
    failures = []
    for participant in participants:
        origin = participant.get("origin", "")
        flight = _search_live_one(
            storage, providers, origin, destination, out_date, ret_date
        )
        if flight:
            live_flights.append(flight)
        else:
            failures.append(participant.get("label") or origin)

    old_total = float(saved.get("total_price") or 0)
    old_grand = float(saved.get("grand_total") or old_total)

    if failures or len(live_flights) != len(participants):
        event = {
            "status": "not_found",
            "old_total": old_total,
            "new_total": 0,
            "old_grand_total": old_grand,
            "new_grand_total": 0,
            "delta": 0,
            "confidence_label": "UNAVAILABLE",
            "details": {
                "verified_at": datetime.now().isoformat(timespec="seconds"),
                "missing": failures,
                "provider_count": len(providers),
            },
        }
        storage.save_verification_event(result_id, event)
        return {
            "ok": False,
            "status": "not_found",
            "message": "Live verification could not find every participant flight.",
            **event,
        }

    labels = [p.get("label", f"Person {i+1}") for i, p in enumerate(participants)]
    fresh = score_group_meetup(
        live_flights,
        labels,
        nights=int(saved.get("nights") or 2),
        storage=storage,
        luggage=luggage,
        include_transfers=include_transfers,
    )

    if not fresh:
        event = {
            "status": "failed_scoring",
            "old_total": old_total,
            "new_total": 0,
            "old_grand_total": old_grand,
            "new_grand_total": 0,
            "delta": 0,
            "confidence_label": "UNAVAILABLE",
            "details": {"verified_at": datetime.now().isoformat(timespec="seconds")},
        }
        storage.save_verification_event(result_id, event)
        return {"ok": False, "message": "Live flights failed scoring.", **event}

    new_total = float(fresh.total_price)
    new_grand = float(fresh.grand_total or fresh.total_price)
    delta = round(new_grand - old_grand, 2)
    abs_delta = abs(delta)
    if abs_delta <= 5:
        status = "still_available"
    elif delta > 0:
        status = "price_increased"
    else:
        status = "price_dropped"

    confidence = "HIGH" if include_duffel and any(
        p.source == "Duffel" for p in fresh.participants
    ) else "LIVE"
    details = {
        "verified_at": datetime.now().isoformat(timespec="seconds"),
        "participants": [p.to_dict() for p in fresh.participants],
        "providers_used": sorted({p.source for p in fresh.participants if p.source}),
        "luggage": luggage,
        "include_transfers": include_transfers,
    }
    event = {
        "status": status,
        "old_total": old_total,
        "new_total": new_total,
        "old_grand_total": old_grand,
        "new_grand_total": new_grand,
        "delta": delta,
        "confidence_label": confidence,
        "details": details,
    }
    storage.save_verification_event(result_id, event)
    return {"ok": True, "result": fresh.to_dict(), **event}


def fare_intelligence(storage: Storage, origin: str = "", destination: str = "") -> dict:
    """Small local analytics snapshot from the owned fare warehouse."""
    stats = storage.get_price_observation_stats(
        origin=origin.upper() if origin else "",
        destination=destination.upper() if destination else "",
    )
    if not stats.get("count"):
        return {
            "count": 0,
            "summary": "No local fare history yet. Run searches/nightly_surface first.",
            "stats": stats,
        }
    median = stats.get("median") or 0
    p25 = stats.get("p25") or 0
    p75 = stats.get("p75") or 0
    return {
        "count": stats["count"],
        "summary": (
            f"{stats['count']} observations; median EUR {median:.0f}, "
            f"middle band EUR {p25:.0f}-{p75:.0f}."
        ),
        "stats": stats,
    }
