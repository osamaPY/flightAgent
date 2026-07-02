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
    Airport("HEL", "Helsinki", "Helsinki", "Finland", "🇫🇮", 60.31, 24.96),
    Airport("ARN", "Stockholm Arlanda", "Stockholm", "Sweden", "🇸🇪", 59.65, 17.91),
    Airport("OSL", "Oslo Gardermoen", "Oslo", "Norway", "🇳🇴", 60.19, 11.10),
    Airport("MUC", "Munich", "Munich", "Germany", "🇩🇪", 48.35, 11.78),
    Airport("ZRH", "Zurich", "Zurich", "Switzerland", "🇨🇭", 47.45, 8.55),
    Airport("AMS", "Amsterdam Schiphol", "Amsterdam", "Netherlands", "🇳🇱", 52.31, 4.76),
    Airport("BRU", "Brussels", "Brussels", "Belgium", "🇧🇪", 50.90, 4.48),
    Airport("CDG", "Paris Charles de Gaulle", "Paris", "France", "🇫🇷", 49.01, 2.55),
    Airport("NCE", "Nice Côte d'Azur", "Nice", "France", "🇫🇷", 43.66, 7.21),
    Airport("MRS", "Marseille Provence", "Marseille", "France", "🇫🇷", 43.43, 5.21),
    Airport("LYS", "Lyon–Saint-Exupéry", "Lyon", "France", "🇫🇷", 45.72, 5.08),
    Airport("HAM", "Hamburg", "Hamburg", "Germany", "🇩🇪", 53.63, 9.98),
    Airport("DUS", "Düsseldorf", "Düsseldorf", "Germany", "🇩🇪", 51.28, 6.76),
    Airport("STR", "Stuttgart", "Stuttgart", "Germany", "🇩🇪", 48.69, 9.22),
    Airport("NAP", "Naples International", "Naples", "Italy", "🇮🇹", 40.88, 14.29),
    Airport("CTA", "Catania–Fontanarossa", "Catania", "Italy", "🇮🇹", 37.47, 15.06),
    Airport("PMO", "Palermo", "Palermo", "Italy", "🇮🇹", 38.18, 13.10),
    Airport("PSA", "Pisa International", "Pisa", "Italy", "🇮🇹", 43.68, 10.40),
    Airport("BLQ", "Bologna Guglielmo Marconi", "Bologna", "Italy", "🇮🇹", 44.53, 11.28),
    Airport("VNO", "Vilnius International", "Vilnius", "Lithuania", "🇱🇹", 54.64, 25.28),
    Airport("TLL", "Tallinn", "Tallinn", "Estonia", "🇪🇪", 59.41, 24.83),
    Airport("POZ", "Poznań–Ławica", "Poznań", "Poland", "🇵🇱", 52.42, 16.82),
    Airport("WRO", "Wrocław Copernicus", "Wrocław", "Poland", "🇵🇱", 51.10, 16.88),
    Airport("KRK", "Kraków John Paul II", "Kraków", "Poland", "🇵🇱", 50.08, 19.78),
    Airport("SKG", "Thessaloniki", "Thessaloniki", "Greece", "🇬🇷", 40.52, 22.97),
    Airport("HER", "Heraklion International", "Heraklion", "Greece", "🇬🇷", 35.34, 25.18),
    Airport("CFU", "Corfu International", "Corfu", "Greece", "🇬🇷", 39.61, 19.91),
    Airport("LPA", "Gran Canaria", "Gran Canaria", "Spain", "🇪🇸", 27.93, -15.38),
    Airport("TFS", "Tenerife South", "Tenerife", "Spain", "🇪🇸", 28.04, -16.57),
    Airport("SVQ", "Seville", "Seville", "Spain", "🇪🇸", 37.42, -5.89),
    Airport("ALC", "Alicante–Elche", "Alicante", "Spain", "🇪🇸", 38.28, -0.56),
    Airport("BIO", "Bilbao", "Bilbao", "Spain", "🇪🇸", 43.30, -2.91),
]

def get_destinations(exclude_iatas: List[str]) -> List[Airport]:
    # Ensure origins are always excluded
    return [a for a in CANDIDATE_DESTINATIONS if a.iata not in exclude_iatas]

def load_europe_airports_from_ourairports():
    pass
