import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from dataclasses import dataclass
from typing import List, Tuple

load_dotenv()

@dataclass
class DateWindow:
    depart_earliest: str
    depart_latest: str
    min_nights: int
    max_nights: int

class Config:
    ORIGINS_A = ["BGY", "MXP", "LIN"]
    ORIGINS_B = ["RIX"] # Riga only as requested
    CURRENCY = "EUR"
    
    TARGET_PRICE_EUR = int(os.getenv("TARGET_PRICE_EUR", 200))
    SERPAPI_MONTHLY_BUDGET = int(os.getenv("SERPAPI_MONTHLY_BUDGET", 90))
    
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    TRAVELPAYOUTS_TOKEN = os.getenv("TRAVELPAYOUTS_TOKEN")
    SERPAPI_KEY = os.getenv("SERPAPI_KEY")
    RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
    FLIGHTAPI_KEY = os.getenv("FLIGHTAPI_KEY")
    DUFFEL_TOKEN = os.getenv("DUFFEL_TOKEN")

    @staticmethod
    def generate_weekend_windows(count: int = 8) -> List[DateWindow]:
        windows = []
        today = datetime.now()
        # Find next Friday
        days_until_friday = (4 - today.weekday() + 7) % 7
        if days_until_friday == 0:
            days_until_friday = 7
        
        first_friday = today + timedelta(days=days_until_friday)
        
        # If the first Friday is tomorrow or today, skip to the next week
        if (first_friday - today).days < 3:
            first_friday += timedelta(weeks=1)
            
        for i in range(count):
            friday = first_friday + timedelta(weeks=i)
            # Window: Depart Friday or Saturday, stay 2-4 nights
            windows.append(DateWindow(
                depart_earliest=friday.strftime("%Y-%m-%d"),
                depart_latest=(friday + timedelta(days=1)).strftime("%Y-%m-%d"),
                min_nights=2,
                max_nights=4
            ))
        return windows

DATE_WINDOWS = Config.generate_weekend_windows()
