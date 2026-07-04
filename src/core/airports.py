from dataclasses import dataclass
from typing import List, Optional

@dataclass
class Airport:
    iata: str
    name: str
    city: str
    country: str
    flag: str
    lat: float = 0.0
    lon: float = 0.0

SCHENGEN_COUNTRIES = {
    "Austria", "Belgium", "Bulgaria", "Croatia", "Czech Republic",
    "Denmark", "Estonia", "Finland", "France", "Germany", "Greece",
    "Hungary", "Iceland", "Italy", "Latvia", "Liechtenstein", "Lithuania",
    "Luxembourg", "Malta", "Netherlands", "Norway", "Poland",
    "Portugal", "Romania", "Slovakia", "Slovenia", "Spain", "Sweden", "Switzerland",
}

# All European countries (Schengen + non-Schengen) for "europe" universe
EUROPE_COUNTRIES = SCHENGEN_COUNTRIES | {
    "United Kingdom", "Ireland", "Turkey", "Ukraine", "Moldova",
    "Serbia", "Bosnia and Herzegovina", "North Macedonia", "Montenegro",
    "Albania", "Belarus", "Russia", "Georgia", "Armenia", "Azerbaijan",
    "Kosovo", "Cyprus", "Andorra", "Monaco", "San Marino", "Vatican City",
    "Israel", "Morocco", "Tunisia", "Egypt",
}

# ═════════════════════════════════════════════════════════════════════════
# ALL EUROPEAN AIRPORTS — Schengen + non-Schengen
# 160+ airports across 40+ countries. No hardcoded exclusions.
# ═════════════════════════════════════════════════════════════════════════

