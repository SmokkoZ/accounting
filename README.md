# Surebet Accounting System

A Python-based system for managing surebet accounting, including bet ingestion, verification, settlement, and ledger management.

## Overview

The Surebet Accounting System is designed to streamline the process of tracking and managing surebets across multiple betting accounts. It provides a web-based interface for bet verification, surebet matching, settlement calculations, and financial reporting.

## Prerequisites

- Python 3.12 or higher
- Git

## Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd surebet-accounting
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   
   # On Windows:
   venv\Scripts\activate
   
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Set up environment variables:
   ```bash
   cp .env.example .env
   # Edit .env with your API keys and configuration
   ```

## Running the Application

Start the Streamlit application:

```bash
streamlit run src/ui/app.py
```

The application will be available at `http://localhost:8501`

## Project Structure

```
surebet-accounting/
├── .env                        # Environment configuration (API keys)
├── .env.example                # Template for .env
├── .gitignore                  # Git ignore rules
├── requirements.txt            # Python dependencies
├── README.md                   # This file
├── data/                       # Data directory (git-ignored)
│   ├── screenshots/            # Bet screenshots
│   ├── exports/                # Excel exports
│   └── logs/                   # Application logs
├── docs/                       # Documentation
├── src/                        # Source code
│   ├── core/                   # Core configuration
│   ├── services/               # Business logic
│   ├── integrations/           # External API clients
│   ├── models/                 # Domain entities
│   ├── ui/                     # Streamlit UI
│   ├── utils/                  # Shared utilities
│   └── jobs/                   # Background jobs
└── tests/                      # Test suite
    ├── unit/                   # Unit tests
    ├── integration/            # Integration tests
    └── e2e/                    # End-to-end tests
```

## Development

### Code Quality

The project uses several tools to maintain code quality:

- **Black**: Code formatting (line length: 100)
- **Ruff**: Linting
- **mypy**: Static type checking
- **pytest**: Testing framework

Run code quality checks:

```bash
# Format code
black src/ tests/

# Run linter
ruff check src/ tests/

# Run type checking
mypy src/

# Run tests
pytest tests/
```

### Pre-commit Hooks

Install pre-commit hooks to automatically run code quality checks before each commit:

```bash
pre-commit install
```

## Release Notes

- **2025-11-13 -- Exit Settlement Flow**
  - Added the backend ExitSettlementService and UI guardrails so the Streamlit Statements and Operations screens run *Settle Associate Now* with cutoff confirmation, versioned receipts, and explicit "Your Fair Balance (YF = ND + FS)" copy.
- Statement Excel exports now append a model footnote (Model: YF-v1 (YF = ND + FS; I'' = TB - YF). Values exclude operator fees/taxes.) and every run writes a markdown receipt to data/exports/receipts/<associate_id>/.
- Soft rollout toggle: set SUREBET_YF_COPY_ROLLOUT=legacy in .streamlit/secrets.toml to keep the legacy "Should Hold" wording during partner enablement; switch it to enabled (default) once training is complete. The flag only affects UI copy/notes, so workbook fields remain backward compatible.

## Configuration

### Environment Variables

Create a `.env` file based on `.env.example` with the following variables:

```bash
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_ADMIN_CHAT_ID=your_admin_chat_id

# OpenAI
OPENAI_API_KEY=your_openai_key_here

# FX API
FX_API_KEY=your_fx_api_key_here
FX_API_BASE_URL=https://api.exchangerate-api.com/v4/latest/

# Paths
DB_PATH=data/surebet.db
SCREENSHOT_DIR=data/screenshots
EXPORT_DIR=data/exports
LOG_DIR=data/logs

# Logging
LOG_LEVEL=INFO
```

## Features

- **Bet Ingestion**: OCR-based bet slip processing using OpenAI GPT-4o
- **Bet Verification**: Approval workflow for incoming bets
- **Surebet Matching**: Deterministic matching algorithm
- **Settlement Engine**: Automated profit/loss calculations
- **Ledger Management**: Comprehensive financial tracking
- **FX Conversion**: Multi-currency support with daily rate updates
- **Export Functionality**: Excel exports for accounting purposes
- **Monthly Statements**: Automated associate statements
- **Statement & ROI Workbooks**: `StatementService.export_statement_excel` and `export_surebet_roi_excel` generate per-bookmaker allocations plus per-surebet ROI snapshots (see `docs/examples/statement_A123_YYYY-MM-DD.xlsx` and `docs/examples/surebet_roi_A123_YYYY-MM-DD.xlsx`). These snapshots reuse the existing statement math and explicitly note that values exclude operator fees/taxes.

### Change Notes -- YF & Exit Settlement Alignment (2025-11-13)

- Adopt unified financial identity: Your Fair Balance (YF) = Net Deposits (ND) + Fair Shares (FS); replaces the prior 'Should Hold' label in UI/docs.
- Standardize ND computation: store WITHDRAWAL as negative and DEPOSIT as positive; compute ND by summing signed amounts (no double-negation).
- Keep imbalance: I'' = TB - YF where TB is total bookmaker holdings; reconciliation still targets I'' -> 0.
- Add 'Settle Associate Now' flow: computes I'' at a cutoff and posts a single balancing DEPOSIT/WITHDRAWAL to zero it; Excel exports at exit include an 'Exit Payout' row (-I'').
- Workbooks: include YF in summaries plus a version footnote (e.g., Model: YF-v1 -- YF=ND+FS; I''=TB-YF; values exclude operator fees/taxes).
- Backward compatibility: no schema changes; existing math reused; older references to 'Should Hold' now map to YF. Where docs state RAW_PROFIT_EUR = SHOULD_HOLD - NET_DEPOSITS, this equals FS under YF (YF - ND = FS).

#### Excel Identity Notes (YF-v1)

- export_statement_excel and export_surebet_roi_excel prepend an Identity Version row showing YF-v1 so downstream automation can detect copy updates without schema changes.
- Each workbook ends with a footnote: Model: YF-v1 -- YF = ND + FS; I'' = TB - YF. Legacy 'Should Hold' values map to YF; exports remain backward compatible.
- ND/FS/YF/TB/I'' rows remain append-only; historical exports are untouched and legacy columns keep their ordering.

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For support and questions, please contact the development team.
