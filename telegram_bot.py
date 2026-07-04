"""
Flight Meetup Bot v7.0 - "One card" UI/UX rewrite

Design:
  * The UI is ONE message per chat that navigates like an app: every tap
    EDITS the card in place (no message spam). Screens: Home → Group Hub →
    Search Panel → Progress → Results → City Detail, with Back everywhere.
  * Search setup is a SETTINGS PANEL with smart defaults - launch is 1 tap;
    tap any row to change it. (Replaces the old 6-step linear wizard.)
  * Live progress actually works now: a sync callback from the search thread
    schedules edits on the event loop into the REQUESTER's chat
    (v6 progress was an un-awaited coroutine posting to the owner's chat).
  * Group-friendly: joiners land on the Group Hub with buttons, members can
    type CITY NAMES ("milan") instead of IATA codes, the owner is pinged on
    joins, and EVERY member is pinged when results are ready.
  * All text is HTML with esc() on user content (Markdown injection fixed).
  * Backward compatible: old inline buttons (res_/ver_/paid_/cd_/rp_/
    wizpick_/quick_/newgrp/guide/adm_*) and /results_<id>-style commands
    still route.

Pure rendering helpers live in src/core/bot_ui.py (offline-tested).
"""

import asyncio
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import src.utils.compat  # noqa: F401

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Conflict
from telegram.ext import (
    ApplicationBuilder, CallbackQueryHandler, CommandHandler,
    ContextTypes, MessageHandler, filters,
)
from dotenv import load_dotenv

from src.core import ai_assistant as ai
from src.core import bot_ui as ui
from src.core.bot_ui import esc, eur
from src.core.config import Config
from src.core.logger import log_error, log_info
from src.core.notifier import Notifier
from src.core.provider_factory import build_guest_providers, build_providers
from src.core.search_request import ParticipantGroup, SearchRequest
from src.core.storage import Storage
from src.core.verification import fare_intelligence, verify_result
from main import SEARCH_STOP_EVENT, booking_mode

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
load_dotenv()


# ═══════════════════════════════ HELPERS ═══════════════════════════════

def _tid(u): return str(u.effective_user.id)


def _uname(u):
    uu = u.effective_user
    return uu.username or uu.first_name or str(uu.id)


# Members the owner added by hand (they have no Telegram account) get a
# synthetic id with this prefix. They count in searches but are never messaged.
_MANUAL_PREFIX = "manual_"


def _is_manual(telegram_id) -> bool:
    return str(telegram_id).startswith(_MANUAL_PREFIX)


def _member_name(m) -> str:
    """Display name for a member: label first (set for everyone incl. manual),
    then username, then id."""
    return m.get('label') or m.get('username') or m.get('telegram_id')


def _is_owner(u):
    uid = str(u.effective_user.id)
    aid = str(Config.TELEGRAM_CHAT_ID)
    return uid == aid if (aid and aid != "None") else False


def _ensure_user(u):
    Storage().upsert_user(str(u.effective_user.id),
                          u.effective_user.username or "",
                          u.effective_user.first_name or "")


def _gate():
    return os.getenv("REQUIRE_INVITE_CODE", "0") == "1"


def _allowed(u):
    if not _gate():
        return True
    return Storage().get_user(str(u.effective_user.id)) is not None


def _kb(rows):
    return InlineKeyboardMarkup(rows) if rows else None


async def _show(update, context, text, rows=None):
    """THE core UI primitive: edit the tapped card in place; if that's not
    possible (command entry, message too old), send a fresh card.
    Returns the message that now shows the card."""
    markup = _kb(rows)
    q = update.callback_query
    if q and q.message:
        try:
            await q.message.edit_text(
                text, parse_mode='HTML',
                disable_web_page_preview=True, reply_markup=markup)
            return q.message
        except BadRequest as e:
            if "not modified" in str(e).lower():
                return q.message
            # fall through - send a fresh card
    return await update.effective_message.reply_text(
        text, parse_mode='HTML',
        disable_web_page_preview=True, reply_markup=markup)


def _btn(label, data):
    return InlineKeyboardButton(label, callback_data=data)


HOME_BTN = _btn("🏠 Home", "home")


# ═══════════════════════════════ SCREENS ═══════════════════════════════
# Every screen is a function that builds (text, rows) and calls _show().

async def scr_home(update, context):
    """Home: your groups + create + help. The place Back always leads."""
    _ensure_user(update)
    s = Storage()
    groups = s.list_user_groups(_tid(update))

    if groups:
        text = (
            "✈️ <b>Flight Meetup</b>\n"
            "Pick a group - or create a new one.\n"
        )
        rows = []
        for g in groups[:8]:
            n = len(s.get_group_members(g['id']))
            rows.append([_btn(f"✈️ {g['name']}  ·  {n} member{'s' if n != 1 else ''}",
                              f"hub_{g['id']}")])
    else:
        text = (
            "✈️ <b>Flight Meetup</b>\n\n"
            "Find the cheapest &amp; fairest city for you and your friends "
            "to meet - flights, bags and transfers all included in one "
            "true price.\n\n"
            "① Create a group\n"
            "② Friends join with one tap\n"
            "③ Launch a search - I do the rest\n"
        )
        rows = []

    action = [_btn("➕ New group", "newgrp"), _btn("❓ How it works", "help")]
    rows.append(action)
    if _is_owner(update):
        rows.append([_btn("🛡 Admin", "adm_dash")])
    await _show(update, context, text, rows)


async def scr_hub(update, context, gid):
    """Group Hub - the centerpiece: members, status, all actions."""
    s = Storage()
    g = s.get_group(gid)
    if not g:
        await _show(update, context, "❌ That group no longer exists.",
                    [[HOME_BTN]])
        return
    members = s.get_group_members(gid)
    me = _tid(update)

    lines = [f"✈️ <b>{esc(g['name'])}</b>", ""]
    for m in members:
        if m['telegram_id'] == me:
            who = "You"
        else:
            who = esc(_member_name(m))
            if _is_manual(m['telegram_id']):
                who += " <i>(added by you)</i>"
        lines.append(f"👤 {who} - {esc(', '.join(m['origins']))}")
    if len(members) < 2:
        lines += ["", "💡 Add a friend's airports below (or invite them) "
                      "so we have at least 2 people to search for."]

    searches = s.list_searches_by_group(gid, limit=1)
    if searches:
        sr = searches[0]
        icon = {"running": "🔍", "completed": "✅"}.get(sr['status'], "·")
        lines += ["", f"{icon} Last search: {sr['status']}"
                      f" · {sr.get('result_count', 0)} deals"]

    manual_count = sum(1 for m in members if _is_manual(m['telegram_id']))
    rows = [
        [_btn("🚀 Search now", f"go_{gid}"), _btn("⚙️ Custom", f"cfg_{gid}")],
        [_btn("➕ Add a friend", f"addf_{gid}"),
         _btn("📤 Invite link", f"inv_{gid}")],
        [_btn("🏆 Results", f"res_{gid}"),
         _btn("✏️ My airports", f"myap_{gid}")],
    ]
    last = [_btn("🚪 Leave", f"leave_{gid}")]
    if manual_count:
        last.insert(0, _btn("👥 Manage people", f"ppl_{gid}"))
    rows.append(last)
    rows.append([HOME_BTN])
    await _show(update, context, "\n".join(lines), rows)