CANDIDATE_DESTINATIONS = [
    # ── SCHENGEN (original 122 + expansion) ──
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
    Airport("ORY", "Paris Orly", "Paris", "France", "🇫🇷", 48.73, 2.36),
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
    Airport("FCO", "Rome Fiumicino", "Rome", "Italy", "🇮🇹", 41.80, 12.23),
    Airport("CIA", "Rome Ciampino", "Rome", "Italy", "🇮🇹", 41.80, 12.59),
    Airport("MLA", "Malta", "Malta", "Malta", "🇲🇹", 35.85, 14.47),
    Airport("GVA", "Geneva", "Geneva", "Switzerland", "🇨🇭", 46.23, 6.10),
    Airport("LUX", "Luxembourg", "Luxembourg", "Luxembourg", "🇱🇺", 49.62, 6.20),
    Airport("BTS", "Bratislava", "Bratislava", "Slovakia", "🇸🇰", 48.17, 17.21),
    Airport("LJU", "Ljubljana", "Ljubljana", "Slovenia", "🇸🇮", 46.22, 14.45),
    Airport("IBZ", "Ibiza", "Ibiza", "Spain", "🇪🇸", 38.87, 1.37),
    Airport("MAH", "Menorca", "Menorca", "Spain", "🇪🇸", 39.86, 4.21),
    Airport("RHO", "Rhodes", "Rhodes", "Greece", "🇬🇷", 36.40, 28.08),
    Airport("JTR", "Santorini", "Santorini", "Greece", "🇬🇷", 36.40, 25.47),
    Airport("JMK", "Mykonos", "Mykonos", "Greece", "🇬🇷", 37.43, 25.34),
    Airport("ZAD", "Zadar", "Zadar", "Croatia", "🇭🇷", 44.10, 15.34),
    Airport("SPU", "Split", "Split", "Croatia", "🇭🇷", 43.53, 16.29),
    Airport("DBV", "Dubrovnik", "Dubrovnik", "Croatia", "🇭🇷", 42.56, 18.26),
    Airport("TRN", "Turin", "Turin", "Italy", "🇮🇹", 45.20, 7.65),
    Airport("GOA", "Genoa", "Genoa", "Italy", "🇮🇹", 44.41, 8.85),
    Airport("VRN", "Verona", "Verona", "Italy", "🇮🇹", 45.40, 10.89),
    Airport("TRS", "Trieste", "Trieste", "Italy", "🇮🇹", 45.83, 13.47),
    Airport("BDS", "Brindisi", "Brindisi", "Italy", "🇮🇹", 40.66, 17.95),
    Airport("SUF", "Lamezia Terme", "Lamezia", "Italy", "🇮🇹", 38.91, 16.24),
    Airport("CAG", "Cagliari", "Cagliari", "Italy", "🇮🇹", 39.25, 9.06),
    Airport("OLB", "Olbia Costa Smeralda", "Olbia", "Italy", "🇮🇹", 40.90, 9.52),
    Airport("AHO", "Alghero", "Alghero", "Italy", "🇮🇹", 40.63, 8.29),
    Airport("PEG", "Perugia", "Perugia", "Italy", "🇮🇹", 43.09, 12.51),
    Airport("AOI", "Ancona", "Ancona", "Italy", "🇮🇹", 43.62, 13.36),
    Airport("TLS", "Toulouse–Blagnac", "Toulouse", "France", "🇫🇷", 43.63, 1.37),
    Airport("BOD", "Bordeaux–Mérignac", "Bordeaux", "France", "🇫🇷", 44.83, -0.72),
    Airport("NTE", "Nantes Atlantique", "Nantes", "France", "🇫🇷", 47.16, -1.61),
    Airport("MPL", "Montpellier–Méditerranée", "Montpellier", "France", "🇫🇷", 43.58, 3.96),
    Airport("BIA", "Bastia – Poretta", "Bastia", "France", "🇫🇷", 42.55, 9.49),
    Airport("SCQ", "Santiago de Compostela", "Santiago", "Spain", "🇪🇸", 42.90, -8.42),
    Airport("VGO", "Vigo–Peinador", "Vigo", "Spain", "🇪🇸", 42.23, -8.63),
    Airport("OVD", "Asturias", "Oviedo", "Spain", "🇪🇸", 43.56, -6.03),
    Airport("SDR", "Santander", "Santander", "Spain", "🇪🇸", 43.43, -3.82),
    Airport("VIT", "Vitoria", "Vitoria", "Spain", "🇪🇸", 42.88, -2.72),
    Airport("GRO", "Girona–Costa Brava", "Girona", "Spain", "🇪🇸", 41.90, 2.76),
    Airport("REU", "Reus", "Reus", "Spain", "🇪🇸", 41.15, 1.17),
    Airport("RMU", "Región de Murcia", "Murcia", "Spain", "🇪🇸", 37.80, -1.12),
    Airport("LEI", "Almería", "Almería", "Spain", "🇪🇸", 36.85, -2.37),
    Airport("XRY", "Jerez", "Jerez", "Spain", "🇪🇸", 36.74, -6.06),
    Airport("ACE", "Lanzarote", "Lanzarote", "Spain", "🇪🇸", 28.95, -13.61),
    Airport("FUE", "Fuerteventura", "Fuerteventura", "Spain", "🇪🇸", 28.45, -13.87),
    Airport("SPC", "La Palma", "La Palma", "Spain", "🇪🇸", 28.63, -17.76),
    Airport("CGN", "Cologne Bonn", "Cologne", "Germany", "🇩🇪", 50.87, 7.14),
    Airport("FKB", "Karlsruhe/Baden-Baden", "Karlsruhe", "Germany", "🇩🇪", 48.78, 8.08),
    Airport("BRE", "Bremen", "Bremen", "Germany", "🇩🇪", 53.05, 8.79),
    Airport("HAJ", "Hanover", "Hanover", "Germany", "🇩🇪", 52.46, 9.68),
    Airport("LEJ", "Leipzig/Halle", "Leipzig", "Germany", "🇩🇪", 51.42, 12.24),
    Airport("NUE", "Nuremberg", "Nuremberg", "Germany", "🇩🇪", 49.50, 11.08),
    Airport("GDN", "Gdańsk Lech Wałęsa", "Gdańsk", "Poland", "🇵🇱", 54.38, 18.47),
    Airport("KTW", "Katowice", "Katowice", "Poland", "🇵🇱", 50.47, 19.08),
    Airport("WMI", "Warsaw Modlin", "Warsaw", "Poland", "🇵🇱", 52.45, 20.65),
    Airport("RZE", "Rzeszów–Jasionka", "Rzeszów", "Poland", "🇵🇱", 50.11, 22.02),
    Airport("SZZ", "Solidarity Szczecin–Goleniów", "Szczecin", "Poland", "🇵🇱", 53.58, 14.90),
    Airport("BZG", "Bydgoszcz", "Bydgoszcz", "Poland", "🇵🇱", 53.10, 17.98),
    Airport("LUZ", "Lublin", "Lublin", "Poland", "🇵🇱", 51.24, 22.71),
    Airport("GOT", "Göteborg Landvetter", "Gothenburg", "Sweden", "🇸🇪", 57.66, 12.29),
    Airport("BLL", "Billund", "Billund", "Denmark", "🇩🇰", 55.74, 9.15),
    Airport("AAL", "Aalborg", "Aalborg", "Denmark", "🇩🇰", 57.09, 9.85),
    Airport("TMP", "Tampere–Pirkkala", "Tampere", "Finland", "🇫🇮", 61.41, 23.60),
    Airport("TKU", "Turku", "Turku", "Finland", "🇫🇮", 60.51, 22.26),
    Airport("EIN", "Eindhoven", "Eindhoven", "Netherlands", "🇳🇱", 51.46, 5.37),
    Airport("MST", "Maastricht Aachen", "Maastricht", "Netherlands", "🇳🇱", 50.91, 5.77),
    Airport("RTM", "Rotterdam The Hague", "Rotterdam", "Netherlands", "🇳🇱", 51.96, 4.44),
    Airport("BSL", "EuroAirport Basel Mulhouse", "Basel", "Switzerland", "🇨🇭", 47.59, 7.53),
    Airport("SZG", "Salzburg", "Salzburg", "Austria", "🇦🇹", 47.79, 13.00),
    Airport("GRZ", "Graz", "Graz", "Austria", "🇦🇹", 47.00, 15.43),
    Airport("INN", "Innsbruck", "Innsbruck", "Austria", "🇦🇹", 47.26, 11.34),
    Airport("KLU", "Klagenfurt", "Klagenfurt", "Austria", "🇦🇹", 46.64, 14.34),
    Airport("ZAG", "Zagreb", "Zagreb", "Croatia", "🇭🇷", 45.74, 16.07),
    Airport("PUY", "Pula", "Pula", "Croatia", "🇭🇷", 44.89, 13.92),
    Airport("RJK", "Rijeka", "Rijeka", "Croatia", "🇭🇷", 45.22, 14.57),
    Airport("SOF", "Sofia", "Sofia", "Bulgaria", "🇧🇬", 42.70, 23.41),
    Airport("VAR", "Varna", "Varna", "Bulgaria", "🇧🇬", 43.23, 27.83),
    Airport("BOJ", "Burgas", "Burgas", "Bulgaria", "🇧🇬", 42.57, 27.52),
    Airport("OTP", "Bucharest Henri Coandă", "Bucharest", "Romania", "🇷🇴", 44.57, 26.10),
    Airport("CLJ", "Cluj-Napoca", "Cluj-Napoca", "Romania", "🇷🇴", 46.79, 23.69),
    Airport("TSR", "Timișoara", "Timișoara", "Romania", "🇷🇴", 45.81, 21.34),
    Airport("IAS", "Iași", "Iași", "Romania", "🇷🇴", 47.18, 27.62),
    Airport("TRD", "Trondheim", "Trondheim", "Norway", "🇳🇴", 63.45, 10.92),
    Airport("BGO", "Bergen", "Bergen", "Norway", "🇳🇴", 60.29, 5.22),
    Airport("SVG", "Stavanger", "Stavanger", "Norway", "🇳🇴", 58.88, 5.64),
    Airport("TOS", "Tromsø", "Tromsø", "Norway", "🇳🇴", 69.68, 18.92),
    Airport("FAO", "Faro", "Faro", "Portugal", "🇵🇹", 37.01, -7.97),
    Airport("FNC", "Madeira", "Funchal", "Portugal", "🇵🇹", 32.70, -16.77),
    Airport("PDL", "Ponta Delgada", "Ponta Delgada", "Portugal", "🇵🇹", 37.74, -25.70),
    Airport("MMX", "Malmö", "Malmö", "Sweden", "🇸🇪", 55.54, 13.37),
    Airport("NYO", "Stockholm Skavsta", "Stockholm", "Sweden", "🇸🇪", 58.79, 16.91),
    Airport("VST", "Stockholm Västerås", "Stockholm", "Sweden", "🇸🇪", 59.59, 16.63),
    Airport("LLA", "Luleå", "Luleå", "Sweden", "🇸🇪", 65.54, 22.12),
    Airport("SXB", "Strasbourg", "Strasbourg", "France", "🇫🇷", 48.54, 7.63),
    Airport("LIL", "Lille", "Lille", "France", "🇫🇷", 50.56, 3.09),
    Airport("RNS", "Rennes", "Rennes", "France", "🇫🇷", 48.07, -1.73),
    Airport("ETZ", "Metz-Nancy-Lorraine", "Metz", "France", "🇫🇷", 48.98, 6.25),
    Airport("PUF", "Pau", "Pau", "France", "🇫🇷", 43.38, -0.42),
    Airport("CFE", "Clermont-Ferrand", "Clermont-Ferrand", "France", "🇫🇷", 45.78, 3.16),
    Airport("LDE", "Lourdes/Tarbes", "Lourdes", "France", "🇫🇷", 43.18, -0.00),
    Airport("EGC", "Bergerac", "Bergerac", "France", "🇫🇷", 44.82, 0.52),
    Airport("RDZ", "Rodez", "Rodez", "France", "🇫🇷", 44.41, 2.48),
    Airport("LRH", "La Rochelle", "La Rochelle", "France", "🇫🇷", 46.18, -1.20),
    Airport("CMF", "Chambéry", "Chambéry", "France", "🇫🇷", 45.64, 5.88),
    Airport("LGG", "Liège", "Liège", "Belgium", "🇧🇪", 50.64, 5.44),
    Airport("OST", "Ostend–Bruges", "Ostend", "Belgium", "🇧🇪", 51.20, 2.87),
    Airport("ANR", "Antwerp", "Antwerp", "Belgium", "🇧🇪", 51.19, 4.46),
    Airport("DRS", "Dresden", "Dresden", "Germany", "🇩🇪", 51.13, 13.77),
    Airport("DTM", "Dortmund", "Dortmund", "Germany", "🇩🇪", 51.52, 7.61),
    Airport("FMM", "Memmingen", "Memmingen", "Germany", "🇩🇪", 47.99, 10.24),
    Airport("HHN", "Frankfurt–Hahn", "Hahn", "Germany", "🇩🇪", 49.95, 7.26),
    Airport("NRN", "Weeze", "Weeze", "Germany", "🇩🇪", 51.60, 6.14),
    Airport("SCN", "Saarbrücken", "Saarbrücken", "Germany", "🇩🇪", 49.21, 7.11),
    Airport("ERF", "Erfurt–Weimar", "Erfurt", "Germany", "🇩🇪", 50.98, 10.96),
    Airport("PAD", "Paderborn/Lippstadt", "Paderborn", "Germany", "🇩🇪", 51.62, 8.62),
    Airport("LBC", "Lübeck", "Lübeck", "Germany", "🇩🇪", 53.81, 10.72),
    Airport("GWT", "Sylt", "Sylt", "Germany", "🇩🇪", 54.91, 8.34),
    Airport("LCA", "Larnaca", "Larnaca", "Cyprus", "🇨🇾", 34.88, 33.62),
    Airport("PFO", "Paphos", "Paphos", "Cyprus", "🇨🇾", 34.72, 32.48),
    Airport("CHQ", "Chania", "Chania", "Greece", "🇬🇷", 35.53, 24.15),
    Airport("KGS", "Kos", "Kos", "Greece", "🇬🇷", 36.79, 27.09),
    Airport("ZTH", "Zakynthos", "Zakynthos", "Greece", "🇬🇷", 37.75, 20.88),
    Airport("EFL", "Kefalonia", "Kefalonia", "Greece", "🇬🇷", 38.12, 20.50),
    Airport("GPA", "Patras", "Patras", "Greece", "🇬🇷", 38.15, 21.43),

    # ── NON-SCHENGEN EUROPE ──

    # United Kingdom
    Airport("LHR", "London Heathrow", "London", "United Kingdom", "🇬🇧", 51.47, -0.46),
    Airport("LGW", "London Gatwick", "London", "United Kingdom", "🇬🇧", 51.15, -0.18),
    Airport("STN", "London Stansted", "London", "United Kingdom", "🇬🇧", 51.88, 0.24),
    Airport("LTN", "London Luton", "London", "United Kingdom", "🇬🇧", 51.87, -0.37),
    Airport("LCY", "London City", "London", "United Kingdom", "🇬🇧", 51.50, 0.05),
    Airport("MAN", "Manchester", "Manchester", "United Kingdom", "🇬🇧", 53.35, -2.28),
    Airport("BHX", "Birmingham", "Birmingham", "United Kingdom", "🇬🇧", 52.45, -1.75),
    Airport("EDI", "Edinburgh", "Edinburgh", "United Kingdom", "🇬🇧", 55.95, -3.37),
    Airport("GLA", "Glasgow", "Glasgow", "United Kingdom", "🇬🇧", 55.87, -4.43),
    Airport("BRS", "Bristol", "Bristol", "United Kingdom", "🇬🇧", 51.38, -2.72),
    Airport("LPL", "Liverpool", "Liverpool", "United Kingdom", "🇬🇧", 53.33, -2.85),
    Airport("NCL", "Newcastle", "Newcastle", "United Kingdom", "🇬🇧", 55.04, -1.69),
    Airport("LBA", "Leeds Bradford", "Leeds", "United Kingdom", "🇬🇧", 53.87, -1.66),
    Airport("BFS", "Belfast International", "Belfast", "United Kingdom", "🇬🇧", 54.66, -6.22),
    Airport("BHD", "Belfast City", "Belfast", "United Kingdom", "🇬🇧", 54.62, -5.87),
    Airport("CWL", "Cardiff", "Cardiff", "United Kingdom", "🇬🇧", 51.40, -3.34),
    Airport("SOU", "Southampton", "Southampton", "United Kingdom", "🇬🇧", 50.95, -1.36),
    Airport("ABZ", "Aberdeen", "Aberdeen", "United Kingdom", "🇬🇧", 57.20, -2.20),
    Airport("BOH", "Bournemouth", "Bournemouth", "United Kingdom", "🇬🇧", 50.78, -1.84),
    Airport("EMA", "East Midlands", "Nottingham", "United Kingdom", "🇬🇧", 52.83, -1.33),
    Airport("MME", "Teesside", "Darlington", "United Kingdom", "🇬🇧", 54.51, -1.43),
    Airport("EXT", "Exeter", "Exeter", "United Kingdom", "🇬🇧", 50.73, -3.41),
    Airport("INV", "Inverness", "Inverness", "United Kingdom", "🇬🇧", 57.54, -4.05),

    # Ireland
    Airport("DUB", "Dublin", "Dublin", "Ireland", "🇮🇪", 53.43, -6.24),
    Airport("ORK", "Cork", "Cork", "Ireland", "🇮🇪", 51.84, -8.49),
    Airport("SNN", "Shannon", "Shannon", "Ireland", "🇮🇪", 52.70, -8.92),
    Airport("KIR", "Kerry", "Kerry", "Ireland", "🇮🇪", 52.18, -9.52),
    Airport("NOC", "Knock", "Knock", "Ireland", "🇮🇪", 53.91, -8.82),

    # Turkey
    Airport("IST", "Istanbul Airport", "Istanbul", "Turkey", "🇹🇷", 41.26, 28.74),
    Airport("SAW", "Istanbul Sabiha Gökçen", "Istanbul", "Turkey", "🇹🇷", 40.90, 29.31),
    Airport("AYT", "Antalya", "Antalya", "Turkey", "🇹🇷", 36.90, 30.80),
    Airport("ADB", "Izmir Adnan Menderes", "Izmir", "Turkey", "🇹🇷", 38.29, 27.16),
    Airport("ESB", "Ankara Esenboğa", "Ankara", "Turkey", "🇹🇷", 40.13, 33.00),
    Airport("DLM", "Dalaman", "Dalaman", "Turkey", "🇹🇷", 36.71, 28.79),
    Airport("BJV", "Bodrum Milas", "Bodrum", "Turkey", "🇹🇷", 37.25, 27.66),
    Airport("TZX", "Trabzon", "Trabzon", "Turkey", "🇹🇷", 40.99, 39.79),

    # Ukraine
    Airport("KBP", "Kyiv Boryspil", "Kyiv", "Ukraine", "🇺🇦", 50.34, 30.89),
    Airport("IEV", "Kyiv Zhuliany", "Kyiv", "Ukraine", "🇺🇦", 50.40, 30.45),
    Airport("LWO", "Lviv", "Lviv", "Ukraine", "🇺🇦", 49.81, 23.96),
    Airport("ODS", "Odesa", "Odesa", "Ukraine", "🇺🇦", 46.43, 30.68),
    Airport("HRK", "Kharkiv", "Kharkiv", "Ukraine", "🇺🇦", 49.92, 36.29),

    # Moldova
    Airport("KIV", "Chișinău International", "Chișinău", "Moldova", "🇲🇩", 46.93, 28.93),
    Airport("BZY", "Bălți International", "Bălți", "Moldova", "🇲🇩", 47.84, 27.78),

    # Serbia
    Airport("BEG", "Belgrade Nikola Tesla", "Belgrade", "Serbia", "🇷🇸", 44.82, 20.31),
    Airport("INI", "Niš Constantine the Great", "Niš", "Serbia", "🇷🇸", 43.34, 21.85),

    # Bosnia and Herzegovina
    Airport("SJJ", "Sarajevo International", "Sarajevo", "Bosnia and Herzegovina", "🇧🇦", 43.82, 18.33),
    Airport("TZL", "Tuzla International", "Tuzla", "Bosnia and Herzegovina", "🇧🇦", 44.46, 18.72),
    Airport("BNX", "Banja Luka", "Banja Luka", "Bosnia and Herzegovina", "🇧🇦", 44.94, 17.30),

    # North Macedonia
    Airport("SKP", "Skopje International", "Skopje", "North Macedonia", "🇲🇰", 41.96, 21.62),
    Airport("OHD", "Ohrid St. Paul the Apostle", "Ohrid", "North Macedonia", "🇲🇰", 41.18, 20.74),

    # Montenegro
    Airport("TGD", "Podgorica", "Podgorica", "Montenegro", "🇲🇪", 42.36, 19.25),
    Airport("TIV", "Tivat", "Tivat", "Montenegro", "🇲🇪", 42.40, 18.72),

    # Albania
    Airport("TIA", "Tirana International", "Tirana", "Albania", "🇦🇱", 41.41, 19.72),

    # Georgia
    Airport("TBS", "Tbilisi International", "Tbilisi", "Georgia", "🇬🇪", 41.67, 44.95),
    Airport("KUT", "Kutaisi International", "Kutaisi", "Georgia", "🇬🇪", 42.18, 42.48),
    Airport("BUS", "Batumi International", "Batumi", "Georgia", "🇬🇪", 41.61, 41.60),

    # Armenia
    Airport("EVN", "Zvartnots International", "Yerevan", "Armenia", "🇦🇲", 40.15, 44.40),

    # Azerbaijan
    Airport("GYD", "Heydar Aliyev International", "Baku", "Azerbaijan", "🇦🇿", 40.47, 50.05),

    # Belarus
    Airport("MSQ", "Minsk National", "Minsk", "Belarus", "🇧🇾", 53.88, 28.03),

    # Russia (major European airports)
    Airport("SVO", "Sheremetyevo International", "Moscow", "Russia", "🇷🇺", 55.97, 37.41),
    Airport("DME", "Domodedovo International", "Moscow", "Russia", "🇷🇺", 55.41, 37.90),
    Airport("VKO", "Vnukovo International", "Moscow", "Russia", "🇷🇺", 55.60, 37.29),
    Airport("LED", "Pulkovo", "Saint Petersburg", "Russia", "🇷🇺", 59.80, 30.26),
    Airport("KZN", "Kazan International", "Kazan", "Russia", "🇷🇺", 55.61, 49.28),
    Airport("KRR", "Krasnodar", "Krasnodar", "Russia", "🇷🇺", 45.03, 39.15),
    Airport("ROV", "Platov International", "Rostov-on-Don", "Russia", "🇷🇺", 47.26, 39.82),
    Airport("GDX", "Sokol", "Magadan", "Russia", "🇷🇺", 59.91, 150.72),

    # Israel
    Airport("TLV", "Ben Gurion", "Tel Aviv", "Israel", "🇮🇱", 32.01, 34.89),

    # Morocco
    Airport("CMN", "Casablanca Mohammed V", "Casablanca", "Morocco", "🇲🇦", 33.37, -7.59),
    Airport("RAK", "Marrakech Menara", "Marrakech", "Morocco", "🇲🇦", 31.61, -8.04),
    Airport("AGA", "Agadir–Al Massira", "Agadir", "Morocco", "🇲🇦", 30.32, -9.41),
    Airport("FEZ", "Fès–Saïs", "Fes", "Morocco", "🇲🇦", 33.93, -4.98),
    Airport("TNG", "Tangier Ibn Battouta", "Tangier", "Morocco", "🇲🇦", 35.73, -5.92),

    # Tunisia
    Airport("TUN", "Tunis–Carthage", "Tunis", "Tunisia", "🇹🇳", 36.85, 10.23),
    Airport("NBE", "Enfidha–Hammamet", "Enfidha", "Tunisia", "🇹🇳", 36.08, 10.44),
    Airport("DJE", "Djerba–Zarzis", "Djerba", "Tunisia", "🇹🇳", 33.87, 10.77),

    # Egypt
    Airport("CAI", "Cairo International", "Cairo", "Egypt", "🇪🇬", 30.12, 31.41),
    Airport("HRG", "Hurghada International", "Hurghada", "Egypt", "🇪🇬", 27.18, 33.80),
    Airport("SSH", "Sharm El Sheikh", "Sharm El Sheikh", "Egypt", "🇪🇬", 27.98, 34.39),
]


