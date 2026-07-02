from dataclasses import dataclass
from typing import List

@dataclass
class Airport:
    iata: str
    name: str
    city: str
    country: str
    flag: str
    lat: float = 0.0
    lon: float = 0.0

# COMMON DESTINATIONS SERVED BY RYANAIR FROM BOTH MILAN AND RIGA
CANDIDATE_DESTINATIONS = [
    Airport("BGY", "Milan Bergamo", "Milan", "Italy", "🇮🇹", 45.67, 9.70),
    Airport("MXP", "Milan Malpensa", "Milan", "Italy", "🇮🇹", 45.63, 8.72),
    Airport("LIN", "Milan Linate", "Milan", "Italy", "🇮🇹", 45.45, 9.28),
    Airport("CRL", "Brussels Charleroi", "Brussels", "Belgium", "🇧🇪", 50.46, 4.45),
    Airport("BER", "Berlin Brandenburg", "Berlin", "Germany", "🇩🇪", 52.37, 13.50),
    Airport("VIE", "Vienna International", "Vienna", "Austria", "🇦🇹", 48.11, 16.56),
    Airport("BUD", "Budapest Ferenc Liszt", "Budapest", "Hungary", "🇭🇺", 47.43, 19.26),
    Airport("PRG", "Prague Václav Havel", "Prague", "Czech Republic", "🇨🇿", 50.10, 14.26),
    Airport("WAW", "Warsaw Chopin", "Warsaw", "Poland", "🇵🇱", 52.17, 20.97),
    Airport("CPH", "Copenhagen", "Copenhagen", "Denmark", "🇩🇰", 55.62, 12.65),
    Airport("BCN", "Barcelona–El Prat", "Barcelona", "Spain", "🇪🇸", 41.30, 2.08),
    Airport("MAD", "Madrid–Barajas", "Madrid", "Spain", "🇪🇸", 40.49, -3.57),
    Airport("FRA", "Frankfurt", "Frankfurt", "Germany", "🇩🇪", 50.03, 8.57),
    Airport("BVA", "Paris Beauvais", "Paris", "France", "🇫🇷", 49.45, 2.11),
    Airport("LIS", "Lisbon", "Lisbon", "Portugal", "🇵🇹", 38.77, -9.14),
    Airport("OPO", "Porto", "Porto", "Portugal", "🇵🇹", 41.24, -8.68),
    Airport("AGP", "Málaga", "Málaga", "Spain", "🇪🇸", 36.67, -4.50),
    Airport("ATH", "Athens International", "Athens", "Greece", "🇬🇷", 37.94, 23.94),
    Airport("RIX", "Riga International", "Riga", "Latvia", "🇱🇻", 56.92, 23.97),
    Airport("TSF", "Treviso", "Venice", "Italy", "🇮🇹", 45.65, 12.20),
    Airport("VLC", "Valencia", "Valencia", "Spain", "🇪🇸", 39.49, -0.48),
    Airport("PMI", "Palma de Mallorca", "Palma", "Spain", "🇪🇸", 39.55, 2.73),
    Airport("VCE", "Venice Marco Polo", "Venice", "Italy", "🇮🇹", 45.51, 12.35),
]

def get_destinations(exclude_iatas: List[str]) -> List[Airport]:
    # Ensure origins are always excluded
    return [a for a in CANDIDATE_DESTINATIONS if a.iata not in exclude_iatas]

def load_europe_airports_from_ourairports():
    pass