async def scr_invite(update, context, gid):
    s = Storage()
    g = s.get_group(gid)
    if not g:
        await _show(update, context, "❌ Group not found.", [[HOME_BTN]])
        return
    bot_name = context.bot.username
    link = f"https://t.me/{bot_name}?start=join_{g['invite_code']}"
    share = (f"https://t.me/share/url?url={link}"
             f"&text=Join%20my%20flight%20meetup%20group!")
    text = (
        f"📤 <b>Invite friends to {esc(g['name'])}</b>\n\n"
        f"Send them this link - one tap and they're in:\n\n"
        f"{link}\n\n"
        f"<i>They'll be asked where they fly from, then everything "
        f"else is buttons.</i>"
    )
    rows = [
        [InlineKeyboardButton("📨 Share via Telegram", url=share)],
        [_btn("⬅️ Back", f"hub_{gid}")],
    ]
    await _show(update, context, text, rows)


async def scr_leave(update, context, gid, confirmed=False):
    s = Storage()
    g = s.get_group(gid)
    if not g:
        await scr_home(update, context)
        return
    if not confirmed:
        await _show(update, context,
                    f"🚪 Leave <b>{esc(g['name'])}</b>?",
                    [[_btn("Yes, leave", f"leavey_{gid}"),
                      _btn("⬅️ Stay", f"hub_{gid}")]])
        return
    s.leave_group(gid, _tid(update))
    await scr_home(update, context)


async def start_add_friend(update, context, gid):
    """Owner adds a friend by hand: name, then airports. No invite needed."""
    g = Storage().get_group(gid)
    if not g:
        await _show(update, context, "❌ Group not found.", [[HOME_BTN]])
        return
    context.user_data['await'] = {'kind': 'friend_name', 'gid': gid}
    await _show(
        update, context,
        f"➕ <b>Add a friend to {esc(g['name'])}</b>\n\n"
        "What's their name? It's just a label for the results - they don't "
        "need Telegram or to do anything.\n\n"
        "Type their name below 👇",
        [[_btn("⬅️ Back", f"hub_{gid}")]])


async def scr_people(update, context, gid):
    """Manage members: list everyone, remove manually-added ones."""
    s = Storage()
    g = s.get_group(gid)
    if not g:
        await _show(update, context, "❌ Group not found.", [[HOME_BTN]])
        return
    members = s.get_group_members(gid)
    me = _tid(update)
    lines = [f"👥 <b>People in {esc(g['name'])}</b>", ""]
    rows = []
    for m in members:
        manual = _is_manual(m['telegram_id'])
        tag = (" <i>(added by you)</i>" if manual
               else (" <i>(you)</i>" if m['telegram_id'] == me else ""))
        lines.append(f"👤 {esc(_member_name(m))}{tag} - "
                     f"{esc(', '.join(m['origins']))}")
        if manual:
            rows.append([_btn(f"🗑 Remove {_member_name(m)}",
                              f"rmf_{gid}_{m['telegram_id']}")])
    rows.append([_btn("➕ Add a friend", f"addf_{gid}")])
    rows.append([_btn("⬅️ Back", f"hub_{gid}")])
    await _show(update, context, "\n".join(lines), rows)


async def scr_help(update, context):
    text = (
        "❓ <b>How it works</b>\n\n"
        "You and your friends live in different cities and want to meet "
        "somewhere. I search every destination and date combo, and rank "
        "cities by the <b>true all-in cost</b> for the whole group - "
        "flights + luggage fees + airport transfers.\n\n"
        "① <b>Create a group</b>, share the invite link\n"
        "② Everyone types where they fly from - city names are fine "
        "(\"milan\", \"riga\")\n"
        "③ <b>Search now</b> uses smart defaults, or customize dates, "
        "nights, bags, transfers, scope\n"
        "④ Everyone gets pinged when results are in\n"
        "⑤ Tap a city → full breakdown per person → "
        "🔎 check the live price before booking\n\n"
        "<b>Reading results</b>\n"
        "💎 All-in = flights + bags + transfers\n"
        "🟢 confirmed by multiple sources · 🔵 single source - verify\n"
        "Bars show who pays more (fairness).\n\n"
        "<i>Prices move fast - always tap 🔎 before booking.</i>"
    )
    await _show(update, context, text, [[HOME_BTN]])


# ═══════════════════════ SEARCH SETTINGS PANEL ═══════════════════════

def _cfg(context, gid):
    key = f"cfg_{gid}"
    if key not in context.user_data:
        context.user_data[key] = ui.default_search_config()
    return context.user_data[key]


def _panel_rows(gid):
    return [
        [_btn("🚀  LAUNCH SEARCH", f"cfgl_{gid}")],
        [_btn("📅 Dates", f"cfgo_{gid}_dates"),
         _btn("🌙 Nights", f"cfgo_{gid}_nights")],
        [_btn("🧳 Luggage", f"cfgo_{gid}_lug"),
         _btn("🚆 Transfers", f"cfgo_{gid}_xfer")],
        [_btn("✈️ Flights", f"cfgo_{gid}_dir"),
         _btn("🌍 Where", f"cfgo_{gid}_scope")],
        [_btn("⬅️ Back", f"hub_{gid}")],
    ]


async def scr_panel(update, context, gid):
    s = Storage()
    g = s.get_group(gid)
    if not g:
        await _show(update, context, "❌ Group not found.", [[HOME_BTN]])
        return
    members = s.get_group_members(gid)
    cfg = _cfg(context, gid)
    await _show(update, context,
                ui.fmt_settings_panel(g['name'], len(members), cfg),
                _panel_rows(gid))


