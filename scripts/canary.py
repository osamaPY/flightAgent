"""Daily canary health check.

Scheduled via cron / Task Scheduler. Queries BGY→VIE ~3 weeks out
on every active provider and asserts prices are in a sane band
(EUR 20-400). If GoogleScraper's protobuf silently breaks, you
find out THIS MORNING, not weeks later via garbage data.

Run: python scripts/canary.py
"""

import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import src.utils.compat  # noqa

from src.core.provider_factory import build_providers
from src.core.storage import Storage
from src.core.cost_utils import is_sane_price
from src.core.notifier import Notifier
from src.core.config import Config
from src.core.logger import log_info, log_error

# ~3 weeks from now
TARGET_DATE = (datetime.now() + timedelta(days=21)).strftime("%Y-%m-%d")
RET_DATE = (datetime.now() + timedelta(days=23)).strftime("%Y-%m-%d")


def run_canary():
    storage = Storage()
    providers = build_providers()
    notifier = Notifier(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_ID)

    results = []
    for p in providers:
        if not p.is_healthy():
            results.append(f"  [SKIP] {p.name()} — not healthy")
            continue

        try:
            rt = p.search_round_trip("BGY", "VIE", TARGET_DATE, TARGET_DATE,
                                     RET_DATE, RET_DATE)
            if not rt or rt.price <= 0:
                results.append(f"  [FAIL] {p.name()} — no result for BGY→VIE")
            else:
                sane, reason = is_sane_price(rt.price, "VIE", storage)
                status = "OK" if sane else "WARN"
                results.append(
                    f"  [{status}] {p.name()} — EUR {rt.price:.0f} ({reason})"
                )
        except Exception as e:
            results.append(f"  [FAIL] {p.name()} — {e}")

    all_ok = all("FAIL" not in r for r in results)
    summary = (
        f"🐦 CANARY {TARGET_DATE}\n"
        + "\n".join(results)
        + f"\n\n{'✅ All providers healthy' if all_ok else '❌ SEE FAILURES ABOVE'}"
    )

    print(summary)
    if notifier.bot_token and notifier.chat_id:
        notifier.send_message(summary)


if __name__ == "__main__":
    run_canary()
