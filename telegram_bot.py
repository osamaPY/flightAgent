import logging
import asyncio
import os
import sys

# Ensure the project root is in sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
from dotenv import load_dotenv

from src.core.config import Config
from src.core.storage import Storage
from src.core.notifier import Notifier
from src.core.logger import log_info, log_error, get_recent_logs
from src.core.providers import (
    RyanairProvider, TravelpayoutsProvider, SerpApiProvider, 
    RapidApiProvider, FlightApiProvider, KiwiRapidApiProvider,
    DuffelProvider, BookingComProvider
)
from main import monitor_mode, show_latest_results, discover_mode, verify_mode, test_providers, selftest, SEARCH_STOP_EVENT

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
# Silence verbose httpx logs from telegram library
logging.getLogger("httpx").setLevel(logging.WARNING)

load_dotenv()

def get_app_context():
    storage = Storage()
    notifier = Notifier(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_ID)
    providers = [
        RyanairProvider(),
        TravelpayoutsProvider(Config.TRAVELPAYOUTS_TOKEN),
        SerpApiProvider(Config.SERPAPI_KEY, storage),
        RapidApiProvider(Config.RAPIDAPI_KEY),
        FlightApiProvider(Config.FLIGHTAPI_KEY),
        KiwiRapidApiProvider(Config.RAPIDAPI_KEY),
        DuffelProvider(Config.DUFFEL_TOKEN),
        BookingComProvider(Config.RAPIDAPI_KEY)
    ]
    return storage, notifier, providers

async def get_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔍 Search", callback_data='search'),
         InlineKeyboardButton("✅ Verify", callback_data='verify')],
        [InlineKeyboardButton("📊 Results", callback_data='results'),
         InlineKeyboardButton("📡 Status", callback_data='status')],
        [InlineKeyboardButton("🛑 Stop", callback_data='stop'),
         InlineKeyboardButton("📜 Logs", callback_data='logs')],
        [InlineKeyboardButton("🏥 Health", callback_data='health'), 
         InlineKeyboardButton("🧪 Selftest", callback_data='selftest')],
        [InlineKeyboardButton("🌍 Discover", callback_data='discover'),
         InlineKeyboardButton("🧹 Clear", callback_data='clear')]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.core.config import Config
    origins_b = ", ".join(Config.ORIGINS_B)
    welcome_text = (
        "✈️ **Flight Meet**\n\n"
        f"Find cheap meetups from {origins_b}."
    )
    reply_markup = await get_menu_keyboard()
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    cmd = query.data
    # Map callback data to existing command functions
    if cmd == 'search':
        await cmd_search(update, context)
    elif cmd == 'verify':
        await cmd_verify(update, context)
    elif cmd == 'results':
        await cmd_results(update, context)
    elif cmd == 'status':
        await cmd_status(update, context)
    elif cmd == 'stop':
        await cmd_stop(update, context)
    elif cmd == 'logs':
        await cmd_logs(update, context)
    elif cmd == 'health':
        await cmd_health(update, context)
    elif cmd == 'selftest':
        await cmd_selftest(update, context)
    elif cmd == 'discover':
        await cmd_discover(update, context)
    elif cmd == 'clear':
        await cmd_clear(update, context)

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    storage, _, _ = get_app_context()
    storage.clear_results()
    await msg.reply_text("History cleared.")

async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if context.bot_data.get("search_active"):
        await msg.reply_text("Search running.")
        return

    await msg.reply_text("Search started.")
    storage, notifier, providers = get_app_context()
    
    # Use bot_data for global search state
    context.bot_data["search_active"] = True
    context.bot_data["current_city"] = "Init"
    context.bot_data["progress"] = "0/0"
    SEARCH_STOP_EVENT.clear()

    def progress_callback(current, total, city):
        context.bot_data["current_city"] = city
        context.bot_data["progress"] = f"{current}/{total}"
        if current == 1 or current % 5 == 0 or current == total:
            notifier.send_message(f"Scanning {current}/{total} ({city})")

    async def run_scan():
        try:
            await asyncio.to_thread(monitor_mode, storage, notifier, providers, progress_callback)
            if not SEARCH_STOP_EVENT.is_set():
                await update.effective_message.reply_text("Done.")
        except Exception as e:
            await update.effective_message.reply_text(f"Error: {e}")
        finally:
            context.bot_data["search_active"] = False

    asyncio.create_task(run_scan())