async def scr_panel_setting(update, context, gid, key):
    """Swap the panel keyboard for one setting's options (same message)."""
    cfg = _cfg(context, gid)
    g = Storage().get_group(gid)
    if not g:
        await _show(update, context, "❌ Group not found.", [[HOME_BTN]])
        return
    base = ui.fmt_settings_panel(g['name'],
                                 len(Storage().get_group_members(gid)), cfg)
    back = _btn("⬅️ Back", f"cfg_{gid}")

    if key == "dates":
        today = datetime.now()
        weekend = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
        opts = [
            ("🏖 This weekend", weekend, weekend + timedelta(days=3)),
            ("📅 Next 2 weeks", today + timedelta(days=3),
             today + timedelta(days=17)),
            ("🗓 Next month", today + timedelta(days=14),
             today + timedelta(days=42)),
            ("☀️ Rest of summer", today + timedelta(days=7),
             datetime(today.year, 9, 1)),
        ]
        rows = [[_btn(lbl, f"cfgv_{gid}_dates_"
                           f"{a.strftime('%Y-%m-%d')}_{b.strftime('%Y-%m-%d')}")]
                for lbl, a, b in opts if a < b]
        rows.append([_btn("⌨️ Type custom dates", f"cfgo_{gid}_cdates")])
        rows.append([back])
        await _show(update, context, base + "\n\n📅 <b>When can you travel?</b>",
                    rows)

    elif key == "cdates":
        context.user_data['await'] = {'kind': 'cfg_dates', 'gid': gid}
        await _show(update, context,
                    base + "\n\n⌨️ Type the window, e.g.\n"
                           "<code>2026-08-01 to 2026-08-14</code>",
                    [[back]])

    elif key == "nights":
        rows = [
            [_btn("2 nights", f"cfgv_{gid}_nights_2_2"),
             _btn("3 nights", f"cfgv_{gid}_nights_3_3")],
            [_btn("4 nights", f"cfgv_{gid}_nights_4_4"),
             _btn("5 nights", f"cfgv_{gid}_nights_5_5")],
            [_btn("Flexible 2-4", f"cfgv_{gid}_nights_2_4"),
             _btn("Flexible 3-7", f"cfgv_{gid}_nights_3_7")],
            [back],
        ]
        await _show(update, context, base + "\n\n🌙 <b>How long?</b>", rows)

    elif key == "lug":
        rows = [
            [_btn("🎒 10kg cabin bag", f"cfgv_{gid}_lug_c10")],
            [_btn("📦 23kg checked bag", f"cfgv_{gid}_lug_c23")],
            [_btn("👜 Personal item only (cheapest)", f"cfgv_{gid}_lug_none")],
            [back],
        ]
        await _show(update, context,
                    base + "\n\n🧳 <b>Luggage?</b> Bag fees go into the "
                           "true cost (budget airlines charge extra).",
                    rows)

    elif key == "xfer":
        rows = [
            [_btn("🚆 Include airport→city transfers", f"cfgv_{gid}_xfer_1")],
            [_btn("💰 Flights only", f"cfgv_{gid}_xfer_0")],
            [back],
        ]
        await _show(update, context,
                    base + "\n\n🚆 <b>Count transfer costs?</b> "
                           "(e.g. Bergamo→Milan €12)",
                    rows)

    elif key == "dir":
        rows = [
            [_btn("🟢 Any flights (cheapest)", f"cfgv_{gid}_dir_0")],
            [_btn("🎯 Direct only", f"cfgv_{gid}_dir_1")],
            [back],
        ]
        await _show(update, context, base + "\n\n✈️ <b>Connections ok?</b>",
                    rows)

    elif key == "scope":
        rows = [
            [_btn("🌍 Europe (recommended)", f"cfgv_{gid}_scope_europe")],
            [_btn("🛂 Schengen only", f"cfgv_{gid}_scope_schengen")],
            [_btn("🌐 Everywhere", f"cfgv_{gid}_scope_anywhere")],
            [back],
        ]
        await _show(update, context, base + "\n\n🌍 <b>Where to look?</b>",
                    rows)
    else:
        await scr_panel(update, context, gid)


async def cb_panel_set(update, context, gid, key, value_parts):
    """Apply a cfgv_* choice and re-render the panel."""
    cfg = _cfg(context, gid)
    if key == "dates" and len(value_parts) >= 2:
        cfg['start'], cfg['end'] = value_parts[0], value_parts[1]
    elif key == "nights" and len(value_parts) >= 2:
        cfg['min_n'], cfg['max_n'] = int(value_parts[0]), int(value_parts[1])
    elif key == "lug":
        cfg['luggage'] = {"c10": "carryon_10kg", "c23": "checked_23kg",
                          "none": "none"}.get(value_parts[0], "carryon_10kg")
    elif key == "xfer":
        cfg['transfers'] = value_parts[0] == "1"
    elif key == "dir":
        cfg['direct'] = value_parts[0] == "1"
    elif key == "scope":
        cfg['scope'] = value_parts[0]
    await scr_panel(update, context, gid)


# ═══════════════════════════ SEARCH RUNNER ═══════════════════════════

async def launch_search(update, context, gid, cfg=None):
    """Guarded launch → progress card that edits in place → member fan-out."""
    s = Storage()
    g = s.get_group(gid)
    if not g:
        await _show(update, context, "❌ Group not found.", [[HOME_BTN]])
        return
    members = s.get_group_members(gid)
    if len(members) < 2:
        await _show(update, context,
                    f"👥 <b>{esc(g['name'])}</b> needs at least 2 people "
                    f"before a search makes sense.\n\n"
                    f"Add a friend's airports yourself, or send them the "
                    f"invite link.",
                    [[_btn("➕ Add a friend", f"addf_{gid}")],
                     [_btn("📤 Invite link", f"inv_{gid}")],
                     [_btn("⬅️ Back", f"hub_{gid}")]])
        return
    if context.bot_data.get(f"sa_{gid}"):
        await _show(update, context,
                    "🔍 A search is already running for this group.",
                    [[_btn("⬅️ Back", f"hub_{gid}")]])
        return

    cfg = cfg or _cfg(context, gid)
    participants = [ParticipantGroup(label=_member_name(m), origins=m['origins'])
                    for m in members]
    req = SearchRequest(
        participants=participants,
        depart_earliest=cfg['start'], depart_latest=cfg['end'],
        min_nights=cfg['min_n'], max_nights=cfg['max_n'],
        destination_universe=cfg['scope'],
        luggage=cfg['luggage'], include_transfers=cfg['transfers'],
        direct_only=cfg['direct'], max_stops=0 if cfg['direct'] else 2,
    )
    sid = s.create_search(gid, req)
    s.update_search_status(sid, 'running')

    group_name = g['name']
    stop_rows = [[_btn("⏹ Stop search", f"stop_{gid}")]]
    msg = await _show(update, context,
                      ui.fmt_progress(group_name, 0, "warming up…", 0),
                      stop_rows)

    providers = build_providers() if _is_owner(update) \
        else build_guest_providers()
    notifier = Notifier(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_ID)

    context.bot_data[f"sa_{gid}"] = True
    context.bot_data[f"st_{gid}"] = datetime.now()
    SEARCH_STOP_EVENT.clear()

    loop = asyncio.get_running_loop()
    started = time.time()
    state = {"t": 0.0, "pct": -1}
    requester = _tid(update)
    bot = context.bot

    def prog_cb(cur, tot, city):
        """SYNC callback from the search thread → schedules a card edit on
        the event loop. This is the v6 fix: async prog_cb was never awaited."""
        if not tot:
            return
        pct = int(cur / tot * 100)
        now = time.time()
        if pct == state["pct"]:
            return
        if (now - state["t"]) < 4 and pct < 100:
            return
        state.update(t=now, pct=pct)
        context.bot_data[f"scity_{gid}"] = city
        text = ui.fmt_progress(group_name, pct, city, now - started)

        async def _edit():
            try:
                await msg.edit_text(text, parse_mode='HTML',
                                    reply_markup=_kb(stop_rows))
            except BadRequest:
                pass

        asyncio.run_coroutine_threadsafe(_edit(), loop)

    async def run():
        try:
            summary = await asyncio.to_thread(
                booking_mode, s, notifier, providers,
                progress_callback=prog_cb, search_request=req)
            secs = int(time.time() - started)
            cities = {getattr(r, 'dest_city', '') or r.destination
                      for r in summary.results}
            stopped = " (stopped early)" if summary.stopped else ""

            done = (
                f"✅ <b>Search done{stopped} - {esc(group_name)}</b>\n\n"
                f"🏆 {len(summary.results)} deals in {len(cities)} cities"
                f" · {secs // 60}m{secs % 60}s\n\n"
                f"Everyone in the group has been notified."
            )
            try:
                await msg.edit_text(done, parse_mode='HTML', reply_markup=_kb(
                    [[_btn("🏆 View results", f"res_{gid}")],
                     [_btn("⬅️ Group", f"hub_{gid}"), HOME_BTN]]))
            except BadRequest:
                pass

            # ── Fan-out: ping every member (the "with others" moment) ──
            ping = (f"🏆 <b>Results are ready!</b>\n\n"
                    f"<b>{esc(group_name)}</b> found "
                    f"{len(summary.results)} deals in {len(cities)} cities.")
            for m in members:
                if m['telegram_id'] == requester:
                    continue
                try:
                    await bot.send_message(
                        chat_id=int(m['telegram_id']), text=ping,
                        parse_mode='HTML', reply_markup=_kb(
                            [[_btn("🏆 See the deals", f"res_{gid}")]]))
                except Exception:
                    pass  # member never started the bot - skip silently
        except Exception as e:
            log_error(f"search run failed: {e}")
            try:
                await msg.edit_text(
                    f"❌ Search failed: {esc(str(e)[:200])}",
                    parse_mode='HTML',
                    reply_markup=_kb([[_btn("⬅️ Group", f"hub_{gid}")]]))
            except BadRequest:
                pass
        finally:
            context.bot_data[f"sa_{gid}"] = False
            s.update_search_status(sid, 'completed')

    asyncio.create_task(run())


