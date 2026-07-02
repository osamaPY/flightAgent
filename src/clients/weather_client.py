import requests
from typing import Optional, Dict, Any
from datetime import datetime

class WeatherClient:
    """
    Client for Open-Meteo (Free, No Key required).
    Provides 7-day weather forecasts for meetup cities.
    """
    def __init__(self):
        self.base_url = "https://api.open-meteo.com/v1/forecast"

    def get_forecast(self, lat: float, lon: float, date: str) -> Optional[str]:
        """
        Retrieves forecast for a specific date (YYYY-MM-DD).
        If date is beyond 7 days, returns a general climatology estimate or None.
        """
        if lat == 0.0 and lon == 0.0:
            return None

        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            "timezone": "auto"
        }

        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            daily = data.get("daily", {})
            dates = daily.get("time", [])
            
            if date in dates:
                idx = dates.index(date)
                code = daily.get("weather_code", [])[idx]
                t_max = daily.get("temperature_2m_max", [])[idx]
                t_min = daily.get("temperature_2m_min", [])[idx]
                
                condition = self._interpret_code(code)
                return f"{condition} ({t_min}°C to {t_max}°C)"
            else:
                return "Forecast unavailable (too far out)"
        except Exception:
            return None

    def _interpret_code(self, code: int) -> str:
        """Translates WMO weather codes to human-readable strings."""
        codes = {
            0: "Clear sky ☀️",
            1: "Mainly clear 🌤", 2: "Partly cloudy ⛅️", 3: "Overcast ☁️",
            45: "Foggy 🌫", 48: "Depositing rime fog 🌫",
            51: "Light drizzle 🌦", 53: "Moderate drizzle 🌦", 55: "Dense drizzle 🌦",
            61: "Slight rain 🌧", 63: "Moderate rain 🌧", 65: "Heavy rain 🌧",
            71: "Slight snow ❄️", 73: "Moderate snow ❄️", 75: "Heavy snow ❄️",
            77: "Snow grains ❄️",
            80: "Slight rain showers 🌦", 81: "Moderate rain showers 🌦", 82: "Violent rain showers 🌧",
            85: "Slight snow showers ❄️", 86: "Heavy snow showers ❄️",
            95: "Thunderstorm ⛈", 96: "TS with slight hail ⛈", 99: "TS with heavy hail ⛈"
        }
        return codes.get(code, "Unknown")

if __name__ == "__main__":
    client = WeatherClient()
    # Test for Brussels
    res = client.get_forecast(50.46, 4.45, datetime.now().strftime("%Y-%m-%d"))
    print(f"Weather in Brussels today: {res}")
