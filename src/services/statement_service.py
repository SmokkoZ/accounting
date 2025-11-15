"""
Monthly Statement Service

Calculates associate statements including funding, entitlement, and reconciliation.
All calculations are read-only and use cutoff date filtering.
"""

from __future__ import annotations

import io
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
from dataclasses import dataclass

import structlog
import xlsxwriter
from xlsxwriter.utility import xl_rowcol_to_cell
from datetime import datetime

from src.core.database import get_db_connection
from src.services import settlement_constants as _settlement_constants
from src.utils.datetime_helpers import utc_now_iso

if TYPE_CHECKING:
    from src.services.exit_settlement_service import ExitSettlementResult

logger = structlog.get_logger()

SETTLEMENT_NOTE_PREFIX = getattr(
    _settlement_constants, "SETTLEMENT_NOTE_PREFIX", "Settle Associate Now"
)
SETTLEMENT_TOLERANCE = getattr(
    _settlement_constants, "SETTLEMENT_TOLERANCE", Decimal("0.01")
)
SETTLEMENT_MODEL_VERSION = getattr(
    _settlement_constants, "SETTLEMENT_MODEL_VERSION", "YF-v1"
)
SETTLEMENT_MODEL_FOOTNOTE = getattr(
    _settlement_constants,
    "SETTLEMENT_MODEL_FOOTNOTE",
    "Model: YF-v1 (YF = ND + FS; I'' = TB - YF). Values exclude operator fees/taxes.",
)


@dataclass
class BookmakerStatementRow:
    """Per-bookmaker summary for statement output."""

    bookmaker_name: str
    balance_eur: Decimal
    deposits_eur: Decimal
    withdrawals_eur: Decimal
    balance_native: Decimal
    native_currency: str


@dataclass
class StatementCalculations:
    """Container for all statement calculation results."""

    associate_id: int
    net_deposits_eur: Decimal
    should_hold_eur: Decimal
    current_holding_eur: Decimal
    fair_share_eur: Decimal
    profit_before_payout_eur: Decimal
    raw_profit_eur: Decimal
    delta_eur: Decimal
    total_deposits_eur: Decimal
    total_withdrawals_eur: Decimal
    bookmakers: List[BookmakerStatementRow]
    associate_name: str
    home_currency: str
    cutoff_date: str
    generated_at: str

    @property
    def fs_eur(self) -> Decimal:
        """Expose Fair Share (FS) derived from BET_RESULT share rows."""
        return self.fair_share_eur

    @property
    def yf_eur(self) -> Decimal:
        """Expose Yield Funds (YF) alias for should hold."""
        return self.net_deposits_eur + self.fair_share_eur

    @property
    def tb_eur(self) -> Decimal:
        """Expose Total Balance (TB) alias for current holding."""
        return self.current_holding_eur

    @property
    def i_double_prime_eur(self) -> Decimal:
        """Expose imbalance (I'') alias for delta."""
        return self.current_holding_eur - self.yf_eur

    @property
    def exit_payout_eur(self) -> Decimal:
        """Amount that must be paid out during exit to zero the imbalance."""
        return -self.i_double_prime_eur


@dataclass
class PartnerFacingSection:
    """Data for partner-facing statement section."""
    net_deposits_eur: Decimal
    fair_share_eur: Decimal
    yield_funds_eur: Decimal
    total_balance_eur: Decimal
    imbalance_eur: Decimal
    exit_payout_eur: Decimal
    total_deposits_eur: Decimal
    total_withdrawals_eur: Decimal
    profit_before_payout_eur: Decimal
    raw_profit_eur: Decimal
    bookmakers: List[BookmakerStatementRow]


@dataclass
class InternalSection:
    """Data for internal-only statement section."""
    current_holdings: str
    reconciliation_delta: str
    delta_indicator: str
    net_deposits_eur: Decimal
    fair_share_eur: Decimal
    yield_funds_eur: Decimal
    total_balance_eur: Decimal
    imbalance_eur: Decimal
    exit_payout_eur: Decimal


@dataclass
class WorkbookExportPayload:
    """Container describing an in-memory Excel export."""

    filename: str
    content: bytes
    generated_at: str