# ═══════════════════════════════ RESULTS ═══════════════════════════════

def _load_deals(context, gid):
    """Load latest-search results for a group; returns (all, deduped_by_city)."""
    s = Storage()
    searches = s.list_searches_by_group(gid, limit=1)
    if not searches:
        return None, None, None
    results = s.get_search_results(searches[0]['id'])
    seen, deduped = set(), []
    for r in results:
        city = r.get('dest_city') or ui.city_of(r['destination'])
        if city in seen:
            continue
        seen.add(city)
        deduped.append(r)
    context.user_data['r_all'] = results
    context.user_data['r_deals'] = deduped
    context.user_data['r_gid'] = gid
    return searches[0], results, deduped


async def scr_results(update, context, gid, page=0):
    s = Storage()
    g = s.get_group(gid)
    if not g:
        await _show(update, context, "❌ Group not found.", [[HOME_BTN]])
        return
    search, results, deduped = _load_deals(context, gid)
    if search is None:
        await _show(update, context,
                    f"🏆 <b>{esc(g['name'])}</b>\n\nNo searches yet - "
                    f"launch the first one!",
                    [[_btn("🚀 Search now", f"go_{gid}")],
                     [_btn("⬅️ Back", f"hub_{gid}")]])
        return
    if not results:
        status = search.get('status', '?')
        hint = ("Still searching - I'll ping you when it's done."
                if status == 'running' else "The search found no deals.")
        await _show(update, context,
                    f"🏆 <b>{esc(g['name'])}</b>\n\n{hint}",
                    [[_btn("🔄 Refresh", f"res_{gid}")],
                     [_btn("🚀 New search", f"go_{gid}"),
                      _btn("⬅️ Back", f"hub_{gid}")]])
        return

    text, page, total_pages = ui.fmt_results_list(g['name'], deduped, page)

    per = 8
    chunk = deduped[page * per:(page + 1) * per]
    rows = []
    for i in range(0, len(chunk), 2):
        row = []
        for r in chunk[i:i + 2]:
            d = r['destination']
            city = r.get('dest_city') or ui.city_of(d)
            flag = r.get('dest_flag') or ui.flag_of(d)
            row.append(_btn(f"{flag} {city}", f"cd_{gid}_{d}"))
        rows.append(row)
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(_btn("◀️", f"rp_{gid}_{page - 1}"))
        nav.append(_btn(f"{page + 1}/{total_pages}", "noop"))
        if page < total_pages - 1:
            nav.append(_btn("▶️", f"rp_{gid}_{page + 1}"))
        rows.append(nav)
    if ai.available() and len(deduped) >= 2:
        rows.append([_btn("✨ Which should we pick?", f"aipick_{gid}")])
    rows.append([_btn("🔄 Refresh", f"res_{gid}"),
                 _btn("⬅️ Group", f"hub_{gid}")])
    await _show(update, context, text, rows)


async def scr_city(update, context, gid, dest):
    """City detail: best deal fully broken down + other date options."""
    deals = context.user_data.get('r_all') or []
    if not deals or context.user_data.get('r_gid') != gid:
        _load_deals(context, gid)
        deals = context.user_data.get('r_all') or []
    matching = [r for r in deals if r['destination'] == dest]
    if not matching:
        await scr_results(update, context, gid)
        return

    best = matching[0]
    text = ui.fmt_result_detail(best)
    if len(matching) > 1:
        text += "\n\n<b>Other dates for this city:</b>"
        for i, r in enumerate(matching[1:5], 2):
            out, ret = r['outbound_date'], r['return_date']
            n = ui.nights_of(out, ret)
            text += (f"\n{i}. {esc(out)} → {esc(ret)} · {n}n · "
                     f"<b>{eur(float(r.get('grand_total') or r['total_price']))}</b>")

    rows = []
    for i, r in enumerate(matching[:4], 1):
        rid = r.get('id')
        if rid:
            rows.append([_btn(f"🔎 Check live price #{i}", f"ver_{rid}"),
                         _btn(f"📝 I booked #{i}", f"paid_{rid}")])
    if ai.available():
        city = best.get('dest_city') or ui.city_of(dest)
        rows.append([_btn(f"✨ Things to do in {city}", f"aicity_{gid}_{dest}")])
    rows.append([_btn("⬅️ All results", f"res_{gid}"),
                 _btn("✈️ Group", f"hub_{gid}")])
    await _show(update, context, text, rows)


async def cb_verify(update, context, rid):
    q = update.callback_query
    note = await q.message.reply_text(
        "🔎 Checking live prices - this takes 20-60 seconds…")
    result = await asyncio.to_thread(
        verify_result, Storage(), rid, _is_owner(update))
    status = str(result.get('status', 'unknown')).replace('_', ' ')
    if not result.get('ok'):
        await note.edit_text(
            f"🚫 <b>Live check: {esc(status)}</b>\n\n"
            f"{esc(result.get('message', 'Could not verify right now.'))}\n"
            "Try again later or open the booking links.",
            parse_mode='HTML')
        return
    old_g = float(result.get('old_grand_total') or 0)
    new_g = float(result.get('new_grand_total') or 0)
    delta = float(result.get('delta') or 0)
    arrow = "🔺" if delta > 0 else ("🔻" if delta < 0 else "▪️")
    lines = [
        f"🔎 <b>Live check: {esc(status)}</b>",
        "",
        f"Saved all-in: {eur(old_g)}",
        f"Live all-in: <b>{eur(new_g)}</b>  {arrow} "
        f"{'+' if delta > 0 else ''}{eur(delta)}",
        "",
    ]
    for p in result.get('details', {}).get('participants', []):
        lines.append(f"{esc(p.get('label', '?'))} · {esc(p.get('origin', '?'))} "
                     f"· {eur(p.get('price', 0))}")
    lines += ["", "<i>Book only if the checkout page matches this.</i>"]
    await note.edit_text("\n".join(lines), parse_mode='HTML')


async def cb_ai_pick(update, context, gid):
    """✨ AI recommendation across the group's ranked deals."""
    q = update.callback_query
    if context.user_data.get('r_gid') != gid or not context.user_data.get('r_deals'):
        _load_deals(context, gid)
    deals = context.user_data.get('r_deals') or []
    if len(deals) < 2:
        await q.message.reply_text("Not enough deals to compare yet.")
        return
    g = Storage().get_group(gid)
    name = g['name'] if g else "your group"
    note = await q.message.reply_text("✨ Weighing cost, fairness and vibe…")
    text = await asyncio.to_thread(ai.recommend_meetup, deals, name)
    if not text:
        await note.edit_text(
            "✨ The AI concierge is unavailable right now - but the list is "
            "already sorted cheapest-first, so #1 is your best-value pick.")
        return
    await note.edit_text(
        f"✨ <b>AI pick - {esc(name)}</b>\n\n{esc(text)}\n\n"
        f"<i>AI suggestion from the real computed deals. "
        f"Always tap 🔎 to verify the live price before booking.</i>",
        parse_mode='HTML')


