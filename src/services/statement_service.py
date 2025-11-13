"""
Monthly Statement Service

Calculates associate statements including funding, entitlement, and reconciliation.
All calculations are read-only and use cutoff date filtering.
"""

from __future__ import annotations

import csv
import io
import re
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

import structlog
from datetime import datetime

from src.core.database import get_db_connection
from src.services.funding_transaction_service import (
    FundingTransaction,
    FundingTransactionError,
    FundingTransactionService,
)
from src.services.settlement_constants import SETTLEMENT_NOTE_PREFIX
from src.utils.datetime_helpers import utc_now_iso

logger = structlog.get_logger()
SETTLEMENT_TOLERANCE = Decimal("0.01")


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
class CsvExportPayload:
    """Container describing an in-memory CSV export."""

    filename: str
    content: bytes
    generated_at: str


@dataclass
class SettleAssociateResult:
    """Result metadata returned after executing Settle Associate Now."""

    entry_id: Optional[int]
    entry_type: Optional[str]
    amount_eur: Decimal
    delta_before: Decimal
    delta_after: Decimal
    note: str
    was_posted: bool
    updated_calculations: StatementCalculations


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
        Get detailed transaction list for CSV export.
        
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
    # CSV Export helpers
    # ------------------------------------------------------------------

    def export_statement_csv(
        self,
        associate_id: int,
        cutoff_date: str,
        *,
        calculations: Optional[StatementCalculations] = None,
    ) -> CsvExportPayload:
        """
        Export statement CSV with per-bookmaker allocations and totals.

        Args:
            associate_id: Target associate
            cutoff_date: Cutoff date (inclusive)
            calculations: Optional precomputed calculations to avoid recompute
        """
        calc = calculations or self.generate_statement(associate_id, cutoff_date)
        export_time = utc_now_iso()
        multibook_delta = self._calculate_multibook_delta(associate_id, cutoff_date)
        rows = self._build_statement_csv_rows(calc, export_time, multibook_delta)
        csv_bytes = self._rows_to_csv(rows)
        filename = self._build_filename(
            prefix="legacy_statement",
            associate_alias=calc.associate_name,
            cutoff_date=cutoff_date,
        )
        return CsvExportPayload(filename=filename, content=csv_bytes, generated_at=export_time)

    def export_surebet_roi_csv(
        self,
        associate_id: int,
        cutoff_date: str,
        *,
        calculations: Optional[StatementCalculations] = None,
    ) -> CsvExportPayload:
        """
        Export per-surebet ROI CSV for a given associate.

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
        csv_bytes = self._rows_to_csv(rows)
        filename = self._build_filename(
            prefix="surebet_roi",
            associate_alias=calc.associate_name,
            cutoff_date=cutoff_date,
        )
        return CsvExportPayload(filename=filename, content=csv_bytes, generated_at=export_time)

    def settle_associate_now(
        self,
        associate_id: int,
        cutoff_date: str,
        *,
        calculations: Optional[StatementCalculations] = None,
        created_by: str = "system",
    ) -> SettleAssociateResult:
        """
        Execute the Settle Associate Now workflow.

        Computes the imbalance at the provided cutoff, writes a single balancing
        DEPOSIT/WITHDRAWAL entry, and returns an updated statement snapshot.
        """
        calc = calculations or self.generate_statement(associate_id, cutoff_date)
        delta_before = calc.i_double_prime_eur.quantize(Decimal("0.01"))
        amount_eur = abs(delta_before)

        if amount_eur <= SETTLEMENT_TOLERANCE:
            note = "Associate already balanced - no ledger entry created."
            return SettleAssociateResult(
                entry_id=None,
                entry_type=None,
                amount_eur=Decimal("0.00"),
                delta_before=delta_before,
                delta_after=delta_before,
                note=note,
                was_posted=False,
                updated_calculations=calc,
            )

        entry_type = "WITHDRAWAL" if delta_before > 0 else "DEPOSIT"
        settlement_note = f"{SETTLEMENT_NOTE_PREFIX} ({cutoff_date})"

        funding_service = FundingTransactionService()
        try:
            transaction = FundingTransaction(
                associate_id=associate_id,
                bookmaker_id=None,
                transaction_type=entry_type,
                amount_native=amount_eur,
                native_currency="EUR",
                note=settlement_note,
                created_by=created_by,
            )
            entry_id = funding_service.record_transaction(
                transaction, created_at_override=cutoff_date
            )
        except (FundingTransactionError, ValueError) as exc:
            raise RuntimeError(f"Failed to post settlement entry: {exc}") from exc
        finally:
            funding_service.close()

        updated_calc = self.generate_statement(associate_id, cutoff_date)
        delta_after = updated_calc.i_double_prime_eur.quantize(Decimal("0.01"))

        return SettleAssociateResult(
            entry_id=entry_id,
            entry_type=entry_type,
            amount_eur=amount_eur,
            delta_before=delta_before,
            delta_after=delta_after,
            note=settlement_note,
            was_posted=True,
            updated_calculations=updated_calc,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rows_to_csv(self, rows: List[List[str]]) -> bytes:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerows(rows)
        return buffer.getvalue().encode("utf-8")

    def _build_statement_csv_rows(
        self,
        calc: StatementCalculations,
        export_time: str,
        multibook_delta: Decimal,
    ) -> List[List[str]]:
        rows: List[List[str]] = [
            ["Associate", calc.associate_name],
            ["As of (UTC)", calc.cutoff_date],
            ["Generated", export_time],
            [
                "Note",
                "Totals in EUR. Native shown for reference. FX frozen at posting time.",
            ],
            [],
        ]

        header = [
            "Bookmaker",
            "Balance Native",
            "",
            "CCY",
            "Balance EUR",
            "CCY_EUR",
        ]
        rows.append(header)

        if calc.bookmakers:
            for bookmaker in calc.bookmakers:
                rows.append(
                    [
                        self._normalize_bookmaker_name(bookmaker.bookmaker_name),
                        self._format_decimal(bookmaker.balance_native),
                        "",
                        bookmaker.native_currency or "",
                        self._format_decimal(bookmaker.balance_eur),
                        "EURO",
                    ]
                )
        else:
            rows.append(
                [
                    "No bookmaker balances available",
                    "",
                    "",
                    "",
                    self._format_decimal(Decimal("0")),
                    "EURO",
                ]
            )

        rows.append([])
        rows.extend(
            [
                ["Net Deposits (ND)", self._format_decimal(calc.net_deposits_eur), "EURO"],
                ["Fair Share (FS)", self._format_decimal(calc.fs_eur), "EURO"],
                [
                    "Yield Funds (YF = ND + FS)",
                    self._format_decimal(calc.yf_eur),
                    "EURO",
                ],
                ["Total Balance (TB)", self._format_decimal(calc.tb_eur), "EURO"],
                ["Imbalance (I'' = TB - YF)", self._format_decimal(calc.i_double_prime_eur), "EURO"],
                ["Exit Payout (-I'')", self._format_decimal(calc.exit_payout_eur), "EURO"],
                ["Multibook Delta", self._format_decimal(multibook_delta), "EURO"],
                ["UTILE (YF - ND)", self._format_decimal(calc.raw_profit_eur), "EURO"],
            ]
        )
        return rows

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
        return f"{prefix}_{alias_slug}_{date_part}.csv"

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", (value or "").strip()).strip("-").lower()
        return slug or "associate"

    def _normalize_bookmaker_name(self, name: str) -> str:
        if not name:
            return ""
        if name.isupper() or name.islower():
            return name.title()
        return name
