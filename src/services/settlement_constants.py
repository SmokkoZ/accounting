"""
Shared constants for Settle Associate workflows.

Keeping these values in one place prevents missing or divergent definitions
across the reconciliation, statement, and bookmaker services.
"""

from decimal import Decimal

SETTLEMENT_NOTE_PREFIX = "Settle Associate Now"
SETTLEMENT_TOLERANCE = Decimal("0.01")
SETTLEMENT_MODEL_VERSION = "YF-v1"
SETTLEMENT_MODEL_FOOTNOTE = (
    "Model: YF-v1 -- YF = ND + FS; I'' = TB - YF. Legacy 'Should Hold' values map to YF; "
    "exports append-only for backward compatibility."
)
