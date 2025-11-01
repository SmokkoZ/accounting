"""
Development reset script for the Surebet Accounting System.

Usage:
  python scripts/reset_dev_db.py            # Reset DB only (keeps screenshots/logs/exports)
  python scripts/reset_dev_db.py --hard     # Also clears screenshots, logs, exports
  python scripts/reset_dev_db.py --yes      # Skip confirmation prompt

This script deletes the SQLite database file configured by Config.DB_PATH and
reinitializes it with schema + seed data. Optionally removes data folders.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

import sys

# Ensure project root is on sys.path so `src` imports work when executed from anywhere
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import Config
from src.core.database import initialize_database


def remove_path(p: Path) -> None:
    if p.is_file():
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    elif p.is_dir():
        shutil.rmtree(p, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset development database and optionally data folders")
    parser.add_argument("--hard", action="store_true", help="Also delete screenshots, logs, and exports")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    db_path = Path(Config.DB_PATH)
    root = Path(".").resolve()

    print("\n=== Surebet Dev Reset ===")
    print(f"Project root: {root}")
    print(f"DB path: {db_path}")
    if args.hard:
        print("Mode: HARD (also clearing data/screenshots, data/logs, data/exports)")
    else:
        print("Mode: SOFT (DB only)")

    if not args.yes:
        try:
            confirm = input("Type 'RESET' to proceed: ").strip()
        except KeyboardInterrupt:
            print("\nAborted.")
            return
        if confirm.upper() != "RESET":
            print("Aborted.")
            return

    # Delete DB file if present
    if db_path.exists():
        try:
            db_path.unlink()
            print(f"Deleted DB file: {db_path}")
        except Exception as e:
            print(f"Failed to delete DB file: {e}")

    # Optionally purge folders
    if args.hard:
        for folder in (Path(Config.SCREENSHOT_DIR), Path(Config.LOG_DIR), Path(Config.EXPORT_DIR)):
            if folder.exists():
                try:
                    shutil.rmtree(folder, ignore_errors=True)
                    print(f"Deleted folder: {folder}")
                except Exception as e:
                    print(f"Failed to delete {folder}: {e}")

    # Reinitialize DB (schema + seed)
    try:
        conn = initialize_database()
        conn.close()
        print("Reinitialized database (schema + seed data)")
    except Exception as e:
        print(f"Failed to initialize database: {e}")
        raise

    print("\nReset complete. You can now rerun the app/bot.")


if __name__ == "__main__":
    main()
