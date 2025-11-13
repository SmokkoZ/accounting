"""
Funding Transaction Service for Story 5.5

Wraps ledger entry creation for DEPOSIT/WITHDRAWAL operations in the Associate Operations Hub.
Provides centralized business rules and validation for funding transactions.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Dict, List, Optional

import structlog

from src.core.database import get_db_connection
from src.services.fx_manager import get_fx_rate
from src.services.settlement_constants import SETTLEMENT_NOTE_PREFIX
from src.utils.database_utils import TransactionError, transactional
from src.utils.datetime_helpers import utc_now_iso

logger = structlog.get_logger(__name__)

TWO_PLACES = Decimal("0.01")


class FundingTransactionError(Exception):
    """Raised when funding transaction operations fail."""

    pass


@dataclass
class FundingTransaction:
    """Funding transaction details for ledger entry creation."""
    associate_id: int
    bookmaker_id: Optional[int]  # None for associate-level funding
    transaction_type: str  # 'DEPOSIT' or 'WITHDRAWAL'
    amount_native: Decimal
    native_currency: str
    note: Optional[str]
    created_by: str = "local_user"

    def __post_init__(self) -> None:
        """Validate transaction data after creation."""
        if self.transaction_type not in ['DEPOSIT', 'WITHDRAWAL']:
            raise ValueError(f"Invalid transaction_type: {self.transaction_type}")
        if self.amount_native <= 0:
            raise ValueError("Amount must be positive")
        if not self.native_currency or len(self.native_currency) != 3:
            raise ValueError("Currency must be a valid 3-letter ISO code")


class FundingTransactionService:
    """Service for managing funding transactions with business rule centralization."""
    
    def __init__(self, db: Optional[sqlite3.Connection] = None) -> None:
        """Initialize funding transaction service with database connection."""
        self._owns_connection = db is None
        self.db = db or get_db_connection()
    
    def close(self) -> None:
        """Close the managed database connection if owned by the service."""
        if not self._owns_connection:
            return
        try:
            self.db.close()
        except Exception:  # pragma: no cover - defensive close
            pass

    def record_transaction(
        self,
        transaction: FundingTransaction,
        *,
        created_at_override: Optional[str] = None,
    ) -> str:
        """
        Record a funding transaction and create ledger entry.
        
        Args:
            transaction: Funding transaction details
            
        Returns:
            Ledger entry ID of the created transaction
            
        Raises:
            FundingTransactionError: If validation or ledger creation fails
        """
        try:
            # Validate transaction
            self._validate_transaction(transaction)
            
            with transactional(self.db) as conn:
                # Get current FX rate
                fx_rate = self._get_fx_rate(transaction.native_currency)
                
                # Calculate amount (negative for withdrawals)
                amount_native = transaction.amount_native
                if transaction.transaction_type == 'WITHDRAWAL':
                    amount_native = -amount_native
                
                # Create ledger entry
                ledger_id = self._create_ledger_entry(
                    conn=conn,
                    transaction=transaction,
                    amount_native=amount_native,
                    fx_rate_snapshot=fx_rate,
                    created_at_override=created_at_override,
                )
                
                logger.info(
                    "funding_transaction_recorded",
                    ledger_id=ledger_id,
                    associate_id=transaction.associate_id,
                    bookmaker_id=transaction.bookmaker_id,
                    transaction_type=transaction.transaction_type,
                    amount_native=str(amount_native),
                    native_currency=transaction.native_currency,
                    fx_rate=str(fx_rate),
                    created_by=transaction.created_by
                )
                
                return ledger_id
                
        except TransactionError as e:
            raise FundingTransactionError(f"Database transaction failed: {e}") from e
        except (ValueError, InvalidOperation) as e:
            raise FundingTransactionError(f"Invalid input: {e}") from e
        except Exception as e:
            logger.error(
                "funding_transaction_failed",
                associate_id=transaction.associate_id,
                transaction_type=transaction.transaction_type,
                amount_native=str(transaction.amount_native),
                currency=transaction.native_currency,
                error=str(e),
                exc_info=True
            )
            raise FundingTransactionError(f"Failed to record funding transaction: {e}") from e

    def get_transaction_history(
        self,
        associate_id: Optional[int] = None,
        bookmaker_id: Optional[int] = None,
        days: int = 30
    ) -> List[Dict]:
        """
        Get recent funding transaction history.
        
        Args:
            associate_id: Filter by associate ID (optional)
            bookmaker_id: Filter by bookmaker ID (optional)
            days: Number of days to look back (default: 30)
            
        Returns:
            List of funding transactions with details
        """
        try:
            from datetime import datetime, timezone
            
            cutoff_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            cutoff_date_iso = cutoff_date.isoformat() + "Z"
            
            query = """
            SELECT 
                le.id,
                le.type as transaction_type,
                le.associate_id,
                a.display_alias as associate_alias,
                le.bookmaker_id,
                b.bookmaker_name as bookmaker_name,
                le.amount_native,
                le.native_currency,
                le.fx_rate_snapshot,
                le.amount_eur,
                le.created_at_utc,
                le.created_by,
                le.note
            FROM ledger_entries le
            JOIN associates a ON le.associate_id = a.id
            LEFT JOIN bookmakers b ON le.bookmaker_id = b.id
            WHERE le.type IN ('DEPOSIT', 'WITHDRAWAL')
            AND le.created_at_utc >= ?
            """
            
            params: List = [cutoff_date_iso]
            
            if associate_id:
                query += " AND le.associate_id = ?"
                params.append(associate_id)
                
            if bookmaker_id:
                query += " AND le.bookmaker_id = ?"
                params.append(bookmaker_id)
            
            query += " ORDER BY le.created_at_utc DESC"
            
            cursor = self.db.execute(query, params)
            rows = cursor.fetchall()
            
            history = []
            for row in rows:
                history.append({
                    'id': row['id'],
                    'transaction_type': row['transaction_type'],
                    'associate_id': row['associate_id'],
                    'associate_alias': row['associate_alias'],
                    'bookmaker_id': row['bookmaker_id'],
                    'bookmaker_name': row['bookmaker_name'],
                    'amount_native': Decimal(row['amount_native']),
                    'native_currency': row['native_currency'],
                    'fx_rate_snapshot': Decimal(row['fx_rate_snapshot']),
                    'amount_eur': Decimal(row['amount_eur']),
                    'created_at_utc': row['created_at_utc'],
                    'created_by': row['created_by'],
                    'note': row['note']
                })
            
            return history
            
        except Exception as e:
            logger.error(
                "funding_history_query_failed",
                associate_id=associate_id,
                bookmaker_id=bookmaker_id,
                days=days,
                error=str(e),
                exc_info=True
            )
            raise FundingTransactionError(f"Failed to retrieve funding history: {e}") from e

    def get_associate_balance_summary(self, associate_id: int) -> Dict[str, Decimal]:
        """
        Get balance summary for an associate.
        
        Args:
            associate_id: ID of the associate
            
        Returns:
            Dictionary with balance metrics
        """
        try:
            # Net deposits (deposits - withdrawals)
            cursor = self.db.execute(
                """
                SELECT 
                    SUM(CAST(amount_eur AS REAL)) AS net_deposits_eur
                FROM ledger_entries 
                WHERE associate_id = ?
                  AND type IN ('DEPOSIT', 'WITHDRAWAL')
                  AND (note IS NULL OR note NOT LIKE ?)
                """,
                (associate_id, f"{SETTLEMENT_NOTE_PREFIX}%")
            )
            net_deposits_row = cursor.fetchone()
            net_deposits_eur = Decimal(str(net_deposits_row['net_deposits_eur'] or 0)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            
            # Current holdings (positive ledger entries from betting activities)
            cursor = self.db.execute(
                """
                SELECT 
                    SUM(CAST(amount_eur AS REAL)) AS current_holding_eur
                FROM ledger_entries
                WHERE associate_id = ?
                """,
                (associate_id,)
            )
            holdings_row = cursor.fetchone()
            current_holding_eur = Decimal(str(holdings_row['current_holding_eur'] or 0)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            
            delta_eur = current_holding_eur - net_deposits_eur
            
            return {
                'net_deposits_eur': net_deposits_eur,
                'current_holding_eur': current_holding_eur,
                'delta_eur': delta_eur.quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
                'should_hold_eur': net_deposits_eur
            }
            
        except Exception as e:
            logger.error(
                "balance_summary_failed",
                associate_id=associate_id,
                error=str(e),
                exc_info=True
            )
            raise FundingTransactionError(f"Failed to get balance summary: {e}") from e

    def validate_funding_amount(
        self,
        amount_native: Decimal,
        native_currency: str
    ) -> None:
        """
        Validate funding amount meets business rules.
        
        Args:
            amount_native: Amount in native currency
            native_currency: Currency code
            
        Raises:
            FundingTransactionError: If validation fails
        """
        if amount_native <= 0:
            raise FundingTransactionError("Amount must be positive")
        
        if amount_native > Decimal("100000"):  # Prevent accidental large amounts
            raise FundingTransactionError("Amount exceeds maximum allowed (€100,000 equivalent)")
        
        # Additional currency-specific validations can be added here
        if not native_currency or len(native_currency) != 3:
            raise FundingTransactionError("Invalid currency code")

    def _validate_transaction(self, transaction: FundingTransaction) -> None:
        """Validate transaction details."""
        self.validate_funding_amount(transaction.amount_native, transaction.native_currency)
        
        # Verify associate exists
        cursor = self.db.execute(
            "SELECT id FROM associates WHERE id = ?",
            (transaction.associate_id,)
        )
        if not cursor.fetchone():
            raise FundingTransactionError(f"Associate not found: {transaction.associate_id}")
        
        # Verify bookmaker exists if specified
        if transaction.bookmaker_id:
            cursor = self.db.execute(
                "SELECT id FROM bookmakers WHERE id = ? AND associate_id = ?",
                (transaction.bookmaker_id, transaction.associate_id)
            )
            if not cursor.fetchone():
                raise FundingTransactionError(f"Bookmaker not found: {transaction.bookmaker_id}")

    def _get_fx_rate(self, currency: str) -> Decimal:
        """Get current FX rate for currency."""
        from datetime import date
        
        fx_rate = get_fx_rate(currency, date.today())
        if fx_rate is None:
            logger.warning("fx_rate_missing", currency=currency)
            return Decimal("1.0")  # Default to 1:1 if rate unavailable
        return fx_rate.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

    def _create_ledger_entry(
        self,
        conn: sqlite3.Connection,
        transaction: FundingTransaction,
        amount_native: Decimal,
        fx_rate_snapshot: Decimal,
        created_at_override: Optional[str] = None,
    ) -> int:
        """Create a ledger entry for the funding transaction."""
        amount_eur = self._quantize_currency(amount_native * fx_rate_snapshot)
        
        columns = [
            "type",
            "associate_id",
            "bookmaker_id",
            "surebet_id",
            "bet_id",
            "settlement_state",
            "amount_native",
            "native_currency",
            "fx_rate_snapshot",
            "amount_eur",
            "principal_returned_eur",
            "per_surebet_share_eur",
            "settlement_batch_id",
            "created_by",
            "note",
        ]
        values = [
            transaction.transaction_type,
            transaction.associate_id,
            transaction.bookmaker_id,
            None,  # surebet_id
            None,  # bet_id
            None,  # settlement_state
            str(amount_native),
            transaction.native_currency,
            str(fx_rate_snapshot),
            str(amount_eur),
            None,  # principal_returned_eur
            None,  # per_surebet_share_eur
            None,  # settlement_batch_id
            transaction.created_by,
            transaction.note,
        ]

        if created_at_override:
            columns.append("created_at_utc")
            values.append(created_at_override)

        placeholders = ", ".join("?" for _ in columns)
        column_list = ", ".join(columns)
        cursor = conn.execute(
            f"INSERT INTO ledger_entries ({column_list}) VALUES ({placeholders})",
            values,
        )
        
        return cursor.lastrowid

    @staticmethod
    def _quantize_currency(value: Decimal) -> Decimal:
        """Round monetary values to cents."""
        return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    # Context manager convenience -------------------------------------------------

    def __enter__(self) -> "FundingTransactionService":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
