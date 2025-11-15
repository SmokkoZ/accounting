"""
Balance history aggregation and export helpers.

Provides read-only accessors that power the Associates Hub Balance History tab.
Queries the bookmaker_balance_checks table, computes ND/YF/TB/I'' metrics from
ledger entries, and emits styled Excel exports that follow the Epic 12.2 rules.
"""

from __future__ import annotations

import io
import sqlite3
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd
import structlog

from src.core.database import get_db_connection

logger = structlog.get_logger(__name__)

TWO_PLACES = Decimal("0.01")


def _to_decimal(value: Optional[object], *, default: str = "0") -> Decimal:
    """Convert raw DB values into quantized Decimal numbers."""
    if value in (None, ""):
        return Decimal(default).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    try:
        return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class BalanceHistoryEntry:
    """One historical balance snapshot enriched with ND/YF/TB/I''."""

    id: int
    associate_id: int
    associate_alias: str
    bookmaker_id: int
    bookmaker_name: str
    check_date_utc: str
    balance_eur: Decimal
    balance_native: Decimal
    native_currency: str
    fx_rate_used: Decimal
    note: Optional[str]
    net_deposits_eur: Decimal
    fair_share_eur: Decimal
    yf_eur: Decimal
    tb_eur: Decimal
    imbalance_eur: Decimal
    ledger_balance_eur: Decimal
    source: str = "Balance check"


@dataclass(frozen=True)
class BalanceHistoryResult:
    """Return payload for paginated history queries."""

    entries: List[BalanceHistoryEntry]
    total_count: int


@dataclass(frozen=True)
class BalanceHistoryExport:
    """Metadata for generated Excel exports."""

    file_name: str
    content: bytes
    row_count: int


