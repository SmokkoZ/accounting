# Coding Standards

**Version:** v4
**Last Updated:** 2025-10-29
**Parent Document:** [Architecture Overview](../architecture.md)

---

## Overview

This document defines coding standards, style guidelines, and best practices for the Surebet Accounting System codebase.

---

## Python Style Guide

### Base Standard

Follow **PEP 8** with modifications:
- Line length: **100 characters** (not 79)
- Use **Black** for auto-formatting (no manual enforcement)

### Code Formatting Tool

**Black** (opinionated formatter)

```bash
# Install
pip install black

# Format all files
black src/ tests/

# Check without modifying
black --check src/
```

**.pre-commit-config.yaml:**
```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.0.0
    hooks:
      - id: black
        args: [--line-length=100]
```

---

## Naming Conventions

### General Rules

| Element | Convention | Example |
|---------|------------|---------|
| **Functions** | snake_case | `calculate_settlement()` |
| **Variables** | snake_case | `surebet_id`, `amount_eur` |
| **Classes** | PascalCase | `BetIngestionService`, `SettlementEngine` |
| **Constants** | UPPER_SNAKE_CASE | `ADMIN_ASSOCIATE_ID`, `MAX_RETRIES` |
| **Private methods** | _leading_underscore | `_get_opposite_side()` |
| **Modules** | snake_case | `bet_ingestion.py`, `fx_manager.py` |

### Database Field Names

**Match Python conventions:**
- Use `snake_case`: `associate_id`, `amount_eur`, `created_at_utc`
- Avoid camelCase in SQL (e.g., `associateId` ❌)

### Specific Naming Patterns

**Boolean variables:**
```python
# GOOD
is_multi = True
has_matched = False
is_admin = bet.associate_id == ADMIN_ASSOCIATE_ID

# BAD
multi = True  # Unclear type
matched_flag = False  # Redundant "flag" suffix
```

**Collections:**
```python
# GOOD (plural)
bets = load_bets()
ledger_entries = query_ledger()

# BAD (singular for collection)
bet = load_bets()  # Confusing
```

---

## Type Hints

### Requirement

**All public functions MUST have type hints**

```python
# GOOD
def calculate_roi(surebet_id: int) -> Dict[str, Decimal]:
    ...

# BAD (missing type hints)
def calculate_roi(surebet_id):
    ...
```

### Type Hint Examples

```python
from typing import List, Dict, Optional, Literal
from decimal import Decimal

# Simple types
def get_bet(bet_id: int) -> Optional[Dict]:
    ...

# Literal for enums
def settle_surebet(
    surebet_id: int,
    outcome: Literal["A_WON", "B_WON"],
    overrides: Dict[int, str]
) -> str:
    ...

# Decimal for currency
def convert_to_eur(amount: Decimal, fx_rate: Decimal) -> Decimal:
    ...
```

### Type Checking

**Use mypy for static type checking**

```bash
# Install
pip install mypy

# Run type check
mypy src/

# Configuration: mypy.ini
[mypy]
python_version = 3.12
disallow_untyped_defs = True
warn_return_any = True
warn_unused_ignores = True
```

---

## Decimal Usage (CRITICAL)

### Rule: Never Use Float for Currency

```python
from decimal import Decimal

# CORRECT
stake = Decimal("100.50")
odds = Decimal("1.91")
payout = stake * odds  # Decimal("191.955")

# WRONG - NEVER USE FLOAT
stake = 100.50  # ❌ Float introduces rounding errors
odds = 1.91     # ❌
```

### String Conversion

**Always construct Decimal from string, not float:**

```python
# GOOD
amount = Decimal("100.50")

# BAD (float intermediary)
amount = Decimal(100.50)  # May have precision loss
```

### Database Storage

**Store as TEXT in SQLite:**

```python
# GOOD
cursor.execute("INSERT INTO bets (stake) VALUES (?)", (str(stake),))

# On read, convert back
stake = Decimal(row["stake"])
```

---

## UTC Timestamps

### Format

**ISO8601 with "Z" suffix:**

```python
from datetime import datetime

# GOOD
created_at_utc = datetime.utcnow().isoformat() + "Z"
# "2025-10-29T14:30:00.123456Z"

# BAD (no Z suffix)
created_at_utc = datetime.utcnow().isoformat()
```

### Timezone Rule

**All timestamps in UTC, no local time:**

```python
# GOOD
kickoff_time_utc = "2025-10-30T19:00:00Z"

# BAD (local time)
kickoff_time = "2025-10-30 19:00:00"  # Which timezone?
```