async def cb_ai_city(update, context, gid, dest):
    """✨ AI 'things to do' for a chosen city, sized to the trip length."""
    q = update.callback_query
    deals = context.user_data.get('r_all') or []
    matching = [r for r in deals if r['destination'] == dest]
    nights, month = 3, ""
    if matching:
        r = matching[0]
        nights = ui.nights_of(r['outbound_date'], r['return_date']) or 3
        try:
            month = datetime.strptime(
                r['outbound_date'], "%Y-%m-%d").strftime("%B")
        except Exception:
            pass
    from src.core.airports import CANDIDATE_DESTINATIONS
    ap = next((x for x in CANDIDATE_DESTINATIONS if x.iata == dest), None)
    city = ui.city_of(dest)
    country = ap.country if ap else ""
    note = await q.message.reply_text(f"✨ Dreaming up {city} ideas…")
    text = await asyncio.to_thread(ai.city_vibe, city, country, nights, month)
    if not text:
        await note.edit_text("✨ AI ideas aren't available right now.")
        return
    await note.edit_text(
        f"✨ <b>{esc(city)} - {nights}-night ideas</b>\n\n{esc(text)}\n\n"
        f"<i>AI-generated inspiration.</i>", parse_mode='HTML')


# ═══════════════════ TEXT FLOWS (awaited free-text) ═══════════════════
# One dispatcher, flag-based: context.user_data['await'] = {'kind': ..., ...}

async def start_newgroup(update, context):
    _ensure_user(update)
    context.user_data['await'] = {'kind': 'grp_name'}
    await _show(update, context,
                "➕ <b>New group</b>\n\n"
                "What should we call it?\n"
                "<i>e.g. \"Summer Trip\", \"Weekend Crew\"</i>\n\n"
                "Type the name below 👇",
                [[_btn("❌ Cancel", "home")]])


async def _ask_airports(update, context, purpose, gid=None, gname=None,
                        group_label=None, friend=None):
    context.user_data['await'] = {'kind': 'origins', 'purpose': purpose,
                                  'gid': gid, 'gname': gname, 'friend': friend}
    if friend:
        prompt = f"🛫 <b>Where does {esc(friend)} fly from?</b>"
    else:
        where = f" for <b>{esc(group_label)}</b>" if group_label else ""
        prompt = f"🛫 <b>Where do you fly from{where}?</b>"
    await update.effective_message.reply_text(
        f"{prompt}\n\n"
        "Type a city or airport code - several are fine:\n"
        "<i>milan</i> · <i>riga</i> · <i>BGY, MXP</i> · <i>london</i>",
        parse_mode='HTML')


def _ap_keyboard(ap):
    """Toggle keyboard for multi-airport city suggestions."""
    rows = []
    for iata, on in ap['sel'].items():
        mark = "✅" if on else "▫️"
        rows.append([_btn(f"{mark} {ui.airport_label(iata)}", f"apt_{iata}")])
    rows.append([_btn("✔️ Confirm airports", "apok")])
    return rows


def _ap_text(ap):
    picked = ap['base'] + [i for i, on in ap['sel'].items() if on]
    lines = ["🛫 <b>Got it - confirm your airports</b>", ""]
    if ap['base']:
        lines.append("✓ " + ", ".join(ui.airport_label(i) for i in ap['base']))
    if ap['sel']:
        lines.append("Tap to include/exclude:")
    if ap.get('unknown_note'):
        lines += ["", f"⚠️ Unknown but accepted: "
                      f"{esc(', '.join(ap['unknown_note']))}"]
    if not picked:
        lines += ["", "⚠️ Nothing selected yet."]
    return "\n".join(lines)


async def _handle_origins_text(update, context, awaiting):
    raw = update.message.text.strip()
    resolved, suggestions, unknown = ui.resolve_airports(raw)

    # Unknown 3-letter tokens are accepted (may be real airports outside DB);
    # everything else unknown is dropped with a note.
    accepted_unknown = [u for u in unknown if len(u) == 3 and u.isalpha()]
    if not resolved and not suggestions and not accepted_unknown:
        await update.effective_message.reply_text(
            "I couldn't find that - try a city (<i>milan</i>) or a "
            "3-letter airport code (<i>BGY</i>).", parse_mode='HTML')
        context.user_data['await'] = awaiting  # keep waiting
        return

    if suggestions:
        sel = {}
        for city, airports in suggestions.items():
            for a in airports:
                sel[a.iata] = True
        ap = {'base': resolved + accepted_unknown, 'sel': sel,
              'unknown_note': accepted_unknown,
              'purpose': awaiting.get('purpose'),
              'gid': awaiting.get('gid'), 'gname': awaiting.get('gname'),
              'friend': awaiting.get('friend')}
        context.user_data['ap'] = ap
        await update.effective_message.reply_text(
            _ap_text(ap), parse_mode='HTML',
            reply_markup=_kb(_ap_keyboard(ap)))
        return

    await _finish_airports(update, context, resolved + accepted_unknown,
                           awaiting.get('purpose'), awaiting.get('gid'),
                           awaiting.get('gname'), awaiting.get('friend'))


async def _finish_airports(update, context, origins, purpose, gid, gname,
                           friend=None):
    """Airports confirmed → complete whichever flow needed them."""
    s = Storage()
    tid = _tid(update)

    if purpose == 'grp':
        g = s.create_group(gname, tid)
        s.join_group(g['id'], tid, _uname(update), origins)
        bot_name = context.bot.username
        link = f"https://t.me/{bot_name}?start=join_{g['invite_code']}"
        share = (f"https://t.me/share/url?url={link}"
                 f"&text=Join%20my%20flight%20meetup%20group!")
        await update.effective_message.reply_text(
            f"✅ <b>{esc(g['name'])} is ready!</b>\n\n"
            f"👤 You fly from: {esc(', '.join(origins))}\n\n"
            f"Now invite your friends - one tap and they're in:\n{link}",
            parse_mode='HTML', disable_web_page_preview=True,
            reply_markup=_kb([
                [InlineKeyboardButton("📨 Share via Telegram", url=share)],
                [_btn("✈️ Open group", f"hub_{g['id']}")],
            ]))

    elif purpose == 'join':
        g = s.get_group(gid)
        if not g:
            await update.effective_message.reply_text("❌ Group vanished.")
            return
        s.join_group(gid, tid, _uname(update), origins)
        members = s.get_group_members(gid)
        # Ping the group creator
        try:
            if g['created_by'] != tid:
                await context.bot.send_message(
                    chat_id=int(g['created_by']),
                    text=f"👋 <b>{esc(_uname(update))}</b> joined "
                         f"<b>{esc(g['name'])}</b> - "
                         f"{len(members)} member{'s' if len(members) != 1 else ''} now.",
                    parse_mode='HTML',
                    reply_markup=_kb([[_btn("✈️ Open group", f"hub_{gid}")]]))
        except Exception:
            pass
        await update.effective_message.reply_text(
            f"✅ <b>You're in {esc(g['name'])}!</b>\n"
            f"👤 You fly from: {esc(', '.join(origins))}",
            parse_mode='HTML',
            reply_markup=_kb([[_btn("✈️ Open group", f"hub_{gid}")]]))

    elif purpose == 'edit':
        s.join_group(gid, tid, _uname(update), origins)  # upserts origins
        await update.effective_message.reply_text(
            f"✅ Airports updated: {esc(', '.join(origins))}",
            parse_mode='HTML',
            reply_markup=_kb([[_btn("✈️ Back to group", f"hub_{gid}")]]))

    elif purpose == 'addfriend':
        g = s.get_group(gid)
        if not g:
            await update.effective_message.reply_text("❌ Group not found.")
            return
        name = (friend or "Friend").strip()[:40]
        # Manual members have no Telegram account: give them a synthetic id so
        # they count as a participant in the search but are never messaged.
        import secrets
        manual_id = f"{_MANUAL_PREFIX}{secrets.token_hex(4)}"
        s.join_group(gid, manual_id, name, origins)
        members = s.get_group_members(gid)
        await update.effective_message.reply_text(
            f"✅ Added <b>{esc(name)}</b> flying from "
            f"{esc(', '.join(origins))}.\n"
            f"👥 {esc(g['name'])} now has {len(members)} "
            f"{'person' if len(members) == 1 else 'people'}. "
            f"You can search whenever you're ready.",
            parse_mode='HTML',
            reply_markup=_kb([
                [_btn("➕ Add another", f"addf_{gid}"),
                 _btn("🚀 Search now", f"go_{gid}")],
                [_btn("✈️ Open group", f"hub_{gid}")],
            ]))


