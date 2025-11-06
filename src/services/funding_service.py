"""
Funding Service for managing deposit/withdrawal events and draft approval workflow.

Implements Story 5.4 requirements: pending funding events, draft management,
and ledger entry creation for funding operations.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Dict, List, Optional

import sqlite3
import structlog

from src.core.database import get_db_connection
from src.services.fx_manager import get_fx_rate
from src.utils.database_utils import TransactionError, transactional
from src.utils.datetime_helpers import utc_now_iso

logger = structlog.get_logger(__name__)


class FundingError(Exception):
    """Raised when funding operations fail."""

    pass


@dataclass
class FundingDraft:
    """Draft funding event awaiting approval."""
    draft_id: str  # UUID for in-memory tracking
    associate_id: int
    associate_alias: str
    bookmaker_id: int
    bookmaker_name: str
    event_type: str  # 'DEPOSIT' or 'WITHDRAWAL'
    amount_native: Decimal
    currency: str
    note: Optional[str]
    created_at_utc: str

    def __post_init__(self) -> None:
        """Validate draft data after creation."""
        if self.event_type not in ['DEPOSIT', 'WITHDRAWAL']:
            raise ValueError(f"Invalid event_type: {self.event_type}")
        if self.amount_native <= 0:
            raise ValueError("Amount must be positive")
        if not self.currency or len(self.currency) != 3:
            raise ValueError("Currency must be a valid 3-letter ISO code")
        if self.bookmaker_id <= 0:
            raise ValueError("Bookmaker ID must be a positive integer")
        if not self.bookmaker_name:
            raise ValueError("Bookmaker name must be provided")


class FundingService:
    """Service for managing funding events and draft approval workflow."""
    
    def __init__(self, db: Optional[sqlite3.Connection] = None) -> None:
        """Initialize funding service with database connection."""
        self._owns_connection = db is None
        self.db = db or get_db_connection()
        self._drafts: Dict[str, FundingDraft] = {}  # In-memory draft storage
    
    def close(self) -> None:
        """Close the managed database connection if owned by the service."""
        if not self._owns_connection:
            return
        try:
            self.db.close()
        except Exception:  # pragma: no cover - defensive path
            pass

    def create_funding_draft(
        self, 
        associate_id: int, 
        bookmaker_id: int,
        event_type: str, 
        amount_native: Decimal, 
        currency: str, 
        note: Optional[str] = None,
        associate_alias: Optional[str] = None,
        bookmaker_name: Optional[str] = None,
    ) -> str:
        """
        Create a funding draft and return draft ID.

        Args:
            associate_id: ID of the associate
            bookmaker_id: ID of the bookmaker account
            event_type: 'DEPOSIT' or 'WITHDRAWAL'
            amount_native: Positive amount in native currency
            currency: 3-letter ISO currency code
            note: Optional note for the funding event
            associate_alias: Optional alias for display purposes
            bookmaker_name: Optional bookmaker name for display

        Returns:
            Draft ID (UUID) for tracking

        Raises:
            FundingError: If validation fails
        """
        try:
            # Validate inputs
            if amount_native <= 0:
                raise FundingError("Amount must be positive")
            
            if event_type not in ['DEPOSIT', 'WITHDRAWAL']:
                raise FundingError("Event type must be 'DEPOSIT' or 'WITHDRAWAL'")
            
            if not currency or len(currency) != 3:
                raise FundingError("Currency must be a valid 3-letter ISO code")
            
            if bookmaker_id <= 0:
                raise FundingError("Bookmaker must be selected")

            # Get associate alias if not provided
            if associate_alias is None:
                associate_alias = self._get_associate_alias(associate_id)
            
            # Get bookmaker name and validate association if not provided
            if bookmaker_name is None:
                bookmaker_name = self._get_bookmaker_name(associate_id, bookmaker_id)

            # Create draft
            draft_id = str(uuid.uuid4())
            
            draft = FundingDraft(
                draft_id=draft_id,
                associate_id=associate_id,
                associate_alias=associate_alias,
                bookmaker_id=bookmaker_id,
                bookmaker_name=bookmaker_name,
                event_type=event_type,
                amount_native=amount_native,
                currency=currency.upper(),
                note=note,
                created_at_utc=utc_now_iso()
            )
            
            self._drafts[draft_id] = draft
            
            logger.info(
                "funding_draft_created",
                draft_id=draft_id,
                associate_id=associate_id,
                event_type=event_type,
                amount_native=str(amount_native),
                currency=currency,
                note=note
            )
            
            return draft_id
            
        except (ValueError, InvalidOperation) as e:
            raise FundingError(f"Invalid input: {e}") from e

    def get_pending_drafts(self) -> List[FundingDraft]:
        """
        Get all pending funding drafts.

        Returns:
            List of pending funding drafts ordered by creation time
        """
        return sorted(
            self._drafts.values(),
            key=lambda d: d.created_at_utc,
            reverse=True
        )

    def accept_funding_draft(self, draft_id: str, created_by: str = "local_user") -> str:
        """
        Accept draft and create ledger entry. Returns ledger entry ID.

        Args:
            draft_id: ID of the draft to accept
            created_by: User who accepted the draft

        Returns:
            ID of the created ledger entry

        Raises:
            FundingError: If draft not found or ledger creation fails
        """
        draft = self._drafts.get(draft_id)
        if not draft:
            raise FundingError("Draft not found")
        
        try:
            with transactional(self.db) as conn:
                # Get current FX rate
                fx_rate = get_fx_rate(draft.currency, datetime.now(timezone.utc).date())
                
                # Calculate amount (negative for withdrawals)
                amount_native = draft.amount_native
                if draft.event_type == 'WITHDRAWAL':
                    amount_native = -amount_native
                
                # Create ledger entry
                ledger_id = self._create_ledger_entry(
                    conn=conn,
                    entry_type=draft.event_type,
                    associate_id=draft.associate_id,
                    bookmaker_id=draft.bookmaker_id,
                    amount_native=amount_native,
                    native_currency=draft.currency,
                    fx_rate_snapshot=fx_rate,
                    note=draft.note,
                    created_by=created_by
                )
                
                logger.info(
                    "funding_draft_accepted",
                    draft_id=draft_id,
                    ledger_id=ledger_id,
                    event_type=draft.event_type,
                    associate_id=draft.associate_id,
                    bookmaker_id=draft.bookmaker_id,
                    amount_native=str(amount_native),
                    currency=draft.currency,
                    fx_rate=str(fx_rate)
                )
                
                # Remove draft
                del self._drafts[draft_id]
                
                return ledger_id
                
        except TransactionError as e:
            raise FundingError(f"Database transaction failed: {e}") from e
        except Exception as e:
            logger.error(
                "funding_acceptance_failed",
                draft_id=draft_id,
                error=str(e),
                exc_info=True
            )
            raise FundingError(f"Failed to accept funding draft: {e}") from e

    def reject_funding_draft(self, draft_id: str) -> None:
        """
        Remove draft without creating ledger entry.

        Args:
            draft_id: ID of the draft to reject

        Raises:
            FundingError: If draft not found
        """
        draft = self._drafts.get(draft_id)
        if not draft:
            raise FundingError("Draft not found")
        
        logger.info(
            "funding_draft_rejected",
            draft_id=draft_id,
            event_type=draft.event_type,
            associate_id=draft.associate_id,
            amount_native=str(draft.amount_native),
            currency=draft.currency
        )
        
        # Remove draft
        del self._drafts[draft_id]

    def get_funding_history(self, days: int = 30) -> List[Dict]:
        """
        Get recent accepted funding events for history display.

        Args:
            days: Number of days to look back (default: 30)

        Returns:
            List of funding events with details
        """
        try:
            cutoff_date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            cutoff_date_iso = cutoff_date.isoformat() + "Z"
            
            cursor = self.db.execute(
                """
                SELECT 
                    le.id,
                    le.type as event_type,
                    le.associate_id,
                    a.display_alias as associate_alias,
                    le.bookmaker_id,
                    COALESCE(b.bookmaker_name, '(unknown)') as bookmaker_name,
                    le.amount_native,
                    le.native_currency,
                    le.fx_rate_snapshot,
                    le.amount_eur,
                    le.created_at_utc,
                    le.note
                FROM ledger_entries le
                JOIN associates a ON le.associate_id = a.id
                LEFT JOIN bookmakers b ON le.bookmaker_id = b.id
                WHERE le.type IN ('DEPOSIT', 'WITHDRAWAL')
                AND le.created_at_utc >= ?
                ORDER BY le.created_at_utc DESC
                """,
                (cutoff_date_iso,)
            )
            
            history = []
            for row in cursor.fetchall():
                history.append({
                    'id': row['id'],
                    'event_type': row['event_type'],
                    'associate_id': row['associate_id'],
                    'associate_alias': row['associate_alias'],
                    'bookmaker_id': row['bookmaker_id'],
                    'bookmaker_name': row['bookmaker_name'],
                    'amount_native': Decimal(row['amount_native']),
                    'native_currency': row['native_currency'],
                    'fx_rate_snapshot': Decimal(row['fx_rate_snapshot']),
                    'amount_eur': Decimal(row['amount_eur']),
                    'created_at_utc': row['created_at_utc'],
                    'note': row['note']
                })
            
            return history
            
        except Exception as e:
            logger.error(
                "funding_history_query_failed",
                days=days,
                error=str(e),
                exc_info=True
            )
            raise FundingError(f"Failed to retrieve funding history: {e}") from e

    def _get_associate_alias(self, associate_id: int) -> str:
        """Get associate display alias from database."""
        cursor = self.db.execute(
            "SELECT display_alias FROM associates WHERE id = ?",
            (associate_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise FundingError(f"Associate not found: {associate_id}")
        return row['display_alias']

    def _get_bookmaker_name(self, associate_id: int, bookmaker_id: int) -> str:
        """Validate bookmaker relationship and return its name."""
        cursor = self.db.execute(
            """
            SELECT bookmaker_name
            FROM bookmakers
            WHERE id = ? AND associate_id = ?
            """,
            (bookmaker_id, associate_id),
        )
        row = cursor.fetchone()
        if not row:
            raise FundingError("Selected bookmaker is not assigned to the associate")
        return row["bookmaker_name"]

    def _create_ledger_entry(
        self,
        conn: sqlite3.Connection,
        entry_type: str,
        associate_id: int,
        bookmaker_id: Optional[int],
        amount_native: Decimal,
        native_currency: str,
        fx_rate_snapshot: Decimal,
        note: Optional[str],
        created_by: str
    ) -> int:
        """Create a ledger entry for funding event."""
        amount_eur = self._quantize_currency(amount_native * fx_rate_snapshot)
        
        cursor = conn.execute(
            """
            INSERT INTO ledger_entries (
                type,
                associate_id,
                bookmaker_id,
                surebet_id,
                bet_id,
                settlement_state,
                amount_native,
                native_currency,
                fx_rate_snapshot,
                amount_eur,
                principal_returned_eur,
                per_surebet_share_eur,
                settlement_batch_id,
                created_by,
                note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_type,
                associate_id,
                bookmaker_id,
                None,  # surebet_id
                None,  # bet_id
                None,  # settlement_state
                str(amount_native),
                native_currency,
                str(fx_rate_snapshot),
                str(amount_eur),
                None,  # principal_returned_eur
                None,  # per_surebet_share_eur
                None,  # settlement_batch_id
                created_by,
                note
            )
        )
        
        return cursor.lastrowid

    @staticmethod
    def _quantize_currency(value: Decimal) -> Decimal:
        """Round monetary values to cents."""
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
