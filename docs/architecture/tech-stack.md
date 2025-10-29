# Technology Stack

**Version:** v4
**Last Updated:** 2025-10-29
**Parent Document:** [Architecture Overview](../architecture.md)

---

## Overview

The Surebet Accounting System uses a **Python-first, local-first** technology stack optimized for rapid development, data integrity, and single-operator deployment.

---

## Core Technologies

### Programming Language

**Python 3.12+**

**Justification:**
- Rich ecosystem for data processing, decimal math, and API integrations
- Built-in `Decimal` type for currency precision (no float rounding errors)
- Excellent libraries for Telegram, OpenAI, and web frameworks
- Rapid prototyping and iterative development
- Strong typing support via `mypy`

**Alternatives Considered:**
- Node.js: Rejected due to float precision issues with currency
- Go: Rejected due to slower prototyping speed for MVP
- C#: Rejected due to platform lock-in (Windows-centric)

---

## Frontend Stack

### UI Framework

**Streamlit 1.30+**

**Justification:**
- Zero frontend boilerplate (no HTML/CSS/JavaScript required)
- Built-in widgets for forms, tables, file uploads
- Fast iteration cycle (hot reload on save)
- Perfect for single-operator internal tools
- Native support for dataframes, charts, and metrics

**Limitations:**
- Not suitable for multi-user production apps (no session isolation)
- Limited customization compared to React/Vue
- Sequential execution model (reruns entire script on interaction)

**Future Migration Path:** If multi-operator support needed, migrate to FastAPI backend + React frontend

### UI Components

```python
# Core Streamlit widgets used
st.selectbox()          # Dropdowns (associate, bookmaker, event selection)
st.file_uploader()      # Screenshot upload
st.button()             # Actions (Approve, Reject, Settle)
st.dataframe()          # Bet tables, ledger views
st.metric()             # Counters (Waiting review, Settled today)
st.expander()           # Collapsible sections
st.form()               # Input forms with submit
st.image()              # Screenshot previews
```

---

## Backend Stack

### Core Framework

**Python Standard Library + Custom Services**

No heavy framework needed (Flask/FastAPI) since:
- Single operator (no REST API requirements)
- Streamlit handles HTTP layer
- Business logic is pure Python

### Key Libraries

| Library | Version | Purpose |
|---------|---------|---------|
| `python-telegram-bot` | 20.0+ | Telegram Bot API (async support, polling mode) |
| `openai` | 1.0.0+ | GPT-4o API for OCR + normalization |
| `httpx` | 0.25.0+ | Async HTTP client for FX API |
| `structlog` | 23.0.0+ | Structured JSON logging |
| `pandas` | 2.1.0+ | CSV export, data manipulation |
| `pillow` | 10.0.0+ | Image handling (screenshot processing) |
| `python-dotenv` | 1.0.0+ | Environment variable management |

### Currency Math

**`decimal.Decimal` (Python stdlib)**

**Critical Requirement:** All currency values MUST use `Decimal`, never `float`

```python
from decimal import Decimal

# CORRECT
stake = Decimal("100.50")
odds = Decimal("1.91")
payout = stake * odds  # Decimal("191.955")

# WRONG - DO NOT USE
stake = 100.50  # float introduces rounding errors
```

**Storage:** All `Decimal` values stored as TEXT in SQLite to preserve exact precision

---

## Database Stack

### Database Engine

**SQLite 3.40+**

**Justification:**
- Zero configuration (single file database)
- ACID guarantees (Atomicity, Consistency, Isolation, Durability)
- WAL mode for crash resistance
- 140 TB theoretical limit (far exceeds MVP needs: ~100 MB)
- Built-in support in Python stdlib
- Excellent for single-user, local-first applications

