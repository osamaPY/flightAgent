import concurrent.futures
from datetime import datetime
from typing import Any, Dict, List, Optional

# Polyfill imghdr for Python 3.13+
import src.utils.compat  # noqa: F401

from fastapi import FastAPI, HTTPException, Query

from main import get_best_flight
from src.core.airports import is_schengen_airport
from src.core.provider_factory import build_providers
from src.core.providers import FlightProvider
from src.core.scoring import Flight
from src.core.storage import Storage
from src.core.verification import fare_intelligence, verify_result


app = FastAPI(
    title="Flight Optimizer API v6",
    description="Multi-user flight meetup search API. Provider endpoints, group management, share links.",
    version="6.0.0",
)

storage = Storage()
providers = build_providers(storage)
LEG_TIMEOUT_SECONDS = 25
MATRIX_TIMEOUT_SECONDS = 35


def _flight_to_dict(flight: Optional[Flight]) -> Optional[Dict[str, Any]]:
    if not flight:
        return None
    return {
        "origin": flight.origin,
        "destination": flight.destination,
        "price": float(flight.price),
        "outbound_date": flight.outbound_date,
        "return_date": flight.return_date,
        "stops": int(flight.stops or 0),
        "arrival_time": str(flight.arrival_time),
        "source": flight.source,
        "is_approximate": bool(flight.is_approximate),
    }


def _healthy_providers() -> List[FlightProvider]:
    return [provider for provider in providers if provider.is_healthy()]


def _call_round_trip(provider: FlightProvider, origin: str, destination: str, out_date: str, return_date: str) -> Optional[Flight]:
    cached = storage.get_cached_flight(provider.name(), origin, destination, out_date, return_date)
    if cached:
        storage.save_provider_quote(provider.name(), cached)
        return cached

    result = provider.search_round_trip(origin, destination, out_date, out_date, return_date, return_date)
    if not result:
        return None

    if result.outbound_date != out_date or result.return_date != return_date:
        return None

    storage.set_cached_flight(provider.name(), result)
    storage.save_provider_quote(provider.name(), result)
    return result


def _call_one_way(provider: FlightProvider, origin: str, destination: str, date: str) -> List[Flight]:
    legs = provider.search_one_way(origin, destination, date)
    for leg in legs:
        storage.save_flight_leg(provider.name(), leg)
    return legs


def _collect_completed(future_map: Dict[Any, FlightProvider], timeout_seconds: int) -> tuple:
    done, pending = concurrent.futures.wait(future_map, timeout=timeout_seconds)
    for future in pending:
        future.cancel()
    return done, pending


def _require_known_route(origin: str, destination: str) -> None:
    """v6.1: Ensure airports are known. No longer restricts to Schengen-only."""
    from src.core.airports import get_airport
    blocked = []
    if not get_airport(origin.upper()):
        blocked.append(origin)
    if not get_airport(destination.upper()):
        blocked.append(destination)
    if blocked:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown airports: {', '.join(blocked)}. Use valid IATA codes.",
        )


@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": "Flight Optimizer Local API",
        "endpoints": [
            "/health",
            "/search",
            "/leg",
            "/matrix",
            "/scrape/health",
            "/scrape/leg",
            "/scrape/search",
            "/scrape/matrix",
        ],
    }


@app.get("/health")
def health() -> Dict[str, Any]:
    provider_rows = []
    for provider in providers:
        ok = provider.is_healthy()
        provider_rows.append({
            "provider": provider.name(),
            "ok": ok,
            "reason": "OK" if ok else provider.get_health_reason(),
        })

    return {
        "ok": any(row["ok"] for row in provider_rows),
        "time": datetime.now().isoformat(timespec="seconds"),
        "providers": provider_rows,
    }


