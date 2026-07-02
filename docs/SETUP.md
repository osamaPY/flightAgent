# Setup and Configuration

## 🛠 Prerequisites
- Python 3.11+
- SQLite

## 📥 Installation
1. Clone the repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env`.

## 🔑 Environment Variables
| Variable | Description | Source |
|----------|-------------|--------|
| `TELEGRAM_BOT_TOKEN` | Token for your bot | @BotFather |
| `TELEGRAM_CHAT_ID` | Your chat ID | Use `/selftest` or a bot |
| `TRAVELPAYOUTS_TOKEN` | API Token | Travelpayouts |
| `SERPAPI_KEY` | Google Flights API | SerpApi |
| `RAPIDAPI_KEY` | Sky Scrapper API | RapidAPI |
| `FLIGHTAPI_KEY` | FlightAPI.io Token | FlightAPI.io |
| `TARGET_PRICE_EUR` | Max combined price for alerts | Optional (default: 200) |

## 🚀 Running the App
- **Telegram (Recommended)**:
  ```bash
  python telegram_bot.py
  ```
- **CLI Menu**:
  ```bash
  python main.py
  ```
- **Direct Scan**:
  ```bash
  python main.py monitor
  ```
