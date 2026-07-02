# Flight Meet Agent ✈️

A personal, non-commercial Python tool designed to find the cheapest European city where two people (originating from Milan and Riga) can meet. This project follows a "near-€0" philosophy by leveraging free/unofficial data sources for broad monitoring and only using paid/limited APIs for final verification.

## 🏗️ Clean Project Structure

To keep the root directory tidy, the project is organized as follows:

-   `main.py`: Entry point for CLI menu.
-   `telegram_bot.py`: Entry point for the interactive Telegram bot.
-   `start.bat`: One-click launcher for Windows.
-   `src/core/`: Core logic (Scoring, Storage, Notifier, Config).
-   `src/clients/`: API implementations for flight providers.
-   `data/`: Persistent storage (SQLite DB, CSV exports, local cache).
-   `docs/`: Detailed setup and architectural guides.

## 🚀 Setup

1.  **Environment**: Python 3.11+
2.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Telegram Bot**:
    - Create a bot with [@BotFather](https://t.me/botfather).
    - Get your Chat ID (e.g., via [@userinfobot](https://t.me/userinfobot)).
4.  **API Tokens**:
    - Get a free [Travelpayouts Token](https://www.travelpayouts.com/en/developers/api).
    - (Optional) Get a [SerpApi Key](https://serpapi.com/) for Google Flights verification.
5.  **Configure `.env`**:
    - Copy `.env.example` to `.env`.
    - Fill in your tokens and adjust `TARGET_PRICE_EUR` as desired.

## 🛠️ Usage Modes

-   **`python main.py monitor`**: Runs the core scanning loop. Recommended for GitHub Actions cron.
-   **`python main.py discover`**: Proposes new cities to add to `airports.py` based on cached data.
-   **`python main.py verify`**: Uses Google Flights (via SerpApi) to confirm the best deals found in the database.
-   **`python main.py selftest`**: Verifies connectivity, database, and environment variables.

## 🤖 Automated Execution (GitHub Actions)

The repository includes a workflow in `.github/workflows/flight-check.yml` that:
- Runs `monitor` every 12 hours.
- Runs `discover` every Sunday.
- Commits updated results and price history back to the repository.

## ⚠️ Important Disclaimer

**"Verify manually before booking."**

This tool is for personal, non-commercial use only.
- **Data Fragility**: Unofficial endpoints (Ryanair) can break or change without notice.
- **Cached Data**: Travelpayouts data is often cached and may not reflect real-time availability.
- **Baggage**: Headline fares usually exclude checked bags.
- **Accuracy**: AI is used only for ranking and summarization; it never estimates prices.

Always confirm final prices and times on official airline websites or Google Flights before making any payments.