async def on_message(update, context):
    """All free-text lands here; dispatch on the awaited flag."""
    awaiting = context.user_data.pop('await', None)
    if not awaiting:
        await update.effective_message.reply_text(
            "Tap a button to get around 👇",
            reply_markup=_kb([[HOME_BTN, _btn("❓ Help", "help")]]))
        return

    kind = awaiting['kind']

    if kind == 'grp_name':
        name = update.message.text.strip()[:60]
        if not name:
            context.user_data['await'] = awaiting
            await update.effective_message.reply_text("Type a name 🙂")
            return
        await _ask_airports(update, context, 'grp', gname=name,
                            group_label=name)

    elif kind == 'friend_name':
        name = update.message.text.strip()[:40]
        if not name:
            context.user_data['await'] = awaiting
            await update.effective_message.reply_text("Type their name 🙂")
            return
        await _ask_airports(update, context, 'addfriend',
                            gid=awaiting['gid'], friend=name)

    elif kind == 'origins':
        await _handle_origins_text(update, context, awaiting)

    elif kind == 'cfg_dates':
        gid = awaiting['gid']
        dates = re.findall(r'\d{4}-\d{2}-\d{2}', update.message.text)
        if not dates:
            context.user_data['await'] = awaiting
            await update.effective_message.reply_text(
                "Format: <code>2026-08-01 to 2026-08-14</code>",
                parse_mode='HTML')
            return
        cfg = _cfg(context, gid)
        cfg['start'] = dates[0]
        cfg['end'] = dates[1] if len(dates) > 1 else (
            datetime.strptime(dates[0], "%Y-%m-%d") + timedelta(days=14)
        ).strftime("%Y-%m-%d")
        g = Storage().get_group(gid)
        members = Storage().get_group_members(gid)
        await update.effective_message.reply_text(
            ui.fmt_settings_panel(g['name'], len(members), cfg),
            parse_mode='HTML', reply_markup=_kb(_panel_rows(gid)))

    elif kind == 'paid':
        rid = awaiting['rid']
        m = re.search(r'\d+(?:[.,]\d+)?', update.message.text)
        if not m:
            context.user_data['await'] = awaiting
            await update.effective_message.reply_text(
                "Send the total as a number, e.g. <code>214.50</code>",
                parse_mode='HTML')
            return
        amount = float(m.group(0).replace(',', '.'))
        result = Storage().get_result(int(rid))
        if not result:
            await update.effective_message.reply_text("Result not found anymore.")
            return
        Storage().save_paid_price_report(
            result_id=int(rid), search_id=result.get('search_id', ''),
            telegram_id=_tid(update), destination=result['destination'],
            outbound_date=result['outbound_date'],
            return_date=result['return_date'],
            reported_total=amount,
            notes=update.message.text[m.end():].strip(),
        )
        await update.effective_message.reply_text(
            f"📝 Saved - you paid <b>{eur(amount)}</b>. "
            f"This makes future price estimates smarter. Thank you!",
            parse_mode='HTML')


# ═══════════════════════════════ COMMANDS ═══════════════════════════════

async def _reject(update):
    await update.effective_message.reply_text(
        "🔐 <b>Invite-only bot</b>\n\nAsk the owner for an invite link.",
        parse_mode='HTML')


async def cmd_start(update, context):
    if not _allowed(update):
        args = context.args
        if args and args[0].startswith("inv_"):
            if Storage().get_user(f"inv_{args[0].replace('inv_', '')}"):
                _ensure_user(update)
            else:
                await _reject(update)
                return
        else:
            await _reject(update)
            return
    _ensure_user(update)

    args = context.args
    if args and args[0].startswith("join_"):
        await _start_join(update, context, args[0].replace("join_", ""))
        return
    await scr_home(update, context)


async def _start_join(update, context, code):
    s = Storage()
    g = s.get_group_by_invite(code)
    if not g:
        await update.effective_message.reply_text(
            "❌ That invite link doesn't work anymore.",
            reply_markup=_kb([[HOME_BTN]]))
        return
    members = s.get_group_members(g['id'])
    if _tid(update) in {m['telegram_id'] for m in members}:
        await scr_hub(update, context, g['id'])
        return
    names = ", ".join(esc(m['username']) for m in members)
    await update.effective_message.reply_text(
        f"👋 <b>You're invited to {esc(g['name'])}!</b>\n"
        f"👥 Already in: {names}\n",
        parse_mode='HTML')
    await _ask_airports(update, context, 'join', gid=g['id'],
                        group_label=g['name'])


async def cmd_join(update, context):
    _ensure_user(update)
    if not context.args:
        await update.effective_message.reply_text(
            "Usage: /joingroup &lt;code&gt; - or just tap your friend's "
            "invite link.", parse_mode='HTML')
        return
    await _start_join(update, context, context.args[0])


async def cmd_invite(update, context):
    """Owner-only: mint an access-invite for the invite-gate.
    (v6 let ANYONE mint codes - that bypassed the gate.)"""
    if not _is_owner(update):
        await update.effective_message.reply_text("⛔ Owner only.")
        return
    import secrets
    code = secrets.token_urlsafe(8)[:10]
    Storage().upsert_user(f"inv_{code}", code, "invite")
    bot_name = context.bot.username
    await update.effective_message.reply_text(
        f"📨 <b>Access invite</b>\n\nhttps://t.me/{bot_name}?start=inv_{code}",
        parse_mode='HTML', disable_web_page_preview=True)


async def cmd_help(update, context):
    await scr_help(update, context)


