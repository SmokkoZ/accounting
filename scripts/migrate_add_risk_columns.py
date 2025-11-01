"""
Migration script to add risk calculation columns to surebets table.

This script adds the following columns to the surebets table:
- worst_case_profit_eur
- total_staked_eur
- roi
- risk_classification

Run this script after upgrading to version 3.2.
"""

import sqlite3
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.database import get_db_connection
from src.services.surebet_calculator import SurebetRiskCalculator


def check_columns_exist(conn: sqlite3.Connection) -> bool:
    """Check if risk calculation columns already exist.

    Args:
        conn: SQLite database connection

    Returns:
        True if columns already exist, False otherwise
    """
    cursor = conn.execute("PRAGMA table_info(surebets)")
    columns = {row[1] for row in cursor.fetchall()}

    required_columns = {
        "worst_case_profit_eur",
        "total_staked_eur",
        "roi",
        "risk_classification",
    }

    return required_columns.issubset(columns)


def add_risk_columns(conn: sqlite3.Connection) -> None:
    """Add risk calculation columns to surebets table.

    Args:
        conn: SQLite database connection
    """
    print("Adding risk calculation columns to surebets table...")

    # Add columns one by one (SQLite doesn't support ADD COLUMN for multiple columns)
    columns_to_add = [
        "worst_case_profit_eur TEXT",
        "total_staked_eur TEXT",
        "roi TEXT",
        "risk_classification TEXT",
    ]

    for column in columns_to_add:
        try:
            conn.execute(f"ALTER TABLE surebets ADD COLUMN {column}")
            print(f"  ✓ Added column: {column.split()[0]}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print(f"  ⚠ Column {column.split()[0]} already exists, skipping")
            else:
                raise

    conn.commit()
    print("✓ Columns added successfully")


def recalculate_existing_surebets(conn: sqlite3.Connection) -> None:
    """Recalculate risk for all existing surebets.

    Args:
        conn: SQLite database connection
    """
    print("\nRecalculating risk for existing surebets...")

    # Get all surebet IDs
    cursor = conn.execute("SELECT id FROM surebets WHERE status IN ('open', 'matched')")
    surebet_ids = [row[0] for row in cursor.fetchall()]

    if not surebet_ids:
        print("  No surebets to recalculate")
        return

    calculator = SurebetRiskCalculator(conn)
    success_count = 0
    error_count = 0

    for surebet_id in surebet_ids:
        try:
            # Calculate risk
            risk_data = calculator.calculate_surebet_risk(surebet_id)

            # Update surebet with calculated values
            conn.execute(
                """
                UPDATE surebets
                SET worst_case_profit_eur = ?,
                    total_staked_eur = ?,
                    roi = ?,
                    risk_classification = ?
                WHERE id = ?
                """,
                (
                    str(risk_data["worst_case_profit_eur"]),
                    str(risk_data["total_staked_eur"]),
                    str(risk_data["roi"]),
                    risk_data["risk_classification"],
                    surebet_id,
                ),
            )
            conn.commit()
            success_count += 1
            print(
                f"  ✓ Recalculated surebet {surebet_id}: "
                f"{risk_data['risk_classification']} "
                f"(ROI: {risk_data['roi']:.2f}%)"
            )

        except Exception as e:
            error_count += 1
            print(f"  ✗ Error recalculating surebet {surebet_id}: {e}")

    print(f"\n✓ Recalculation complete: {success_count} success, {error_count} errors")


def main():
    """Run migration to add risk calculation columns."""
    print("=" * 60)
    print("Migration: Add Risk Calculation Columns to Surebets Table")
    print("=" * 60)

    # Connect to database
    try:
        conn = get_db_connection()
        print(f"✓ Connected to database")
    except Exception as e:
        print(f"✗ Failed to connect to database: {e}")
        sys.exit(1)

    try:
        # Check if columns already exist
        if check_columns_exist(conn):
            print("\n⚠ Risk calculation columns already exist in surebets table")
            print("Skipping column addition, proceeding to recalculation only...")
        else:
            # Add columns
            add_risk_columns(conn)

        # Recalculate existing surebets
        recalculate_existing_surebets(conn)

        print("\n" + "=" * 60)
        print("✓ Migration completed successfully")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        conn.rollback()
        sys.exit(1)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