---

## Error Handling

### Use Specific Exceptions

```python
# GOOD
try:
    bet_id = BetIngestionService().ingest_screenshot(...)
except FileNotFoundError as e:
    logger.error(f"Screenshot not found: {e}")
    raise BetIngestionError(f"Screenshot missing: {e}")

# BAD (bare except)
try:
    bet_id = ...
except:  # ❌ Never catch all exceptions
    pass
```

### Custom Exceptions

```python
# src/core/exceptions.py
class BetIngestionError(Exception):
    """Raised when bet ingestion fails"""
    pass

class SettlementError(Exception):
    """Raised when settlement validation fails"""
    pass
```

### Logging Errors

```python
import structlog

logger = structlog.get_logger()

try:
    ...
except BetIngestionError as e:
    logger.error("ingestion_failed", error=str(e), bet_id=bet_id)
    raise  # Re-raise after logging
```

---

## Logging Standards

### Use Structured Logging

```python
# GOOD (structured)
logger.info("bet_verified", bet_id=1234, associate="Alice")

# BAD (string formatting)
logger.info(f"Bet {bet_id} verified for Alice")  # Harder to parse
```

### Log Levels

| Level | When to Use |
|-------|-------------|
| **DEBUG** | Detailed flow, SQL queries |
| **INFO** | Key events (bet verified, surebet settled) |
| **WARNING** | Recoverable issues (FX API unavailable, using cached rate) |
| **ERROR** | Failures requiring attention (Telegram send failed) |
| **CRITICAL** | System-wide failures (database corruption) |

### Example

```python
logger.debug("querying_incoming_bets", status="incoming")
logger.info("bet_verified", bet_id=1234)
logger.warning("fx_api_unavailable", currency="AUD", using_cached=True)
logger.error("telegram_send_failed", chat_id=123, retries=3)
```

---

## SQL Query Standards

### Parameterized Queries Only

```python
# GOOD
cursor.execute("SELECT * FROM bets WHERE id = ?", (bet_id,))

# BAD (SQL injection risk)
cursor.execute(f"SELECT * FROM bets WHERE id = {bet_id}")  # ❌ NEVER
```

### Multi-line Queries

**Use triple quotes for readability:**

```python
# GOOD
cursor.execute("""
    SELECT b.*, a.display_alias, bk.bookmaker_name
    FROM bets b
    JOIN associates a ON b.associate_id = a.id
    JOIN bookmakers bk ON b.bookmaker_id = bk.id
    WHERE b.status = ?
    ORDER BY b.created_at_utc DESC
""", (status,))

# BAD (single line)
cursor.execute("SELECT b.*, a.display_alias FROM bets b JOIN associates a ON b.associate_id = a.id WHERE b.status = ? ORDER BY b.created_at_utc DESC", (status,))
```

---

## Function Design

### Single Responsibility Principle

**Each function should do ONE thing:**

```python
# GOOD (focused)
def calculate_surebet_profit(bets: List[Dict]) -> Decimal:
    """Calculate total profit/loss for a surebet in EUR"""
    return sum(Decimal(bet["net_gain_eur"]) for bet in bets)

def determine_participant_count(betting_associates: List[int], admin_staked: bool) -> int:
    """Determine N for equal-split calculation"""
    return len(betting_associates) if admin_staked else len(betting_associates) + 1

# BAD (doing too much)
def settle_and_export(surebet_id):
    # Settles surebet AND exports CSV (two responsibilities)
    ...
```

### Function Length

**Keep functions under 50 lines**

- If longer, extract helper functions
- Use early returns to reduce nesting

```python
# GOOD (early return)
def approve_bet(bet_id: int):
    bet = load_bet(bet_id)
    if not bet:
        raise ValueError("Bet not found")

    if bet["status"] != "incoming":
        raise ValueError("Bet already processed")

    # Main logic...

# BAD (deep nesting)
def approve_bet(bet_id: int):
    bet = load_bet(bet_id)
    if bet:
        if bet["status"] == "incoming":
            # Main logic nested 2 levels deep
            ...
```

---

## Documentation

### Docstrings (Required for Public Functions)

**Use Google-style docstrings:**

