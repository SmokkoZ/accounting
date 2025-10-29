# Integration Architecture

**Version:** v4
**Last Updated:** 2025-10-29
**Parent Document:** [Architecture Overview](../architecture.md)

---

## Overview

The system integrates with three external services:
1. **Telegram Bot API** - Screenshot ingestion, coverage proof delivery
2. **OpenAI GPT-4o** - OCR and bet normalization
3. **FX Rate API** - Currency conversion rates

---

## 1. Telegram Bot Integration

### Library

`python-telegram-bot` v20+

**Features:**
- Async/await support (built on `asyncio`)
- Polling mode (no webhook setup required)
- Photo handling, media groups, message forwarding
- Update filtering and handlers

### Bot Architecture

```
src/integrations/telegram_bot.py
├── TelegramBotService
│   ├── start_polling()          # Main event loop
│   ├── handle_photo()           # Screenshot ingestion (FR-1)
│   ├── handle_text()            # Deposit/withdrawal parsing (future)
│   ├── send_coverage_proof()    # FR-5: Send screenshots to multibook chats
│   └── log_message()            # Log to multibook_message_log
```

### Configuration

```python
# .env
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_ADMIN_CHAT_ID=987654321

# Database: telegram_chats table (optional for MVP, can be hardcoded)
CREATE TABLE telegram_chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL UNIQUE,  -- Telegram chat ID
    chat_type TEXT NOT NULL CHECK (chat_type IN ('bookmaker', 'multibook')),
    associate_id INTEGER NOT NULL REFERENCES associates(id),
    bookmaker_id INTEGER REFERENCES bookmakers(id),  -- NULL for multibook
    created_at_utc TEXT NOT NULL
);
```

### Bot Handlers

#### Photo Handler (Screenshot Ingestion)

```python
# src/integrations/telegram_bot.py
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

class TelegramBotService:
    def __init__(self):
        self.app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self.db = get_db_connection()

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        FR-1: Telegram Screenshot Ingestion

        1. Check if chat is whitelisted (in telegram_chats table)
        2. Download photo
        3. Extract associate_id, bookmaker_id from chat mapping
        4. Call BetIngestionService.ingest_telegram_screenshot()
        5. Reply with bet ID
        """
        chat_id = update.effective_chat.id

        # Check if whitelisted
        chat_mapping = self.db.execute("""
            SELECT associate_id, bookmaker_id
            FROM telegram_chats
            WHERE chat_id = ? AND chat_type = 'bookmaker'
        """, (chat_id,)).fetchone()

        if not chat_mapping:
            logger.warning(f"Unknown chat: {chat_id}")
            await update.message.reply_text("⚠️ This chat is not configured for bet ingestion.")
            return

        # Download photo
        photo = update.message.photo[-1]  # Highest resolution
        file = await photo.get_file()
        screenshot_path = f"data/screenshots/telegram_{photo.file_id}.png"
        await file.download_to_drive(screenshot_path)

        # Ingest
        try:
            bet_id = BetIngestionService().ingest_telegram_screenshot(
                screenshot_path,
                chat_mapping["associate_id"],
                chat_mapping["bookmaker_id"],
                update.message.message_id
            )
            await update.message.reply_text(f"✅ Bet received! ID: {bet_id}. Check Incoming Bets page.")
        except Exception as e:
            logger.error(f"Ingestion failed: {e}")
            await update.message.reply_text(f"❌ Error processing bet: {e}")

    def start_polling(self):
        """
        Start Telegram bot polling loop (blocking call)
        """
        # Register handlers
        self.app.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))

        # Start polling
        logger.info("Starting Telegram bot polling...")
        self.app.run_polling()
```

#### Coverage Proof Sender (FR-5)

```python
async def send_coverage_proof(self, surebet_id: int):
    """
    FR-5: Coverage Proof Distribution

    1. Load surebet with all bets and screenshots
    2. Group bets by side (A vs B)
    3. For each associate on Side A:
       - Get their multibook chat_id
       - Send all Side B screenshots
       - Log to multibook_message_log
    4. Repeat for Side B (send Side A screenshots)
    """
    cursor = self.db.cursor()

    # Load surebet and bets
    surebet = cursor.execute("SELECT * FROM surebets WHERE id = ?", (surebet_id,)).fetchone()
    bets = cursor.execute("""
        SELECT b.*, sb.side, a.display_alias
        FROM bets b
        JOIN surebet_bets sb ON b.id = sb.bet_id
        JOIN associates a ON b.associate_id = a.id
        WHERE sb.surebet_id = ?
    """, (surebet_id,)).fetchall()

    # Group by side
    side_a_bets = [b for b in bets if b["side"] == "A"]
    side_b_bets = [b for b in bets if b["side"] == "B"]

    # Send to Side A associates (they get Side B screenshots)
    for associate_id in set(b["associate_id"] for b in side_a_bets):
        multibook_chat_id = cursor.execute("""
            SELECT chat_id FROM telegram_chats
            WHERE associate_id = ? AND chat_type = 'multibook'
        """, (associate_id,)).fetchone()["chat_id"]

        # Collect Side B screenshots
        media_group = [InputMediaPhoto(open(b["screenshot_path"], "rb")) for b in side_b_bets]

        # Send
        caption = f"Coverage proof for {surebet['event_name']} {surebet['market_code']}. You're covered!"
        messages = await self.app.bot.send_media_group(
            chat_id=multibook_chat_id,
            media=media_group,
            caption=caption
        )

        # Log
        cursor.execute("""
            INSERT INTO multibook_message_log (surebet_id, associate_id, telegram_message_id, screenshots_sent)
            VALUES (?, ?, ?, ?)
        """, (surebet_id, associate_id, messages[0].message_id, json.dumps([b["screenshot_path"] for b in side_b_bets])))

    # Repeat for Side B (send Side A screenshots)
    # ... (similar logic)

    self.db.commit()
```

