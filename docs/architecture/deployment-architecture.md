# Deployment Architecture

**Version:** v4
**Last Updated:** 2025-10-29
**Parent Document:** [Architecture Overview](../architecture.md)

---

## Overview

The Surebet Accounting System is deployed as a **local desktop application** running on a single operator machine. No cloud infrastructure, no containers, no remote access.

---

## Deployment Model

### Single-Machine Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              ACCOUNTANT MACHINE                              │
│  OS: Windows 10/11 | macOS 12+ | Ubuntu 20.04+              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Application: c:\surebet-accounting\                  │   │
│  │                                                       │   │
│  │ ├── venv\                Python virtual environment  │   │
│  │ ├── src\                 Source code                 │   │
│  │ ├── data\                                            │   │
│  │ │   ├── surebet.db       SQLite database (WAL mode) │   │
│  │ │   ├── screenshots\     Bet screenshots            │   │
│  │   │   ├── exports\           CSV ledger backups        │   │
│  │ │   └── logs\            Application logs           │   │
│  │ ├── .env                 Environment config          │   │
│  │ └── requirements.txt     Python dependencies         │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Running Processes:                                   │   │
│  │                                                       │   │
│  │ 1. Streamlit UI                                      │   │
│  │    http://localhost:8501                             │   │
│  │    PID: 1234                                         │   │
│  │                                                       │   │
│  │ 2. Telegram Bot (polling)                            │   │
│  │    PID: 1235                                         │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Local Development Setup

### Prerequisites

- **Python 3.12+** installed
- **Git** (optional, for version control)
- **Internet connection** (for initial setup, Telegram, OpenAI, FX APIs)

### Installation Steps

```bash
# 1. Clone repository (or download ZIP)
git clone https://github.com/your-org/surebet-accounting.git
cd surebet-accounting

# 2. Create virtual environment
python3.12 -m venv venv

# 3. Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 4. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 5. Create data directories
mkdir -p data/screenshots data/exports data/logs

# 6. Configure environment variables
cp .env.example .env
# Edit .env with your API keys

# 7. Initialize database
python -m src.core.database init

# 8. Verify installation
python -m pytest tests/
```

---

## Production Deployment (Operator Machine)

### Directory Structure

```
C:\surebet-accounting\          (Windows)
~/surebet-accounting/           (macOS/Linux)
├── venv\                       Python virtual environment
├── src\                        Source code
├── data\
│   ├── surebet.db              SQLite database
│   ├── surebet.db-shm          Shared memory (WAL mode)
│   ├── surebet.db-wal          Write-ahead log
│   ├── screenshots\
│   │   ├── 20251029_120530_2_5_1234.png
│   │   └── ...
│   ├── exports\
│   │   ├── ledger_20251029.csv
│   │   └── ...
│   └── logs\
│       ├── application.log
│       ├── telegram_bot.log
│       └── settlement.log
├── tests\
├── .env                        Environment config (DO NOT COMMIT)
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Process Management

### Manual Start (MVP)

**Terminal 1 - Streamlit UI:**
```bash
cd c:\surebet-accounting
venv\Scripts\activate
streamlit run src/ui/app.py
```

**Terminal 2 - Telegram Bot:**
```bash
cd c:\surebet-accounting
venv\Scripts\activate
python -m src.integrations.telegram_bot
```

### Automated Start (Future Enhancement)

#### Windows - Task Scheduler

Create two scheduled tasks:
1. **Start Streamlit** on login
2. **Start Telegram Bot** on login

```bat
REM start_ui.bat
cd C:\surebet-accounting
call venv\Scripts\activate
streamlit run src/ui/app.py
```

```bat
REM start_bot.bat
cd C:\surebet-accounting
call venv\Scripts\activate
python -m src.integrations.telegram_bot
```

#### macOS - LaunchAgent

```xml
<!-- ~/Library/LaunchAgents/com.surebet.streamlit.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.surebet.streamlit</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/operator/surebet-accounting/venv/bin/streamlit</string>
        <string>run</string>
        <string>/Users/operator/surebet-accounting/src/ui/app.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
