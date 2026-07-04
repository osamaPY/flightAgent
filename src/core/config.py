import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from dataclasses import dataclass
from typing import List, Tuple, Optional

load_dotenv()

@dataclass
class DateWindow:
    depart_earliest: str
    depart_latest: str
    min_nights: int
    max_nights: int

class Config:
    # ── v6: no more hardcoded origins ──
    # Origins are now per-search via SearchRequest (src/core/search_request.py).
    # These remain as CONVENIENCE DEFAULTS only - used when no SearchRequest is provided
    # (CLI menu, backward compat, scripts).
    DEFAULT_ORIGINS_A = ["BGY", "MXP", "LIN"]
    DEFAULT_ORIGINS_B = ["RIX"]

    CURRENCY = "EUR"

    TARGET_PRICE_EUR = int(os.getenv("TARGET_PRICE_EUR", 200))
    MAX_API_CALLS_PER_RUN = int(os.getenv("MAX_API_CALLS_PER_RUN", 300))

    # ── Telegram ──
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

    # ── Duffel (optional paid GDS provider) ──
    DUFFEL_TOKEN = os.getenv("DUFFEL_TOKEN")

    # ── DeepSeek LLM (optional AI concierge in the Telegram bot) ──
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # ── API auth (future; not central to the current bot) ──
    JWT_SECRET = os.getenv("JWT_SECRET", "")
    JWT_ALGORITHM = "HS256"
    JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "30"))

    @staticmethod
    def generate_date_windows(
        start: str = "2026-07-15",
        end: str = "2026-08-12",
        min_nights: int = 2,
        max_nights: int = 4,
    ) -> List[DateWindow]:
        """Generate 1-week DateWindow chunks for any date range.

        v6: Fully parameterized - no hardcoded dates.
        """
        windows = []
        start_dt = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")

        current = start_dt
        while current <= end_dt:
            chunk_end = current + timedelta(days=6)
            if chunk_end > end_dt:
                chunk_end = end_dt
            windows.append(DateWindow(
                depart_earliest=current.strftime("%Y-%m-%d"),
                depart_latest=chunk_end.strftime("%Y-%m-%d"),
                min_nights=min_nights,
                max_nights=max_nights,
            ))
            current = chunk_end + timedelta(days=1)

        return windows

    @staticmethod
    def generate_holiday_windows() -> List[DateWindow]:
        """Backward-compatible: the original Jul 15 - Aug 12, 2026 holiday windows."""
        return Config.generate_date_windows(
            start="2026-07-15",
            end="2026-08-12",
            min_nights=2,
            max_nights=4,
        )

# Backward-compatible module-level constant (used by scripts that haven't been updated yet)
DATE_WINDOWS = Config.generate_holiday_windows()

# Deprecated aliases - kept for scripts that still reference them.
# New code should use SearchRequest from src.core.search_request.
ORIGINS_A = Config.DEFAULT_ORIGINS_A
ORIGINS_B = Config.DEFAULT_ORIGINS_B
