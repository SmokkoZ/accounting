"""
Repository layer for bookmaker balance checks.

Provides UPSERT helpers and query utilities used by the bookmaker balance
drilldown service (Story 5.3).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from src.core.database import get_db_connection


def _utc_now_iso() -> str:
    """Return current UTC timestamp with Z suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _row_to_dict(row: sqlite3.Row) -> Dict:
    """Convert a SQLite row into a plain dict with Decimal conversions."""
    return {
        "id": row["id"],
        "associate_id": row["associate_id"],
        "bookmaker_id": row["bookmaker_id"],
        "balance_native": Decimal(str(row["balance_native"])),
        "native_currency": row["native_currency"],
        "balance_eur": Decimal(str(row["balance_eur"])),
        "fx_rate_used": Decimal(str(row["fx_rate_used"])),
        "check_date_utc": row["check_date_utc"],
        "note": row["note"],
        "created_at_utc": row["created_at_utc"],
    }


class BookmakerBalanceCheckRepository:
    """Data access helpers for the bookmaker_balance_checks table."""

    def __init__(self, db: sqlite3.Connection | None = None) -> None:
        self._owns_connection = db is None
        self.db = db or get_db_connection()

    def close(self) -> None:
        """Close the managed database connection if owned by the repository."""
        if not self._owns_connection:
            return
        try:
            self.db.close()
        except Exception:  # pragma: no cover - defensive close
            pass

    # --------------------------------------------------------------------- #
    # Write helpers
    # --------------------------------------------------------------------- #

    def upsert_balance_check(
        self,
        associate_id: int,
        bookmaker_id: int,
        balance_native: Decimal,
        native_currency: str,
        balance_eur: Decimal,
        fx_rate_used: Decimal,
        *,
        check_date_utc: Optional[str] = None,
        note: Optional[str] = None,
    ) -> int:
        """
        Insert or update a balance check entry.

        Returns:
            Primary key ID of the inserted/updated record.
        """
        timestamp = check_date_utc or _utc_now_iso()

        payload = (
            associate_id,
            bookmaker_id,
            str(balance_native),
            native_currency.upper(),
            str(balance_eur),
            str(fx_rate_used),
            timestamp,
            note,
        )

        cursor = self.db.execute(
            """
            INSERT INTO bookmaker_balance_checks (
                associate_id,
                bookmaker_id,
                balance_native,
                native_currency,
                balance_eur,
                fx_rate_used,
                check_date_utc,
                note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(associate_id, bookmaker_id, check_date_utc) DO UPDATE SET
                balance_native = excluded.balance_native,
                native_currency = excluded.native_currency,
                balance_eur = excluded.balance_eur,
                fx_rate_used = excluded.fx_rate_used,
                note = excluded.note
            """,
            payload,
        )
        self.db.commit()

        # For UPSERT updates, lastrowid is 0; fetch the existing record ID.
        if cursor.lastrowid:
            return int(cursor.lastrowid)

        lookup = self.db.execute(
            """
            SELECT id FROM bookmaker_balance_checks
            WHERE associate_id = ? AND bookmaker_id = ? AND check_date_utc = ?
            """,
            (associate_id, bookmaker_id, timestamp),
        ).fetchone()
        if lookup is None:  # pragma: no cover - should not happen
            raise RuntimeError("Failed to resolve bookmaker_balance_checks id after UPSERT.")
        return int(lookup["id"])

    # --------------------------------------------------------------------- #
    # Read helpers
    # --------------------------------------------------------------------- #

    def get_latest_check(self, associate_id: int, bookmaker_id: int) -> Optional[Dict]:
        """
        Return the most recent balance check for an associate/bookmaker pair.
        """
        row = self.db.execute(
            """
            SELECT *
            FROM bookmaker_balance_checks
            WHERE associate_id = ? AND bookmaker_id = ?
            ORDER BY check_date_utc DESC
            LIMIT 1
            """,
            (associate_id, bookmaker_id),
        ).fetchone()
        return _row_to_dict(row) if row else None

    def get_latest_checks_map(self) -> Dict[Tuple[int, int], Dict]:
        """
        Return a dict keyed by (associate_id, bookmaker_id) for the latest checks.
        """
        rows = self.db.execute(
            """
            SELECT bc.*
            FROM bookmaker_balance_checks bc
            JOIN (
                SELECT associate_id, bookmaker_id, MAX(check_date_utc) AS latest_check
                FROM bookmaker_balance_checks
                GROUP BY associate_id, bookmaker_id
            ) latest
            ON bc.associate_id = latest.associate_id
            AND bc.bookmaker_id = latest.bookmaker_id
            AND bc.check_date_utc = latest.latest_check
            """
        ).fetchall()

        latest: Dict[Tuple[int, int], Dict] = {}
        for row in rows:
            latest[(row["associate_id"], row["bookmaker_id"])] = _row_to_dict(row)
        return latest

    def list_recent_checks(
        self, *, limit: int = 50, associate_id: Optional[int] = None
    ) -> List[Dict]:
        """Return recent balance checks ordered by timestamp."""
        query = """
            SELECT *
            FROM bookmaker_balance_checks
            WHERE 1=1
        """
        params: List = []
        if associate_id is not None:
            query += " AND associate_id = ?"
            params.append(associate_id)

        query += " ORDER BY check_date_utc DESC LIMIT ?"
        params.append(limit)

        rows = self.db.execute(query, params).fetchall()
        return [_row_to_dict(row) for row in rows]

    def list_checks_for_bookmakers(
        self, bookmaker_ids: Iterable[int]
    ) -> Dict[Tuple[int, int], List[Dict]]:
        """
        Return all checks for the supplied bookmaker IDs keyed by (associate_id, bookmaker_id).
        """
        ids = list(bookmaker_ids)
        if not ids:
            return {}

        placeholders = ",".join("?" for _ in ids)
        rows = self.db.execute(
            f"""
            SELECT *
            FROM bookmaker_balance_checks
            WHERE bookmaker_id IN ({placeholders})
            ORDER BY check_date_utc DESC
            """,
            ids,
        ).fetchall()

        grouped: Dict[Tuple[int, int], List[Dict]] = {}
        for row in rows:
            key = (row["associate_id"], row["bookmaker_id"])
            grouped.setdefault(key, []).append(_row_to_dict(row))
        return grouped

