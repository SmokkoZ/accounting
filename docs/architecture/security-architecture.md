# Security Architecture

**Version:** v4
**Last Updated:** 2025-10-29
**Parent Document:** [Architecture Overview](../architecture.md)

---

## Overview

The Surebet Accounting System operates in a **trusted local environment** with a single operator. Security focuses on:
1. API key protection
2. Data integrity (not confidentiality)
3. Input validation
4. Audit trail preservation

---

## Threat Model

### Trust Boundaries

```
┌─────────────────────────────────────────────────────────────┐
│                    TRUSTED                                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Operator's Machine                                    │   │
│  │ - Local filesystem: data/                            │   │
│  │ - Python processes (Streamlit, Telegram bot)         │   │
│  │ - SQLite database                                    │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                          ▲ │
                          │ │ HTTPS
                          │ ▼
┌─────────────────────────────────────────────────────────────┐
│                    UNTRUSTED                                 │
│  - Telegram API                                              │
│  - OpenAI API                                                │
│  - FX Rate API                                               │
│  - Internet                                                  │
└─────────────────────────────────────────────────────────────┘
```

### Threat Scenarios

| Threat | Likelihood | Impact | Mitigation |
|--------|------------|--------|------------|
| **API Key Exposure** | Medium | High | Store in `.env`, add to `.gitignore`, never hardcode |
| **Database Tampering** | Low | High | Operator machine trusted, append-only ledger for audit trail |
| **Telegram Bot Hijack** | Low | Medium | Whitelist known chats only, no public commands |
| **SQLite Corruption** | Low | High | WAL mode, regular backups, integrity checks |
| **Screenshot Tampering** | Low | Medium | All edits logged in `verification_audit`, screenshots immutable |
| **OpenAI Prompt Injection** | Medium | Low | Operator reviews all OCR results before approval |

### Out of Scope Threats

**The following are NOT mitigated (acceptable for single-operator local app):**

