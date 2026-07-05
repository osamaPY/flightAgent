"""Offline tests for the v7 bot UI helpers (src/core/bot_ui.py).

Pure string/data tests - no telegram, no network, no DB.
Run:  python -m pytest tests/test_bot_ui.py -q
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import src.utils.compat  # noqa

from src.core import bot_ui as ui


# ---------------------------------------------------------------------------
# esc()
# ---------------------------------------------------------------------------

def test_esc_hostile_group_name():
    assert ui.esc("<b>Crew</b> & _friends_*") == "&lt;b&gt;Crew&lt;/b&gt; &amp; _friends_*"


def test_esc_none_and_numbers():
    assert ui.esc(None) == ""
    assert ui.esc(42) == "42"


# ---------------------------------------------------------------------------
# resolve_airports()
# ---------------------------------------------------------------------------

def test_resolve_plain_iata_codes():
    resolved, sugg, unknown = ui.resolve_airports("BGY, MXP")
    assert resolved == ["BGY", "MXP"]
    assert sugg == {} and unknown == []


def test_resolve_city_multi_airport_suggests():
    resolved, sugg, unknown = ui.resolve_airports("milan")
    assert resolved == []
    assert "Milan" in sugg
    assert {a.iata for a in sugg["Milan"]} >= {"BGY", "MXP", "LIN"}
    assert unknown == []


def test_resolve_city_single_airport_resolves():
    resolved, sugg, unknown = ui.resolve_airports("riga")
    assert resolved == ["RIX"]
    assert sugg == {} and unknown == []


def test_resolve_mixed_input():
    resolved, sugg, unknown = ui.resolve_airports("Milan, RIX, xyzzy, QQQ")
    assert resolved == ["RIX"]
    assert "Milan" in sugg
    assert "QQQ" in unknown          # plausible IATA outside DB - passthrough
    assert "xyzzy" in unknown


def test_resolve_case_and_spacing_forgiving():
    resolved, _, _ = ui.resolve_airports("  bgy ,RIX ")
    assert resolved == ["BGY", "RIX"]


def test_resolve_dedups():
    resolved, _, _ = ui.resolve_airports("BGY, bgy, riga, RIX")
    assert resolved == ["BGY", "RIX"]


# ---------------------------------------------------------------------------
# Formatting atoms
# ---------------------------------------------------------------------------

def test_eur_and_nights():
    assert ui.eur(214.5) == "€214" or ui.eur(214.5) == "€215"  # rounding display
    assert ui.eur(None) == "€?"
    assert ui.nights_of("2026-08-01", "2026-08-04") == 3
    assert ui.nights_of("bad", "worse") == 0


def test_fmt_date_windows_safe():
    assert ui.fmt_date("2026-08-01") == "Aug 1"
    assert ui.fmt_date("garbage") == "garbage"


def test_progress_bar_bounds():
    assert ui.progress_bar(0) == "░" * 12
    assert ui.progress_bar(100) == "▓" * 12
    assert ui.progress_bar(-5) == "░" * 12
    assert ui.progress_bar(250) == "▓" * 12
    assert len(ui.progress_bar(50)) == 12


def test_default_config_shape():
    cfg = ui.default_search_config()
    assert set(cfg) == {"start", "end", "min_n", "max_n",
                        "luggage", "transfers", "direct", "scope"}
    assert cfg["luggage"] == "carryon_10kg"
    assert cfg["scope"] == "europe"
    assert cfg["start"] < cfg["end"]


# ---------------------------------------------------------------------------
# Settings panel
# ---------------------------------------------------------------------------

def test_settings_panel_renders_all_settings():
    cfg = ui.default_search_config()
    text = ui.fmt_settings_panel("Weekend <Crew>", 3, cfg)
    assert "Weekend &lt;Crew&gt;" in text          # escaped
    assert "Dates" in text and "Nights" in text
    assert "10kg cabin bag" in text
    assert "included" in text
    assert "any (cheapest)" in text
    assert "Europe" in text
    assert "3 members" in text


def test_settings_panel_renders_schengen_scope_label():
    cfg = ui.default_search_config()
    cfg["scope"] = "schengen"
    text = ui.fmt_settings_panel("Crew", 2, cfg)
    assert "Schengen countries only" in text


def test_settings_panel_renders_once_and_stays_short():
    # Regression: implicit string concatenation used to make "─" * 18 repeat
    # the whole panel 18x, blowing past Telegram's 4096-char limit.
    cfg = ui.default_search_config()
    text = ui.fmt_settings_panel("nerds trip", 2, cfg)
    assert text.count("Search - nerds trip") == 1
    assert text.count("🌍 <b>Where</b>") == 1
    assert text.count("─" * 18) == 2          # exactly the two divider rows
    assert len(text) < 1000                   # nowhere near the 4096 limit


def test_nights_label_fixed_vs_range():
    assert ui.nights_label({"min_n": 3, "max_n": 3}) == "3 nights"
    assert ui.nights_label({"min_n": 2, "max_n": 4}) == "2-4 nights"


# ---------------------------------------------------------------------------
# Results rendering
# ---------------------------------------------------------------------------

def _deal(dest="VIE", city="Vienna", grand=142.0, total=100.0, **kw):
    d = {
        "destination": dest, "dest_city": city, "dest_flag": "🇦🇹",
        "total_price": total, "grand_total": grand,
        "outbound_date": "2026-08-03", "return_date": "2026-08-06",
        "confidence_label": "HIGH",
        "participants": [
            {"label": "You", "origin": "BGY", "price": 60.0, "airline": "FR"},
            {"label": "Sara", "origin": "RIX", "price": 40.0, "airline": "BT"},
        ],
    }
    d.update(kw)
    return d


def test_results_list_medals_and_pagination():
    deals = [_deal(city=f"City{i}", grand=100 + i) for i in range(10)]
    text, page, total_pages = ui.fmt_results_list("Crew", deals, page=0)
    assert "\U0001f947" in text                     # gold medal on #1
    assert total_pages == 2
    text2, page2, _ = ui.fmt_results_list("Crew", deals, page=99)
    assert page2 == 1                                # clamped
    assert "9." in text2 or "10." in text2


def test_results_list_empty():
    text, page, tp = ui.fmt_results_list("Crew", [])
    assert "No deals yet" in text and tp == 1


def test_results_list_shows_rich_breakdown():
    text, _, _ = ui.fmt_results_list(
        "Crew", [_deal(bag_cost=40.0, transfer_cost=24.0)])
    assert "€142 all-in" in text
    assert "pp" in text                              # per-person headline
    assert "flights" in text and "bags €40" in text and "transfers €24" in text
    assert "You €60" in text and "Sara €40" in text  # per-person preview
    assert "all direct" in text                      # connection summary


def test_result_detail_cheapest_and_pays_most_tags():
    text = ui.fmt_result_detail(_deal())
    assert "cheapest" in text                         # Sara at €40
    assert "pays most" in text                        # You at €60


def test_result_detail_per_night_line():
    # 3 nights, €142 all-in, 2 people -> ~€71pp -> ~€23/night each
    text = ui.fmt_result_detail(_deal())
    assert "per person, per night" in text


def test_result_detail_full_card():
    text = ui.fmt_result_detail(_deal(bag_cost=40.0, transfer_cost=24.0), rank=1)
    assert "Vienna" in text
    assert "Group receipt" in text
    assert "All-in total" in text and "€142" in text
    assert "Bags" in text and "€40" in text
    assert "Transfers" in text and "€24" in text
    assert "Per person" in text and "€71" in text     # 142 / 2 travellers
    assert "2 travellers" in text
    assert "Per-person tickets" in text
    assert "fare €60" in text
    assert "% of total" in text                       # per-person share
    assert "You" in text and "Sara" in text
    assert "Fairness" in text and "spread €20" in text
    assert "confirmed by multiple sources" in text
    assert "Open ticket search" in text
    assert "google.com/travel/flights" in text       # booking links


def test_result_detail_escapes_participant_labels():
    d = _deal()
    d["participants"][0]["label"] = "<script>"
    text = ui.fmt_result_detail(d)
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


def test_result_detail_verification_line():
    d = _deal(verification={"status": "price_up", "new_grand_total": 155.0,
                            "verified_at": "2026-07-05T10:00"})
    text = ui.fmt_result_detail(d)
    assert "last check: price up" in text
    assert "€155" in text


# ---------------------------------------------------------------------------
# Progress card
# ---------------------------------------------------------------------------

def test_progress_card_eta_and_escape():
    text = ui.fmt_progress("Crew & <Co>", 50, "Vienna", elapsed_s=60, found=3)
    assert "50%" in text
    assert "~60s left" in text or "~1min left" in text
    assert "Crew &amp; &lt;Co&gt;" in text
    assert "3 deals so far" in text


def test_progress_card_no_eta_at_zero():
    text = ui.fmt_progress("Crew", 0, "", elapsed_s=1)
    assert "left" not in text


def test_progress_card_step_counts():
    text = ui.fmt_progress("Crew", 1, "Tirana", elapsed_s=2,
                           current=7, total=500)
    assert "7/500 checks" in text
    assert "now checking: Tirana" in text
