"""
Ledger Export Service

Handles exporting full ledger to CSV format for audit and backup purposes.
Follows strict CSV formatting standards and includes comprehensive validation.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog
from src.core.database import get_db_connection

logger = structlog.get_logger()


class LedgerExportService:
    """Service for exporting ledger entries to CSV format."""

    def __init__(self, export_dir: str = "data/exports"):
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def export_full_ledger(self) -> Tuple[str, int]:
        """
        Export complete ledger to CSV.
        
        Returns:
            Tuple of (file_path, row_count)
            
        Raises:
            Exception: If export fails for any reason
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"ledger_{timestamp}.csv"
        file_path = self.export_dir / filename

        logger.info("starting_ledger_export", filename=filename, file_path=str(file_path))

        try:
            conn = get_db_connection()
            row_count = self._export_ledger_to_csv(conn, file_path)
            conn.close()

            # Validate export
            self._validate_export(file_path, row_count)

            logger.info("ledger_export_completed", file_path=str(file_path), row_count=row_count)
            return str(file_path), row_count

        except Exception as e:
            logger.error("ledger_export_failed", error=str(e), file_path=str(file_path))
            raise

    def _export_ledger_to_csv(self, conn, file_path: Path) -> int:
        """Execute ledger query and write to CSV file."""
        query = """
            SELECT
                le.id AS entry_id,
                le.type AS entry_type,
                a.display_alias AS associate_alias,
                bk.bookmaker_name,
                le.amount_native,
                le.native_currency,
                le.fx_rate_snapshot,
                le.amount_eur,
                le.settlement_state,
                le.principal_returned_eur,
                le.per_surebet_share_eur,
                le.surebet_id,
                le.bet_id,
                le.settlement_batch_id,
                le.created_at_utc,
                le.created_by,
                le.note
            FROM ledger_entries le
            JOIN associates a ON le.associate_id = a.id
            LEFT JOIN bookmakers bk ON le.bookmaker_id = bk.id
            ORDER BY le.created_at_utc ASC
        """

        cursor = conn.cursor()
        cursor.execute(query)

        # Define CSV columns
        fieldnames = [
            "entry_id", "entry_type", "associate_alias", "bookmaker_name",
            "surebet_id", "bet_id", "settlement_batch_id", "settlement_state",
            "amount_native", "native_currency", "fx_rate_snapshot", "amount_eur",
            "principal_returned_eur", "per_surebet_share_eur",
            "created_at_utc", "created_by", "note"
        ]

        row_count = 0
        with open(file_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(
                csvfile, 
                fieldnames=fieldnames,
                delimiter=",",
                quoting=csv.QUOTE_MINIMAL
            )
            
            # Write header
            writer.writeheader()

            # Write data rows
            for row in cursor.fetchall():
                # Convert row to dict and format values
                formatted_row = self._format_row_for_csv(dict(row))
                writer.writerow(formatted_row)
                row_count += 1

        return row_count

    def _format_row_for_csv(self, row: Dict) -> Dict:
        """Format a database row for CSV output."""
        formatted = {}
        
        for key, value in row.items():
            if value is None:
                formatted[key] = ""
            elif key in [
                "amount_native", "fx_rate_snapshot", "amount_eur",
                "principal_returned_eur", "per_surebet_share_eur"
            ]:
                # Decimal fields - convert to string to preserve precision
                formatted[key] = str(value) if value else ""
            elif key in ["entry_id", "surebet_id", "bet_id"]:
                # Integer fields
                formatted[key] = str(value) if value else ""
            else:
                # Text fields
                formatted[key] = str(value) if value else ""
                
        return formatted

    def _validate_export(self, file_path: Path, expected_row_count: int) -> None:
        """Validate that export was successful."""
        if not file_path.exists():
            raise FileNotFoundError(f"Export file not created: {file_path}")

        # Count rows in CSV (excluding header)
        with open(file_path, "r", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            actual_row_count = sum(1 for _ in reader)

        if actual_row_count != expected_row_count:
            raise ValueError(
                f"Row count mismatch: expected {expected_row_count}, "
                f"found {actual_row_count} in CSV"
            )

        logger.info("export_validation_passed", file_path=str(file_path), row_count=actual_row_count)

    def get_export_history(self, limit: int = 10) -> List[Dict]:
        """
        Get list of recent export files with metadata.
        
        Args:
            limit: Maximum number of files to return
            
        Returns:
            List of dictionaries with file metadata
        """
        exports = []
        
        if not self.export_dir.exists():
            return exports

        # Get all ledger CSV files with proper timestamp format, sorted by modification time (newest first)
        csv_files = sorted(
            self.export_dir.glob("ledger_*.csv"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )

        for file_path in csv_files[:limit]:
            try:
                stat = file_path.stat()
                
                # Count rows in file
                with open(file_path, "r", encoding="utf-8") as csvfile:
                    reader = csv.DictReader(csvfile)
                    row_count = sum(1 for _ in reader)
                
                exports.append({
                    "filename": file_path.name,
                    "file_path": str(file_path),
                    "file_size": stat.st_size,
                    "row_count": row_count,
                    "created_time": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                })
            except Exception as e:
                logger.warning("failed_to_read_export_metadata", file=str(file_path), error=str(e))
                continue

        return exports

    def get_file_size_display(self, size_bytes: int) -> str:
        """Convert file size to human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"