def get_destinations(
    exclude_iatas: Optional[List[str]] = None,
    universe: str = "europe",
) -> List[Airport]:
    """Get valid meetup destinations.

    v6.1: universe parameter — "schengen", "europe" (default), or "anywhere".
    No more hardcoded Schengen-only filter. Anyone from any country can
    search and find meetup cities.

    Args:
        exclude_iatas: IATA codes to exclude (participant origins)
        universe: "schengen" | "europe" | "anywhere"
    """
    exclude_iatas = exclude_iatas or []
    actual_exclude = set(exclude_iatas)

    if universe == "anywhere":
        allowed = CANDIDATE_DESTINATIONS
    elif universe == "europe":
        allowed = [a for a in CANDIDATE_DESTINATIONS if a.country in EUROPE_COUNTRIES]
    else:  # schengen
        allowed = [a for a in CANDIDATE_DESTINATIONS if a.country in SCHENGEN_COUNTRIES]

    destinations = [a for a in allowed if a.iata not in actual_exclude]

    # Add origin cities as "meet at home" options
    if exclude_iatas:
        home_candidates = [a for a in CANDIDATE_DESTINATIONS if a.iata in exclude_iatas]
        for hc in home_candidates:
            home_airport = Airport(
                hc.iata,
                f"{hc.city} (Home)",
                hc.city,
                hc.country,
                "🏠",
                hc.lat,
                hc.lon,
            )
            if hc.iata not in {a.iata for a in destinations}:
                destinations.append(home_airport)

    return destinations


