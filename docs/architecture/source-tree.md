# Source Tree Documentation

**Version:** v4
**Last Updated:** 2025-10-29
**Parent Document:** [Architecture Overview](../architecture.md)

---

## Overview

This document explains the directory structure and purpose of each file/folder in the Surebet Accounting System.

---

## Root Directory

```
surebet-accounting/
├── .env                        # Environment config (API keys, paths)
├── .env.example                # Template for .env (committed to git)
├── .gitignore                  # Git ignore rules
├── .pre-commit-config.yaml     # Pre-commit hooks config
├── mypy.ini                    # Type checking config
├── pytest.ini                  # Pytest config
├── requirements.txt            # Python dependencies
├── README.md                   # Project overview, quick start
├── data/                       # Data directory (git-ignored)
├── docs/                       # Documentation
├── src/                        # Source code
└── tests/                      # Test suite
```

---

## `.env` File

**Purpose:** Store sensitive configuration (API keys, paths)

**Example:**
```bash
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
OPENAI_API_KEY=sk-proj-xxx
FX_API_KEY=xxx
DB_PATH=data/surebet.db
```

**Critical:** Added to `.gitignore` (never committed)

---

## `.env.example` File

**Purpose:** Template for developers to create their own `.env`

**Example:**
```bash
# Copy this to .env and fill in your values
TELEGRAM_BOT_TOKEN=your_bot_token_here
OPENAI_API_KEY=your_openai_key_here
```

**Committed to git** (safe, no secrets)

---

## `.gitignore` File

**Purpose:** Prevent sensitive/generated files from being committed

**Key Entries:**
```
# Environment
.env

# Data (never commit)
data/
*.db
*.db-shm
*.db-wal

# Python
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/

# IDE
.vscode/
.idea/
```

---

## `requirements.txt` File

**Purpose:** Python dependencies

**Example:**
```
# Core
streamlit>=1.30.0
python-telegram-bot>=20.0
openai>=1.0.0
pandas>=2.1.0
pillow>=10.0.0
python-dotenv>=1.0.0
httpx>=0.25.0
structlog>=23.0.0

# Development
pytest>=7.0.0
pytest-asyncio>=0.21.0
pytest-mock>=3.11.0
pytest-cov>=4.1.0
freezegun>=1.2.0
black>=23.0.0
mypy>=1.5.0
ruff>=0.1.0
```

**Install:** `pip install -r requirements.txt`

---

## `README.md` File

**Purpose:** Project overview, quick start guide

**Sections:**
1. What is this project?
2. Prerequisites
3. Installation steps
4. Running the application
5. Project structure
6. Contributing guidelines
7. License

---

## `data/` Directory (Git-Ignored)

```
data/
├── surebet.db                  # SQLite database
├── surebet.db-shm              # Shared memory (WAL mode)
├── surebet.db-wal              # Write-ahead log
├── screenshots/                # Bet screenshots
│   ├── 20251029_120530_2_5_1234.png
│   ├── 20251029_121045_3_7_1235.png
│   └── ...
├── exports/                    # CSV exports
│   ├── ledger_20251029.csv
│   ├── ledger_backup_20251028.csv
│   └── ...
└── logs/                       # Application logs
    ├── application.log
    ├── telegram_bot.log
    └── settlement.log
```

**Purpose:** Local data storage (database, screenshots, logs, exports)

**Git Status:** Entire directory ignored (not committed)

---

## `docs/` Directory

```
docs/
├── prd.md                      # Product Requirements Document
├── architecture.md             # Main architecture document
└── architecture/               # Sharded architecture docs
    ├── tech-stack.md
    ├── frontend-architecture.md
    ├── backend-architecture.md
    ├── data-architecture.md
    ├── integration-architecture.md
    ├── deployment-architecture.md
    ├── security-architecture.md
    ├── testing-strategy.md
    ├── data-flows.md
    ├── coding-standards.md
    └── source-tree.md (this file)
```

**Purpose:** Project documentation (PRD, architecture, guides)

---

## `src/` Directory (Source Code)

### Overview

```
src/
├── core/                       # Core configuration and shared types
├── services/                   # Business logic services
├── integrations/               # External API clients
├── models/                     # Domain entities
├── ui/                         # Streamlit UI
├── utils/                      # Shared utilities
└── jobs/                       # Background jobs (cron scripts)
```