- **Unauthorized access to operator's machine** (physical/remote)
- **Malicious associates** (trust model assumes friends)
- **Data encryption at rest** (operator's machine is trusted)
- **Network sniffing** (HTTPS already used for API calls)
- **Multi-user access control** (no RBAC, single operator)

---

## API Key Management

### Storage

**.env File (NOT committed to git):**
```bash
# CRITICAL: Add .env to .gitignore
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
OPENAI_API_KEY=sk-proj-xxx
FX_API_KEY=xxx
```

**.gitignore:**
```
# Never commit these
.env
*.env.local
*.env.production
```

### Loading Secrets

```python
# src/core/config.py
from dotenv import load_dotenv
import os

load_dotenv()

class Config:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    FX_API_KEY = os.getenv("FX_API_KEY")

    # Validate required secrets
    @classmethod
    def validate(cls):
        required = ["TELEGRAM_BOT_TOKEN", "OPENAI_API_KEY"]
        missing = [key for key in required if not getattr(cls, key)]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

# On startup
Config.validate()
```

### Best Practices

1. **Never hardcode** API keys in source code
2. **Never log** API keys (redact in logs)
3. **Rotate keys** quarterly (good practice)
4. **Use `.env.example`** as template (commit this, not `.env`)

```python
# Redact secrets in logs
logger.info(f"Telegram token: {TELEGRAM_BOT_TOKEN[:10]}***")  # Only show first 10 chars
```

---

## Data Protection

### Data at Rest

**SQLite Database:**
- **No encryption** (MVP acceptable for trusted local machine)
- **File permissions:** Operator user only (OS-level)
- **Future enhancement:** Encrypt `data/` folder with OS-level encryption

**Windows - BitLocker:**
```
Enable BitLocker on C:\ drive (includes data\surebet.db)
```

**macOS - FileVault:**
```
System Preferences → Security & Privacy → FileVault → Turn On
```

**Linux - LUKS:**
```bash
# Encrypt home directory (includes ~/surebet-accounting/data/)
```

### Data in Transit

**All external API calls use HTTPS:**
- Telegram API: `https://api.telegram.org`
- OpenAI API: `https://api.openai.com`
- FX API: `https://api.exchangerate-api.com`

**No custom TLS configuration needed** (Python `requests`/`httpx` use system certificates)

---

## Input Validation

### Screenshot Upload

**File Type Validation:**
```python
# src/services/bet_ingestion.py
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}

def validate_screenshot(file):
    ext = os.path.splitext(file.name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Invalid file type: {ext}. Allowed: {ALLOWED_EXTENSIONS}")

    # Check file size (max 10 MB)
    if file.size > 10 * 1024 * 1024:
        raise ValueError("File too large (max 10 MB)")
```

**Path Traversal Prevention:**
```python
# Sanitize filename (remove ../ and other dangerous chars)
import re

def sanitize_filename(filename):
    # Remove path traversal attempts
    filename = os.path.basename(filename)

    # Remove non-alphanumeric (except . and _)
    filename = re.sub(r'[^\w\.-]', '', filename)

    return filename
```

### Database Inputs (SQL Injection Prevention)

**Always use parameterized queries:**

```python
# GOOD - Parameterized query
cursor.execute("SELECT * FROM bets WHERE id = ?", (bet_id,))

# BAD - String formatting (vulnerable to SQL injection)
cursor.execute(f"SELECT * FROM bets WHERE id = {bet_id}")  # NEVER DO THIS
```

### Decimal Validation

```python
# src/ui/utils/validators.py
from decimal import Decimal, InvalidOperation

def validate_decimal(value: str) -> bool:
    try:
        d = Decimal(value)
        # Check reasonable bounds (e.g., stake < €1,000,000)
        if d < 0 or d > Decimal("1000000"):
            return False
        return True
    except (InvalidOperation, ValueError):
        return False
```

---

## Telegram Bot Security

### Chat Whitelisting

**Only process messages from known chats:**

```python
# src/integrations/telegram_bot.py
async def handle_photo(update, context):
    chat_id = update.effective_chat.id

    # Check whitelist
    whitelisted = cursor.execute("""
        SELECT 1 FROM telegram_chats WHERE chat_id = ?
    """, (chat_id,)).fetchone()

    if not whitelisted:
        logger.warning(f"Unauthorized chat: {chat_id}")
        await update.message.reply_text("⚠️ This chat is not authorized.")
        return

    # Process photo...
```

### No Public Commands

**Bot responds ONLY to:**
- Photos (screenshots)
- Configured chats (bookmaker chats, multibook chats)

**No slash commands** like `/start`, `/help` (reduces attack surface)

### Rate Limiting

**Prevent spam/abuse:**

```python
# Simple rate limiting (in-memory)
from collections import defaultdict
from time import time

last_message_time = defaultdict(float)
RATE_LIMIT_SECONDS = 5

async def handle_photo(update, context):
    chat_id = update.effective_chat.id
    now = time()

    if now - last_message_time[chat_id] < RATE_LIMIT_SECONDS:
        await update.message.reply_text("⚠️ Too many requests. Wait 5 seconds.")
        return

    last_message_time[chat_id] = now
    # Process photo...
```

---

## Audit Trail & Data Integrity

### Append-Only Ledger (System Law #1)

**Immutable Financial Records:**

```sql
-- NO UPDATE OR DELETE allowed on ledger_entries
-- All corrections are forward-only (BOOKMAKER_CORRECTION type)

-- Example: Late VOID correction
INSERT INTO ledger_entries (
    type, associate_id, bookmaker_id, amount_native, native_currency,
    fx_rate_snapshot, amount_eur, note
) VALUES (
    'BOOKMAKER_CORRECTION', 5, 12, '-50.00', 'AUD',
    '1.50', '-33.33', 'Correction for late VOID on Surebet 45'
);
```

**Benefits:**
- Complete audit trail
- No data loss
- Easy to trace all financial decisions
- Compliance-ready (if future regulatory requirements)

### Verification Audit Log

**All bet edits logged:**

```sql
-- verification_audit table
INSERT INTO verification_audit (bet_id, field_name, old_value, new_value, edited_by)
VALUES (1234, 'stake', '100.00', '105.00', 'operator');
```

**Query audit history:**
```sql
SELECT * FROM verification_audit
WHERE bet_id = 1234
ORDER BY edited_at_utc ASC;
```

---

## Access Control

### Single-Operator Model

**No RBAC (Role-Based Access Control):**
- Only one user (operator)
- No login/password
- No session management

**Streamlit runs on localhost only:**
```python
# src/ui/app.py
# Do NOT expose to 0.0.0.0 (external access)
# Default: localhost:8501 (internal only)
```

**If remote access needed (future):**
- Use SSH tunnel: `ssh -L 8501:localhost:8501 operator@machine`
- Or deploy with proper authentication (FastAPI + JWT)

---

## Logging & Monitoring

### Sensitive Data Redaction

**Never log full API keys or passwords:**

```python
# src/utils/logging_config.py
import structlog

def redact_sensitive(event_dict):
    """
    Redact sensitive fields from logs
    """
    sensitive_keys = ["api_key", "password", "token", "secret"]

    for key in sensitive_keys:
        if key in event_dict:
            value = event_dict[key]
            if value:
                event_dict[key] = f"{value[:4]}***"  # Show first 4 chars only

    return event_dict

structlog.configure(
    processors=[
        redact_sensitive,
        structlog.processors.JSONRenderer()
    ]
)
```

### Log File Permissions

**Restrict log access to operator user:**

```bash
# Linux/macOS
chmod 600 data/logs/*.log

# Windows (PowerShell)
icacls data\logs\*.log /inheritance:r /grant:r "OPERATOR:F"
```

---

## Backup Security

### Backup Location

**External Drive (encrypted):**
- Use encrypted USB drive (BitLocker, FileVault, LUKS)
- Copy backups weekly

**Cloud Backup (optional):**
- Enable encryption-at-rest (Dropbox, OneDrive support this)
- Use two-factor authentication on cloud account

---

## Third-Party Dependencies

### Supply Chain Security

**Verify package integrity:**

```bash
# Use pip with hash checking
pip install --require-hashes -r requirements.txt
```

**requirements.txt with hashes:**
```
streamlit==1.30.0 --hash=sha256:abc123...
python-telegram-bot==20.0 --hash=sha256:def456...
```

**Scan for vulnerabilities:**

```bash
# Use safety to check for known CVEs
pip install safety
safety check
```

---

## Incident Response

### Scenario: API Key Compromised

**Steps:**
1. **Rotate key immediately** (Telegram, OpenAI, FX API)
2. **Update `.env` with new key**
3. **Restart processes**
4. **Review logs** for unauthorized usage
5. **Check billing** (OpenAI usage dashboard)

### Scenario: Suspicious Ledger Entry

**Steps:**
1. **Query verification_audit** to see who made changes
2. **Check settlement_batch_id** to group related entries
3. **Export ledger CSV** for offline analysis
4. **Create BOOKMAKER_CORRECTION** if error found

---

## Compliance Considerations

### GDPR (if applicable)

**Personal Data:**
- Associate names (display_alias) are minimal
- No addresses, phone numbers, emails stored
- Screenshots may contain personal info (bookmaker account numbers)

**Data Subject Rights:**
- Right to erasure: NOT applicable (financial records must be retained)
- Right to access: Operator can export ledger CSV
- Right to rectification: Use forward-only corrections

**Data Retention:**
- Keep all data indefinitely (audit trail requirement)
- Screenshots archived annually (move to cold storage)

### Anti-Money Laundering (AML)

**Not applicable for MVP** (friends-and-family betting pool)

**If commercialized:**
- Implement KYC (Know Your Customer) for associates
- Monitor for suspicious transaction patterns
- Report large deposits/withdrawals

---

## Security Checklist (Deployment)

Before deploying to production:

- [ ] `.env` file created with valid API keys
- [ ] `.env` added to `.gitignore`
- [ ] Database file permissions set (operator user only)
- [ ] Log file permissions set (operator user only)
- [ ] Backup strategy configured (external drive or cloud)
- [ ] Telegram bot whitelisted chats configured
- [ ] SQLite integrity check: `PRAGMA integrity_check;`
- [ ] Test API keys work (send test Telegram message)
- [ ] Review logs for ERROR entries
- [ ] Verify no hardcoded secrets in source code

---

**End of Document**
