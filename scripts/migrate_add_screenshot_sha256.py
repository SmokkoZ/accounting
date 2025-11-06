#!/usr/bin/env python3
"""
Database migration to add screenshot_sha256 column to bets table.

This migration adds a column to store SHA256 hashes of uploaded screenshots
for duplicate detection purposes.
"""

import sqlite3
import sys
from pathlib import Path
import os

# Add src to path for imports
current_dir = Path(__file__).parent
src_dir = current_dir.parent / "src"
sys.path.insert(0, str(src_dir))

try:
    from core.config import Config
    from utils.logging_config import setup_logging
    logger = setup_logging()
except ImportError as e:
    print(f"Import error: {e}")
    print("Using basic logging instead")
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


def migrate_add_screenshot_sha256():
    """
    Add screenshot_sha256 column to bets table.
    
    Returns:
        bool: True if migration succeeded, False otherwise
    """
    db_path = Config.DB_PATH
    
    try:
        # Connect to database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if column already exists
        cursor.execute("PRAGMA table_info(bets)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'screenshot_sha256' in columns:
            logger.info("screenshot_sha256 column already exists in bets table")
            conn.close()
            return True
        
        # Add the column
        logger.info("Adding screenshot_sha256 column to bets table...")
        cursor.execute("""
            ALTER TABLE bets 
            ADD COLUMN screenshot_sha256 TEXT
        """)
        
        # Create index for faster duplicate detection
        logger.info("Creating index on screenshot_sha256...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_bets_screenshot_sha256 
            ON bets(screenshot_sha256)
        """)
        
        conn.commit()
        conn.close()
        
        logger.info("Migration completed successfully")
        return True
        
    except sqlite3.Error as e:
        logger.error(f"Database error during migration: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during migration: {e}")
        return False


if __name__ == "__main__":
    print("Starting migration: Add screenshot_sha256 column...")
    
    success = migrate_add_screenshot_sha256()
    
    if success:
        print("✅ Migration completed successfully!")
        sys.exit(0)
    else:
        print("❌ Migration failed!")
        sys.exit(1)