```python
def settle_surebet(
    surebet_id: int,
    base_outcome: Literal["A_WON", "B_WON"],
    overrides: Dict[int, str],
    operator_note: str
) -> str:
    """
    Settle a surebet and create ledger entries for all participants.

    Args:
        surebet_id: ID of the surebet to settle
        base_outcome: Which side won ("A_WON" or "B_WON")
        overrides: Bet-level overrides {bet_id: "WON"/"LOST"/"VOID"}
        operator_note: Human-readable explanation for audit trail

    Returns:
        settlement_batch_id (UUID) linking all created ledger entries

    Raises:
        SettlementError: If surebet already settled or validation fails

    Example:
        >>> engine = SettlementEngine()
        >>> batch_id = engine.settle_surebet(45, "A_WON", {}, "Man Utd won 2-1")
        >>> print(batch_id)
        "abc-123-def-456"
    """
    ...
```

### Comments

**Explain WHY, not WHAT:**

```python
# GOOD (explains reasoning)
# Admin gets extra seat if they did NOT stake (System Law #3)
n = len(betting_associates) + 1 if not admin_staked else len(betting_associates)

# BAD (obvious from code)
# Calculate N
n = len(betting_associates) + 1
```

---

## Testing Standards

### Test File Naming

**Prefix with `test_`:**

```
tests/
├── unit/
│   ├── test_settlement_engine.py
│   ├── test_surebet_matcher.py
│   └── test_fx_manager.py
├── integration/
│   └── test_bet_ingestion_flow.py
└── e2e/
    └── test_full_surebet_lifecycle.py
```

### Test Function Naming

**Use descriptive names:**

```python
# GOOD
def test_equal_split_with_admin_seat():
    """
    Given: Surebet with 2 associates, admin did NOT stake
    When: Settlement calculated
    Then: N = 3 (2 associates + 1 admin seat)
    """
    ...

# BAD
def test_settlement():  # Too vague
    ...
```

### AAA Pattern

**Arrange, Act, Assert:**

```python
def test_void_participates_in_split():
    # Arrange
    surebet_id = create_test_surebet(...)

    # Act
    engine.settle_surebet(surebet_id, "A_WON", {"bet_2": "VOID"})

    # Assert
    ledger = get_ledger_entries(surebet_id)
    assert ledger[1]["settlement_state"] == "VOID"
    assert ledger[1]["per_surebet_share_eur"] is not None
```

---

## Git Commit Messages

### Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- **feat**: New feature
- **fix**: Bug fix
- **refactor**: Code restructuring (no behavior change)
- **docs**: Documentation only
- **test**: Adding/fixing tests
- **chore**: Tooling, dependencies

### Examples

```
feat(settlement): Add equal-split calculation with admin seat logic

Implement System Law #3: Admin gets exactly one extra seat in the split
if they did NOT stake. This ensures fair profit/loss distribution.

Closes #45
```

```
fix(fx-manager): Use last known rate when API unavailable

When FX API times out, fallback to most recent cached rate for the
currency instead of failing. Log warning for operator review.

Fixes #78
```

---

## Code Review Checklist

Before submitting PR:

- [ ] All public functions have type hints
- [ ] All currency values use `Decimal` (never `float`)
- [ ] All timestamps in UTC with "Z" suffix
- [ ] SQL queries use parameterized placeholders (`?`)
- [ ] Error handling with specific exceptions
- [ ] Logging uses structured format
- [ ] Tests written (unit + integration if applicable)
- [ ] Docstrings for public functions
- [ ] Black formatting applied
- [ ] mypy type check passes
- [ ] pytest passes (all tests green)

---

## Anti-Patterns to Avoid

### 1. Float for Currency

```python
# NEVER
stake = 100.50  # ❌ Use Decimal
```

### 2. String Formatting in SQL

```python
# NEVER
cursor.execute(f"WHERE id = {bet_id}")  # ❌ SQL injection
```

### 3. Bare Except

```python
# NEVER
try:
    ...
except:  # ❌ Catch specific exceptions
    pass
```

### 4. Modifying Ledger Entries

```python
# NEVER
cursor.execute("UPDATE ledger_entries SET amount_eur = ?", ...)  # ❌ Append-only!
```

### 5. Hardcoded API Keys

```python
# NEVER
TELEGRAM_BOT_TOKEN = "123456:ABC..."  # ❌ Use .env
```

---

## Pre-Commit Hooks

**Install pre-commit:**

```bash
pip install pre-commit
pre-commit install
```

**.pre-commit-config.yaml:**

```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.0.0
    hooks:
      - id: black
        args: [--line-length=100]

  - repo: https://github.com/charliermarsh/ruff-pre-commit
    rev: v0.1.0
    hooks:
      - id: ruff
        args: [--fix, --exit-non-zero-on-fix]

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.5.0
    hooks:
      - id: mypy
        additional_dependencies: [types-all]
```

---

**End of Document**
