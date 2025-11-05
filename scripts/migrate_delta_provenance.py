"""
Migration script for delta provenance backfill.

This script populates surebet_settlement_links table with historical data
from existing settled surebets and their ledger entries.
"""

import sqlite3
from decimal import Decimal
from typing import List, Dict, Tuple, Optional
import sys
import os

# Add src to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.core.database import get_db_connection
from src.core.schema import create_surebet_settlement_links_table, create_ledger_entries_table
from src.utils.logging_config import configure_logging

def get_logger(name: str = None):
    """Get a logger instance for the migration script."""
    import structlog
    return structlog.get_logger(name)

logger = get_logger(__name__)


def get_settled_surebets(conn: sqlite3.Connection) -> List[Dict]:
    """Get all settled surebets with their associated bets."""
    query = """
        SELECT 
            s.id as surebet_id,
            s.settled_at_utc
        FROM surebets s
        WHERE s.status = 'settled'
        ORDER BY s.id
    """
    cursor = conn.execute(query)
    return [dict(zip([col[0] for col in cursor.description], row)) for row in cursor.fetchall()]


def get_settlement_ledger_entries(conn: sqlite3.Connection, surebet_id: int) -> List[Dict]:
    """Get all ledger entries for a settled surebet."""
    query = """
        SELECT 
            le.id,
            le.associate_id,
            le.amount_eur,
            le.settlement_state,
            le.created_at_utc
        FROM ledger_entries le
        WHERE le.surebet_id = ? 
        AND le.type = 'BET_RESULT'
        ORDER BY le.id
    """
    cursor = conn.execute(query, (surebet_id,))
    return [dict(zip([col[0] for col in cursor.description], row)) for row in cursor.fetchall()]


def determine_winner_loser(entries: List[Dict]) -> Tuple[Optional[Dict], Optional[Dict]]:
    """
    Determine winner and loser from settlement ledger entries.
    
    Returns tuple of (winner_entry, loser_entry). May return (None, None) if unclear.
    """
    if len(entries) != 2:
        logger.warning(f"Expected 2 entries for surebet settlement, got {len(entries)}")
        return None, None
    
    won_entries = [e for e in entries if e['settlement_state'] == 'WON']
    lost_entries = [e for e in entries if e['settlement_state'] == 'LOST']
    
    if len(won_entries) == 1 and len(lost_entries) == 1:
        return won_entries[0], lost_entries[0]
    
    # Handle VOID cases - treat as neutral
    void_entries = [e for e in entries if e['settlement_state'] == 'VOID']
    if len(void_entries) == 2:
        # Both void - no winner/loser, but we still create link for tracking
        return entries[0], entries[1]  # Arbitrary assignment
    
    logger.warning(f"Unexpected settlement state combination: {[e['settlement_state'] for e in entries]}")
    return None, None


def create_settlement_link(
    conn: sqlite3.Connection,
    surebet_id: int,
    winner_entry: Dict,
    loser_entry: Dict
) -> None:
    """Create a settlement link record."""
    try:
        # Use amount from the winner's entry (positive)
        amount_eur = winner_entry['amount_eur']
        
        conn.execute(
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
                winner_entry['associate_id'],
                loser_entry['associate_id'],
                amount_eur,
                winner_entry['id'],
                loser_entry['id'],
                winner_entry['created_at_utc']
            )
        )
        
        logger.info(f"Created settlement link for surebet {surebet_id}: "
                  f"associate {winner_entry['associate_id']} won vs associate {loser_entry['associate_id']} lost")
        
    except sqlite3.IntegrityError as e:
        logger.error(f"Failed to create settlement link for surebet {surebet_id}: {e}")


def update_ledger_entries_with_opponent(
    conn: sqlite3.Connection,
    winner_entry: Dict,
    loser_entry: Dict
) -> None:
    """Update ledger entries with opposing associate IDs."""
    try:
        # Update winner entry with loser as opponent
        conn.execute(
            "UPDATE ledger_entries SET opposing_associate_id = ? WHERE id = ?",
            (loser_entry['associate_id'], winner_entry['id'])
        )
        
        # Update loser entry with winner as opponent
        conn.execute(
            "UPDATE ledger_entries SET opposing_associate_id = ? WHERE id = ?",
            (winner_entry['associate_id'], loser_entry['id'])
        )
        
    except sqlite3.Error as e:
        logger.error(f"Failed to update opposing associate IDs: {e}")