NEARBY_AIRPORT_GROUPS = {
    "Paris": ["BVA", "CDG", "ORY"],
    "Brussels": ["BRU", "CRL", "ANR"],
    "Milan": ["BGY", "MXP", "LIN"],
    "Venice": ["VCE", "TSF"],
    "Rome": ["FCO", "CIA"],
    "Warsaw": ["WAW", "WMI"],
    "Barcelona": ["BCN", "GRO", "REU"],
    "London": ["LHR", "LGW", "STN", "LTN", "LCY"],
    "Istanbul": ["IST", "SAW"],
    "Kyiv": ["KBP", "IEV"],
    "Moscow": ["SVO", "DME", "VKO"],
    "Stockholm": ["ARN", "NYO", "VST"],
    "Bucharest": ["OTP"],
    "Belgrade": ["BEG"],
    "Tbilisi": ["TBS"],
    "Belfast": ["BFS", "BHD"],
}

# ── Airport lookup ──

def get_airport(iata: str) -> Optional[Airport]:
    return next((a for a in CANDIDATE_DESTINATIONS if a.iata == iata), None)


def is_schengen_airport(iata: str) -> bool:
    airport = get_airport(iata.upper())
    return bool(airport and airport.country in SCHENGEN_COUNTRIES)


def expand_nearby_airports(airport: Airport, exclude_iatas: set = None) -> List[Airport]:
    """v6.1: Expand to nearby airports for any city, excluding participant origins.

    No longer Schengen-gated — works for London, Istanbul, Kyiv, etc.
    """
    if exclude_iatas is None:
        exclude_iatas = set()
    iatas = NEARBY_AIRPORT_GROUPS.get(airport.city, [airport.iata])
    airports = [get_airport(iata) for iata in iatas]
    return [a for a in airports if a and a.iata not in exclude_iatas]


def load_europe_airports_from_ourairports():
    pass