### Error Handling

```python
# Retry with exponential backoff
from telegram.error import TelegramError
import asyncio

async def send_with_retry(self, chat_id, text, max_retries=3):
    for attempt in range(max_retries):
        try:
            await self.app.bot.send_message(chat_id, text)
            return
        except TelegramError as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff
                logger.warning(f"Telegram error: {e}. Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"Failed to send message after {max_retries} attempts: {e}")
                raise
```

### Rate Limiting

Telegram API limits:
- 30 messages/second to different chats
- 1 message/second to same chat

**Strategy:** Add delays between bulk sends

```python
for chat_id in multibook_chats:
    await send_coverage_proof(chat_id, ...)
    await asyncio.sleep(0.5)  # 500ms delay
```

---

## 2. OpenAI GPT-4o Integration

### Library

`openai` Python SDK v1.0+

### OCR Pipeline

```python
# src/integrations/openai_client.py
from openai import OpenAI
import base64

class OpenAIClient:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def extract_bet_from_screenshot(self, screenshot_path: str) -> Dict[str, Any]:
        """
        FR-1: OCR + Normalization

        1. Encode screenshot as base64
        2. Send to GPT-4o with structured prompt
        3. Parse JSON response
        4. Return extracted data
        """
        # Encode image
        with open(screenshot_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        # Call GPT-4o
        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": self._get_extraction_prompt()
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_data}"
                            }
                        },
                        {
                            "type": "text",
                            "text": "Extract bet details from this screenshot and return JSON."
                        }
                    ]
                }
            ],
            response_format={"type": "json_object"},
            max_tokens=500
        )

        # Parse response
        result = json.loads(response.choices[0].message.content)

        # Add metadata
        result["model_version_extraction"] = response.model
        result["model_version_normalization"] = response.model

        return result

    def _get_extraction_prompt(self) -> str:
        """
        Structured prompt for bet extraction
        """
        return """You are a bet slip OCR system. Extract the following from the screenshot:

**Required Fields:**
- canonical_event: Normalize team/event names (e.g., "Man Utd" → "Manchester United")
- market_code: Map to one of:
  - TOTAL_GOALS_OVER_UNDER
  - ASIAN_HANDICAP
  - BOTH_TEAMS_TO_SCORE_YES_NO
  - FIRST_HALF_TOTAL_CORNERS_OVER_UNDER
  - RED_CARD_YES_NO_FULL_MATCH
- period_scope: FULL_MATCH, FIRST_HALF, or SECOND_HALF
- line_value: Decimal (e.g., 2.5 for Over/Under 2.5). NULL if not applicable.
- side: OVER, UNDER, YES, NO, TEAM_A, TEAM_B
- stake: Decimal (e.g., 100.50)
- odds: Decimal (e.g., 1.91)
- payout: Decimal (potential return if won)
- currency: ISO code (AUD, GBP, EUR, USD)
- kickoff_time_utc: ISO8601 guess (e.g., "2025-10-30T19:00:00Z")
- normalization_confidence: 0.0-1.0 (0.8+ = high confidence)
- is_multi: Boolean (true if accumulator/parlay)

**Examples:**
- "Man Utd vs Liverpool - Total Goals Over 2.5" → market_code: TOTAL_GOALS_OVER_UNDER, line_value: 2.5, side: OVER
- "Both teams to score - Yes" → market_code: BOTH_TEAMS_TO_SCORE_YES_NO, line_value: NULL, side: YES

**Return JSON only. No additional text.**

Example output:
{
  "canonical_event": "Manchester United vs Liverpool",
  "market_code": "TOTAL_GOALS_OVER_UNDER",
  "period_scope": "FULL_MATCH",
  "line_value": "2.5",
  "side": "OVER",
  "stake": "100.00",
  "odds": "1.91",
  "payout": "191.00",
  "currency": "AUD",
  "kickoff_time_utc": "2025-10-30T19:00:00Z",
  "normalization_confidence": 0.85,
  "is_multi": false
}
"""
```

### Confidence Scoring

```python
def classify_confidence(confidence: float) -> str:
    if confidence >= 0.8:
        return "✅"  # High confidence
    else:
        return "⚠"   # Low confidence, needs extra review
```