@app.get("/leg")
def leg(
    origin: str = Query(..., min_length=3, max_length=3),
    destination: str = Query(..., min_length=3, max_length=3),
    date: str = Query(..., description="YYYY-MM-DD"),
) -> Dict[str, Any]:
    origin = origin.upper()
    destination = destination.upper()
    _require_known_route(origin, destination)
    found: List[Flight] = []
    errors: List[Dict[str, str]] = []

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)
    future_map = {
        executor.submit(_call_one_way, provider, origin, destination, date): provider
        for provider in _healthy_providers()
    }
    done, pending = _collect_completed(future_map, LEG_TIMEOUT_SECONDS)
    for future in done:
        provider = future_map[future]
        try:
            found.extend(future.result())
        except Exception as exc:
            errors.append({"provider": provider.name(), "error": str(exc)})
    for future in pending:
        errors.append({"provider": future_map[future].name(), "error": f"Timed out after {LEG_TIMEOUT_SECONDS}s"})
    executor.shutdown(wait=False, cancel_futures=True)

    clean = [flight for flight in found if flight.price and flight.price > 0]
    clean.sort(key=lambda flight: flight.price)

    return {
        "origin": origin,
        "destination": destination,
        "date": date,
        "count": len(clean),
        "best": _flight_to_dict(clean[0]) if clean else None,
        "legs": [_flight_to_dict(flight) for flight in clean[:50]],
        "errors": errors,
    }


@app.get("/search")
def search(
    origin: str = Query(..., min_length=3, max_length=3),
    destination: str = Query(..., min_length=3, max_length=3),
    out: str = Query(..., description="YYYY-MM-DD"),
    return_date: str = Query(..., alias="return", description="YYYY-MM-DD"),
) -> Dict[str, Any]:
    origin = origin.upper()
    destination = destination.upper()
    _require_known_route(origin, destination)
    best = get_best_flight(storage, [origin], destination, out, return_date, providers)

    return {
        "origin": origin,
        "destination": destination,
        "outbound_date": out,
        "return_date": return_date,
        "best": _flight_to_dict(best),
        "quote_stats": storage.get_quote_stats(origin, destination, out, return_date),
    }


@app.get("/matrix")
def matrix(
    origin: str = Query(..., min_length=3, max_length=3),
    destination: str = Query(..., min_length=3, max_length=3),
    out: str = Query(..., description="YYYY-MM-DD"),
    return_date: str = Query(..., alias="return", description="YYYY-MM-DD"),
) -> Dict[str, Any]:
    origin = origin.upper()
    destination = destination.upper()
    _require_known_route(origin, destination)
    quotes: List[Flight] = []
    errors: List[Dict[str, str]] = []

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)
    future_map = {
        executor.submit(_call_round_trip, provider, origin, destination, out, return_date): provider
        for provider in _healthy_providers()
        if origin != destination
    }
    done, pending = _collect_completed(future_map, MATRIX_TIMEOUT_SECONDS)
    for future in done:
        provider = future_map[future]
        try:
            result = future.result()
            if result and result.price and result.price > 0:
                quotes.append(result)
        except Exception as exc:
            errors.append({"provider": provider.name(), "error": str(exc)})
    for future in pending:
        errors.append({"provider": future_map[future].name(), "error": f"Timed out after {MATRIX_TIMEOUT_SECONDS}s"})
    executor.shutdown(wait=False, cancel_futures=True)

    quotes.sort(key=lambda flight: flight.price)

    return {
        "origin": origin,
        "destination": destination,
        "outbound_date": out,
        "return_date": return_date,
        "best": _flight_to_dict(quotes[0]) if quotes else None,
        "quotes": [_flight_to_dict(flight) for flight in quotes],
        "quote_stats": storage.get_quote_stats(origin, destination, out, return_date),
        "errors": errors,
    }


# ------------------------------------------------------------------
# Direct Airline Scraper endpoints
# ------------------------------------------------------------------

@app.get("/scrape/health")
def scraper_health() -> Dict[str, Any]:
    """Health check for all direct airline scrapers."""
    from src.scrapers.engine import get_engine
    engine = get_engine()
    return {
        "ok": True,
        "time": datetime.now().isoformat(timespec="seconds"),
        "scrapers": engine.health_check(),
    }


@app.get("/scrape/leg")
def scrape_leg(
    origin: str = Query(..., min_length=3, max_length=3),
    destination: str = Query(..., min_length=3, max_length=3),
    date: str = Query(..., description="YYYY-MM-DD"),
) -> Dict[str, Any]:
    """One-way search using ONLY direct airline scrapers (no paid APIs)."""
    origin = origin.upper()
    destination = destination.upper()
    _require_known_route(origin, destination)

    from src.scrapers.engine import get_engine
    engine = get_engine()
    legs = engine.search_one_way(origin, destination, date)

    return {
        "origin": origin,
        "destination": destination,
        "date": date,
        "count": len(legs),
        "best": _flight_to_dict(legs[0]) if legs else None,
        "legs": [_flight_to_dict(f) for f in legs[:50]],
    }


