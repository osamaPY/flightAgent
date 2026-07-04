"""v5: Daily DB backup — copies flights.db to a timestamped backup.

The price_history table is the most valuable asset in the project —
it powers L1 calendar pre-scan, L5 smart ordering, deal percentiles,
and trend analysis. It is irreplaceable. Back it up.

Run via Task Scheduler / cron: python scripts/backup_db.py
"""

import sys
import os
import shutil
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import src.utils.compat  # noqa

DB_PATH = os.path.join("data", "flights.db")
BACKUP_DIR = os.path.join("data", "backups")
MAX_BACKUPS = 7


def backup():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found")
        return

    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    backup_path = os.path.join(BACKUP_DIR, f"flights_{ts}.db")

    shutil.copy2(DB_PATH, backup_path)
    size_kb = os.path.getsize(backup_path) / 1024
    print(f"Backed up to {backup_path} ({size_kb:.0f} KB)")

    # Rotate old backups
    backups = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.endswith(".db")],
        reverse=True,
    )
    for old in backups[MAX_BACKUPS:]:
        os.remove(os.path.join(BACKUP_DIR, old))
        print(f"  Removed old backup: {old}")

    print(f"  Kept {min(len(backups), MAX_BACKUPS)} backups")


if __name__ == "__main__":
    backup()