---

### `src/core/` - Core Configuration

```
src/core/
├── __init__.py
├── config.py                   # Environment config loader
├── database.py                 # SQLite connection manager
├── exceptions.py               # Custom exception classes
└── types.py                    # Shared type definitions
```

#### `config.py`

**Purpose:** Load environment variables, validate configuration

```python
from dotenv import load_dotenv
import os

load_dotenv()

class Config:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    DB_PATH = os.getenv("DB_PATH", "data/surebet.db")

    @classmethod
    def validate(cls):
        """Raise ValueError if required config missing"""
        ...
```

#### `database.py`

**Purpose:** Database initialization, connection management

```python
import sqlite3

def get_db_connection(db_path: str = "data/surebet.db"):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn

def create_schema(conn):
    """Create all tables and indexes"""
    ...
```

#### `exceptions.py`

**Purpose:** Custom exception classes

```python
class BetIngestionError(Exception):
    pass

class SettlementError(Exception):
    pass
```

---

### `src/services/` - Business Logic

```
src/services/
├── __init__.py
├── bet_ingestion.py            # FR-1: OCR pipeline, bet creation
├── bet_verification.py         # FR-2: Approval workflow
├── surebet_matcher.py          # FR-3: Deterministic matching
├── surebet_calculator.py       # FR-4: ROI calculation
├── coverage_service.py         # FR-5: Coverage proof delivery
├── settlement_engine.py        # FR-6: Settlement math
├── ledger_service.py           # Ledger queries, export
├── fx_manager.py               # FX rate caching
└── reconciliation.py           # FR-8: Health check calculations
```

**Purpose:** Core domain logic (one file per functional area)

**Example Class:**
```python
# src/services/settlement_engine.py
class SettlementEngine:
    def __init__(self, db):
        self.db = db

    def settle_surebet(self, surebet_id, outcome, overrides, note):
        """Settle surebet and create ledger entries"""
        ...
```

---

### `src/integrations/` - External API Clients

```
src/integrations/
├── __init__.py
├── telegram_bot.py             # Telegram Bot API (polling, handlers)
├── openai_client.py            # GPT-4o OCR + normalization
└── fx_api_client.py            # FX rate API client
```

**Purpose:** Wrappers for external services (Telegram, OpenAI, FX API)

**Example:**
```python
# src/integrations/openai_client.py
class OpenAIClient:
    def extract_bet_from_screenshot(self, screenshot_path: str) -> Dict:
        """Call GPT-4o to extract bet details"""
        ...
```

---

### `src/models/` - Domain Entities

```
src/models/
├── __init__.py
├── bet.py                      # Bet domain model
├── surebet.py                  # Surebet domain model
├── ledger_entry.py             # Ledger entry model
└── enums.py                    # Enums (BetStatus, SettlementState, etc.)
```

**Purpose:** Data classes representing core entities

**Example:**
```python
# src/models/bet.py
from dataclasses import dataclass
from decimal import Decimal

@dataclass
class Bet:
    id: int
    associate_id: int
    bookmaker_id: int
    status: str
    stake: Decimal
    odds: Decimal
    # ...
```

---

### `src/ui/` - Streamlit UI

```
src/ui/
├── __init__.py
├── app.py                      # Main entry point
├── pages/
│   ├── 1_incoming_bets.py      # FR-1, FR-2: Ingestion & review
│   ├── 2_surebets.py           # FR-3, FR-4, FR-5: Matching & coverage
│   ├── 3_settlement.py         # FR-6: Settlement
│   ├── 4_reconciliation.py     # FR-8: Health check
│   ├── 5_export.py             # FR-9: Ledger export
│   └── 6_statements.py         # FR-10: Monthly statements
├── components/
│   ├── __init__.py
│   ├── bet_card.py             # Reusable bet display
│   ├── surebet_table.py        # Surebet summary table
│   ├── settlement_preview.py   # Settlement calculation preview
│   └── reconciliation_card.py  # Associate health card
└── utils/
    ├── __init__.py
    ├── formatters.py           # EUR formatting, date display
    ├── validators.py           # Input validation
    └── state_management.py     # Session state helpers
```

**Purpose:** Streamlit web UI (pages, components, utilities)

