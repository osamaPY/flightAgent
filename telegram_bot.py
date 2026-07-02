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
        [InlineKeyboardButton("🚀 Start Search (Fast/Free)", callback_data='search')],
        [InlineKeyboardButton("✅ Verify Best Deals (Paid)", callback_data='verify')],
        [InlineKeyboardButton("📜 View Latest Results", callback_data='results')],
        [InlineKeyboardButton("📊 Check Status", callback_data='status')],
        [InlineKeyboardButton("🛑 Stop Search", callback_data='stop')],
        [InlineKeyboardButton("📊 View Logs", callback_data='logs')],
        [InlineKeyboardButton("🏥 Health Check", callback_data='health'), 
         InlineKeyboardButton("🛠 Selftest", callback_data='selftest')],
        [InlineKeyboardButton("🔎 Discover Cities", callback_data='discover')],
        [InlineKeyboardButton("🧹 Clear History", callback_data='clear')]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.core.config import Config
    origins_b = ", ".join(Config.ORIGINS_B)
    welcome_text = (
        "✈️ **Welcome to Flight Meet Agent!**\n\n"
        f"I can help you find the cheapest European cities to meet with your friend from {origins_b}.\n\n"
        "Use the buttons below to control the agent:"
    )
    reply_markup = await get_menu_keyboard()
    await update.message.reply_text(welcome_text, parse_mode='Markdown', reply_markup=reply_markup)

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
    await msg.reply_text("🧹 Database results cleared! Ready for a fresh start.")

async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if context.bot_data.get("search_active"):
        await msg.reply_text("🚨 A search is already running! Use /status to check progress or /stop to abort.")
        return

    await msg.reply_text("🚀 Starting full scan! I will update you every 5 cities and notify you when finished.")
    storage, notifier, providers = get_app_context()
    
    # Use bot_data for global search state
    context.bot_data["search_active"] = True
    context.bot_data["current_city"] = "Initializing..."
    context.bot_data["progress"] = "0/0"
    SEARCH_STOP_EVENT.clear()

    def progress_callback(current, total, city):
        context.bot_data["current_city"] = city
        context.bot_data["progress"] = f"{current}/{total}"
        # Update user every 5 cities to avoid spamming but show bot is alive
        if current == 1 or current % 5 == 0 or current == total:
            notifier.send_message(f"🛰 **Progress Update:** Scanning city {current} of {total} ({city})...")

    async def run_scan():
        try:
            await asyncio.to_thread(monitor_mode, storage, notifier, providers, progress_callback)
            if not SEARCH_STOP_EVENT.is_set():
                await update.effective_message.reply_text("✅ Scan completed successfully! Use 'View Latest Results' button to see them.")
        except Exception as e:
            await update.effective_message.reply_text(f"❌ Error during scan: {e}")
        finally:
            context.bot_data["search_active"] = False

    asyncio.create_task(run_scan())

async def cmd_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    await msg.reply_text("🔎 **Verification Started:** I'm re-checking the top 5 candidates with paid APIs (SerpApi/Google Flights). This may take a minute...")
    
    storage, notifier, providers = get_app_context()
    
    async def run_verify():
        try:
            await asyncio.to_thread(verify_mode, storage, notifier, providers)
            await msg.reply_text("✅ Verification finished! Check the messages above for confirmed deals.")
        except Exception as e:
            await msg.reply_text(f"❌ Error during verification: {e}")

    asyncio.create_task(run_verify())

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not context.bot_data.get("search_active"):
        await msg.reply_text("ℹ️ No active search running.")
        return
    
    city = context.bot_data.get("current_city", "Unknown")
    prog = context.bot_data.get("progress", "0/0")
    await msg.reply_text(f"📊 **Current Status:**\n• Progress: {prog} cities\n• Currently Scanning: {city}\n\nUse /stop to abort.")

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not context.bot_data.get("search_active"):
        await msg.reply_text("ℹ️ No active search to stop.")
        return
    
    SEARCH_STOP_EVENT.set()
    await msg.reply_text("🛑 Cancellation signal sent. The bot will stop after the current airport scan (within ~30s).")

async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    logs = get_recent_logs(25)
    await msg.reply_text(f"📊 **Recent Activity Logs:**\n\n```\n{logs}\n```", parse_mode='Markdown')

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
        await msg.reply_text(f"❌ Database error: {e}. Try running a search first.")
        return
    
    if not rows:
        await msg.reply_text("No recent results found. Try running /search first.")
        return

    text = "📊 **Best Fair Meetup Results:**\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    seen = set()
    count = 0
    for row in rows:
        dest, total, out, ret, a_org, a_p, b_org, b_p, gap, fairness = row
        
        # Deduplicate identical route+date
        key = (dest, out, ret)
        if key in seen: continue
        seen.add(key)
        
        # Lookup metadata
        dest_info = next((a for a in CANDIDATE_DESTINATIONS if a.iata == dest), None)
        flag = dest_info.flag if dest_info else "📍"
        city = dest_info.city if dest_info else dest
        country = dest_info.country if dest_info else ""
        
        link_a = generate_booking_link(a_org, dest, out, ret)
        link_b = generate_booking_link(b_org, dest, out, ret)
        
        fairness_label = "Balanced ⚖️" if fairness < 15 else "Fair ⚖️" if fairness < 30 else "Lopsided ⚖️"
        
        text += (
            f"{flag} **{city}, {country}** ({dest})\n"
            f"📅 {out} to {ret}\n"
            f"💰 **Total: €{total:.2f}** | {fairness_label}\n"
            f"👤 Me ({a_org}): €{a_p:.2f} | 👤 Her: €{b_p:.2f}\n"
            f"⏱️ Gap: {gap}h | 🔗 [Book Me]({link_a}) | [Book Her]({link_b})\n"
            f"─────────────────────\n"
        )
        
        count += 1
        if count >= 6: break # Show top 6 to keep message size readable
    
    text += "\n⚠️ *Prices fluctuate. Verify manually.*"
    await msg.reply_text(text, parse_mode='Markdown', disable_web_page_preview=True)
    
async def cmd_discover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    await msg.reply_text("🔎 Fetching new shared destinations from Travelpayouts...")
    _, _, providers = get_app_context()
    # This mode normally prints to stdout, we'll just confirm it ran
    discover_mode(providers)
    await msg.reply_text("✅ Discovery finished. Shared routes are tracked in the scan engine.")

async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    _, _, providers = get_app_context()
    text = "🏥 **Provider Health Check:**\n"
    for p in providers:
        status = "✅ Healthy" if p.is_healthy() else "❌ Offline/Error"
        text += f"• {p.name()}: {status}\n"
    await msg.reply_text(text, parse_mode='Markdown')

async def cmd_selftest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    storage, notifier, providers = get_app_context()
    await msg.reply_text("🛠 Running full system diagnostic... please wait.")
    
    # Capture stdout of selftest
    import io
    import contextlib
    f = io.StringIO()
    with contextlib.redirect_stdout(f):
        selftest(storage, notifier, providers)
    
    output = f.getvalue()
    await msg.reply_text(f"🛠 **System Selftest Results:**\n\n`{output}`", parse_mode='Markdown')

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