```

```bash
# Load LaunchAgent
launchctl load ~/Library/LaunchAgents/com.surebet.streamlit.plist
```

#### Linux - systemd

```ini
# /etc/systemd/system/surebet-streamlit.service
[Unit]
Description=Surebet Streamlit UI
After=network.target

[Service]
Type=simple
User=operator
WorkingDirectory=/home/operator/surebet-accounting
ExecStart=/home/operator/surebet-accounting/venv/bin/streamlit run src/ui/app.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start service
sudo systemctl enable surebet-streamlit
sudo systemctl start surebet-streamlit
```

---

## Backup Strategy

### Daily Automated Backup

**Excel Export (Cron Job):**

```bash
# Crontab (Linux/macOS)
0 2 * * * cd /home/operator/surebet-accounting && venv/bin/python -m src.jobs.export_ledger_daily

# Windows Task Scheduler
# Run daily at 2:00 AM: python -m src.jobs.export_ledger_daily
```

**Backup Script:**
```python
# src/jobs/export_ledger_daily.py
from src.services.ledger_export_service import LedgerExportService


def export_ledger():
    service = LedgerExportService()
    service.export_full_ledger()


if __name__ == "__main__":
    export_ledger()
```

### Manual SQLite Backup

```bash
# Weekly backup (operator runs manually)
# Windows
copy data\surebet.db data\surebet_backup_%date:~-4,4%%date:~-7,2%%date:~-10,2%.db

# macOS/Linux
cp data/surebet.db data/surebet_backup_$(date +%Y%m%d).db

# Copy to external drive
copy data\surebet_backup_*.db E:\Backups\
```

### Cloud Backup (Optional)

**Sync `data/` folder to cloud storage:**

- **Dropbox**: Install Dropbox desktop, symlink `data/` to Dropbox folder
- **OneDrive**: Similar approach
- **Google Drive**: Use Google Backup & Sync

```bash
# Example: Symlink to Dropbox
# Windows (as Administrator)
mklink /D "C:\Users\Operator\Dropbox\surebet-backups" "C:\surebet-accounting\data"

# macOS/Linux
ln -s ~/surebet-accounting/data ~/Dropbox/surebet-backups
```

---

## Monitoring & Health Checks

### Manual Health Check (Daily Operator Routine)

1. **Check Reconciliation Page**
   - Review DELTA for all associates
   - Flag any anomalies (DELTA > €100)

2. **Review Logs**
   ```bash
   # Check for ERROR entries
   grep "ERROR" data/logs/application.log
   ```

3. **Verify Telegram Bot**
   - Send test photo to bookmaker chat
   - Confirm bet appears in Incoming Bets

4. **Verify Streamlit UI**
   - Access http://localhost:8501
   - Confirm pages load

### Automated Health Checks (Future)

```python
# src/jobs/health_check.py
def run_health_check():
    issues = []

    # 1. Check database file exists and is not locked
    if not os.path.exists("data/surebet.db"):
        issues.append("❌ Database file missing")

    # 2. Check Telegram bot last message
    last_message_age = get_last_telegram_message_age()
    if last_message_age > timedelta(hours=48):
        issues.append(f"⚠️ No Telegram messages in {last_message_age.hours} hours")

    # 3. Check FX rate freshness
    oldest_fx_rate = get_oldest_fx_rate_age()
    if oldest_fx_rate > timedelta(days=7):
        issues.append(f"⚠️ FX rates not updated in {oldest_fx_rate.days} days")

    # 4. Check disk space
    free_space_gb = get_free_disk_space()
    if free_space_gb < 1:
        issues.append(f"❌ Low disk space: {free_space_gb:.2f} GB")

    # Report
    if issues:
        logger.warning("Health check issues:\n" + "\n".join(issues))
        # Future: Send email/Telegram alert
    else:
        logger.info("✅ Health check passed")
```

---

## Disaster Recovery

### Scenario 1: Database Corruption

**Symptoms:** SQLite errors, app crashes

**Recovery:**
```bash
# 1. Stop all processes
# 2. Check database integrity
sqlite3 data/surebet.db "PRAGMA integrity_check;"