**Running:** `streamlit run src/ui/app.py`

---

### `src/utils/` - Shared Utilities

```
src/utils/
├── __init__.py
├── decimal_helpers.py          # Decimal arithmetic utilities
├── datetime_helpers.py         # UTC ISO8601 formatting
└── logging_config.py           # Structured logging setup
```

**Purpose:** Cross-cutting utilities (logging, date formatting, decimal helpers)

**Example:**
```python
# src/utils/datetime_helpers.py
from datetime import datetime

def utc_now_iso() -> str:
    """Return current UTC time as ISO8601 with Z suffix"""
    return datetime.utcnow().isoformat() + "Z"
```

---

### `src/jobs/` - Background Jobs

```
src/jobs/
├── __init__.py
├── fetch_fx_rates.py           # Daily FX rate update
└── export_ledger_daily.py      # Automated CSV export
```

**Purpose:** Cron-scheduled background tasks

**Example:**
```python
# src/jobs/fetch_fx_rates.py
def update_fx_rates_daily():
    """Cron job: Run daily at midnight UTC"""
    ...

if __name__ == "__main__":
    update_fx_rates_daily()
```

**Running:** `python -m src.jobs.fetch_fx_rates`

---

## `tests/` Directory

```
tests/
├── __init__.py
├── conftest.py                 # Shared fixtures (test DB, mocks)
├── unit/                       # Unit tests (70% coverage target)
│   ├── __init__.py
│   ├── test_settlement_engine.py
│   ├── test_surebet_calculator.py
│   ├── test_surebet_matcher.py
│   ├── test_fx_manager.py
│   └── test_reconciliation.py
├── integration/                # Integration tests (25% target)
│   ├── __init__.py
│   ├── test_bet_ingestion_flow.py
│   ├── test_settlement_flow.py
│   └── test_fx_caching.py
├── e2e/                        # End-to-end tests (5% target)
│   ├── __init__.py
│   └── test_full_surebet_lifecycle.py
└── fixtures/                   # Test data (screenshots, SQL seeds)
    ├── sample_screenshots/
    │   ├── bet_over_2_5.png
    │   └── bet_under_2_5.png
    ├── sample_associates.sql
    └── sample_bets.sql
```

**Purpose:** Test suite (unit, integration, E2E)

**Running:** `pytest tests/`

---

## File Naming Conventions

### Python Files

- **Modules:** snake_case (e.g., `bet_ingestion.py`)
- **Test files:** `test_` prefix (e.g., `test_settlement_engine.py`)

### Data Files

- **Screenshots:** `{timestamp}_{associate_id}_{bookmaker_id}_{bet_id}.png`
  - Example: `20251029_120530_2_5_1234.png`

- **CSV Exports:** `ledger_{date}.csv`
  - Example: `ledger_20251029.csv`

- **Logs:** `{component}.log`
  - Example: `telegram_bot.log`, `application.log`

---

## Import Conventions

### Absolute Imports (Preferred)

```python
# GOOD
from src.services.settlement_engine import SettlementEngine
from src.core.database import get_db_connection

# BAD (relative)
from ..services.settlement_engine import SettlementEngine
```

### Grouping Order

```python
# 1. Standard library
import os
import sqlite3
from datetime import datetime

# 2. Third-party libraries
import streamlit as st
from telegram import Update

# 3. Local imports
from src.services.bet_ingestion import BetIngestionService
from src.core.config import Config
```

---

## Configuration Files

### `mypy.ini` - Type Checking

```ini
[mypy]
python_version = 3.12
disallow_untyped_defs = True
warn_return_any = True
warn_unused_ignores = True
```

### `pytest.ini` - Test Configuration

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = --strict-markers --tb=short
```

### `.pre-commit-config.yaml` - Git Hooks

```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.0.0
    hooks:
      - id: black
        args: [--line-length=100]
```

---

## Summary: Key Directories

| Directory | Purpose | Git Status |
|-----------|---------|------------|
| `src/` | Source code | Committed |
| `tests/` | Test suite | Committed |
| `docs/` | Documentation | Committed |
| `data/` | Local data (DB, screenshots, logs) | **Ignored** |
| `.env` | Environment config | **Ignored** |
| `venv/` | Python virtual environment | **Ignored** |

---

**End of Document**
