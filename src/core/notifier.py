import requests
from src.core.scoring import MeetupResult, generate_booking_link
from src.clients.weather_client import WeatherClient
from src.core.airports import CANDIDATE_DESTINATIONS

class Notifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self.weather = WeatherClient()

    def format_alert(self, result: MeetupResult) -> str:
        # Generate direct booking links
        link_a = generate_booking_link(result.a_origin, result.destination, result.outbound_date, result.return_date)
        link_b = generate_booking_link(result.b_origin, result.destination, result.outbound_date, result.return_date)
        
        dest_display = f"{result.dest_flag} {result.dest_city}, {result.dest_country} ({result.destination})"
        fairness = "✅ Fair Deal" if result.fairness_penalty < 15 else "⚖️ Balanced" if result.fairness_penalty < 30 else "⚠️ Lopsided"
        
        # Weather fetch
        weather_text = ""
        dest_info = next((a for a in CANDIDATE_DESTINATIONS if a.iata == result.destination), None)
        if dest_info:
            forecast = self.weather.get_forecast(dest_info.lat, dest_info.lon, result.outbound_date)
            if forecast:
                weather_text = f"🌤 **Weather:** {forecast}\n"

        return (
            f"📍 **{dest_display}**\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 **Total: €{result.total_price:.2f}** ({fairness})\n\n"
            f"{weather_text}"
            f"👨‍💻 **Milan ({result.a_origin}):** €{result.a_price:.2f} — [Book]({link_a})\n"
            f"👩‍💼 **Riga ({result.b_origin}):** €{result.b_price:.2f} — [Book]({link_b})\n\n"
            f"📅 **{result.outbound_date} ➔ {result.return_date}**\n"
            f"⏳ Landing Gap: {result.arrival_gap_hours}h\n"
            f"🔌 Source: {result.source}\n"
            f"⚠️ Verify manually before booking."
        )

    def format_results_list(self, results: list) -> str:
        if not results:
            return "📭 No results found."
        
        text = "📊 **Top 10 Fair Deals:**\n\n"
        for i, res in enumerate(results[:10]):
            fairness = "✅" if res.fairness_penalty < 15 else "⚖️" if res.fairness_penalty < 30 else "⚠️"
            text += f"{i+1}. {res.dest_flag} **{res.dest_city}** — €{res.total_price:.2f} {fairness}\n"
            text += f"   📅 {res.outbound_date} | 🔌 {res.source}\n\n"
        
        text += "Use /results to see more or /search to refresh."
        return text

    def send_message(self, text: str):
        if not self.bot_token or not self.chat_id:
            print("Telegram config missing, skipping notification.")
            return
        
        try:
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True
            }
            requests.post(self.base_url, json=payload, timeout=10)
        except Exception as e:
            print(f"Failed to send Telegram message: {e}")

if __name__ == "__main__":
    print("Notifier updated with readable format.")
