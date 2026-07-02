# Flight Meet Agent - Documentation

## 🗺 Overview
Flight Meet Agent is a personal flight discovery tool designed to find the cheapest European cities for two people (one in Milan, one in Riga) to meet up.

## 🏗 Architecture
The project follows a **Provider-based Architecture**, allowing it to scale across multiple flight data sources while remaining resilient to API failures.

- **Storage**: SQLite database (`flights.db`) for tracking history, best prices, and API budgets.
- **Providers**: Unified interface for Ryanair, Travelpayouts, SerpApi (Google Flights), SkyScrapper (RapidAPI), and FlightAPI.io.
- **Scoring**: A custom engine that calculates "Fairness" to ensure neither person pays a disproportionate amount.
- **Interfaces**: Fully interactive Telegram Bot and a secondary CLI menu.

## 🚀 Key Features
- **Fair-Deal Ranking**: Prioritizes trips where costs are balanced between both travelers.
- **Multi-Origin Scanning**: Searches multiple airports (BGY, MXP, LIN) for Milan and RIX for Riga.
- **Mobile First**: Control scans, view results, and check health directly from Telegram.
- **Price History**: Tracks all-time best prices to identify true "drops".
- **Budget Protection**: Hard guards on paid APIs (like SerpApi) to keep costs at €0.

## 📁 File Structure
- `main.py`: Application entry point and CLI menu.
- `telegram_bot.py`: Main interactive interface.
- `providers.py`: Provider abstraction layer.
- `scoring.py`: Scoring and ranking logic.
- `airports.py`: Destination metadata and flags.
- `storage.py`: SQLite persistence layer.
- `notifier.py`: Telegram message formatting.
- `*_client.py`: Specific API implementations.