async def cmd_status(update, context):
    active = []
    for k, v in (context.bot_data or {}).items():
        if k.startswith("sa_") and v:
            gid = k.replace("sa_", "")
            city = context.bot_data.get(f"scity_{gid}", "…")
            ts = context.bot_data.get(f"st_{gid}")
            mins = int((datetime.now() - ts).total_seconds() / 60) if ts else 0
            g = Storage().get_group(gid)
            name = g['name'] if g else gid
            active.append(f"🔍 <b>{esc(name)}</b> - {esc(city)} ({mins}m)")
    await update.effective_message.reply_text(
        "\n".join(active) if active else "😴 No searches running.",
        parse_mode='HTML', reply_markup=_kb([[HOME_BTN]]))


async def cmd_stop(update, context):
    SEARCH_STOP_EVENT.set()
    await update.effective_message.reply_text(
        "🛑 Stopping - results found so far are saved.")


async def cmd_health(update, context):
    providers = build_providers()
    txt = "🏥 <b>Providers</b>\n\n"
    for p in providers:
        ok = p.is_healthy()
        txt += f"{'✅' if ok else '❌'} {esc(p.name())}"
        if not ok:
            txt += f" - {esc(p.get_health_reason())}"
        txt += "\n"
    txt += f"\n🤖 AI concierge: {'✅ on' if ai.available() else '➖ off (no key)'}"
    await update.effective_message.reply_text(txt, parse_mode='HTML')


async def cmd_intelligence(update, context):
    args = [a.upper() for a in context.args]
    origin = args[0] if len(args) >= 1 else ""
    dest = args[1] if len(args) >= 2 else ""
    data = fare_intelligence(Storage(), origin=origin, destination=dest)
    stats = data.get('stats', {})
    text = f"🧠 <b>Local fare intelligence</b>\n\n{esc(data.get('summary'))}\n"
    providers = stats.get('providers') or []
    if providers:
        text += "\n<b>Providers observed:</b>\n"
        for p in providers[:8]:
            text += (f"· {esc(p['provider'])}: {p['count']} obs, "
                     f"min {eur(p['min_price'])}, avg {eur(p['avg_price'])}\n")
    text += "\nUse /intelligence BGY VIE for one route."
    await update.effective_message.reply_text(text, parse_mode='HTML')


async def cmd_leave(update, context):
    _ensure_user(update)
    if not context.args:
        await scr_home(update, context)
        return
    if Storage().leave_group(context.args[0], _tid(update)):
        await update.effective_message.reply_text("✅ Left the group.")
    else:
        await update.effective_message.reply_text("Group not found.")


# ═══════════════════════════════ ADMIN ═══════════════════════════════

async def cmd_admin(update, context):
    if not _is_owner(update):
        await update.effective_message.reply_text("⛔ Owner only.")
        return
    s = Storage()
    args = context.args or []
    if args:
        sub = args[0]
        if sub == "users":
            await _admin_users(update, context, s)
        elif sub == "groups":
            await _admin_groups(update, context, s)
        elif sub == "searches":
            await _admin_searches(update, context, s)
        elif sub == "results":
            await _admin_results(update, context, s)
        else:
            await update.effective_message.reply_text(
                "/admin · /admin users · /admin groups · "
                "/admin searches · /admin results")
        return
    await scr_admin(update, context)


async def scr_admin(update, context):
    if not _is_owner(update):
        return
    s = Storage()
    st = s.admin_stats()
    top = "\n".join(
        f"  {i + 1}. {esc(ui.city_of(d['destination']))} - {d['count']}x, "
        f"from {eur(d['cheapest'])}"
        for i, d in enumerate(st['top_destinations']))
    text = (
        "🛡 <b>Admin</b>\n\n"
        f"👥 {st['total_users']} users ({st['active_24h']} active today) · "
        f"{st['total_groups']} groups\n"
        f"🔍 {st['total_searches']} searches "
        f"({st['running']} running, {st['completed']} done)\n"
        f"🏆 {st['total_results']} results ({st['results_24h']} today) · "
        f"{st['cities_30d']} cities/30d\n\n"
        f"<b>Top destinations</b>\n{top}"
    )
    rows = [
        [_btn("👥 Users", "adm_users"), _btn("✈️ Groups", "adm_groups")],
        [_btn("🔍 Searches", "adm_searches"), _btn("🏆 Results", "adm_results")],
        [HOME_BTN],
    ]
    await _show(update, context, text, rows)


async def _admin_users(update, context, s):
    users = s.admin_all_users()
    lines = ["👥 <b>All users</b>", ""]
    for u in users[:20]:
        name = u['first_name'] or u['username'] or u['telegram_id']
        lines.append(
            f"· <b>{esc(name)}</b> <code>{esc(u['telegram_id'])}</code> - "
            f"{u['group_count']}g/{u['search_count']}s, "
            f"joined {str(u.get('created_at', '?'))[:10]}")
    if len(users) > 20:
        lines.append(f"<i>… and {len(users) - 20} more</i>")
    await _show(update, context, "\n".join(lines) or "No users.",
                [[_btn("⬅️ Admin", "adm_dash")]])


async def _admin_groups(update, context, s):
    groups = s.admin_all_groups()
    lines = ["✈️ <b>All groups</b>", ""]
    for g in groups[:15]:
        mstr = ", ".join(f"{esc(m['username'])} "
                         f"({esc(','.join(m['origins']))})"
                         for m in g['members'])
        lines.append(f"· <b>{esc(g['name'])}</b> - {mstr} - "
                     f"{g['search_count']} searches")
    if len(groups) > 15:
        lines.append(f"<i>… and {len(groups) - 15} more</i>")
    await _show(update, context, "\n".join(lines) or "No groups.",
                [[_btn("⬅️ Admin", "adm_dash")]])


async def _admin_searches(update, context, s):
    searches = s.admin_all_searches(limit=15)
    lines = ["🔍 <b>Recent searches</b>", ""]
    for sr in searches:
        icon = {"running": "🟠", "completed": "🟢",
                "failed": "🔴"}.get(sr['status'], "⚪")
        lines.append(
            f"{icon} <b>{esc(sr.get('group_name', '?'))}</b> · "
            f"{esc(sr.get('depart_earliest', '?'))}→"
            f"{esc(sr.get('depart_latest', '?'))} · "
            f"{sr.get('result_count', 0)} results")
    await _show(update, context, "\n".join(lines) or "No searches.",
                [[_btn("⬅️ Admin", "adm_dash")]])


async def _admin_results(update, context, s):
    results = s.admin_recent_results(limit=15)
    lines = ["🏆 <b>Recent deals (all users)</b>", ""]
    for r in results:
        d = r['destination']
        grand = float(r.get('grand_total', 0) or r.get('total_price', 0) or 0)
        lines.append(
            f"· {ui.flag_of(d)} <b>{esc(ui.city_of(d))}</b> {eur(grand)} · "
            f"{esc(r.get('outbound_date', '?'))} "
            f"{ui.conf_icon(r.get('confidence_label'))}")
    await _show(update, context, "\n".join(lines) or "No results.",
                [[_btn("⬅️ Admin", "adm_dash")]])


# ═══════════════════════════ CALLBACK ROUTER ═══════════════════════════