### Error Handling

```python
try:
    extracted = openai_client.extract_bet_from_screenshot(path)
except OpenAIError as e:
    logger.error(f"OpenAI API error: {e}")
    # Fallback: Create bet with confidence=0.0
    extracted = {
        "normalization_confidence": 0.0,
        "note": f"OCR failed: {e}"
    }
```

### Cost Estimation

**GPT-4o Pricing (as of 2025):**
- Image input: ~$0.025 per image
- Text output: ~$0.01 per 1000 tokens

**Monthly Cost (200 screenshots):**
- 200 screenshots × $0.025 = **$5/month**

---

## 3. FX Rate API Integration

### Provider: Exchangerate-API

**Base URL:** `https://api.exchangerate-api.com/v4/latest/`

**Free Tier:** 1500 requests/month (sufficient for daily updates)

### API Client

```python
# src/integrations/fx_api_client.py
import httpx
from decimal import Decimal

class FXAPIClient:
    def __init__(self):
        self.base_url = os.getenv("FX_API_BASE_URL", "https://api.exchangerate-api.com/v4/latest/")

    def fetch_daily_rates(self, base_currency: str = "EUR") -> Dict[str, Decimal]:
        """
        Fetch all rates with base EUR

        Returns:
        {
            "AUD": Decimal("1.65"),
            "GBP": Decimal("0.85"),
            "USD": Decimal("1.10"),
            ...
        }
        """
        response = httpx.get(f"{self.base_url}{base_currency}", timeout=10)
        response.raise_for_status()

        data = response.json()
        rates = {}
        for currency, rate in data["rates"].items():
            rates[currency] = Decimal(str(rate))

        return rates

    def fetch_rate(self, currency: str, target_date: date) -> Decimal:
        """
        Fetch single rate for currency on target_date

        Note: Exchangerate-API only provides latest rates, not historical.
        For historical rates, use Fixer.io or ECB.
        """
        rates = self.fetch_daily_rates()
        if currency not in rates:
            raise ValueError(f"Currency {currency} not found in API response")
        return rates[currency]
```

### Caching in FXManager

```python
# src/services/fx_manager.py
class FXManager:
    def get_fx_rate(self, currency: str, target_date: date) -> Decimal:
        """
        1. Check fx_rates_daily table for (currency, target_date)
        2. If found, return cached rate
        3. If not found, fetch from API, cache, return
        4. If API fails, use last known rate
        """
        cursor = self.db.cursor()

        # Check cache
        cached = cursor.execute("""
            SELECT eur_per_unit FROM fx_rates_daily
            WHERE currency = ? AND rate_date = ?
        """, (currency, target_date.isoformat())).fetchone()

        if cached:
            return Decimal(cached["eur_per_unit"])

        # Fetch from API
        try:
            api_client = FXAPIClient()
            rate = api_client.fetch_rate(currency, target_date)

            # Cache
            cursor.execute("""
                INSERT INTO fx_rates_daily (currency, rate_date, eur_per_unit, source)
                VALUES (?, ?, ?, 'exchangerate-api')
            """, (currency, target_date.isoformat(), str(rate)))
            self.db.commit()

            return rate

        except Exception as e:
            logger.warning(f"FX API failed: {e}. Using last known rate.")

            # Fallback to last known rate
            last_known = cursor.execute("""
                SELECT eur_per_unit FROM fx_rates_daily
                WHERE currency = ?
                ORDER BY rate_date DESC
                LIMIT 1
            """, (currency,)).fetchone()

            if last_known:
                return Decimal(last_known["eur_per_unit"])
            else:
                raise ValueError(f"No FX rate available for {currency}")
```

### Daily Update Cron Job

```python
# src/jobs/fetch_fx_rates.py
def update_fx_rates_daily():
    """
    Cron job: Run daily at midnight UTC
    """
    logger.info("Fetching daily FX rates...")

    currencies = ["AUD", "GBP", "USD", "CAD", "NZD"]  # Add all needed currencies
    fx_manager = FXManager()

    for currency in currencies:
        try:
            rate = fx_manager.get_fx_rate(currency, date.today())
            logger.info(f"{currency}: {rate} EUR")
        except Exception as e:
            logger.error(f"Failed to fetch {currency}: {e}")
```

---

## Integration Monitoring

### Telegram Bot Health Check

```python
def check_telegram_bot_status():
    """
    Verify bot is polling
    """
    # Check last message timestamp in database
    last_message = cursor.execute("""
        SELECT MAX(created_at_utc) FROM bets WHERE ingestion_source = 'telegram'
    """).fetchone()

    if not last_message or (datetime.utcnow() - last_message) > timedelta(hours=24):
        logger.warning("No Telegram messages in 24 hours. Bot may be offline.")
```

### OpenAI API Health Check

```python
def check_openai_status():
    """
    Test API with simple completion
    """
    try:
        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "Test"}],
            max_tokens=5
        )
        return True
    except Exception as e:
        logger.error(f"OpenAI API unreachable: {e}")
        return False
```

---

**End of Document**