class StatementService:
    """Service for generating monthly associate statements."""
    
    def __init__(self):
        self.logger = logger.bind(service="statement_service")
    
    def generate_statement(self, associate_id: int, cutoff_date: str) -> StatementCalculations:
        """
        Generate complete statement calculations for an associate.
        
        Args:
            associate_id: ID of the associate
            cutoff_date: ISO datetime string for cutoff (inclusive)
            
        Returns:
            StatementCalculations with all computed values
            
        Raises:
            ValueError: If associate_id not found or cutoff_date invalid
        """
        self.logger.info("generating_statement", associate_id=associate_id, cutoff_date=cutoff_date)
        
        conn = get_db_connection()
        try:
            # Validate associate exists and get name
            associate_name, home_currency = self._get_associate_details(conn, associate_id)
            if not associate_name:
                raise ValueError(f"Associate ID {associate_id} not found")
            
            # Perform all calculations
            (
                total_deposits,
                total_withdrawals,
                net_deposits,
            ) = self._calculate_funding_totals(conn, associate_id, cutoff_date)
            current_holding = self._calculate_current_holding(conn, associate_id, cutoff_date)
            should_hold = self._calculate_should_hold(conn, associate_id, cutoff_date)
            fair_share = self._calculate_profit_before_payout(
                conn, associate_id, cutoff_date
            )
            bookmakers = self._calculate_bookmaker_breakdown(
                conn, associate_id, cutoff_date
            )
            
            # Calculate derived values
            raw_profit = should_hold - net_deposits
            delta = current_holding - should_hold
            
            calculations = StatementCalculations(
                associate_id=associate_id,
                net_deposits_eur=net_deposits,
                should_hold_eur=should_hold,
                current_holding_eur=current_holding,
                fair_share_eur=fair_share,
                profit_before_payout_eur=fair_share,
                raw_profit_eur=raw_profit,
                delta_eur=delta,
                total_deposits_eur=total_deposits,
                total_withdrawals_eur=total_withdrawals,
                bookmakers=bookmakers,
                associate_name=associate_name,
                home_currency=home_currency or "",
                cutoff_date=cutoff_date,
                generated_at=utc_now_iso()
            )
            
            self.logger.info(
                "statement_calculated",
                associate_id=associate_id,
                net_deposits=float(net_deposits),
                should_hold=float(should_hold),
                current_holding=float(current_holding),
                raw_profit=float(raw_profit),
                delta=float(delta)
            )
            
            return calculations
            
        finally:
            conn.close()
    
    def _get_associate_details(self, conn, associate_id: int) -> Tuple[Optional[str], Optional[str]]:
        """Get associate display name and currency by ID."""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT display_alias, home_currency FROM associates WHERE id = ?",
            (associate_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None, None
        return row["display_alias"], row["home_currency"]
    
    def _calculate_funding_totals(
        self, conn, associate_id: int, cutoff_date: str
    ) -> Tuple[Decimal, Decimal, Decimal]:
        """
        Calculate total deposits, withdrawals, and net deposits up to the cutoff date.
        """
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                SUM(
                    CASE
                        WHEN type = 'DEPOSIT' THEN CAST(amount_eur AS REAL)
                        ELSE 0
                    END
                ) AS total_deposits,
                SUM(
                    CASE
                        WHEN type = 'WITHDRAWAL' THEN CAST(amount_eur AS REAL)
                        ELSE 0
                    END
                ) AS signed_withdrawals
            FROM ledger_entries
            WHERE associate_id = ?
              AND type IN ('DEPOSIT', 'WITHDRAWAL')
              AND created_at_utc <= ?
              AND (note IS NULL OR note NOT LIKE ?)
            """,
            (associate_id, cutoff_date, f"{SETTLEMENT_NOTE_PREFIX}%"),
        )
        row = cursor.fetchone()
        if not row:
            return Decimal("0.00"), Decimal("0.00"), Decimal("0.00")

        def _extract(value: object) -> Decimal:
            return Decimal(str(value or 0.0))

        try:
            deposits_value = row["total_deposits"]  # type: ignore[index]
            withdrawals_value = row["signed_withdrawals"]  # type: ignore[index]
        except (TypeError, KeyError, IndexError):
            deposits_value = row[0] if isinstance(row, (list, tuple)) else 0.0  # type: ignore[index]
            withdrawals_value = (
                row[1] if isinstance(row, (list, tuple)) and len(row) > 1 else 0.0  # type: ignore[index]
            )

        total_deposits = _extract(deposits_value)
        signed_withdrawals = _extract(withdrawals_value)
        total_withdrawals = abs(signed_withdrawals)
        net_deposits = total_deposits + signed_withdrawals
        return total_deposits, total_withdrawals, net_deposits

    def _calculate_should_hold(self, conn, associate_id: int, cutoff_date: str) -> Decimal:
        """
        Calculate SHOULD_HOLD_EUR = SUM(principal_returned_eur + per_surebet_share_eur)
        prior to the cutoff.
        """
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                SUM(
                    CAST(principal_returned_eur AS REAL) +
                    CAST(per_surebet_share_eur AS REAL)
                ) AS should_hold_eur
            FROM ledger_entries
            WHERE associate_id = ?
              AND type = 'BET_RESULT'
              AND created_at_utc <= ?
              AND principal_returned_eur IS NOT NULL
              AND per_surebet_share_eur IS NOT NULL
            """,
            (associate_id, cutoff_date),
        )

        row = cursor.fetchone()
        result = row["should_hold_eur"] or 0.0
        return Decimal(str(result))
    
    def _calculate_current_holding(self, conn, associate_id: int, cutoff_date: str) -> Decimal:
        """
        Calculate CURRENT_HOLDING_EUR = SUM(all ledger entries)
        
        Args:
            conn: Database connection
            associate_id: Associate ID
            cutoff_date: Cutoff date (inclusive)
            
        Returns:
            Current holding as Decimal
        """
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                SUM(CAST(amount_eur AS REAL)) AS current_holding_eur
            FROM ledger_entries
            WHERE associate_id = ?
            AND created_at_utc <= ?
        """, (associate_id, cutoff_date))
        
        row = cursor.fetchone()
        result = row["current_holding_eur"] or 0.0
        return Decimal(str(result))

    def _calculate_profit_before_payout(
        self, conn, associate_id: int, cutoff_date: str
    ) -> Decimal:
        """
        Calculate PROFIT_BEFORE_PAYOUT_EUR = SUM(per_surebet_share_eur).

        Args:
            conn: Database connection
            associate_id: Associate ID
            cutoff_date: Cutoff date (inclusive)

        Returns:
            Profit before payout as Decimal
        """
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                SUM(CAST(per_surebet_share_eur AS REAL)) AS profit_before_payout_eur
            FROM ledger_entries
            WHERE associate_id = ?
              AND type = 'BET_RESULT'
              AND per_surebet_share_eur IS NOT NULL
              AND created_at_utc <= ?
            """,
            (associate_id, cutoff_date),
        )

        row = cursor.fetchone()
        if not row:
            return Decimal("0.00")

        try:
            result = row["profit_before_payout_eur"]  # type: ignore[index]
        except (TypeError, KeyError, IndexError):
            result = row[0] if isinstance(row, (list, tuple)) else 0.0  # type: ignore[index]

        return Decimal(str(result or 0.0))

    def _calculate_bookmaker_breakdown(
        self, conn, associate_id: int, cutoff_date: str
    ) -> List[BookmakerStatementRow]:
        """
        Build per-bookmaker balance/deposit/withdrawal summaries.
        """
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                b.id,
                b.bookmaker_name,
                SUM(CASE WHEN le.id IS NULL THEN 0 ELSE CAST(le.amount_eur AS REAL) END) AS balance_eur,
                SUM(CASE WHEN le.type = 'DEPOSIT' THEN CAST(le.amount_eur AS REAL) ELSE 0 END) AS deposits_eur,
                SUM(CASE WHEN le.type = 'WITHDRAWAL' THEN ABS(CAST(le.amount_eur AS REAL)) ELSE 0 END) AS withdrawals_eur,
                SUM(CASE WHEN le.id IS NULL THEN 0 ELSE CAST(le.amount_native AS REAL) END) AS balance_native,
                a.home_currency AS native_currency
            FROM bookmakers b
            JOIN associates a ON a.id = b.associate_id
            LEFT JOIN ledger_entries le
                ON le.bookmaker_id = b.id
               AND le.associate_id = ?
               AND le.created_at_utc <= ?
            WHERE b.associate_id = ?
            GROUP BY b.id, b.bookmaker_name, a.home_currency
            ORDER BY b.bookmaker_name
            """,
            (associate_id, cutoff_date, associate_id),
        )

        rows = cursor.fetchall() or []
        breakdown: List[BookmakerStatementRow] = []
        for row in rows:
            balance = Decimal(str(row["balance_eur"] or 0.0))
            deposits = Decimal(str(row["deposits_eur"] or 0.0))
            withdrawals = Decimal(str(row["withdrawals_eur"] or 0.0))
            balance_native = Decimal(str(row["balance_native"] or 0.0))
            native_currency = row["native_currency"] or ""
            breakdown.append(
                BookmakerStatementRow(
                    bookmaker_name=row["bookmaker_name"],
                    balance_eur=balance.quantize(Decimal("0.01")),
                    deposits_eur=deposits.quantize(Decimal("0.01")),
                    withdrawals_eur=withdrawals.quantize(Decimal("0.01")),
                    balance_native=balance_native.quantize(Decimal("0.01")),
                    native_currency=native_currency,
                )
            )
        return breakdown
    
    def format_partner_facing_section(self, calc: StatementCalculations) -> PartnerFacingSection:
        """
        Format partner-facing statement section.
        
        Args:
            calc: Statement calculations
            
        Returns:
            Formatted partner-facing section
        """
        return PartnerFacingSection(
            net_deposits_eur=calc.net_deposits_eur,
            fair_share_eur=calc.fs_eur,
            yield_funds_eur=calc.yf_eur,
            total_balance_eur=calc.tb_eur,
            imbalance_eur=calc.i_double_prime_eur,
            exit_payout_eur=calc.exit_payout_eur,
            total_deposits_eur=calc.total_deposits_eur,
            total_withdrawals_eur=calc.total_withdrawals_eur,
            profit_before_payout_eur=calc.profit_before_payout_eur,
            raw_profit_eur=calc.raw_profit_eur,
            bookmakers=calc.bookmakers,
        )
    
    def format_internal_section(self, calc: StatementCalculations) -> InternalSection:
        """
        Format internal-only statement section.
        
        Args:
            calc: Statement calculations
            
        Returns:
            Formatted internal section
        """
        current_holdings = self._format_currency(calc.current_holding_eur)
        delta_amount = self._format_currency(abs(calc.delta_eur))
        
        # Determine delta status indicators
        if calc.delta_eur > 0:
            delta_status = f"Holding more by {delta_amount}"
            delta_indicator = "over"
        elif calc.delta_eur < 0:
            delta_status = f"Short by {delta_amount}"
            delta_indicator = "short"
        else:
            delta_status = "Balanced"
            delta_indicator = "balanced"
        
        return InternalSection(
            current_holdings=f"Currently holding: {current_holdings}",
            reconciliation_delta=delta_status,
            delta_indicator=delta_indicator,
            net_deposits_eur=calc.net_deposits_eur,
            fair_share_eur=calc.fs_eur,
            yield_funds_eur=calc.yf_eur,
            total_balance_eur=calc.tb_eur,
            imbalance_eur=calc.i_double_prime_eur,
            exit_payout_eur=calc.exit_payout_eur,
        )
    
    def _format_currency(self, amount: Decimal) -> str:
        """Format Decimal as Euro currency with commas."""
        return f"EUR {amount:,.2f}"
    
    def get_associate_transactions(self, associate_id: int, cutoff_date: str) -> List[Dict]:
        """
        Get detailed transaction list for Excel export.
        
        Args:
            associate_id: Associate ID
            cutoff_date: Cutoff date (inclusive)
            
        Returns:
            List of transaction dictionaries
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    id,
                    type,
                    amount_eur,
                    native_currency,
                    amount_native,
                    fx_rate_snapshot,
                    settlement_state,
                    principal_returned_eur,
                    per_surebet_share_eur,
                    surebet_id,
                    bet_id,
                    created_at_utc,
                    note
                FROM ledger_entries
                WHERE associate_id = ?
                AND created_at_utc <= ?
                ORDER BY created_at_utc DESC
            """, (associate_id, cutoff_date))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
            
        finally:
            conn.close()
    
    def validate_cutoff_date(self, cutoff_date: str) -> bool:
        """
        Validate that cutoff date is not in the future.
        
        Args:
            cutoff_date: ISO datetime string
            
        Returns:
            True if valid, False if future date
        """
        try:
            cutoff_dt = datetime.fromisoformat(cutoff_date.replace('Z', '+00:00'))
            now_dt = datetime.fromisoformat(utc_now_iso().replace('Z', '+00:00'))
            return cutoff_dt.date() <= now_dt.date()
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # Excel export helpers
    # ------------------------------------------------------------------

    def export_statement_excel(
        self,
        associate_id: int,
        cutoff_date: str,
        *,
        calculations: Optional[StatementCalculations] = None,
    ) -> WorkbookExportPayload:
        """
        Export statement Excel workbook with per-bookmaker allocations and totals.

        Args:
            associate_id: Target associate
            cutoff_date: Cutoff date (inclusive)
            calculations: Optional precomputed calculations to avoid recompute
        """
        calc = calculations or self.generate_statement(associate_id, cutoff_date)
        export_time = utc_now_iso()
        multibook_delta = self._calculate_multibook_delta(associate_id, cutoff_date)
        workbook_bytes = self._build_statement_workbook(
            calc, export_time, multibook_delta
        )
        filename = self._build_statement_filename(calc, cutoff_date)
        return WorkbookExportPayload(filename=filename, content=workbook_bytes, generated_at=export_time)

    def export_surebet_roi_excel(
        self,
        associate_id: int,
        cutoff_date: str,
        *,
        calculations: Optional[StatementCalculations] = None,
    ) -> WorkbookExportPayload:
        """
        Export per-surebet ROI Excel workbook for a given associate.

        Args:
            associate_id: Target associate
            cutoff_date: Cutoff date (inclusive)
            calculations: Optional precomputed calculations
        """
        calc = calculations or self.generate_statement(associate_id, cutoff_date)
        export_time = utc_now_iso()

        conn = get_db_connection()
        try:
            roi_rows = self._fetch_roi_rows(conn, associate_id, cutoff_date)
        finally:
            conn.close()

        rows = self._build_roi_csv_rows(calc, export_time, roi_rows)
        workbook_bytes = self._rows_to_workbook(rows, sheet_name="ROI")
        filename = self._build_filename(
            prefix="surebet_roi",
            associate_alias=calc.associate_name,
            cutoff_date=cutoff_date,
        )
        return WorkbookExportPayload(filename=filename, content=workbook_bytes, generated_at=export_time)

    def settle_associate_now(
        self,
        associate_id: int,
        cutoff_date: str,
        *,
        calculations: Optional[StatementCalculations] = None,
        created_by: str = "system",
    ) -> "ExitSettlementResult":
        """
        Backwards-compatible wrapper around ExitSettlementService.
        """
        from src.services.exit_settlement_service import ExitSettlementService

        service = ExitSettlementService(statement_service=self)
        return service.settle_associate_now(
            associate_id,
            cutoff_date,
            calculations=calculations,
            created_by=created_by,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rows_to_workbook(self, rows: List[List[str]], sheet_name: str) -> bytes:
        """Convert tabular rows into an in-memory Excel workbook."""
        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})
        worksheet = workbook.add_worksheet(sheet_name)
        for row_idx, row in enumerate(rows):
            if not row:
                continue
            for col_idx, value in enumerate(row):
                worksheet.write(row_idx, col_idx, value if value is not None else "")
        workbook.close()
        buffer.seek(0)
        return buffer.getvalue()

    def _build_statement_workbook(
        self,
        calc: StatementCalculations,
        export_time: str,
        multibook_delta: Decimal,
    ) -> bytes:
        """
        Build an in-memory workbook that follows the streamlined statement spec.
        """
        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})
        worksheet = workbook.add_worksheet("Statement")
        worksheet.hide_gridlines(2)
        worksheet.set_column("A:A", 32)
        worksheet.set_column("B:B", 20)
        worksheet.set_column("C:C", 10)
        worksheet.set_column("D:D", 22)

        accounting_format_code = '_(* #,##0.00_);_(* (#,##0.00);_(* "-"??_);_(@_)'
        header_label_fmt = workbook.add_format(
            {
                "bold": True,
                "bg_color": "#F2F2F2",
                "border": 1,
                "align": "left",
                "valign": "vcenter",
            }
        )
        header_value_fmt = workbook.add_format(
            {
                "bg_color": "#F2F2F2",
                "border": 1,
                "align": "left",
                "valign": "vcenter",
            }
        )
        bookmaker_header_fmt = workbook.add_format(
            {
                "bold": True,
                "bg_color": "#F2F2F2",
                "border": 1,
                "align": "left",
                "valign": "vcenter",
            }
        )
        bookmaker_text_fmt = workbook.add_format(
            {"border": 1, "align": "left", "valign": "vcenter"}
        )
        bookmaker_currency_fmt = workbook.add_format(
            {
                "border": 1,
                "align": "right",
                "valign": "vcenter",
                "num_format": accounting_format_code,
            }
        )
        bookmaker_ccy_fmt = workbook.add_format(
            {"border": 1, "align": "center", "valign": "vcenter"}
        )
        bookmaker_total_label_fmt = workbook.add_format(
            {"border": 1, "align": "left", "valign": "vcenter", "bold": True}
        )
        bookmaker_total_value_fmt = workbook.add_format(
            {
                "border": 1,
                "align": "right",
                "valign": "vcenter",
                "bold": True,
                "num_format": accounting_format_code,
            }
        )
        bookmaker_total_blank_fmt = workbook.add_format({"border": 1})
        summary_label_fmt = workbook.add_format({"border": 1, "align": "left"})
        summary_label_bold_fmt = workbook.add_format(
            {"border": 1, "align": "left", "bold": True}
        )
        summary_native_fmt = workbook.add_format(
            {"border": 1, "align": "right", "num_format": accounting_format_code}
        )
        summary_currency_fmt = workbook.add_format({"border": 1, "align": "center"})
        summary_value_fmt = workbook.add_format(
            {"border": 1, "align": "right", "num_format": accounting_format_code}
        )
        summary_value_bold_fmt = workbook.add_format(
            {
                "border": 1,
                "align": "right",
                "num_format": accounting_format_code,
                "bold": True,
            }
        )
        summary_heading_fmt = workbook.add_format(
            {"bold": True, "font_size": 12, "align": "left"}
        )
        positive_fmt = workbook.add_format({"font_color": "#0A8A0A"})
        negative_fmt = workbook.add_format({"font_color": "#B00020"})

        header_rows = [
            ("Associate", calc.associate_name),
            ("As of (UTC)", calc.cutoff_date),
            ("Generated", export_time),
        ]
        for row_idx, (label, value) in enumerate(header_rows):
            worksheet.write(row_idx, 0, f"{label}:", header_label_fmt)
            worksheet.write(row_idx, 1, value, header_value_fmt)

        table_header_row = len(header_rows) + 1
        headers = ["Bookmaker", "Native Balance", "CCY", "Balance (EUR)"]
        for col_idx, label in enumerate(headers):
            worksheet.write(table_header_row, col_idx, label, bookmaker_header_fmt)

        data_start_row = table_header_row + 1
        current_row = data_start_row
        has_bookmakers = bool(calc.bookmakers)
        total_native_dec = Decimal("0.00")
        total_eur_dec = Decimal("0.00")
        if has_bookmakers:
            for bookmaker in calc.bookmakers:
                total_native_dec += bookmaker.balance_native
                total_eur_dec += bookmaker.balance_eur
                worksheet.write(
                    current_row,
                    0,
                    self._normalize_bookmaker_name(bookmaker.bookmaker_name) or "",
                    bookmaker_text_fmt,
                )
                worksheet.write_number(
                    current_row,
                    1,
                    self._decimal_to_float(bookmaker.balance_native),
                    bookmaker_currency_fmt,
                )
                worksheet.write(
                    current_row,
                    2,
                    bookmaker.native_currency or "",
                    bookmaker_ccy_fmt,
                )
                worksheet.write_number(
                    current_row,
                    3,
                    self._decimal_to_float(bookmaker.balance_eur),
                    bookmaker_currency_fmt,
                )
                current_row += 1
        else:
            worksheet.write(
                current_row,
                0,
                "No bookmaker balances available",
                bookmaker_text_fmt,
            )
            worksheet.write_blank(current_row, 1, None, bookmaker_text_fmt)
            worksheet.write_blank(current_row, 2, None, bookmaker_text_fmt)
            worksheet.write_number(current_row, 3, 0.0, bookmaker_currency_fmt)
            current_row += 1

        total_row = current_row
        worksheet.write(total_row, 0, "Total", bookmaker_total_label_fmt)
        if has_bookmakers:
            native_start_cell = xl_rowcol_to_cell(data_start_row, 1)
            native_end_cell = xl_rowcol_to_cell(current_row - 1, 1)
            worksheet.write_formula(
                total_row,
                1,
                f"=SUM({native_start_cell}:{native_end_cell})",
                bookmaker_total_value_fmt,
                self._decimal_to_float(total_native_dec),
            )
        else:
            worksheet.write_number(total_row, 1, 0.0, bookmaker_total_value_fmt)
        worksheet.write_blank(total_row, 2, None, bookmaker_total_blank_fmt)
        if has_bookmakers:
            total_eur = sum(
                self._decimal_to_float(bookmaker.balance_eur)
                for bookmaker in calc.bookmakers
            )
            sum_start_cell = xl_rowcol_to_cell(data_start_row, 3)
            sum_end_cell = xl_rowcol_to_cell(current_row - 1, 3)
            worksheet.write_formula(
                total_row,
                3,
                f"=SUM({sum_start_cell}:{sum_end_cell})",
                bookmaker_total_value_fmt,
                total_eur,
            )
        else:
            worksheet.write_number(total_row, 3, 0.0, bookmaker_total_value_fmt)

        native_multiplier = Decimal("1")
        if has_bookmakers and calc.tb_eur != Decimal("0"):
            native_multiplier = total_native_dec / calc.tb_eur

        summary_heading_row = total_row + 2
        worksheet.merge_range(
            summary_heading_row,
            0,
            summary_heading_row,
            3,
            "Summary (All amounts in EUR)",
            summary_heading_fmt,
        )
        summary_start_row = summary_heading_row + 1
        home_currency = (calc.home_currency or "EUR").upper()
        summary_rows: List[Dict[str, Any]] = [
            {
                "label": "Total Balance",
                "value": calc.tb_eur,
                "native": total_native_dec if has_bookmakers else calc.tb_eur,
                "currency": home_currency,
                "emphasize": False,
            },
            {
                "label": "Net Deposits (ND)",
                "value": calc.net_deposits_eur,
                "native": (calc.net_deposits_eur * native_multiplier),
                "currency": home_currency,
                "emphasize": False,
            },
            {
                "label": "Imbalance (Total Balance − Yield Funds)",
                "value": calc.i_double_prime_eur,
                "native": (calc.i_double_prime_eur * native_multiplier),
                "currency": home_currency,
                "emphasize": True,
            },
            {
                "label": "Fair Share (FS)",
                "value": calc.fs_eur,
                "native": (calc.fs_eur * native_multiplier),
                "currency": home_currency,
                "emphasize": False,
            },
        ]

        for idx, entry in enumerate(summary_rows):
            row_idx = summary_start_row + idx
            label_fmt = (
                summary_label_bold_fmt if entry.get("emphasize") else summary_label_fmt
            )
            value_fmt = (
                summary_value_bold_fmt if entry.get("emphasize") else summary_value_fmt
            )
            worksheet.write(row_idx, 0, entry["label"], label_fmt)
            native_value = entry.get("native")
            if native_value is not None:
                worksheet.write_number(
                    row_idx,
                    1,
                    self._decimal_to_float(native_value),
                    summary_native_fmt,
                )
            else:
                worksheet.write_blank(row_idx, 1, None, summary_native_fmt)
            currency_code = entry.get("currency")
            if currency_code:
                worksheet.write(row_idx, 2, currency_code, summary_currency_fmt)
            else:
                worksheet.write_blank(row_idx, 2, None, summary_currency_fmt)
            worksheet.write_number(
                row_idx,
                3,
                self._decimal_to_float(entry["value"]),
                value_fmt,
            )

        summary_end_row = summary_start_row + len(summary_rows) - 1
        worksheet.conditional_format(
            summary_start_row,
            3,
            summary_end_row,
            3,
            {"type": "cell", "criteria": ">", "value": 0, "format": positive_fmt},
        )
        worksheet.conditional_format(
            summary_start_row,
            3,
            summary_end_row,
            3,
            {"type": "cell", "criteria": "<", "value": 0, "format": negative_fmt},
        )

        workbook.close()
        buffer.seek(0)
        return buffer.getvalue()

    def _build_roi_csv_rows(
        self,
        calc: StatementCalculations,
        export_time: str,
        roi_rows: List[Dict[str, Optional[Decimal]]],
    ) -> List[List[str]]:
        rows: List[List[str]] = [
            ["Associate", calc.associate_name],
            ["As of UTC", calc.cutoff_date],
            ["Generated", export_time],
            ["Identity Version", SETTLEMENT_MODEL_VERSION],
            [
                "Note",
                "ROI rows only include fully settled surebets up to the cutoff.",
            ],
            [],
        ]

        rows.append(
            [
                "Surebet ID",
                "Settled At UTC",
                "Associate Stake (EUR)",
                "Associate Profit (EUR)",
                "Associate ROI %",
                "Group Stake (EUR)",
                "Group Profit (EUR)",
                "Group ROI %",
            ]
        )

        for entry in roi_rows:
            stake = entry.get("associate_stake")
            profit = entry.get("associate_profit")
            group_stake = entry.get("group_stake") or Decimal("0")
            group_profit = entry.get("group_profit") or Decimal("0")

            rows.append(
                [
                    str(entry["surebet_id"]),
                    entry["settled_at_utc"] or "",
                    self._format_decimal(stake or Decimal("0")),
                    self._format_decimal(profit or Decimal("0")),
                    self._format_percentage(self._calculate_roi(profit, stake)),
                    self._format_decimal(group_stake),
                    self._format_decimal(group_profit),
                    self._format_percentage(self._calculate_roi(group_profit, group_stake)),
                ]
            )

        if len(roi_rows) == 0:
            rows.append(["No settled surebets found"] + [""] * 7)

        rows.append([])
        rows.append(["Footnote", SETTLEMENT_MODEL_FOOTNOTE])

        return rows

    def _fetch_roi_rows(
        self, conn, associate_id: int, cutoff_date: str
    ) -> List[Dict[str, Optional[Decimal]]]:
        """
        Query ledger to build per-surebet ROI aggregates.
        """
        cursor = conn.cursor()
        cursor.execute(
            """
            WITH stake_data AS (
                SELECT
                    sb.surebet_id,
                    le.associate_id,
                    SUM(-CAST(le.amount_eur AS REAL)) AS stake_eur
                FROM ledger_entries le
                JOIN surebet_bets sb ON sb.bet_id = le.bet_id
                WHERE le.type = 'BET_STAKE'
                  AND le.bet_id IS NOT NULL
                  AND le.created_at_utc <= ?
                GROUP BY sb.surebet_id, le.associate_id
            ),
            result_data AS (
                SELECT
                    le.surebet_id,
                    le.associate_id,
                    SUM(CAST(le.amount_eur AS REAL)) AS profit_eur
                FROM ledger_entries le
                WHERE le.type = 'BET_RESULT'
                  AND le.surebet_id IS NOT NULL
                  AND le.created_at_utc <= ?
                GROUP BY le.surebet_id, le.associate_id
            ),
            group_stake AS (
                SELECT surebet_id, SUM(stake_eur) AS total_stake
                FROM stake_data
                GROUP BY surebet_id
            ),
            group_profit AS (
                SELECT surebet_id, SUM(profit_eur) AS total_profit
                FROM result_data
                GROUP BY surebet_id
            )
            SELECT
                s.id AS surebet_id,
                s.settled_at_utc,
                sd.stake_eur AS associate_stake_eur,
                rd.profit_eur AS associate_profit_eur,
                gs.total_stake AS group_stake_eur,
                gp.total_profit AS group_profit_eur
            FROM surebets s
            LEFT JOIN stake_data sd
                   ON sd.surebet_id = s.id AND sd.associate_id = ?
            LEFT JOIN result_data rd
                   ON rd.surebet_id = s.id AND rd.associate_id = ?
            LEFT JOIN group_stake gs ON gs.surebet_id = s.id
            LEFT JOIN group_profit gp ON gp.surebet_id = s.id
            WHERE s.status = 'settled'
              AND s.settled_at_utc IS NOT NULL
              AND s.settled_at_utc <= ?
            ORDER BY s.settled_at_utc DESC, s.id DESC
            """,
            (cutoff_date, cutoff_date, associate_id, associate_id, cutoff_date),
        )

        results: List[Dict[str, Optional[Decimal]]] = []
        for row in cursor.fetchall() or []:
            associate_stake = self._to_optional_decimal(row["associate_stake_eur"])
            associate_profit = self._to_optional_decimal(row["associate_profit_eur"])
            if associate_stake is None and associate_profit is None:
                # Skip surebets the associate was never part of
                continue

            results.append(
                {
                    "surebet_id": row["surebet_id"],
                    "settled_at_utc": row["settled_at_utc"],
                    "associate_stake": associate_stake,
                    "associate_profit": associate_profit,
                    "group_stake": self._to_optional_decimal(row["group_stake_eur"]),
                    "group_profit": self._to_optional_decimal(row["group_profit_eur"]),
                }
            )
        return results

    def _calculate_roi(
        self,
        profit: Optional[Decimal],
        stake: Optional[Decimal],
    ) -> Optional[Decimal]:
        if stake is None or stake == Decimal("0"):
            return None
        if profit is None:
            return None
        if abs(stake) < Decimal("0.01"):
            return None
        return (profit / stake) * Decimal("100")

    def _calculate_multibook_delta(
        self,
        associate_id: int,
        cutoff_date: str,
    ) -> Decimal:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                WITH settled_surebets AS (
                    SELECT id
                    FROM surebets
                    WHERE status = 'settled'
                      AND settled_at_utc IS NOT NULL
                      AND settled_at_utc <= ?
                ),
                stake_rows AS (
                    SELECT
                        sb.surebet_id,
                        le.associate_id,
                        SUM(-CAST(le.amount_eur AS REAL)) AS stake_eur
                    FROM ledger_entries le
                    JOIN surebet_bets sb ON sb.bet_id = le.bet_id
                    WHERE le.type = 'BET_STAKE'
                      AND le.created_at_utc <= ?
                      AND sb.surebet_id IN (SELECT id FROM settled_surebets)
                    GROUP BY sb.surebet_id, le.associate_id
                )
                SELECT
                    COALESCE(SUM(CASE WHEN associate_id = ? THEN stake_eur ELSE 0 END), 0) AS associate_total,
                    COALESCE(SUM(stake_eur), 0) AS group_total
                FROM stake_rows
                """,
                (cutoff_date, cutoff_date, associate_id),
            )
            row = cursor.fetchone()
            if not row:
                return Decimal("0.00")
            associate_total = Decimal(str(row["associate_total"] or 0.0))
            group_total = Decimal(str(row["group_total"] or 0.0))
            return group_total - associate_total
        finally:
            conn.close()

    def _format_decimal(self, value: Decimal) -> str:
        quantized = value.quantize(Decimal("0.01"))
        if abs(quantized) < Decimal("0.005"):
            quantized = Decimal("0.00")
        if quantized == Decimal("-0.00"):
            quantized = Decimal("0.00")
        return f"{quantized:,.2f}"

    def _decimal_to_float(self, value: Optional[Decimal]) -> float:
        """Return a rounded float for writing numeric cells."""
        if value is None:
            return 0.0
        quantized = value.quantize(Decimal("0.01"))
        return float(quantized)

    def _format_percentage(self, value: Optional[Decimal]) -> str:
        if value is None:
            return ""
        quantized = value.quantize(Decimal("0.01"))
        if abs(quantized) < Decimal("0.005"):
            quantized = Decimal("0.00")
        return f"{quantized:,.2f}%"

    def _to_optional_decimal(self, value: object) -> Optional[Decimal]:
        if value is None:
            return None
        return Decimal(str(value))

    def _build_filename(self, *, prefix: str, associate_alias: str, cutoff_date: str) -> str:
        date_part = (cutoff_date or "").split("T")[0] or cutoff_date
        if not date_part:
            date_part = datetime.now().strftime("%Y-%m-%d")
        alias_slug = self._slugify(associate_alias)
        return f"{prefix}_{alias_slug}_{date_part}.xlsx"

    def _build_statement_filename(
        self, calc: StatementCalculations, cutoff_date: str
    ) -> str:
        alias_slug = self._slugify(calc.associate_name)
        currency = (calc.home_currency or "EUR").upper()
        date_part = self._format_statement_date(cutoff_date)
        return f"{alias_slug}_{currency}_{date_part}_statement.xlsx"

    def _format_statement_date(self, cutoff_date: str) -> str:
        if not cutoff_date:
            return datetime.now().strftime("%d-%m-%Y")
        normalized = cutoff_date.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            try:
                dt = datetime.strptime(cutoff_date, "%Y-%m-%d")
            except ValueError:
                return cutoff_date
        return dt.strftime("%d-%m-%Y")

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", (value or "").strip()).strip("-").lower()
        return slug or "associate"

    def _normalize_bookmaker_name(self, name: str) -> str:
        if not name:
            return ""
        if name.isupper() or name.islower():
            return name.title()
        return name