class BalanceHistoryService:
    """Fetch balance history entries and provide styled exports."""

    def __init__(self, db: sqlite3.Connection | None = None) -> None:
        self._owns_connection = db is None
        self.db = db or get_db_connection()
        self.db.row_factory = sqlite3.Row
        self._metric_cache: Dict[Tuple[int, Optional[int], str], Tuple[Decimal, Decimal, Decimal]] = {}

    def close(self) -> None:
        """Close owned DB connections."""
        if not self._owns_connection:
            return
        try:
            self.db.close()
        except Exception:  # pragma: no cover - defensive close
            pass

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def fetch_history(
        self,
        *,
        associate_id: Optional[int] = None,
        bookmaker_id: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> BalanceHistoryResult:
        """
        Return enriched balance history entries for the supplied filters.
        """
        rows = self._select_history_rows(
            associate_id=associate_id,
            bookmaker_id=bookmaker_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )
        entries = [self._build_entry(row) for row in rows]
        total = self._count_history_rows(
            associate_id=associate_id,
            bookmaker_id=bookmaker_id,
            start_date=start_date,
            end_date=end_date,
        )
        return BalanceHistoryResult(entries=entries, total_count=total)

    def export_history(
        self,
        *,
        associate_id: Optional[int] = None,
        bookmaker_id: Optional[int] = None,
        start_date: Optional[str],
        end_date: Optional[str],
        associate_label: str,
        bookmaker_label: str,
        max_rows: int = 5000,
    ) -> BalanceHistoryExport:
        """
        Generate a styled Excel workbook for the current filters.
        """
        history = self.fetch_history(
            associate_id=associate_id,
            bookmaker_id=bookmaker_id,
            start_date=start_date,
            end_date=end_date,
            limit=max_rows,
            offset=0,
        )
        dataframe = self._build_dataframe(history.entries)
        buffer = io.BytesIO()
        sheet_name = "Balance History"
        with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
            dataframe.to_excel(writer, sheet_name=sheet_name, index=False, startrow=4)
            workbook = writer.book
            worksheet = writer.sheets[sheet_name]

            worksheet.write(0, 0, "Associate filter")
            worksheet.write(0, 1, associate_label)
            worksheet.write(1, 0, "Bookmaker filter")
            worksheet.write(1, 1, bookmaker_label)
            worksheet.write(2, 0, "Date window")
            date_label = f"{start_date or 'Min'} to {end_date or 'Max'}"
            worksheet.write(2, 1, date_label)

            header_format = workbook.add_format(
                {"bold": True, "bg_color": "#0f172a", "font_color": "#ffffff"}
            )
            if not dataframe.empty:
                for col_idx, column in enumerate(dataframe.columns):
                    worksheet.write(4, col_idx, column, header_format)
                    values = dataframe[column].astype(str)
                    max_length = max(values.map(len).max(), len(column)) + 2
                    worksheet.set_column(col_idx, col_idx, min(max_length, 40))
                worksheet.freeze_panes(5, 0)
            else:
                worksheet.write(4, 0, "No data for selected filters", header_format)

        filename = self._build_filename(
            associate_label=associate_label,
            bookmaker_label=bookmaker_label,
            start_date=start_date,
            end_date=end_date,
        )
        return BalanceHistoryExport(
            file_name=filename,
            content=buffer.getvalue(),
            row_count=len(history.entries),
        )

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _select_history_rows(
        self,
        *,
        associate_id: Optional[int],
        bookmaker_id: Optional[int],
        start_date: Optional[str],
        end_date: Optional[str],
        limit: int,
        offset: int,
    ) -> List[sqlite3.Row]:
        query = [
            "SELECT",
            "  bc.id,",
            "  bc.associate_id,",
            "  a.display_alias AS associate_alias,",
            "  bc.bookmaker_id,",
            "  b.bookmaker_name,",
            "  bc.balance_eur,",
            "  bc.balance_native,",
            "  bc.native_currency,",
            "  bc.fx_rate_used,",
            "  bc.check_date_utc,",
            "  bc.note",
            "FROM bookmaker_balance_checks bc",
            "JOIN associates a ON a.id = bc.associate_id",
            "JOIN bookmakers b ON b.id = bc.bookmaker_id",
            "WHERE 1=1",
        ]
        params: List[object] = []
        if associate_id is not None:
            query.append("AND bc.associate_id = ?")
            params.append(associate_id)
        if bookmaker_id is not None:
            query.append("AND bc.bookmaker_id = ?")
            params.append(bookmaker_id)
        if start_date:
            query.append("AND date(bc.check_date_utc) >= date(?)")
            params.append(start_date)
        if end_date:
            query.append("AND date(bc.check_date_utc) <= date(?)")
            params.append(end_date)
        query.append("ORDER BY bc.check_date_utc DESC, bc.id DESC")
        query.append("LIMIT ? OFFSET ?")
        params.extend([limit, offset])
        sql = "\n".join(query)
        return list(self.db.execute(sql, params))

    def _count_history_rows(
        self,
        *,
        associate_id: Optional[int],
        bookmaker_id: Optional[int],
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> int:
        query = ["SELECT COUNT(*) FROM bookmaker_balance_checks WHERE 1=1"]
        params: List[object] = []
        if associate_id is not None:
            query.append("AND associate_id = ?")
            params.append(associate_id)
        if bookmaker_id is not None:
            query.append("AND bookmaker_id = ?")
            params.append(bookmaker_id)
        if start_date:
            query.append("AND date(check_date_utc) >= date(?)")
            params.append(start_date)
        if end_date:
            query.append("AND date(check_date_utc) <= date(?)")
            params.append(end_date)
        cursor = self.db.execute("\n".join(query), params)
        row = cursor.fetchone()
        return int(row[0]) if row else 0

    def _build_entry(self, row: sqlite3.Row) -> BalanceHistoryEntry:
        balance_eur = _to_decimal(row["balance_eur"])
        metrics = self._calculate_financials(
            associate_id=int(row["associate_id"]),
            bookmaker_id=int(row["bookmaker_id"]),
            cutoff=row["check_date_utc"],
        )
        nd_eur, fs_eur, ledger_total = metrics
        yf_eur = (nd_eur + fs_eur).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        imbalance = (balance_eur - yf_eur).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        return BalanceHistoryEntry(
            id=int(row["id"]),
            associate_id=int(row["associate_id"]),
            associate_alias=row["associate_alias"],
            bookmaker_id=int(row["bookmaker_id"]),
            bookmaker_name=row["bookmaker_name"],
            check_date_utc=row["check_date_utc"],
            balance_eur=balance_eur,
            balance_native=_to_decimal(row["balance_native"]),
            native_currency=row["native_currency"],
            fx_rate_used=_to_decimal(row["fx_rate_used"], default="1"),
            note=row["note"],
            net_deposits_eur=nd_eur,
            fair_share_eur=fs_eur,
            yf_eur=yf_eur,
            tb_eur=balance_eur,
            imbalance_eur=imbalance,
            ledger_balance_eur=ledger_total,
        )

    def _calculate_financials(
        self,
        *,
        associate_id: int,
        bookmaker_id: int,
        cutoff: str,
    ) -> Tuple[Decimal, Decimal, Decimal]:
        cache_key = (associate_id, bookmaker_id, cutoff)
        if cache_key in self._metric_cache:
            return self._metric_cache[cache_key]

        params: List[object] = [associate_id, cutoff, bookmaker_id]

        sql = f"""
            SELECT
                COALESCE(SUM(CASE WHEN type IN ('DEPOSIT','WITHDRAWAL')
                    THEN CAST(amount_eur AS REAL) ELSE 0 END), 0) AS nd_eur,
                COALESCE(SUM(CASE WHEN type = 'BET_RESULT'
                    THEN CAST(per_surebet_share_eur AS REAL) ELSE 0 END), 0) AS fs_eur,
                COALESCE(SUM(CAST(amount_eur AS REAL)), 0) AS ledger_total
            FROM ledger_entries
            WHERE associate_id = ?
              AND created_at_utc <= ?
              AND (bookmaker_id IS NULL OR bookmaker_id = ?)
        """
        cursor = self.db.execute(sql, params)
        row = cursor.fetchone()
        nd_eur = _to_decimal(row["nd_eur"] if row else None)
        fs_eur = _to_decimal(row["fs_eur"] if row else None)
        ledger_total = _to_decimal(row["ledger_total"] if row else None)
        self._metric_cache[cache_key] = (nd_eur, fs_eur, ledger_total)
        return self._metric_cache[cache_key]

    def _build_dataframe(
        self, entries: Sequence[BalanceHistoryEntry]
    ) -> pd.DataFrame:
        records: List[Dict[str, object]] = []
        for entry in entries:
            records.append(
                {
                    "Timestamp (UTC)": entry.check_date_utc,
                    "Associate": entry.associate_alias,
                    "Bookmaker": entry.bookmaker_name,
                    "Net Deposits (ND)": float(entry.net_deposits_eur),
                    "Fair Share (FS)": float(entry.fair_share_eur),
                    "Yield Funds (YF)": float(entry.yf_eur),
                    "Total Balance (TB)": float(entry.tb_eur),
                    "Imbalance (I'')": float(entry.imbalance_eur),
                    "Ledger Total (TB modeled)": float(entry.ledger_balance_eur),
                    "Native Balance": f"{entry.balance_native:,.2f} {entry.native_currency}",
                    "FX Rate Used": float(entry.fx_rate_used),
                    "Source": entry.source,
                    "Note": entry.note or "",
                }
            )
        columns = [
            "Timestamp (UTC)",
            "Associate",
            "Bookmaker",
            "Net Deposits (ND)",
            "Fair Share (FS)",
            "Yield Funds (YF)",
            "Total Balance (TB)",
            "Imbalance (I'')",
            "Ledger Total (TB modeled)",
            "Native Balance",
            "FX Rate Used",
            "Source",
            "Note",
        ]
        if not records:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame(records, columns=columns)

    @staticmethod
    def _build_filename(
        *,
        associate_label: str,
        bookmaker_label: str,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> str:
        alias_slug = BalanceHistoryService._slugify(associate_label or "all")
        bookmaker_slug = BalanceHistoryService._slugify(bookmaker_label or "all")
        start = start_date or "min"
        end = end_date or "max"
        return f"{alias_slug}_{bookmaker_slug}_{start}_{end}_history.xlsx"

    @staticmethod
    def _slugify(value: str) -> str:
        cleaned = "".join(char if char.isalnum() else "-" for char in value.strip().lower())
        cleaned = "-".join(part for part in cleaned.split("-") if part)
        return cleaned or "all"

    def __enter__(self) -> "BalanceHistoryService":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