**Configuration:**
```python
import sqlite3

conn = sqlite3.connect("data/surebet.db", check_same_thread=False)
conn.execute("PRAGMA foreign_keys = ON")       # Enforce referential integrity
conn.execute("PRAGMA journal_mode = WAL")       # Write-Ahead Logging for resilience
conn.execute("PRAGMA synchronous = NORMAL")     # Balance safety vs performance
```

**Alternatives Considered:**
- PostgreSQL: Overkill for single operator, requires server setup
- MySQL: Same issue, plus licensing complexity
- MongoDB: Document model doesn't fit relational ledger structure

### Database Access Pattern

**Direct SQLite queries (no ORM)**

**Justification:**
- Simple schema (no complex relationships)
- Full control over query optimization
- No ORM learning curve
- No impedance mismatch

```python
# Example: Direct parameterized query
cursor.execute(
    "SELECT * FROM bets WHERE status = ? ORDER BY created_at_utc DESC",
    ("incoming",)
)
```

**No ORM libraries needed:**
- SQLAlchemy: Too heavy for simple queries
- Django ORM: Requires Django framework

---

## Integration Stack

### Telegram Bot Framework

**python-telegram-bot 20.0+**

**Features:**
- Async/await support (built on `asyncio`)
- Polling mode (no webhook setup required)
- Rich API for photo handling, media groups, message forwarding
- Active community and excellent documentation

**Mode:** Polling (not webhook)
- Simpler setup (no exposed ports)
- Works on local machine without port forwarding
- Suitable for low-traffic bots (<100 messages/day)

### AI/OCR Service

**OpenAI GPT-4o**

**Justification:**
- Multimodal (text + image input)
- Strong OCR performance on bet slips
- Contextual normalization (team names, market types)
- JSON output mode for structured extraction

**Fallback:** If GPT-4o unavailable, mark bet with `confidence=0.0`, queue for manual entry

### Currency Exchange API

**Options (choose one):**

| Provider | Free Tier | Rate Limit | Notes |
|----------|-----------|------------|-------|
| **Exchangerate-API** | 1500 req/month | Good for daily updates | Recommended |
| **Fixer.io** | 100 req/month | Limited free tier | |
| **European Central Bank (ECB)** | Unlimited | No rate limit | Free, but EUR-centric |

