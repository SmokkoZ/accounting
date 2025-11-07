# Debug Log

## 2025-11-06 Story 8.3 Dialog Patterns
- implemented dialog helper module (`src/ui/helpers/dialogs.py`)
- refactored settlement, incoming bets, admin, and reconciliation flows to use helpers
- tests: `python -m pytest tests/unit/test_dialog_helpers.py`

## 2025-11-07 Story 8.6 Streaming & Progress Indicators
- added streaming/status/toast/pdf helper utilities (`src/ui/helpers/streaming.py`)
- rewired incoming bets, export, settlement, reconciliation, and statements pages to use streaming helpers + PDF previews
- tests: `pytest tests/unit/test_streaming_helpers.py`
