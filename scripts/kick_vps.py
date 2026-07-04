import os
import requests
from dotenv import load_dotenv

def kick_vps():
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN not found in .env")
        return

    print("Releasing bot from remote instance...")
    # v5.1: deleteWebhook + close frees the polling slot WITHOUT logging out.
    # logOut is too aggressive — it invalidates the token for several minutes.
    try:
        r1 = requests.get(
            f"https://api.telegram.org/bot{token}/deleteWebhook", timeout=10
        )
        r2 = requests.get(
            f"https://api.telegram.org/bot{token}/close", timeout=10
        )
        if r1.status_code == 200 and r2.status_code == 200:
            print("SUCCESS: Remote instance released. Start the bot locally now.")
        else:
            print(f"deleteWebhook: {r1.status_code} {r1.text}")
            print(f"close: {r2.status_code} {r2.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    kick_vps()