**Recommended:** Exchangerate-API (https://www.exchangerate-api.com/)

**Caching Strategy:** Fetch once per day (midnight UTC), cache in `fx_rates_daily` table

---

## Development Tools

### Code Quality

| Tool | Purpose | Configuration |
|------|---------|---------------|
| **Black** | Code formatting | Line length: 100, Python 3.12 target |
| **Ruff** | Linting (replaces Flake8, isort, etc.) | Rules: E, F, I, N |
| **mypy** | Static type checking | Strict mode, `--disallow-untyped-defs` |
| **pre-commit** | Git hooks for quality gates | Runs Black, Ruff, mypy before commit |

### Testing Framework

**pytest 7.0+**

**Plugins:**
- `pytest-asyncio` - Test async Telegram bot handlers
- `pytest-mock` - Mock external APIs (OpenAI, Telegram, FX)
- `freezegun` - Freeze time for deterministic timestamp tests
- `pytest-cov` - Code coverage reporting

### Package Management

**pip + requirements.txt**

```bash
# Install dependencies
pip install -r requirements.txt

# Freeze current versions
pip freeze > requirements.txt
```

**Future Enhancement:** Migrate to `poetry` or `pipenv` for better dependency resolution

---

## Runtime Environment

### Python Version

**Minimum:** Python 3.12+

**Justification:**
- Type hints improvements (`type` keyword)
- Performance improvements (faster startup)
- Long-term support (maintained until 2028)

**Installation:**
- Windows: https://www.python.org/downloads/
- macOS: `brew install python@3.12`
- Linux: `sudo apt install python3.12`

### Virtual Environment

**venv (Python stdlib)**

```bash
# Create virtual environment
python3.12 -m venv venv

# Activate
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## External Services

### Required APIs

| Service | Purpose | Cost (MVP) |
|---------|---------|------------|
| **Telegram Bot API** | Bot communication | Free |
| **OpenAI API** | GPT-4o for OCR | ~$5-10/month (est. 200 screenshots @ $0.025/image) |
| **Exchangerate-API** | FX rates | Free (1500 req/month, need ~30/month) |

**Total Estimated Cost:** ~$5-10/month

---

## File Storage

### Screenshot Storage

**Local filesystem:** `data/screenshots/`

**Naming Convention:**
```
{timestamp}_{associate_id}_{bookmaker_id}_{bet_id}.png

Example: 20251029_120530_5_12_1234.png
```

**Retention Policy (Future):**
- Keep all screenshots indefinitely (storage is cheap)
- Optional: Archive to cloud storage (Dropbox, OneDrive) monthly

### Database File

**Location:** `data/surebet.db`

**Backup Strategy:**
1. Daily CSV export (automated cron job)
2. Weekly manual SQLite file copy to external drive
3. Optional: Cloud backup via Dropbox/OneDrive sync

---

## Environment Configuration

### Environment Variables

**Storage:** `.env` file (not committed to git)

```bash
# Telegram
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_ADMIN_CHAT_ID=987654321

# OpenAI
OPENAI_API_KEY=sk-proj-xxx

# FX API
FX_API_KEY=xxx
FX_API_BASE_URL=https://api.exchangerate-api.com/v4/latest/

# Paths
DB_PATH=data/surebet.db
SCREENSHOT_DIR=data/screenshots
EXPORT_DIR=data/exports

# Logging
LOG_LEVEL=INFO
LOG_DIR=data/logs
```

**Loading:**
```python
from dotenv import load_dotenv
import os

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
```

---

## Deployment Dependencies

### Operating System Support

**Supported Platforms:**
- Windows 10/11 (64-bit)
- macOS 12+ (Intel & Apple Silicon)
- Linux (Ubuntu 20.04+, Debian 11+)

**No Docker Required (MVP):**
- Python is cross-platform
- SQLite is built-in
- No containerization overhead

**Future Enhancement:** Dockerize for easier multi-machine deployment

---

## Version Control

### Git + GitHub/GitLab

**.gitignore:**
```
# Environment
.env
venv/

# Data (never commit)
data/
*.db
*.db-shm
*.db-wal

# Python
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.mypy_cache/

# IDE
.vscode/
.idea/
```

---

## Summary: Technology Decision Matrix

| Decision | Technology | Rationale |
|----------|------------|-----------|
| **Language** | Python 3.12 | Decimal precision, rich ecosystem |
| **UI** | Streamlit | Rapid prototyping, zero frontend code |
| **Database** | SQLite (WAL) | Local-first, zero-config, ACID guarantees |
| **Bot Framework** | python-telegram-bot | Async support, polling mode |
| **AI/OCR** | OpenAI GPT-4o | Multimodal, strong accuracy |
| **Currency Math** | Decimal (stdlib) | Exact precision, no float errors |
| **Testing** | pytest | Rich ecosystem, async support |
| **Logging** | structlog | Structured JSON logs |

---

## Future Technology Roadmap

### Phase 2: Multi-Operator Support
- Add: **FastAPI** for REST API backend
- Add: **React** or **Vue** for frontend
- Add: **PostgreSQL** to replace SQLite (multi-user support)
- Add: **Redis** for session management

### Phase 3: Cloud Deployment
- Add: **Docker** + **Docker Compose** for containerization
- Add: **Nginx** for reverse proxy
- Add: **Let's Encrypt** for HTTPS
- Replace polling with **Telegram Webhook** mode

### Phase 4: Real-Time Surebet Detection
- Add: **Apache Kafka** for event streaming
- Add: **Celery** for background task processing
- Add: **Prometheus** + **Grafana** for monitoring

---

**End of Document**
