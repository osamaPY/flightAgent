"""Custom scrapers — active: MultiGoogle (3-mode)."""

from src.scrapers.base import BaseScraper
from src.scrapers.multi_google import MultiModeGoogleScraper
from src.scrapers.engine import ScraperEngine

__all__ = ["BaseScraper", "MultiModeGoogleScraper", "ScraperEngine"]
