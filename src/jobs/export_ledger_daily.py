"""
Daily ledger export job.

Runs the LedgerExportService to produce a styled Excel workbook so that
automated backups match the manual export UI.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from src.services.ledger_export_service import LedgerExportResult, LedgerExportService
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


def export_ledger(associate_id: Optional[int] = None) -> LedgerExportResult:
    """Run the ledger export and return metadata."""
    service = LedgerExportService()
    result = service.export_full_ledger(associate_id=associate_id)
    logger.info(
        "ledger_export_job_completed",
        file_path=result.file_path,
        row_count=result.row_count,
        size_bytes=result.file_size_bytes,
        scope=result.scope_label,
    )
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate styled ledger Excel exports.")
    parser.add_argument(
        "--associate-id",
        type=int,
        default=None,
        help="Optional associate ID to limit the export scope.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        export_ledger(associate_id=args.associate_id)
    except Exception as exc:  # pragma: no cover - ensures job surfaces failure
        logger.error("ledger_export_job_failed", error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
