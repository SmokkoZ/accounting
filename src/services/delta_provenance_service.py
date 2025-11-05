"""
Delta Provenance Service

This service provides delta provenance tracking, allowing associates to trace
their surpluses/shortfalls back to specific counterparties and surebets.
"""

import sqlite3
from decimal import Decimal
from typing import List, Dict, Optional, Tuple
import structlog
from datetime import datetime, timezone

from src.core.database import get_db_connection
from src.utils.datetime_helpers import utc_now_iso

logger = structlog.get_logger(__name__)


class DeltaProvenanceEntry:
    """Represents a single delta provenance entry."""
    
    def __init__(
        self,
        surebet_id: int,
        counterparty_alias: str,
        counterparty_associate_id: int,
        amount_eur: Decimal,
        is_positive: bool,
        created_at_utc: str,
        ledger_entry_id: int,
        note: Optional[str] = None
    ):
        self.surebet_id = surebet_id
        self.counterparty_alias = counterparty_alias
        self.counterparty_associate_id = counterparty_associate_id
        self.amount_eur = amount_eur
        self.is_positive = is_positive
        self.created_at_utc = created_at_utc
        self.ledger_entry_id = ledger_entry_id
        self.note = note
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for UI/API consumption."""
        return {
            'surebet_id': self.surebet_id,
            'counterparty_alias': self.counterparty_alias,
            'counterparty_associate_id': self.counterparty_associate_id,
            'amount_eur': str(self.amount_eur),
            'is_positive': self.is_positive,
            'created_at_utc': self.created_at_utc,
            'ledger_entry_id': self.ledger_entry_id,
            'note': self.note
        }


class DeltaProvenanceSummary:
    """Summary of delta provenance for an associate."""
    
    def __init__(self):
        self.total_surplus = Decimal('0.00')
        self.total_deficit = Decimal('0.00')
        self.net_delta = Decimal('0.00')
        self.surebet_count = 0
        self.counterparty_breakdown: Dict[str, Decimal] = {}
    
    def add_entry(self, entry: DeltaProvenanceEntry) -> None:
        """Add a provenance entry to summary."""
        # For negative entries, use the absolute amount for deficit tracking
        if entry.is_positive:
            self.total_surplus += entry.amount_eur
            signed_amount = entry.amount_eur
        else:
            self.total_deficit += abs(entry.amount_eur)
            signed_amount = -abs(entry.amount_eur)
        
        self.net_delta += signed_amount
        self.surebet_count += 1
        
        # Track counterparty breakdown with signed amount
        counterparty = entry.counterparty_alias
        if counterparty not in self.counterparty_breakdown:
            self.counterparty_breakdown[counterparty] = Decimal('0.00')
        self.counterparty_breakdown[counterparty] += signed_amount
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for UI/API consumption."""
        return {
            'total_surplus': str(self.total_surplus),
            'total_deficit': str(self.total_deficit),
            'net_delta': str(self.net_delta),
            'surebet_count': self.surebet_count,
            'counterparty_breakdown': {
                k: str(v) for k, v in self.counterparty_breakdown.items()
            }
        }