def backfill_surebet(conn: sqlite3.Connection, surebet_id: int) -> bool:
    """
    Backfill a single surebet with settlement links.
    
    Returns True if successful, False otherwise.
    """
    entries = get_settlement_ledger_entries(conn, surebet_id)
    
    if len(entries) < 2:
        logger.warning(f"Surebet {surebet_id} has insufficient settlement entries: {len(entries)}")
        return False
    
    winner_entry, loser_entry = determine_winner_loser(entries)
    
    if winner_entry is None or loser_entry is None:
        logger.warning(f"Could not determine winner/loser for surebet {surebet_id}")
        return False
    
    # Create settlement link
    create_settlement_link(conn, surebet_id, winner_entry, loser_entry)
    
    # Update ledger entries with opponent info
    update_ledger_entries_with_opponent(conn, winner_entry, loser_entry)
    
    return True


def migrate_all_settlements(conn: sqlite3.Connection) -> Tuple[int, int]:
    """
    Migrate all settled surebets to settlement links.
    
    Returns tuple of (total_surebets, successful_migrations).
    """
    surebets = get_settled_surebets(conn)
    total_surebets = len(surebets)
    successful = 0
    
    logger.info(f"Found {total_surebets} settled surebets to migrate")
    
    for surebet in surebets:
        surebet_id = surebet['surebet_id']
        
        # Check if already migrated
        cursor = conn.execute(
            "SELECT COUNT(*) FROM surebet_settlement_links WHERE surebet_id = ?",
            (surebet_id,)
        )
        if cursor.fetchone()[0] > 0:
            logger.debug(f"Surebet {surebet_id} already has settlement links, skipping")
            successful += 1
            continue
        
        if backfill_surebet(conn, surebet_id):
            successful += 1
    
    return total_surebets, successful


def validate_migration(conn: sqlite3.Connection) -> None:
    """Validate the migration results."""
    # Count settlement links
    cursor = conn.execute("SELECT COUNT(*) FROM surebet_settlement_links")
    links_count = cursor.fetchone()[0]
    
    # Count settled surebets
    cursor = conn.execute("SELECT COUNT(*) FROM surebets WHERE status = 'settled'")
    settled_count = cursor.fetchone()[0]
    
    # Count ledger entries with opposing associate set
    cursor = conn.execute("""
        SELECT COUNT(*) FROM ledger_entries 
        WHERE type = 'BET_RESULT' 
        AND opposing_associate_id IS NOT NULL
    """)
    ledger_with_opponent = cursor.fetchone()[0]
    
    logger.info(f"Migration validation:")
    logger.info(f"  - Settlement links created: {links_count}")
    logger.info(f"  - Settled surebets: {settled_count}")
    logger.info(f"  - Ledger entries with opponent: {ledger_with_opponent}")
    
    # Check for any inconsistencies
    if links_count != settled_count:
        logger.warning(f"Warning: Settlement links ({links_count}) != Settled surebets ({settled_count})")


def main():
    """Main migration function."""
    logger.info("Starting delta provenance migration")
    
    conn = get_db_connection()
    
    try:
        # Create settlement links table if not exists
        create_surebet_settlement_links_table(conn)
        
        # Ensure ledger entries table has opposing_associate_id column
        create_ledger_entries_table(conn)
        
        # Start transaction
        conn.execute("BEGIN TRANSACTION")
        
        # Run migration
        total, successful = migrate_all_settlements(conn)
        
        # Validate results
        validate_migration(conn)
        
        # Commit transaction
        conn.execute("COMMIT")
        
        logger.info(f"Migration completed: {successful}/{total} surebets migrated successfully")
        
        if successful == total:
            logger.info("All settled surebets successfully migrated to delta provenance system")
        else:
            logger.warning(f"Migration incomplete: {total - successful} surebets failed")
            
    except Exception as e:
        conn.execute("ROLLBACK")
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        # Don't close connection if it's a mock (for testing)
        if not hasattr(conn, '_mock_name'):
            conn.close()


if __name__ == "__main__":
    main()
