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
â”œâ”€â”€ .env                        # Environment config (API keys, paths)
â”œâ”€â”€ .env.example                # Template for .env (committed to git)
â”œâ”€â”€ .gitignore                  # Git ignore rules
â”œâ”€â”€ .pre-commit-config.yaml     # Pre-commit hooks config
â”œâ”€â”€ mypy.ini                    # Type checking config
â”œâ”€â”€ pytest.ini                  # Pytest config
â”œâ”€â”€ requirements.txt            # Python dependencies
â”œâ”€â”€ README.md                   # Project overview, quick start
â”œâ”€â”€ data/                       # Data directory (git-ignored)
â”œâ”€â”€ docs/                       # Documentation
â”œâ”€â”€ src/                        # Source code
â””â”€â”€ tests/                      # Test suite
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
â”œâ”€â”€ surebet.db                  # SQLite database
â”œâ”€â”€ surebet.db-shm              # Shared memory (WAL mode)
â”œâ”€â”€ surebet.db-wal              # Write-ahead log
â”œâ”€â”€ screenshots/                # Bet screenshots
â”‚   â”œâ”€â”€ 20251029_120530_2_5_1234.png
â”‚   â”œâ”€â”€ 20251029_121045_3_7_1235.png
â”‚   â””â”€â”€ ...
â”œâ”€â”€ exports/                    # CSV exports
â”‚   â”œâ”€â”€ ledger_20251029.csv
â”‚   â”œâ”€â”€ ledger_backup_20251028.csv
â”‚   â””â”€â”€ ...
â””â”€â”€ logs/                       # Application logs
    â”œâ”€â”€ application.log
    â”œâ”€â”€ telegram_bot.log
    â””â”€â”€ settlement.log
```

**Purpose:** Local data storage (database, screenshots, logs, exports)

**Git Status:** Entire directory ignored (not committed)

---

## `docs/` Directory

```
docs/
â”œâ”€â”€ prd.md                      # Product Requirements Document
â”œâ”€â”€ architecture.md             # Main architecture document
â””â”€â”€ architecture/               # Sharded architecture docs
    â”œâ”€â”€ tech-stack.md
    â”œâ”€â”€ frontend-architecture.md
    â”œâ”€â”€ backend-architecture.md
    â”œâ”€â”€ data-architecture.md
    â”œâ”€â”€ integration-architecture.md
    â”œâ”€â”€ deployment-architecture.md
    â”œâ”€â”€ security-architecture.md
    â”œâ”€â”€ testing-strategy.md
    â”œâ”€â”€ data-flows.md
    â”œâ”€â”€ coding-standards.md
    â””â”€â”€ source-tree.md (this file)
