"""
Utility script to align canonical_markets with the project’s normalized taxonomy.

Actions (safe by default):
- Inserts missing market codes from the taxonomy
- Optionally deletes markets not in the taxonomy (use --delete-extra)

Usage:
  python -m scripts.migrate_canonical_markets [--db data/surebet.db] [--delete-extra]
"""

from __future__ import annotations

import argparse
import sqlite3
from typing import Set

from src.domain.market_taxonomy import CANONICAL_MARKETS


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/surebet.db", help="Path to SQLite DB")
    parser.add_argument(
        "--delete-extra",
        action="store_true",
        help="Delete canonical_markets not present in taxonomy (DANGEROUS)",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        conn.execute("PRAGMA foreign_keys=ON")

        # Insert missing
        wanted: Set[str] = set(CANONICAL_MARKETS.keys())
        cur = conn.execute("SELECT market_code FROM canonical_markets")
        existing = {row[0] for row in cur.fetchall()}

        for code in sorted(wanted - existing):
            conn.execute(
                "INSERT INTO canonical_markets (market_code, description, created_at_utc) VALUES (?, ?, datetime('now') || 'Z')",
                (code, CANONICAL_MARKETS[code]),
            )

        removed = 0
        if args.delete_extra:
            # Delete markets not in taxonomy and not referenced by bets/surebets
            extras = existing - wanted
            for code in sorted(extras):
                # Check references
                bet_ref = conn.execute(
                    "SELECT COUNT(1) FROM bets WHERE canonical_market_id IN (SELECT id FROM canonical_markets WHERE market_code = ?)",
                    (code,),
                ).fetchone()[0]
                surebet_ref = conn.execute(
                    "SELECT COUNT(1) FROM surebets WHERE canonical_market_id IN (SELECT id FROM canonical_markets WHERE market_code = ?)",
                    (code,),
                ).fetchone()[0]
                if bet_ref == 0 and surebet_ref == 0:
                    conn.execute("DELETE FROM canonical_markets WHERE market_code = ?", (code,))
                    removed += 1

        conn.commit()

        print(
            f"Inserted: {len(wanted - existing)} | Skipped existing: {len(existing & wanted)} | Deleted: {removed}"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()