async def on_callback(update, context):
    q = update.callback_query
    try:
        await q.answer()
    except Exception:
        pass
    d = q.data or ""
    _ensure_user(update)

    # ── navigation ──
    if d in ("home", "mygroups"):
        await scr_home(update, context)
    elif d in ("help", "guide"):
        await scr_help(update, context)
    elif d == "newgrp":
        await start_newgroup(update, context)
    elif d == "noop":
        pass

    # ── group hub ──
    elif d.startswith("hub_"):
        await scr_hub(update, context, d[4:])
    elif d.startswith("inv_"):
        await scr_invite(update, context, d[4:])
    elif d.startswith("leave_"):
        await scr_leave(update, context, d[6:])
    elif d.startswith("leavey_"):
        await scr_leave(update, context, d[7:], confirmed=True)
    elif d.startswith("myap_"):
        gid = d[5:]
        g = Storage().get_group(gid)
        await _ask_airports(update, context, 'edit', gid=gid,
                            group_label=g['name'] if g else None)

    # ── search ──
    elif d.startswith("go_") or d.startswith("quick_"):
        await launch_search(update, context, d.split("_", 1)[1])
    elif d.startswith("cfg_") or d.startswith("wizpick_"):
        await scr_panel(update, context, d.split("_", 1)[1])
    elif d.startswith("cfgl_"):
        await launch_search(update, context, d[5:],
                            _cfg(context, d[5:]))
    elif d.startswith("cfgo_"):
        parts = d.split("_")
        await scr_panel_setting(update, context, parts[1], parts[2])
    elif d.startswith("cfgv_"):
        parts = d.split("_")
        await cb_panel_set(update, context, parts[1], parts[2], parts[3:])
    elif d.startswith("stop_"):
        SEARCH_STOP_EVENT.set()
        # Immediate visual feedback; the worker wraps up and the completion
        # card then replaces this with the "stopped early" summary.
        try:
            await q.message.edit_text(
                "🛑 <b>Stopping the search</b>\n\nWrapping up the current step - "
                "any deals found so far are saved. Give it a few seconds.",
                parse_mode='HTML')
        except Exception:
            pass

    # ── airport confirm toggles ──
    elif d.startswith("apt_"):
        ap = context.user_data.get('ap')
        if ap:
            iata = d[4:]
            if iata in ap['sel']:
                ap['sel'][iata] = not ap['sel'][iata]
            await _show(update, context, _ap_text(ap), _ap_keyboard(ap))
    elif d == "apok":
        ap = context.user_data.pop('ap', None)
        if ap:
            origins = ap['base'] + [i for i, on in ap['sel'].items() if on]
            if not origins:
                context.user_data['ap'] = ap
                try:
                    await q.answer("Pick at least one airport!", show_alert=True)
                except Exception:
                    pass
            else:
                await _finish_airports(update, context, origins,
                                       ap['purpose'], ap.get('gid'),
                                       ap.get('gname'), ap.get('friend'))

    # ── manual friends ──
    elif d.startswith("addf_"):
        await start_add_friend(update, context, d[5:])
    elif d.startswith("ppl_"):
        await scr_people(update, context, d[4:])
    elif d.startswith("rmf_"):
        _, gid, mid = d.split("_", 2)   # mid = "manual_...."
        if _is_manual(mid):
            Storage().leave_group(gid, mid)
        await scr_people(update, context, gid)

    # ── results ──
    elif d.startswith("res_"):
        await scr_results(update, context, d[4:])
    elif d.startswith("rp_"):
        parts = d.split("_")
        await scr_results(update, context, parts[1], int(parts[2]))
    elif d.startswith("cd_"):
        parts = d.split("_")
        await scr_city(update, context, parts[1], parts[2])
    elif d.startswith("ver_"):
        await cb_verify(update, context, int(d[4:]))
    elif d.startswith("aipick_"):
        await cb_ai_pick(update, context, d[7:])
    elif d.startswith("aicity_"):
        parts = d.split("_")
        await cb_ai_city(update, context, parts[1], parts[2])
    elif d.startswith("paid_"):
        context.user_data['await'] = {'kind': 'paid', 'rid': int(d[5:])}
        await q.message.reply_text(
            "📝 What did you actually pay all-in?\n"
            "Send a number like <code>214.50</code> - add a note after "
            "it if you like.", parse_mode='HTML')

    # ── admin ──
    elif d == "adm_dash":
        await scr_admin(update, context)
    elif d == "adm_users":
        await _admin_users(update, context, Storage())
    elif d == "adm_groups":
        await _admin_groups(update, context, Storage())
    elif d == "adm_searches":
        await _admin_searches(update, context, Storage())
    elif d == "adm_results":
        await _admin_results(update, context, Storage())
    elif d.startswith("admg_"):
        await _admin_groups(update, context, Storage())

    else:
        await q.message.reply_text(
            "That button is from an older version - here's home:",
            reply_markup=_kb([[HOME_BTN]]))


# ═══════════════════════════ DYNAMIC COMMANDS ═══════════════════════════

async def dynamic_cmd(update, context):
    """Legacy /results_<id> style commands still work."""
    t = update.message.text.split()[0]
    if re.match(r'^/results_[a-zA-Z0-9]+$', t):
        await scr_results(update, context, t.replace("/results_", ""))
    elif re.match(r'^/search_[a-zA-Z0-9]+$', t):
        await scr_panel(update, context, t.replace("/search_", ""))
    else:
        await scr_home(update, context)


async def cmd_newsearch(update, context):
    _ensure_user(update)
    if context.args:
        await scr_panel(update, context, context.args[0])
    else:
        await scr_home(update, context)


# ═══════════════════════════════ MAIN ═══════════════════════════════

async def _post_init(app):
    """Register the '/' command menu (v6 never did - menu was empty)."""
    try:
        await app.bot.set_my_commands([
            BotCommand("start", "Home - groups, search, results"),
            BotCommand("help", "How it works"),
            BotCommand("status", "Running searches"),
            BotCommand("stop", "Stop the current search"),
        ])
    except Exception as e:
        log_error(f"set_my_commands failed: {e}")


if __name__ == '__main__':
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN not set.")
        exit(1)

    app = ApplicationBuilder().token(token).post_init(_post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("guide", cmd_help))
    app.add_handler(CommandHandler("invite", cmd_invite))
    app.add_handler(CommandHandler("mygroups", cmd_start))
    app.add_handler(CommandHandler("newgroup", start_newgroup))
    app.add_handler(CommandHandler("joingroup", cmd_join))
    app.add_handler(CommandHandler("leavegroup", cmd_leave))
    app.add_handler(CommandHandler("newsearch", cmd_newsearch))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("intelligence", cmd_intelligence))
    app.add_handler(CommandHandler("admin", cmd_admin))

    app.add_handler(MessageHandler(filters.COMMAND, dynamic_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   on_message))
    app.add_handler(CallbackQueryHandler(on_callback))

    # ── Startup loop (kept from v6) ──
    import requests
    from time import sleep

    def _reachable(tkn):
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{tkn}/getMe", timeout=10)
            return r.json().get("ok", False)
        except Exception:
            return False

    def _clear(tkn):
        try:
            requests.get(
                f"https://api.telegram.org/bot{tkn}/deleteWebhook",
                timeout=10)
            requests.get(f"https://api.telegram.org/bot{tkn}/close",
                         timeout=10)
        except Exception:
            pass

    print("Flight Meetup Bot v7.0 - Starting...")
    while True:
        if _reachable(token):
            try:
                print("Polling...")
                app.run_polling()
                break
            except Conflict:
                print("Conflict - releasing...")
                _clear(token)
                sleep(3)
            except KeyboardInterrupt:
                print("\nStopped.")
                break
        else:
            print("Token issue - retry in 20s...")
            _clear(token)
            sleep(20)