# 3. If corrupted, restore from backup
copy data\surebet_backup_20251028.db data\surebet.db

# 4. Restart processes
```

### Scenario 2: Accidental Data Loss

**Scenario:** Operator accidentally settles wrong surebet

**Recovery:**
- **Never delete ledger entries** (System Law #1)
- Create BOOKMAKER_CORRECTION rows to reverse
- All corrections logged with timestamp and note

### Scenario 3: Machine Failure

**Recovery:**
1. Install Python 3.12 on new machine
2. Restore backup:
   - Copy latest `surebet_backup_YYYYMMDD.db` to `data/surebet.db`
   - Copy screenshots folder
3. Reinstall application (steps from "Installation Steps")
4. Verify data integrity (check reconciliation page)

---

## Upgrade Process

### Python Dependency Upgrade

```bash
# 1. Activate virtual environment
venv\Scripts\activate

# 2. Update specific package
pip install --upgrade streamlit

# 3. Test
python -m pytest tests/

# 4. Freeze new requirements
pip freeze > requirements.txt

# 5. Commit changes
git add requirements.txt
git commit -m "Upgrade streamlit to 1.31.0"
```

### Database Schema Migration

```python
# src/migrations/001_add_column.py
def upgrade(conn):
    """
    Add new column to bets table
    """
    conn.execute("ALTER TABLE bets ADD COLUMN new_field TEXT")
    conn.execute("INSERT INTO schema_version (version) VALUES (2)")
    conn.commit()

def downgrade(conn):
    """
    Not supported - append-only migrations only
    """
    raise NotImplementedError("Downgrades not supported")
```

**Run migration:**
```bash
python -m src.migrations.runner upgrade
```

---

## Configuration Management

### Environment Variables

**.env File:**
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
LOG_DIR=data/logs

# Logging
LOG_LEVEL=INFO
```

**.env.example (committed to git):**
```bash
# Copy this file to .env and fill in your values

TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_ADMIN_CHAT_ID=your_chat_id_here
OPENAI_API_KEY=your_openai_key_here
FX_API_KEY=your_fx_api_key_here
```

**Loading in Code:**
```python
from dotenv import load_dotenv
import os

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
assert TELEGRAM_BOT_TOKEN, "TELEGRAM_BOT_TOKEN not set in .env"
```

---

## Performance Optimization

### Expected Resource Usage

| Resource | Idle | Active (Settlement) |
|----------|------|---------------------|
| CPU | <5% | ~20% |
| RAM | ~200 MB | ~500 MB |
| Disk I/O | Minimal | ~10 MB/s (CSV export) |
| Network | Periodic API calls | ~1 Mbps (screenshot upload) |

**Conclusion:** Any modern laptop/desktop (4GB RAM, dual-core CPU) sufficient

### Database Optimization

**WAL Mode Benefits:**
- Concurrent reads (Streamlit queries) while bot writes
- Faster writes (sequential append)
- Checkpoint automatically handled by SQLite

**Manual Checkpoint (if needed):**
```sql
PRAGMA wal_checkpoint(TRUNCATE);
```

---

## Troubleshooting Guide

### Issue 1: Streamlit Port Already in Use

**Error:** `Address already in use: 8501`

**Fix:**
```bash
# Windows
netstat -ano | findstr :8501
taskkill /PID <PID> /F

# macOS/Linux
lsof -ti:8501 | xargs kill -9

# Or use different port
streamlit run src/ui/app.py --server.port 8502
```

### Issue 2: Telegram Bot Not Responding

**Symptoms:** Photos sent to bot don't create bets

**Debugging:**
```bash
# Check bot logs
tail -f data/logs/telegram_bot.log

# Verify bot token
curl https://api.telegram.org/bot<TOKEN>/getMe

# Check chat whitelist
sqlite3 data/surebet.db "SELECT * FROM telegram_chats;"
```

### Issue 3: OpenAI API Rate Limit

**Error:** `RateLimitError: You exceeded your current quota`

**Fix:**
- Check OpenAI usage dashboard
- Add budget limits
- Queue bets for processing later

---

**End of Document**