@app.get("/scrape/search")
def scrape_search(
    origin: str = Query(..., min_length=3, max_length=3),
    destination: str = Query(..., min_length=3, max_length=3),
    out: str = Query(..., description="YYYY-MM-DD"),
    return_date: str = Query(..., alias="return", description="YYYY-MM-DD"),
) -> Dict[str, Any]:
    """Round-trip search using ONLY direct airline scrapers (free, no API keys)."""
    origin = origin.upper()
    destination = destination.upper()
    _require_known_route(origin, destination)

    from src.scrapers.engine import get_engine
    engine = get_engine()
    result = engine.search_round_trip(origin, destination, out, return_date)

    return {
        "origin": origin,
        "destination": destination,
        "outbound_date": out,
        "return_date": return_date,
        "best": _flight_to_dict(result),
    }


@app.get("/scrape/matrix")
def scrape_matrix(
    origin: str = Query(..., min_length=3, max_length=3),
    destination: str = Query(..., min_length=3, max_length=3),
    out: str = Query(..., description="YYYY-MM-DD"),
    return_date: str = Query(..., alias="return", description="YYYY-MM-DD"),
) -> Dict[str, Any]:
    """Full matrix: all scrapers queried, prices compared side-by-side."""
    origin = origin.upper()
    destination = destination.upper()
    _require_known_route(origin, destination)

    from src.scrapers.engine import get_engine
    engine = get_engine()
    matrix_data = engine.matrix(origin, destination, out, return_date)

    return {
        "origin": origin,
        "destination": destination,
        "outbound_date": out,
        "return_date": return_date,
        "best": _flight_to_dict(matrix_data["best"]),
        "quotes": [_flight_to_dict(f) for f in matrix_data.get("quotes", [])],
        "provider_count": matrix_data["provider_count"],
        "cheapest": matrix_data["cheapest"],
        "spread": matrix_data["spread"],
        "errors": matrix_data["errors"],
    }


# ═════════════════════════════════════════════════════════════════════════
# v6: Group & Share endpoints
# ═════════════════════════════════════════════════════════════════════════

@app.get("/groups/{group_id}")
def get_group(group_id: str) -> Dict[str, Any]:
    """Get group details including members."""
    group = storage.get_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    members = storage.get_group_members(group_id)
    return {
        "group": group,
        "members": members,
        "member_count": len(members),
    }


@app.get("/groups/{group_id}/searches")
def list_group_searches(group_id: str, limit: int = 20) -> Dict[str, Any]:
    """List searches for a group."""
    group = storage.get_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    searches = storage.list_searches_by_group(group_id, limit=limit)
    return {"group": group, "searches": searches}