async def cmd_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    await msg.reply_text("Verifying top candidates.")
    
    storage, notifier, providers = get_app_context()
    
    async def run_verify():
        try:
            await asyncio.to_thread(verify_mode, storage, notifier, providers)
            await msg.reply_text("Verification done.")
        except Exception as e:
            await msg.reply_text(f"Error: {e}")

    asyncio.create_task(run_verify())

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not context.bot_data.get("search_active"):
        await msg.reply_text("Inactive.")
        return
    
    city = context.bot_data.get("current_city", "Unknown")
    prog = context.bot_data.get("progress", "0/0")
    await msg.reply_text(f"Status: {prog} cities\nScanning: {city}")

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not context.bot_data.get("search_active"):
        await msg.reply_text("Inactive.")
        return
    
    SEARCH_STOP_EVENT.set()
    await msg.reply_text("Stopping.")

async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    logs = get_recent_logs(15)
    await msg.reply_text(f"Logs:\n\n```\n{logs}\n```", parse_mode='Markdown')

async def cmd_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    storage, notifier, _ = get_app_context()
    from src.core.scoring import generate_booking_link
    from src.core.airports import CANDIDATE_DESTINATIONS
    
    try:
        with storage._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT destination, total_price, outbound_date, return_date, 
                       a_origin, a_price, b_origin, b_price, arrival_gap_hours, fairness_penalty
                FROM results 
                WHERE timestamp > datetime('now', '-7 days')
                ORDER BY (total_price + fairness_penalty) ASC
            """)
            rows = cursor.fetchall()
    except Exception as e:
        await msg.reply_text(f"Database error: {e}. Run search first.")
        return
    
    if not rows:
        await msg.reply_text("📭 No results.")
        return

    text = "💎 **Best Fair Meetups**\n\n"
    
    seen = set()
    count = 0
    for row in rows:
        dest, total, out, ret, a_org, a_p, b_org, b_p, gap, fairness = row
        
        key = (dest, out, ret)
        if key in seen: continue
        seen.add(key)
        
        from src.core.airports import CANDIDATE_DESTINATIONS
        dest_info = next((a for a in CANDIDATE_DESTINATIONS if a.iata == dest), None)
        city = dest_info.city if dest_info else dest
        flag = dest_info.flag if dest_info else "📍"
        
        fairness_label = "✅ Balanced" if fairness < 15 else "⚖️ Fair" if fairness < 30 else "⚠️ Lopsided"
        
        text += (
            f"{flag} **{city}** ({dest})\n"
            f"📅 {out} to {ret}\n"
            f"💰 €{total:.2f} | {fairness_label}\n"
            f"🅰️: €{a_p:.2f} | 🅱️: €{b_p:.2f}\n"
            f"🔗 [Book A]({link_a}) | [Book B]({link_b})\n\n"
        )
        
        count += 1
        if count >= 6: break
    
    await msg.reply_text(text, parse_mode='Markdown', disable_web_page_preview=True)
    
async def cmd_discover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    await msg.reply_text("Discovering...")
    _, _, providers = get_app_context()
    discover_mode(providers)
    await msg.reply_text("Done.")

async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    _, _, providers = get_app_context()
    text = "Health:\n"
    for p in providers:
        status = "OK" if p.is_healthy() else "Err"
        text += f"{p.name()}: {status}\n"
    await msg.reply_text(text)

async def cmd_selftest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    storage, notifier, providers = get_app_context()
    await msg.reply_text("Testing...")
    
    import io
    import contextlib
    f = io.StringIO()
    with contextlib.redirect_stdout(f):
        selftest(storage, notifier, providers)
    
    output = f.getvalue()
    await msg.reply_text(f"Result:\n\n`{output}`", parse_mode='Markdown')

if __name__ == '__main__':
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN not found.")
        exit(1)

    application = ApplicationBuilder().token(token).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("search", cmd_search))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("stop", cmd_stop))
    application.add_handler(CommandHandler("results", cmd_results))
    application.add_handler(CommandHandler("discover", cmd_discover))
    application.add_handler(CommandHandler("health", cmd_health))
    application.add_handler(CommandHandler("selftest", cmd_selftest))
    
    # Add callback handler for buttons
    application.add_handler(CallbackQueryHandler(button_handler))

    print("Bot is running... Press Ctrl+C to stop.")
    application.run_polling()