class DeltaProvenanceService:
    """Service for delta provenance operations."""
    
    def __init__(self, db_connection: Optional[sqlite3.Connection] = None):
        self.db = db_connection or get_db_connection()
        # Set row_factory to return dictionaries instead of tuples
        if hasattr(self.db, 'row_factory'):
            self.db.row_factory = sqlite3.Row
    
    def get_associate_delta_provenance(
        self,
        associate_id: int,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[DeltaProvenanceEntry], DeltaProvenanceSummary]:
        """
        Get delta provenance for an associate.
        
        Args:
            associate_id: ID of the associate to query
            limit: Maximum number of entries to return
            offset: Number of entries to skip (for pagination)
            
        Returns:
            Tuple of (entries list, summary)
        """
        start_time = datetime.now(timezone.utc)
        
        try:
            # Get settlement links where associate is winner or loser
            query = """
                SELECT 
                    ssl.surebet_id,
                    ssl.amount_eur,
                    ssl.created_at_utc,
                    CASE 
                        WHEN ssl.winner_associate_id = ? THEN ssl.loser_associate_id
                        ELSE ssl.winner_associate_id
                    END as counterparty_associate_id,
                    CASE 
                        WHEN ssl.winner_associate_id = ? THEN ssl.winner_ledger_entry_id
                        ELSE ssl.loser_ledger_entry_id
                    END as ledger_entry_id,
                    CASE 
                        WHEN ssl.winner_associate_id = ? THEN 1
                        ELSE -1
                    END as sign_multiplier,
                    a.display_alias as counterparty_alias,
                    le.note
                FROM surebet_settlement_links ssl
                JOIN associates a ON (
                    (ssl.winner_associate_id = ? AND a.id = ssl.loser_associate_id) OR
                    (ssl.loser_associate_id = ? AND a.id = ssl.winner_associate_id)
                )
                LEFT JOIN ledger_entries le ON (
                    (ssl.winner_associate_id = ? AND le.id = ssl.winner_ledger_entry_id) OR
                    (ssl.loser_associate_id = ? AND le.id = ssl.loser_ledger_entry_id)
                )
                WHERE (ssl.winner_associate_id = ? OR ssl.loser_associate_id = ?)
                ORDER BY ssl.created_at_utc DESC
                LIMIT ? OFFSET ?
            """
            
            cursor = self.db.execute(
                query,
                (
                    associate_id, associate_id, associate_id,  # For CASE statements
                    associate_id, associate_id,               # For JOIN conditions
                    associate_id, associate_id,               # For LEFT JOIN
                    associate_id, associate_id,               # For WHERE clause
                    limit, offset
                )
            )
            
            entries = []
            for row in cursor.fetchall():
                amount_eur = Decimal(row['amount_eur'])
                is_positive = row['sign_multiplier'] > 0
                
                entry = DeltaProvenanceEntry(
                    surebet_id=row['surebet_id'],
                    counterparty_alias=row['counterparty_alias'],
                    counterparty_associate_id=row['counterparty_associate_id'],
                    amount_eur=amount_eur,
                    is_positive=is_positive,
                    created_at_utc=row['created_at_utc'],
                    ledger_entry_id=row['ledger_entry_id'],
                    note=row['note']
                )
                entries.append(entry)
            
            # Build summary
            summary = DeltaProvenanceSummary()
            for entry in entries:
                summary.add_entry(entry)
            
            # Calculate duration and log telemetry
            end_time = datetime.now(timezone.utc)
            duration_ms = int((end_time - start_time).total_seconds() * 1000)
            
            logger.info(
                "delta_provenance_viewed",
                associate_id=associate_id,
                entry_count=len(entries),
                surebet_count=summary.surebet_count,
                duration_ms=duration_ms
            )
            
            return entries, summary
            
        except Exception as e:
            logger.error(
                "delta_provenance_query_failed",
                associate_id=associate_id,
                error=str(e)
            )
            raise
    
    def get_counterparty_delta_summary(
        self,
        associate_id: int,
        counterparty_associate_id: int
    ) -> Dict:
        """
        Get delta summary between two associates.
        
        Args:
            associate_id: Primary associate ID
            counterparty_associate_id: Counterparty associate ID
            
        Returns:
            Dictionary with summary information
        """
        start_time = datetime.now(timezone.utc)
        
        query = """
            SELECT 
                COUNT(*) as transaction_count,
                SUM(CASE 
                    WHEN ssl.winner_associate_id = ? THEN ssl.amount_eur
                    ELSE -ssl.amount_eur
                END) as net_amount_eur,
                SUM(CASE 
                    WHEN ssl.winner_associate_id = ? THEN ssl.amount_eur
                    ELSE 0
                END) as total_won_eur,
                SUM(CASE 
                    WHEN ssl.loser_associate_id = ? THEN ssl.amount_eur
                    ELSE 0
                END) as total_lost_eur,
                MIN(ssl.created_at_utc) as first_transaction,
                MAX(ssl.created_at_utc) as last_transaction
            FROM surebet_settlement_links ssl
            WHERE (ssl.winner_associate_id = ? AND ssl.loser_associate_id = ?)
            OR (ssl.winner_associate_id = ? AND ssl.loser_associate_id = ?)
        """
        
        cursor = self.db.execute(
            query,
            (associate_id, associate_id, associate_id, associate_id, counterparty_associate_id,
             associate_id, counterparty_associate_id)
        )
        
        row = cursor.fetchone()
        
        # Calculate duration and log telemetry
        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)
        
        logger.info(
            "counterparty_summary_viewed",
            associate_id=associate_id,
            counterparty_id=counterparty_associate_id,
            transaction_count=row['transaction_count'] if row else 0,
            duration_ms=duration_ms
        )
        
        if not row:
            return {
                'transaction_count': 0,
                'net_amount_eur': '0.00',
                'total_won_eur': '0.00',
                'total_lost_eur': '0.00',
                'first_transaction': None,
                'last_transaction': None
            }
        
        return {
            'transaction_count': row['transaction_count'],
            'net_amount_eur': f"{Decimal(row['net_amount_eur'] or '0.00'):.2f}",
            'total_won_eur': f"{Decimal(row['total_won_eur'] or '0.00'):.2f}",
            'total_lost_eur': f"{Decimal(row['total_lost_eur'] or '0.00'):.2f}",
            'first_transaction': row['first_transaction'],
            'last_transaction': row['last_transaction']
        }
    
    def get_surebet_delta_details(
        self,
        surebet_id: int,
        associate_id: Optional[int] = None
    ) -> List[Dict]:
        """
        Get delta details for a specific surebet.
        
        Args:
            surebet_id: ID of the surebet to query
            associate_id: Optional associate ID to filter results
            
        Returns:
            List of settlement link details
        """
        start_time = datetime.now(timezone.utc)
        
        query = """
            SELECT 
                ssl.surebet_id,
                ssl.winner_associate_id,
                ssl.loser_associate_id,
                ssl.amount_eur,
                ssl.winner_ledger_entry_id,
                ssl.loser_ledger_entry_id,
                ssl.created_at_utc,
                winner_alias.display_alias as winner_alias,
                loser_alias.display_alias as loser_alias,
                winner_ledger.amount_eur as winner_amount_eur,
                loser_ledger.amount_eur as loser_amount_eur,
                winner_ledger.settlement_state as winner_settlement_state,
                loser_ledger.settlement_state as loser_settlement_state
            FROM surebet_settlement_links ssl
            JOIN associates winner_alias ON ssl.winner_associate_id = winner_alias.id
            JOIN associates loser_alias ON ssl.loser_associate_id = loser_alias.id
            JOIN ledger_entries winner_ledger ON ssl.winner_ledger_entry_id = winner_ledger.id
            JOIN ledger_entries loser_ledger ON ssl.loser_ledger_entry_id = loser_ledger.id
            WHERE ssl.surebet_id = ?
            {associate_filter}
            ORDER BY ssl.created_at_utc DESC
        """
        
        # Add associate filter if specified
        if associate_id:
            associate_filter = "AND (ssl.winner_associate_id = ? OR ssl.loser_associate_id = ?)"
            cursor = self.db.execute(
                query.format(associate_filter=associate_filter),
                (surebet_id, associate_id, associate_id)
            )
        else:
            associate_filter = ""
            cursor = self.db.execute(query.format(associate_filter=associate_filter), (surebet_id,))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'surebet_id': row['surebet_id'],
                'winner_associate_id': row['winner_associate_id'],
                'loser_associate_id': row['loser_associate_id'],
                'winner_alias': row['winner_alias'],
                'loser_alias': row['loser_alias'],
                'amount_eur': row['amount_eur'],
                'winner_amount_eur': row['winner_amount_eur'],
                'loser_amount_eur': row['loser_amount_eur'],
                'winner_settlement_state': row['winner_settlement_state'],
                'loser_settlement_state': row['loser_settlement_state'],
                'winner_ledger_entry_id': row['winner_ledger_entry_id'],
                'loser_ledger_entry_id': row['loser_ledger_entry_id'],
                'created_at_utc': row['created_at_utc']
            })
        
        # Calculate duration and log telemetry
        end_time = datetime.now(timezone.utc)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)
        
        logger.info(
            "surebet_details_viewed",
            surebet_id=surebet_id,
            associate_id=associate_id,
            result_count=len(results),
            duration_ms=duration_ms
        )
        
        return results
    
    def create_settlement_link(
        self,
        surebet_id: int,
        winner_associate_id: int,
        loser_associate_id: int,
        amount_eur: Decimal,
        winner_ledger_entry_id: int,
        loser_ledger_entry_id: int
    ) -> int:
        """
        Create a new settlement link.
        
        Args:
            surebet_id: ID of the settled surebet
            winner_associate_id: ID of the winning associate
            loser_associate_id: ID of the losing associate
            amount_eur: Amount transferred (positive)
            winner_ledger_entry_id: ID of the winner's ledger entry
            loser_ledger_entry_id: ID of the loser's ledger entry
            
        Returns:
            ID of the created settlement link
        """
        start_time = datetime.now(timezone.utc)
        
        try:
            cursor = self.db.execute(
                """
                INSERT INTO surebet_settlement_links (
                    surebet_id,
                    winner_associate_id,
                    loser_associate_id,
                    amount_eur,
                    winner_ledger_entry_id,
                    loser_ledger_entry_id,
                    created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    surebet_id,
                    winner_associate_id,
                    loser_associate_id,
                    str(amount_eur),
                    winner_ledger_entry_id,
                    loser_ledger_entry_id,
                    utc_now_iso()
                )
            )
            
            link_id = cursor.lastrowid
            
            # Calculate duration and log telemetry
            end_time = datetime.now(timezone.utc)
            duration_ms = int((end_time - start_time).total_seconds() * 1000)
            
            logger.info(
                "settlement_link_created",
                surebet_id=surebet_id,
                winner_associate_id=winner_associate_id,
                loser_associate_id=loser_associate_id,
                amount_eur=str(amount_eur),
                link_id=link_id,
                duration_ms=duration_ms
            )
            
            return link_id
            
        except sqlite3.Error as e:
            logger.error(
                "settlement_link_creation_failed",
                surebet_id=surebet_id,
                error=str(e)
            )
            raise
    
    def close(self) -> None:
        """Close the database connection if we created it."""
        # Only close if we created the connection ourselves
        if hasattr(self, '_own_connection') and self._own_connection:
            self.db.close()