```

**Purpose:** Project documentation (PRD, architecture, guides)

---

## `src/` Directory (Source Code)

### Overview

```
src/
â”œâ”€â”€ core/                       # Core configuration and shared types
â”œâ”€â”€ services/                   # Business logic services
â”œâ”€â”€ integrations/               # External API clients
â”œâ”€â”€ models/                     # Domain entities
â”œâ”€â”€ ui/                         # Streamlit UI
â”œâ”€â”€ utils/                      # Shared utilities
â””â”€â”€ jobs/                       # Background jobs (cron scripts)
```

---

### `src/core/` - Core Configuration

```
src/core/
â”œâ”€â”€ __init__.py
â”œâ”€â”€ config.py                   # Environment config loader
â”œâ”€â”€ database.py                 # SQLite connection manager
â”œâ”€â”€ exceptions.py               # Custom exception classes
â””â”€â”€ types.py                    # Shared type definitions
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
â”œâ”€â”€ __init__.py
â”œâ”€â”€ bet_ingestion.py            # FR-1: OCR pipeline, bet creation
â”œâ”€â”€ bet_verification.py         # FR-2: Approval workflow
â”œâ”€â”€ surebet_matcher.py          # FR-3: Deterministic matching
â”œâ”€â”€ surebet_calculator.py       # FR-4: ROI calculation
â”œâ”€â”€ coverage_service.py         # FR-5: Coverage proof delivery
â”œâ”€â”€ settlement_engine.py        # FR-6: Settlement math
â”œâ”€â”€ ledger_service.py           # Ledger queries, export
â”œâ”€â”€ fx_manager.py               # FX rate caching
â””â”€â”€ reconciliation.py           # FR-8: Health check calculations
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
â”œâ”€â”€ __init__.py
â”œâ”€â”€ telegram_bot.py             # Telegram Bot API (polling, handlers)
â”œâ”€â”€ openai_client.py            # GPT-4o OCR + normalization
â””â”€â”€ fx_api_client.py            # FX rate API client
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
â”œâ”€â”€ __init__.py
â”œâ”€â”€ bet.py                      # Bet domain model
â”œâ”€â”€ surebet.py                  # Surebet domain model
â”œâ”€â”€ ledger_entry.py             # Ledger entry model
â””â”€â”€ enums.py                    # Enums (BetStatus, SettlementState, etc.)
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
â”œâ”€â”€ __init__.py
â”œâ”€â”€ app.py                      # Main entry point
â”œâ”€â”€ pages/
â”‚   â”œâ”€â”€ 1_incoming_bets.py      # FR-1, FR-2: Ingestion & review
â”‚   â”œâ”€â”€ 2_surebets.py           # FR-3, FR-4, FR-5: Matching & coverage
â”‚   â”œâ”€â”€ 3_settlement.py         # FR-6: Settlement
â”‚   â”œâ”€â”€ 4_reconciliation.py     # FR-8: Health check
â”‚   â”œâ”€â”€ 5_export.py             # FR-9: Ledger export
â”‚   â””â”€â”€ 6_statements.py         # FR-10: Monthly statements
â”œâ”€â”€ components/
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ bet_card.py             # Reusable bet display
â”‚   â”œâ”€â”€ surebet_table.py        # Surebet summary table
â”‚   â”œâ”€â”€ settlement_preview.py   # Settlement calculation preview
â”‚   â””â”€â”€ reconciliation_card.py  # Associate health card
â””â”€â”€ utils/
    â”œâ”€â”€ __init__.py
    â”œâ”€â”€ formatters.py           # Currency formatting (ISO codes), date display
    â”œâ”€â”€ validators.py           # Input validation
    â””â”€â”€ state_management.py     # Session state helpers
```

**Purpose:** Streamlit web UI (pages, components, utilities)

**Running:** `streamlit run src/ui/app.py`

---

### `src/utils/` - Shared Utilities

```
src/utils/
â”œâ”€â”€ __init__.py
â”œâ”€â”€ decimal_helpers.py          # Decimal arithmetic utilities
â”œâ”€â”€ datetime_helpers.py         # UTC ISO8601 formatting
â””â”€â”€ logging_config.py           # Structured logging setup
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
â”œâ”€â”€ __init__.py
â”œâ”€â”€ fetch_fx_rates.py           # Daily FX rate update
â””â”€â”€ export_ledger_daily.py      # Automated CSV export
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
â”œâ”€â”€ __init__.py
â”œâ”€â”€ conftest.py                 # Shared fixtures (test DB, mocks)
â”œâ”€â”€ unit/                       # Unit tests (70% coverage target)
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ test_settlement_engine.py
â”‚   â”œâ”€â”€ test_surebet_calculator.py
â”‚   â”œâ”€â”€ test_surebet_matcher.py
â”‚   â”œâ”€â”€ test_fx_manager.py
â”‚   â””â”€â”€ test_reconciliation.py
â”œâ”€â”€ integration/                # Integration tests (25% target)
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ test_bet_ingestion_flow.py
â”‚   â”œâ”€â”€ test_settlement_flow.py
â”‚   â””â”€â”€ test_fx_caching.py
â”œâ”€â”€ e2e/                        # End-to-end tests (5% target)
â”‚   â”œâ”€â”€ __init__.py
â”‚   â””â”€â”€ test_full_surebet_lifecycle.py
â””â”€â”€ fixtures/                   # Test data (screenshots, SQL seeds)
    â”œâ”€â”€ sample_screenshots/
    â”‚   â”œâ”€â”€ bet_over_2_5.png
    â”‚   â””â”€â”€ bet_under_2_5.png
    â”œâ”€â”€ sample_associates.sql
    â””â”€â”€ sample_bets.sql
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