@app.get("/searches/{search_id}/results")
def get_search_results(search_id: str) -> Dict[str, Any]:
    """Get ranked results for a completed search."""
    search = storage.get_search(search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")
    results = storage.get_search_results(search_id)
    return {"search": search, "results": results, "count": len(results)}


@app.post("/results/{result_id}/verify")
def verify_saved_result(
    result_id: int,
    include_duffel: bool = Query(False, description="Use paid Duffel if available"),
) -> Dict[str, Any]:
    """Live re-check a saved deal and record the verification event."""
    result = verify_result(storage, result_id, include_duffel=include_duffel)
    if result.get("status") == "missing":
        raise HTTPException(status_code=404, detail="Result not found")
    return result


@app.get("/intelligence/fares")
def fare_history(
    origin: str = Query("", min_length=0, max_length=3),
    destination: str = Query("", min_length=0, max_length=3),
) -> Dict[str, Any]:
    """Local fare-history stats from the append-only observation warehouse."""
    return fare_intelligence(storage, origin=origin, destination=destination)


@app.post("/results/{result_id}/paid-price")
def report_paid_price(
    result_id: int,
    total: float = Query(..., gt=0),
    notes: str = Query("", max_length=500),
) -> Dict[str, Any]:
    """Record what a user actually paid after booking."""
    result = storage.get_result(result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    storage.save_paid_price_report(
        result_id=result_id,
        search_id=result.get("search_id", ""),
        telegram_id="api",
        destination=result["destination"],
        outbound_date=result["outbound_date"],
        return_date=result["return_date"],
        reported_total=total,
        notes=notes,
    )
    return {"ok": True, "result_id": result_id, "reported_total": total}


@app.post("/searches/{search_id}/share")
def create_share(search_id: str) -> Dict[str, Any]:
    """Create a share link for a search's results."""
    search = storage.get_search(search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")
    token = storage.create_share_link(search_id, "api")
    return {"token": token, "url": f"/share/{token}"}


@app.get("/share/{token}")
def view_shared(token: str) -> Dict[str, Any]:
    """Public read-only view of shared results. No auth required."""
    data = storage.get_shared_results(token)
    if not data:
        raise HTTPException(status_code=404, detail="Share link not found or expired")
    return data


@app.get("/share/{token}/html")
def view_shared_html(token: str):
    """Render shared results as a simple HTML page."""
    from fastapi.responses import HTMLResponse
    data = storage.get_shared_results(token)
    if not data:
        raise HTTPException(status_code=404, detail="Share link not found or expired")

    search = data["search"]
    results = data["results"]

    from src.core.airports import CANDIDATE_DESTINATIONS
    iata_to_city = {a.iata: a.city for a in CANDIDATE_DESTINATIONS}
    iata_to_flag = {a.iata: a.flag for a in CANDIDATE_DESTINATIONS}

    rows_html = ""
    for i, r in enumerate(results[:20], 1):
        dest = r["destination"]
        city = iata_to_city.get(dest, dest)
        flag = iata_to_flag.get(dest, "📍")
        grand = r.get("grand_total", 0) or r["total_price"]
        bag = r.get("bag_cost", 0) or 0
        xfer = r.get("transfer_cost", 0) or 0
        out = r["outbound_date"]
        ret = r["return_date"]

        people = ""
        for p in r.get("participants", []):
            people += (
                f'<div style="margin-left:16px;color:#94a3b8">'
                f'{p.get("label","?")}: {p.get("origin","?")} → {dest} '
                f'EUR {p.get("price",0):.0f} ({p.get("airline","")})'
                f'</div>'
            )

        rows_html += f"""
        <div style="background:#1e293b;border-radius:8px;padding:16px;margin:8px 0">
          <strong>#{i}</strong> {flag} <strong>{city}</strong> <code>{dest}</code>
          <br>💰 Flights EUR {r["total_price"]:.0f}
          {" | 🧳 +EUR " + f"{bag:.0f}" if bag > 0 else ""}
          {" | 🚆 +EUR " + f"{xfer:.0f}" if xfer > 0 else ""}
          <strong> = EUR {grand:.0f} all-in</strong>
          <br>📅 {out} → {ret}
          {people}
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Flight Meetup Deals</title>
<style>
  body {{ background:#0f172a; color:#e2e8f0; font-family:system-ui,sans-serif; max-width:800px; margin:0 auto; padding:16px }}
  h1 {{ font-size:1.5rem }}
  a {{ color:#38bdf8 }}
  code {{ background:#334155; padding:1px 4px; border-radius:3px }}
</style>
</head>
<body>
<h1>✈️ Flight Meetup Deals</h1>
<p>📊 {len(results)} deals found · {search.get("depart_earliest","?")} → {search.get("depart_latest","?")}</p>
{rows_html}
<p style="margin-top:24px;color:#64748b;font-size:0.85rem">
  💡 <a href="https://t.me/your_bot">Open in Telegram</a> to create your own search.
</p>
</body>
</html>"""
    return HTMLResponse(content=html)


# ── v6: Root lists new endpoints ──

@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "ok": True,
        "service": "Flight Optimizer API v6",
        "endpoints": {
            "provider": ["/health", "/search", "/leg", "/matrix", "/scrape/health", "/scrape/leg", "/scrape/search", "/scrape/matrix"],
            "groups": ["/groups/{group_id}", "/groups/{group_id}/searches"],
            "searches": ["/searches/{search_id}/results", "/searches/{search_id}/share", "/results/{result_id}/verify", "/results/{result_id}/paid-price"],
            "intelligence": ["/intelligence/fares"],
            "share": ["/share/{token}", "/share/{token}/html"],
        },
    }
