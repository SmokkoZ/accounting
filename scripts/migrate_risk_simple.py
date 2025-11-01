"""Simple migration to add risk columns without Unicode output."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.core.config import Config

def main():
    print("Adding risk columns to surebets table...")

    conn = sqlite3.connect(Config.DB_PATH)

    columns = [
        "worst_case_profit_eur TEXT",
        "total_staked_eur TEXT",
        "roi TEXT",
        "risk_classification TEXT",
    ]

    for column in columns:
        col_name = column.split()[0]
        try:
            conn.execute(f"ALTER TABLE surebets ADD COLUMN {column}")
            print(f"Added: {col_name}")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print(f"Already exists: {col_name}")
            else:
                print(f"Error: {e}")

    conn.commit()
    conn.close()
    print("Migration complete!")

if __name__ == "__main__":
    main()
