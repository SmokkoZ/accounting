# Epic 1: Bet Ingestion Pipeline - Implementation Guide

**Epic Reference**: [epic-1-bet-ingestion.md](./epic-1-bet-ingestion.md)
**Status**: Ready for Development
**Estimated Effort**: 5-7 days (1 developer)

---

## Overview

This guide provides detailed, step-by-step implementation instructions for Epic 1. Follow this sequentially after completing Epic 0 (Foundation).

**Epic Goal**: Build automated bet ingestion from Telegram and manual uploads with GPT-4o extraction.

**Prerequisites**:
- ✅ Epic 0 complete (database, Telegram bot scaffold, Streamlit app)
- ✅ OpenAI API key obtained
- ✅ Development environment set up

---

## Code Structure

### Recommended File Organization

```
Final_App/
├── src/
│   ├── telegram/
│   │   ├── __init__.py
│   │   ├── bot.py                      # Main bot application (from Epic 0)
│   │   ├── handlers.py                 # Message handlers (NEW)
│   │   ├── config.py                   # Chat ID mappings (NEW)
│   │   └── utils.py                    # Helper functions (NEW)
│   ├── extraction/
│   │   ├── __init__.py
│   │   ├── ocr_service.py              # GPT-4o extraction (NEW)
│   │   ├── prompts.py                  # Prompt templates (NEW)
│   │   ├── confidence_scorer.py        # Confidence calculation (NEW)
│   │   └── models.py                   # Extraction result models (NEW)
│   ├── database/
│   │   ├── __init__.py
│   │   ├── models.py                   # SQLAlchemy models (from Epic 0)
│   │   ├── db.py                       # Database connection (from Epic 0)
│   │   └── repositories/
│   │       ├── __init__.py
│   │       └── bet_repository.py       # Bet CRUD operations (NEW)
│   ├── streamlit_app/
│   │   ├── __init__.py
│   │   ├── app.py                      # Main Streamlit app (from Epic 0)
│   │   ├── pages/
│   │   │   └── 1_incoming_bets.py      # Incoming bets page (NEW)
│   │   └── components/
│   │       └── manual_upload.py        # Manual upload component (NEW)
│   └── utils/
│       ├── __init__.py
│       ├── timestamp.py                # UTC timestamp utilities (from Epic 0)
│       └── file_storage.py             # Screenshot file operations (NEW)
├── data/
│   └── screenshots/                    # Screenshot storage (from Epic 0)
├── tests/
│   ├── unit/
│   │   ├── test_telegram_bot.py        # Bot tests (EXISTS per user)
│   │   ├── test_ocr_service.py         # Extraction tests (NEW)
│   │   └── test_confidence_scorer.py   # Scoring tests (NEW)
│   └── integration/
│       └── test_ingestion_flow.py      # End-to-end tests (NEW)
├── config/
│   └── telegram_chats.yaml             # Chat ID mappings (NEW)
├── .env                                # API keys (from Epic 0)
└── requirements.txt                    # Dependencies (from Epic 0)
```

---

## Story 1.1: Telegram Screenshot Ingestion

### Implementation Tasks

#### Task 1.1.1: Create Chat ID Mapping Configuration

**File**: `config/telegram_chats.yaml`

**Implementation**:
```yaml
# Telegram Chat ID to Associate/Bookmaker Mapping
# Format: chat_id: {associate_id, bookmaker_id}

chats:
  123456789:  # Replace with actual chat ID
    associate_id: 1  # Admin
    bookmaker_id: 1  # Bet365
    description: "Admin - Bet365"

  987654321:
    associate_id: 2  # Partner A
    bookmaker_id: 3  # Pinnacle
    description: "Partner A - Pinnacle"

# Multibook chats (for coverage proof in Epic 4)
multibook_chats:
  111222333:
    associate_id: 1
    description: "Admin - All Bookmakers"

  444555666:
    associate_id: 2
    description: "Partner A - All Bookmakers"
```

**Validation**:
- [ ] File exists in `config/` directory
- [ ] Valid YAML syntax
- [ ] At least 2 chat mappings configured
- [ ] Chat IDs match test Telegram chats

---

#### Task 1.1.2: Create Chat Config Loader

**File**: `src/telegram/config.py`

**Implementation**:
```python
"""Telegram chat configuration loader."""
import yaml
from pathlib import Path
from typing import Dict, Optional
from dataclasses import dataclass

@dataclass
class ChatMapping:
    """Telegram chat to associate/bookmaker mapping."""
    chat_id: int
    associate_id: int
    bookmaker_id: int
    description: str

class TelegramConfig:
    """Manages Telegram chat configuration."""

    def __init__(self, config_path: str = "config/telegram_chats.yaml"):
        self.config_path = Path(config_path)
        self._mappings: Dict[int, ChatMapping] = {}
        self._multibook_chats: Dict[int, int] = {}  # chat_id -> associate_id
        self._load_config()

    def _load_config(self):
        """Load chat mappings from YAML file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f)

        # Load bookmaker chats
        for chat_id, mapping in config.get('chats', {}).items():
            self._mappings[int(chat_id)] = ChatMapping(
                chat_id=int(chat_id),
                associate_id=mapping['associate_id'],
                bookmaker_id=mapping['bookmaker_id'],
                description=mapping.get('description', '')
            )

        # Load multibook chats
        for chat_id, mapping in config.get('multibook_chats', {}).items():
            self._multibook_chats[int(chat_id)] = mapping['associate_id']

    def get_mapping(self, chat_id: int) -> Optional[ChatMapping]:
        """Get associate/bookmaker mapping for chat ID."""
        return self._mappings.get(chat_id)

    def is_registered(self, chat_id: int) -> bool:
        """Check if chat ID is registered."""
        return chat_id in self._mappings

    def get_multibook_chat(self, associate_id: int) -> Optional[int]:
        """Get multibook chat ID for associate."""
        for chat_id, assoc_id in self._multibook_chats.items():
            if assoc_id == associate_id:
                return chat_id
        return None

# Singleton instance
telegram_config = TelegramConfig()
```

**Tests** (`tests/unit/test_telegram_config.py`):
```python
import pytest
from src.telegram.config import TelegramConfig

def test_load_config():
    config = TelegramConfig("config/telegram_chats.yaml")
    assert config.is_registered(123456789)

def test_get_mapping():
    config = TelegramConfig("config/telegram_chats.yaml")
    mapping = config.get_mapping(123456789)
    assert mapping.associate_id == 1
    assert mapping.bookmaker_id == 1

def test_unknown_chat():
    config = TelegramConfig("config/telegram_chats.yaml")
    assert not config.is_registered(999999999)
```

---

#### Task 1.1.3: Create Bet Repository (Database Operations)

**File**: `src/database/repositories/bet_repository.py`

**Implementation**:
```python
"""Repository for bet database operations."""
from datetime import datetime
from typing import Optional
from decimal import Decimal
from sqlalchemy.orm import Session
from src.database.models import Bet
from src.utils.timestamp import utc_now_iso

class BetRepository:
    """Handles bet database CRUD operations."""

    def __init__(self, session: Session):
        self.session = session

    def create_incoming_bet(
        self,
        associate_id: int,
        bookmaker_id: int,
        screenshot_path: str,
        ingestion_source: str,
        telegram_message_id: Optional[int] = None,
        operator_note: Optional[str] = None
    ) -> Bet:
        """Create a new bet with status='incoming'."""
        bet = Bet(
            status="incoming",
            ingestion_source=ingestion_source,
            telegram_message_id=telegram_message_id,
            associate_id=associate_id,
            bookmaker_id=bookmaker_id,
            screenshot_path=screenshot_path,
            operator_note=operator_note,
            created_at_utc=utc_now_iso(),
            # Extracted fields start as NULL (filled by OCR)
            canonical_event=None,
            market_code=None,
            period_scope=None,
            line_value=None,
            side=None,
            stake=None,
            odds=None,
            payout=None,
            currency=None,
            kickoff_time_utc=None,
            normalization_confidence=None,
            is_multi=0,
            is_supported=1  # Default to supported (OCR may change)
        )

        self.session.add(bet)
        self.session.commit()
        self.session.refresh(bet)
        return bet

    def update_extraction_results(
        self,
        bet_id: int,
        extraction_data: dict
    ) -> Bet:
        """Update bet with OCR extraction results."""
        bet = self.session.query(Bet).filter(Bet.bet_id == bet_id).one()

        # Update extracted fields
        bet.canonical_event = extraction_data.get('canonical_event')
        bet.market_code = extraction_data.get('market_code')
        bet.period_scope = extraction_data.get('period_scope')
        bet.line_value = extraction_data.get('line_value')
        bet.side = extraction_data.get('side')
        bet.stake = extraction_data.get('stake')
        bet.odds = extraction_data.get('odds')
        bet.payout = extraction_data.get('payout')
        bet.currency = extraction_data.get('currency')
        bet.kickoff_time_utc = extraction_data.get('kickoff_time_utc')
        bet.normalization_confidence = extraction_data.get('confidence')
        bet.is_multi = extraction_data.get('is_multi', 0)
        bet.is_supported = 0 if extraction_data.get('is_multi', 0) else 1
        bet.model_version_extraction = extraction_data.get('model_version')

        self.session.commit()
        self.session.refresh(bet)
        return bet
```

**Tests** (`tests/unit/test_bet_repository.py`):
```python
import pytest
from src.database.repositories.bet_repository import BetRepository
from src.database.db import get_test_session

def test_create_incoming_bet():
    session = get_test_session()
    repo = BetRepository(session)

    bet = repo.create_incoming_bet(
        associate_id=1,
        bookmaker_id=1,
        screenshot_path="data/screenshots/test.png",
        ingestion_source="telegram",
        telegram_message_id=12345
    )

    assert bet.bet_id is not None
    assert bet.status == "incoming"
    assert bet.ingestion_source == "telegram"
    assert bet.canonical_event is None  # Not yet extracted
```

---

#### Task 1.1.4: Create Screenshot Storage Utility

**File**: `src/utils/file_storage.py`

**Implementation**:
```python
"""File storage utilities for screenshots."""
from pathlib import Path
from datetime import datetime
import shutil
from typing import Tuple

SCREENSHOT_DIR = Path("data/screenshots")

def generate_screenshot_filename(
    associate_alias: str,
    bookmaker_name: str,
    source: str = "telegram"
) -> str:
    """Generate unique screenshot filename.

    Format: {timestamp}_{source}_{associate}_{bookmaker}.png
    Example: 20251030_143045_123_telegram_admin_bet365.png
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # milliseconds
    # Sanitize names (remove spaces, special chars)
    associate_clean = associate_alias.lower().replace(" ", "_")
    bookmaker_clean = bookmaker_name.lower().replace(" ", "_")

    return f"{timestamp}_{source}_{associate_clean}_{bookmaker_clean}.png"

def save_screenshot(
    file_bytes: bytes,
    associate_alias: str,
    bookmaker_name: str,
    source: str = "telegram"
) -> Tuple[str, str]:
    """Save screenshot to disk.

    Returns:
        Tuple of (absolute_path, relative_path)
    """
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    filename = generate_screenshot_filename(associate_alias, bookmaker_name, source)
    absolute_path = SCREENSHOT_DIR / filename
    relative_path = f"data/screenshots/{filename}"

    with open(absolute_path, 'wb') as f:
        f.write(file_bytes)

    return str(absolute_path), relative_path

def get_screenshot_path(relative_path: str) -> Path:
    """Convert relative path to absolute Path object."""
    return Path(relative_path)
```

**Tests** (`tests/unit/test_file_storage.py`):
```python
import pytest
from src.utils.file_storage import generate_screenshot_filename, save_screenshot

def test_generate_screenshot_filename():
    filename = generate_screenshot_filename("Admin", "Bet365", "telegram")
    assert "telegram" in filename
    assert "admin" in filename
    assert "bet365" in filename
    assert filename.endswith(".png")

def test_save_screenshot():
    test_bytes = b"fake_image_data"
    abs_path, rel_path = save_screenshot(test_bytes, "Admin", "Bet365")

    assert Path(abs_path).exists()
    assert rel_path.startswith("data/screenshots/")
```

---

#### Task 1.1.5: Implement Telegram Photo Handler

**File**: `src/telegram/handlers.py`

**Implementation**:
```python
"""Telegram message handlers."""
import logging
from telegram import Update
from telegram.ext import ContextTypes
from src.telegram.config import telegram_config
from src.database.db import get_session
from src.database.repositories.bet_repository import BetRepository
from src.utils.file_storage import save_screenshot
from src.extraction.ocr_service import extract_bet_data_async

logger = logging.getLogger(__name__)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo messages (bet screenshots)."""
    chat_id = update.effective_chat.id
    message_id = update.message.message_id

    # Check if chat is registered
    mapping = telegram_config.get_mapping(chat_id)
    if not mapping:
        await update.message.reply_text(
            "⚠️ Unregistered chat. Please contact admin to register this chat."
        )
        logger.warning(f"Photo from unregistered chat: {chat_id}")
        return

    try:
        # Reply immediately
        await update.message.reply_text("📸 Screenshot received. Processing...")

        # Download photo (highest resolution)
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        photo_bytes = await file.download_as_bytearray()

        # Get associate and bookmaker info from database
        session = get_session()
        # TODO: Query associate.display_alias and bookmaker.name
        # For now, use placeholder
        associate_alias = f"associate_{mapping.associate_id}"
        bookmaker_name = f"bookmaker_{mapping.bookmaker_id}"

        # Save screenshot
        abs_path, rel_path = save_screenshot(
            bytes(photo_bytes),
            associate_alias,
            bookmaker_name,
            source="telegram"
        )
        logger.info(f"Screenshot saved: {rel_path}")

        # Create bet record (status="incoming", extracted fields NULL)
        repo = BetRepository(session)
        bet = repo.create_incoming_bet(
            associate_id=mapping.associate_id,
            bookmaker_id=mapping.bookmaker_id,
            screenshot_path=rel_path,
            ingestion_source="telegram",
            telegram_message_id=message_id
        )
        logger.info(f"Bet created: bet_id={bet.bet_id}")

        # Trigger OCR extraction asynchronously (Story 1.2)
        # This will update the bet record with extracted fields
        await extract_bet_data_async(bet.bet_id, abs_path)

        await update.message.reply_text(
            f"✅ Bet #{bet.bet_id} added to review queue."
        )

    except Exception as e:
        logger.error(f"Error processing screenshot: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Error processing screenshot. Please try again or upload manually."
        )

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "🤖 Surebet Bot Ready\n\n"
        "Send a bet screenshot to this chat to ingest it automatically."
    )

async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    await update.message.reply_text(
        "📖 Commands:\n"
        "/start - Check bot status\n"
        "/help - Show this help\n\n"
        "📸 Screenshot Ingestion:\n"
        "- Send bet screenshot to this chat\n"
        "- Bot will extract bet data automatically\n"
        "- Check Incoming Bets page for review"
    )
```

---

#### Task 1.1.6: Update Bot Main File

**File**: `src/telegram/bot.py` (UPDATE from Epic 0)

**Implementation**:
```python
"""Telegram bot main application."""
import logging
import os
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from src.telegram.handlers import handle_photo, handle_start, handle_help

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def main():
    """Start the Telegram bot."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env")

    # Create application
    app = Application.builder().token(token).build()

    # Register handlers
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # Start polling
    logging.info("Starting Telegram bot (polling mode)...")
    app.run_polling(allowed_updates=["message"])

if __name__ == "__main__":
    main()
```

---

#### Task 1.1.7: Test Telegram Ingestion

**Manual Test Procedure**:
1. Start bot: `python src/telegram/bot.py`
2. Send test screenshot to registered Telegram chat
3. Verify bot replies: "Screenshot received. Processing..."
4. Check database: `SELECT * FROM bets WHERE status='incoming'`
5. Verify screenshot file exists: `ls data/screenshots/`
6. Check bet record has `telegram_message_id` populated

**Expected Result**: Bet created with `status="incoming"`, screenshot saved, OCR pending.

---

## Story 1.2: OCR + GPT-4o Extraction Pipeline

### Implementation Tasks

#### Task 1.2.1: Create Extraction Result Model

**File**: `src/extraction/models.py`

**Implementation**:
```python
"""Models for extraction results."""
from dataclasses import dataclass
from typing import Optional
from decimal import Decimal

@dataclass
class ExtractionResult:
    """Result of bet data extraction from screenshot."""

    # Success flag
    success: bool
    error_message: Optional[str] = None

    # Extracted fields
    canonical_event: Optional[str] = None
    market_code: Optional[str] = None
    period_scope: Optional[str] = None
    line_value: Optional[Decimal] = None
    side: Optional[str] = None
    stake: Optional[Decimal] = None
    odds: Optional[Decimal] = None
    payout: Optional[Decimal] = None
    currency: Optional[str] = None
    kickoff_time_utc: Optional[str] = None

    # Metadata
    confidence: float = 0.0  # 0.0 to 1.0
    is_multi: bool = False
    model_version: str = "gpt-4o-2024-11-20"
    raw_response: Optional[str] = None  # For debugging
```

---

#### Task 1.2.2: Create Extraction Prompt Template

**File**: `src/extraction/prompts.py`

**Implementation**:
```python
"""Prompt templates for GPT-4o extraction."""

EXTRACTION_PROMPT_V1 = """You are an expert at extracting structured betting data from bookmaker screenshots.

Analyze this bet slip screenshot and extract the following information in JSON format:

**Required Fields:**
1. **event_name**: The sporting event (teams or competitors). Example: "Manchester United vs Arsenal"
2. **sport**: Sport type. Example: "Soccer", "Tennis", "Basketball"
3. **market_type**: The betting market. Examples:
   - "Total Goals Over/Under"
   - "Asian Handicap"
   - "Match Winner"
   - "Both Teams To Score"
4. **period**: When the bet applies. Examples:
   - "Full Match" (entire game)
   - "First Half"
   - "Second Half"
5. **line_value**: The line or handicap (if applicable). Examples: "2.5", "+0.5", null
6. **bet_side**: Which side of the bet. Examples:
   - For Over/Under: "Over" or "Under"
   - For Yes/No: "Yes" or "No"
   - For Handicap: "Team A" or "Team B"
7. **stake**: Amount wagered (numeric only, no currency symbol)
8. **odds**: Betting odds in decimal format (e.g., 1.90, 2.05)
9. **payout**: Potential payout amount (numeric only)
10. **currency**: Currency code. Examples: "AUD", "GBP", "EUR", "USD"
11. **kickoff_time**: Match start time if visible (ISO8601 format preferred, or best guess)

**Detection:**
12. **is_accumulator**: Boolean - is this a multi-leg accumulator/parlay bet?

**Confidence:**
13. **extraction_confidence**: Your confidence in the extraction (0.0 to 1.0)
   - 1.0 = All fields clearly visible and extracted
   - 0.8 = Most fields clear, minor ambiguity
   - 0.6 = Some fields unclear or missing
   - 0.4 = Major uncertainty, many fields guessed
   - 0.2 = Very unclear, mostly unable to extract

**IMPORTANT RULES:**
- If a field is not visible or unclear, use null
- For decimal odds, convert if needed (e.g., fractional to decimal)
- For line_value, use numeric format: 2.5, not "2.5 goals"
- For bet_side on Over/Under markets: capitalize first letter only ("Over", not "OVER")
- For event_name, include both teams/competitors
- Be conservative with confidence: if unsure, lower the score

**Output Format:**
Return ONLY a valid JSON object with these exact keys (no additional text):

{
  "event_name": "...",
  "sport": "...",
  "market_type": "...",
  "period": "...",
  "line_value": ...,
  "bet_side": "...",
  "stake": ...,
  "odds": ...,
  "payout": ...,
  "currency": "...",
  "kickoff_time": "...",
  "is_accumulator": false,
  "extraction_confidence": 0.9
}
"""

def get_extraction_prompt() -> str:
    """Get the current extraction prompt."""
    return EXTRACTION_PROMPT_V1
```

---

#### Task 1.2.3: Create Confidence Scorer

**File**: `src/extraction/confidence_scorer.py`

**Implementation**:
```python
"""Confidence scoring logic for extractions."""
from typing import Dict, Any

def calculate_confidence(extraction_data: Dict[str, Any]) -> float:
    """Calculate extraction confidence based on field completeness.

    This supplements the model's self-reported confidence with
    objective field completion checks.

    Returns:
        float between 0.0 and 1.0
    """
    # Required fields for a complete extraction
    required_fields = [
        'event_name', 'market_type', 'period', 'bet_side',
        'stake', 'odds', 'payout', 'currency'
    ]

    # Count populated required fields
    populated = sum(
        1 for field in required_fields
        if extraction_data.get(field) is not None
    )

    # Field completion ratio
    field_completion = populated / len(required_fields)

    # Model's self-reported confidence
    model_confidence = extraction_data.get('extraction_confidence', 0.5)

    # Combined score: weighted average
    # 70% model confidence, 30% field completion
    combined_confidence = (0.7 * model_confidence) + (0.3 * field_completion)

    return round(combined_confidence, 2)

def classify_confidence(confidence: float) -> str:
    """Classify confidence level.

    Returns:
        "high", "medium", or "low"
    """
    if confidence >= 0.8:
        return "high"
    elif confidence >= 0.5:
        return "medium"
    else:
        return "low"
```

---

#### Task 1.2.4: Implement OCR Service

**File**: `src/extraction/ocr_service.py`

**Implementation**:
```python
"""GPT-4o vision extraction service."""
import base64
import json
import logging
import os
from pathlib import Path
from typing import Optional
from openai import OpenAI
from decimal import Decimal

from src.extraction.models import ExtractionResult
from src.extraction.prompts import get_extraction_prompt
from src.extraction.confidence_scorer import calculate_confidence
from src.database.db import get_session
from src.database.repositories.bet_repository import BetRepository

logger = logging.getLogger(__name__)

class OCRService:
    """Handles bet data extraction using GPT-4o vision."""

    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = "gpt-4o"  # Vision-capable model

    def encode_image(self, image_path: str) -> str:
        """Encode image to base64."""
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def extract_from_screenshot(self, screenshot_path: str) -> ExtractionResult:
        """Extract bet data from screenshot using GPT-4o vision.

        Args:
            screenshot_path: Absolute path to screenshot file

        Returns:
            ExtractionResult with extracted fields
        """
        try:
            # Encode image
            base64_image = self.encode_image(screenshot_path)

            # Call GPT-4o vision API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": get_extraction_prompt()
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=500,
                temperature=0.2  # Low temperature for consistent extraction
            )

            # Parse response
            content = response.choices[0].message.content
            logger.info(f"GPT-4o response: {content}")

            # Extract JSON from response (may have markdown formatting)
            json_str = content
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()

            data = json.loads(json_str)

            # Calculate confidence
            confidence = calculate_confidence(data)

            # Map to internal field names
            return ExtractionResult(
                success=True,
                canonical_event=data.get('event_name'),
                market_code=self._normalize_market_code(data.get('market_type')),
                period_scope=self._normalize_period(data.get('period')),
                line_value=self._to_decimal(data.get('line_value')),
                side=self._normalize_side(data.get('bet_side')),
                stake=self._to_decimal(data.get('stake')),
                odds=self._to_decimal(data.get('odds')),
                payout=self._to_decimal(data.get('payout')),
                currency=data.get('currency'),
                kickoff_time_utc=data.get('kickoff_time'),
                confidence=confidence,
                is_multi=data.get('is_accumulator', False),
                model_version=self.model,
                raw_response=content
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Raw response: {content}")
            return ExtractionResult(
                success=False,
                error_message=f"JSON parse error: {str(e)}"
            )

        except Exception as e:
            logger.error(f"Extraction failed: {e}", exc_info=True)
            return ExtractionResult(
                success=False,
                error_message=str(e)
            )

    def _normalize_market_code(self, market_type: Optional[str]) -> Optional[str]:
        """Normalize market type to internal code."""
        if not market_type:
            return None

        # Mapping from natural language to internal codes
        market_map = {
            "total goals over/under": "TOTAL_GOALS_OVER_UNDER",
            "asian handicap": "ASIAN_HANDICAP",
            "match winner": "MATCH_WINNER",
            "both teams to score": "BOTH_TEAMS_TO_SCORE",
            "over/under": "TOTAL_GOALS_OVER_UNDER",
        }

        return market_map.get(market_type.lower(), market_type.upper().replace(" ", "_"))

    def _normalize_period(self, period: Optional[str]) -> Optional[str]:
        """Normalize period to internal code."""
        if not period:
            return None

        period_map = {
            "full match": "FULL_MATCH",
            "first half": "FIRST_HALF",
            "second half": "SECOND_HALF",
            "1st half": "FIRST_HALF",
            "2nd half": "SECOND_HALF",
        }

        return period_map.get(period.lower(), period.upper().replace(" ", "_"))

    def _normalize_side(self, side: Optional[str]) -> Optional[str]:
        """Normalize bet side to internal code."""
        if not side:
            return None

        side_map = {
            "over": "OVER",
            "under": "UNDER",
            "yes": "YES",
            "no": "NO",
            "team a": "TEAM_A",
            "team b": "TEAM_B",
        }

        return side_map.get(side.lower(), side.upper())

    def _to_decimal(self, value) -> Optional[Decimal]:
        """Convert value to Decimal, handling None."""
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except:
            return None

# Async wrapper for use in Telegram handlers
async def extract_bet_data_async(bet_id: int, screenshot_path: str):
    """Extract bet data asynchronously (non-blocking for Telegram bot).

    Args:
        bet_id: ID of bet record to update
        screenshot_path: Absolute path to screenshot file
    """
    import asyncio

    def _extract():
        """Synchronous extraction (runs in thread pool)."""
        service = OCRService()
        result = service.extract_from_screenshot(screenshot_path)

        # Update bet record with results
        session = get_session()
        repo = BetRepository(session)

        if result.success:
            repo.update_extraction_results(bet_id, {
                'canonical_event': result.canonical_event,
                'market_code': result.market_code,
                'period_scope': result.period_scope,
                'line_value': result.line_value,
                'side': result.side,
                'stake': result.stake,
                'odds': result.odds,
                'payout': result.payout,
                'currency': result.currency,
                'kickoff_time_utc': result.kickoff_time_utc,
                'confidence': result.confidence,
                'is_multi': 1 if result.is_multi else 0,
                'model_version': result.model_version
            })
            logger.info(f"Bet {bet_id} extraction complete (confidence: {result.confidence})")
        else:
            logger.error(f"Bet {bet_id} extraction failed: {result.error_message}")

    # Run in thread pool to avoid blocking Telegram bot
    await asyncio.get_event_loop().run_in_executor(None, _extract)
```

---

#### Task 1.2.5: Add OpenAI Dependency

**File**: `requirements.txt` (UPDATE)

```txt
# ... existing dependencies ...
openai>=1.0.0
```

Install: `pip install openai`

---

#### Task 1.2.6: Test Extraction Service

**File**: `tests/unit/test_ocr_service.py`

**Implementation**:
```python
import pytest
from src.extraction.ocr_service import OCRService
from pathlib import Path

@pytest.fixture
def sample_screenshot():
    """Path to test screenshot."""
    return "tests/fixtures/sample_bet_screenshot.png"

def test_extract_from_screenshot(sample_screenshot):
    """Test full extraction pipeline."""
    if not Path(sample_screenshot).exists():
        pytest.skip("Sample screenshot not available")

    service = OCRService()
    result = service.extract_from_screenshot(sample_screenshot)

    assert result.success
    assert result.confidence > 0.0
    assert result.canonical_event is not None
    assert result.stake is not None

def test_normalize_market_code():
    service = OCRService()
    assert service._normalize_market_code("Total Goals Over/Under") == "TOTAL_GOALS_OVER_UNDER"
    assert service._normalize_market_code("asian handicap") == "ASIAN_HANDICAP"

def test_normalize_side():
    service = OCRService()
    assert service._normalize_side("Over") == "OVER"
    assert service._normalize_side("under") == "UNDER"
```

**Test Fixtures**:
- Create `tests/fixtures/` directory
- Add sample bet screenshot: `sample_bet_screenshot.png`

---

## Story 1.3: Manual Upload Panel (UI)

### Implementation Tasks

#### Task 1.3.1: Create Manual Upload Component

**File**: `src/streamlit_app/components/manual_upload.py`

**Implementation**:
```python
"""Manual bet upload component for Streamlit."""
import streamlit as st
from src.database.db import get_session
from src.database.repositories.bet_repository import BetRepository
from src.utils.file_storage import save_screenshot
from src.extraction.ocr_service import OCRService

def render_manual_upload_panel():
    """Render manual bet upload panel."""
    st.subheader("📤 Upload Manual Bet")
    st.caption("For screenshots from WhatsApp, camera photos, or other sources")

    with st.form("manual_upload_form"):
        # File upload
        uploaded_file = st.file_uploader(
            "Choose screenshot file",
            type=["png", "jpg", "jpeg"],
            help="Max file size: 10MB"
        )

        # Associate selection
        session = get_session()
        associates = session.execute(
            "SELECT associate_id, display_alias FROM associates ORDER BY display_alias"
        ).fetchall()

        associate_options = {f"{a.display_alias}": a.associate_id for a in associates}
        selected_associate_name = st.selectbox(
            "Associate",
            options=list(associate_options.keys()),
            help="Who placed this bet?"
        )
        selected_associate_id = associate_options[selected_associate_name]

        # Bookmaker selection (filtered by associate)
        bookmakers = session.execute(
            f"""
            SELECT bookmaker_id, name
            FROM bookmakers
            WHERE associate_id={selected_associate_id}
            ORDER BY name
            """
        ).fetchall()

        if not bookmakers:
            st.warning(f"No bookmakers found for {selected_associate_name}")
            bookmaker_options = {}
        else:
            bookmaker_options = {b.name: b.bookmaker_id for b in bookmakers}

        selected_bookmaker_name = st.selectbox(
            "Bookmaker",
            options=list(bookmaker_options.keys()) if bookmaker_options else ["(None available)"],
            help="Which bookmaker account?"
        )
        selected_bookmaker_id = bookmaker_options.get(selected_bookmaker_name)

        # Optional note
        note = st.text_area(
            "Note (optional)",
            placeholder="e.g., 'From WhatsApp group'",
            max_chars=500
        )

        # Submit button
        submitted = st.form_submit_button("Import & OCR", type="primary")

        if submitted:
            # Validation
            if not uploaded_file:
                st.error("Please select a file")
                return
            if not selected_bookmaker_id:
                st.error("Please select a valid bookmaker")
                return

            # Process upload
            try:
                with st.spinner("Processing screenshot..."):
                    # Save screenshot
                    file_bytes = uploaded_file.read()
                    abs_path, rel_path = save_screenshot(
                        file_bytes,
                        selected_associate_name,
                        selected_bookmaker_name,
                        source="manual"
                    )

                    # Create bet record
                    repo = BetRepository(session)
                    bet = repo.create_incoming_bet(
                        associate_id=selected_associate_id,
                        bookmaker_id=selected_bookmaker_id,
                        screenshot_path=rel_path,
                        ingestion_source="manual_upload",
                        operator_note=note if note else None
                    )

                    # Run OCR extraction
                    service = OCRService()
                    result = service.extract_from_screenshot(abs_path)

                    if result.success:
                        repo.update_extraction_results(bet.bet_id, {
                            'canonical_event': result.canonical_event,
                            'market_code': result.market_code,
                            'period_scope': result.period_scope,
                            'line_value': result.line_value,
                            'side': result.side,
                            'stake': result.stake,
                            'odds': result.odds,
                            'payout': result.payout,
                            'currency': result.currency,
                            'kickoff_time_utc': result.kickoff_time_utc,
                            'confidence': result.confidence,
                            'is_multi': 1 if result.is_multi else 0,
                            'model_version': result.model_version
                        })

                    st.success(f"✅ Bet #{bet.bet_id} added to review queue!")
                    st.info(f"Confidence: {result.confidence:.1%}")

            except Exception as e:
                st.error(f"Error: {str(e)}")
                st.exception(e)
```

---

#### Task 1.3.2: Create Incoming Bets Page

**File**: `src/streamlit_app/pages/1_incoming_bets.py`

**Implementation**:
```python
"""Incoming Bets page - displays bets awaiting review."""
import streamlit as st
from src.database.db import get_session
from src.streamlit_app.components.manual_upload import render_manual_upload_panel

st.set_page_config(page_title="Incoming Bets", layout="wide")

st.title("📥 Incoming Bets")

# Manual upload panel at top
with st.expander("📤 Upload Manual Bet", expanded=False):
    render_manual_upload_panel()

st.markdown("---")

# Counters
session = get_session()
counts = session.execute("""
    SELECT
        SUM(CASE WHEN status='incoming' THEN 1 ELSE 0 END) as waiting,
        SUM(CASE WHEN status='verified' AND date(verified_at_utc)=date('now') THEN 1 ELSE 0 END) as approved_today,
        SUM(CASE WHEN status='rejected' AND date(verified_at_utc)=date('now') THEN 1 ELSE 0 END) as rejected_today
    FROM bets
""").fetchone()

col1, col2, col3 = st.columns(3)
col1.metric("Waiting Review", counts.waiting or 0)
col2.metric("Approved Today", counts.approved_today or 0)
col3.metric("Rejected Today", counts.rejected_today or 0)

st.markdown("---")

# Incoming bets queue
st.subheader("📋 Bets Awaiting Review")

# Query incoming bets
incoming_bets = session.execute("""
    SELECT
        b.bet_id,
        b.screenshot_path,
        a.display_alias as associate,
        bk.name as bookmaker,
        b.ingestion_source,
        b.canonical_event,
        b.market_code,
        b.stake,
        b.odds,
        b.payout,
        b.currency,
        b.normalization_confidence,
        b.is_multi,
        b.operator_note,
        b.created_at_utc
    FROM bets b
    JOIN associates a ON b.associate_id = a.associate_id
    JOIN bookmakers bk ON b.bookmaker_id = bk.bookmaker_id
    WHERE b.status = 'incoming'
    ORDER BY b.created_at_utc DESC
""").fetchall()

if not incoming_bets:
    st.info("No bets awaiting review")
else:
    st.caption(f"Showing {len(incoming_bets)} bet(s)")

    for bet in incoming_bets:
        with st.container():
            col1, col2, col3 = st.columns([1, 3, 1])

            with col1:
                # Screenshot preview
                try:
                    st.image(bet.screenshot_path, width=150)
                except:
                    st.warning("Screenshot not found")

            with col2:
                # Bet details
                st.markdown(f"**Bet #{bet.bet_id}** - {bet.associate} @ {bet.bookmaker}")

                # Ingestion source icon
                source_icon = "📱" if bet.ingestion_source == "telegram" else "📤"
                st.caption(f"{source_icon} {bet.ingestion_source} • {bet.created_at_utc}")

                # Extracted data
                if bet.canonical_event:
                    st.write(f"**Event:** {bet.canonical_event}")
                    st.write(f"**Market:** {bet.market_code or '(not extracted)'}")
                    st.write(f"**Bet:** {bet.stake} {bet.currency} @ {bet.odds} = {bet.payout} {bet.currency}")
                else:
                    st.warning("⚠️ Extraction failed - manual entry required")

                # Flags
                if bet.is_multi:
                    st.error("🚫 Accumulator - Not Supported")
                if bet.operator_note:
                    st.info(f"📝 Note: {bet.operator_note}")

            with col3:
                # Confidence badge
                if bet.normalization_confidence:
                    if bet.normalization_confidence >= 0.8:
                        st.success(f"✅ High\n{bet.normalization_confidence:.0%}")
                    elif bet.normalization_confidence >= 0.5:
                        st.warning(f"⚠️ Medium\n{bet.normalization_confidence:.0%}")
                    else:
                        st.error(f"❌ Low\n{bet.normalization_confidence:.0%}")
                else:
                    st.error("❌ Failed")

                # Actions (Epic 2)
                st.button("Approve", key=f"approve_{bet.bet_id}", disabled=True)
                st.button("Reject", key=f"reject_{bet.bet_id}", disabled=True)

            st.markdown("---")
```

---

#### Task 1.3.3: Update Main Streamlit App

**File**: `src/streamlit_app/app.py` (UPDATE from Epic 0)

Ensure navigation includes new page:
```python
"""Main Streamlit application."""
import streamlit as st

st.set_page_config(
    page_title="Surebet Accounting System",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("🎯 Surebet Accounting System")
st.caption("Local-first arbitrage betting management")

st.markdown("""
### Pages
- **Incoming Bets**: Review and approve bet screenshots
- **Surebets** (Coming in Epic 3): View matched surebets
- **Settlement** (Coming in Epic 4): Settle completed events
- **Reconciliation** (Coming in Epic 5): View balances and health
- **Export** (Coming in Epic 6): Export ledger and statements
""")

# Instructions
st.info("""
**Getting Started:**
1. Send bet screenshots to Telegram bookmaker chats
2. Or upload manually via "Incoming Bets" page
3. Review and approve bets
""")
```

---

### Task 1.3.4: Test Manual Upload

**Manual Test Procedure**:
1. Start Streamlit app: `streamlit run src/streamlit_app/app.py`
2. Navigate to "Incoming Bets" page
3. Click "Upload Manual Bet"
4. Select test screenshot file
5. Choose associate and bookmaker
6. Add optional note
7. Click "Import & OCR"
8. Verify:
   - Success message appears
   - Bet appears in incoming queue below
   - Screenshot saved to `data/screenshots/`
   - Database record created

**Expected Result**: Manual upload produces identical bet record as Telegram ingestion.

---

## Integration Testing

### End-to-End Test

**File**: `tests/integration/test_ingestion_flow.py`

**Implementation**:
```python
"""Integration test for full ingestion flow."""
import pytest
from pathlib import Path
from src.database.db import get_test_session
from src.database.repositories.bet_repository import BetRepository
from src.extraction.ocr_service import OCRService
from src.utils.file_storage import save_screenshot

def test_full_ingestion_flow():
    """Test complete flow: upload -> OCR -> database."""
    # Setup
    session = get_test_session()
    repo = BetRepository(session)

    # Simulate screenshot upload
    test_screenshot = Path("tests/fixtures/sample_bet_screenshot.png")
    if not test_screenshot.exists():
        pytest.skip("Test screenshot not available")

    with open(test_screenshot, 'rb') as f:
        screenshot_bytes = f.read()

    # Save screenshot
    abs_path, rel_path = save_screenshot(
        screenshot_bytes,
        "TestAssociate",
        "TestBookmaker",
        "manual"
    )

    # Create bet record
    bet = repo.create_incoming_bet(
        associate_id=1,
        bookmaker_id=1,
        screenshot_path=rel_path,
        ingestion_source="manual_upload"
    )

    assert bet.bet_id is not None
    assert bet.status == "incoming"
    assert bet.canonical_event is None  # Not yet extracted

    # Run OCR extraction
    service = OCRService()
    result = service.extract_from_screenshot(abs_path)

    assert result.success
    assert result.confidence > 0.0

    # Update bet with extraction results
    repo.update_extraction_results(bet.bet_id, {
        'canonical_event': result.canonical_event,
        'market_code': result.market_code,
        'stake': result.stake,
        'odds': result.odds,
        'payout': result.payout,
        'currency': result.currency,
        'confidence': result.confidence,
        'is_multi': 1 if result.is_multi else 0,
        'model_version': result.model_version
    })

    # Verify bet updated
    session.refresh(bet)
    assert bet.canonical_event is not None
    assert bet.normalization_confidence > 0.0

    print(f"✅ Full ingestion flow test passed!")
    print(f"   Bet ID: {bet.bet_id}")
    print(f"   Confidence: {bet.normalization_confidence:.1%}")
    print(f"   Event: {bet.canonical_event}")
```

Run: `pytest tests/integration/test_ingestion_flow.py -v`

---

## Deployment Checklist

### Prerequisites Verification

- [ ] Epic 0 complete and tested
- [ ] Database schema exists (`bets` table)
- [ ] Telegram bot token in `.env`
- [ ] OpenAI API key in `.env`
- [ ] Python 3.12 environment active

### Configuration Setup

- [ ] `config/telegram_chats.yaml` created with real chat IDs
- [ ] At least 2 test Telegram chats registered
- [ ] Associates and bookmakers seeded in database

### Dependency Installation

```bash
pip install -r requirements.txt
```

Required new dependencies:
- `openai>=1.0.0`
- `pyyaml` (for config loading)

### File Structure Creation

```bash
mkdir -p src/extraction
mkdir -p src/telegram
mkdir -p src/streamlit_app/pages
mkdir -p src/streamlit_app/components
mkdir -p config
mkdir -p tests/fixtures
```

### Environment Variables

Add to `.env`:
```
OPENAI_API_KEY=sk-...your-key...
TELEGRAM_BOT_TOKEN=...from-epic-0...
```

---

## Testing Strategy

### Unit Tests (Run First)

```bash
# Test individual components
pytest tests/unit/test_telegram_config.py -v
pytest tests/unit/test_file_storage.py -v
pytest tests/unit/test_confidence_scorer.py -v
pytest tests/unit/test_ocr_service.py -v
```

### Integration Tests (Run After Unit Tests)

```bash
# Test full flow
pytest tests/integration/test_ingestion_flow.py -v
```

### Manual Tests (Run Last)

1. **Telegram Ingestion Test**:
   - Start bot: `python src/telegram/bot.py`
   - Send screenshot to registered chat
   - Verify bot replies and bet created

2. **Manual Upload Test**:
   - Start Streamlit: `streamlit run src/streamlit_app/app.py`
   - Navigate to "Incoming Bets"
   - Upload test screenshot
   - Verify success

3. **OCR Quality Test**:
   - Upload 10 diverse screenshots
   - Check confidence scores
   - Verify >80% have confidence ≥0.8

---

## Performance Benchmarks

### Expected Performance

| Metric | Target | Measurement |
|--------|--------|-------------|
| Telegram ingestion | <5s | Time from photo send to bot reply |
| OCR extraction | <10s | Time for GPT-4o API call |
| Manual upload | <15s | Time from upload to queue appearance |
| Screenshot save | <1s | File write time |

### Monitoring Points

Log these metrics during development:
- OCR API response time
- OCR token usage (cost tracking)
- Extraction confidence distribution
- Error rates by failure type

---

## Troubleshooting Guide

### Issue: Bot doesn't receive photos

**Symptoms**: Send screenshot to Telegram, no bot reply

**Checks**:
1. Bot running? `ps aux | grep bot.py`
2. Chat ID registered? Check `config/telegram_chats.yaml`
3. Bot has message read permission?
4. Check logs: `tail -f bot.log`

**Fix**: Verify chat ID with: `/start` command, bot should reply

---

### Issue: OCR extraction fails

**Symptoms**: Bet created but all fields NULL, confidence=0

**Checks**:
1. OpenAI API key valid? Test: `echo $OPENAI_API_KEY`
2. Rate limit hit? Check logs for "429" error
3. Screenshot readable? Open file manually
4. GPT-4o model available? Check OpenAI status page

**Fix**:
- Invalid key: Update `.env` with valid key
- Rate limit: Wait 1 minute, retry
- Bad screenshot: Use manual entry (Epic 2)

---

### Issue: Low confidence scores (<0.5)

**Symptoms**: Most extractions have confidence <0.5

**Checks**:
1. Screenshot quality (blurry, low res?)
2. Prompt tuning needed?
3. Bookmaker uses unusual format?

**Fix**:
- Improve screenshot quality (ask associates to zoom in)
- Iterate on prompt template in `prompts.py`
- Add bookmaker-specific prompt (future enhancement)

---

### Issue: Accumulators not detected

**Symptoms**: Multi-leg bets have `is_multi=0`

**Checks**:
1. Review extraction prompt
2. Check GPT-4o raw response in logs

**Fix**:
- Enhance prompt: "If you see multiple selections, set is_accumulator=true"
- Add post-processing check (count selections in extracted data)

---

## Next Steps

### After Epic 1 Completion

When all tasks above are complete:

1. **Run Definition of Done checklist** (from [epic-1-bet-ingestion.md](./epic-1-bet-ingestion.md))
2. **Demo to stakeholders**:
   - Show Telegram ingestion
   - Show manual upload
   - Show incoming bets queue
3. **Measure success metrics**:
   - OCR accuracy: Count high-confidence extractions
   - Processing time: Average time per bet
   - Error rate: Failed extractions
4. **Document lessons learned**:
   - What went well?
   - What needed more time?
   - Prompt engineering insights?
5. **Prepare for Epic 2**:
   - Epic 2 (Bet Review & Approval) depends on Epic 1 output
   - Ensure `status="incoming"` bets exist in database
   - Test data ready for review workflow

---

## Appendix: Code Snippets

### Quick Database Query (Check Incoming Bets)

```bash
sqlite3 data/surebet.db "SELECT bet_id, status, ingestion_source, normalization_confidence FROM bets WHERE status='incoming' ORDER BY created_at_utc DESC LIMIT 10;"
```

### Quick Screenshot Count

```bash
ls -1 data/screenshots/ | wc -l
```

### Quick OCR Test (Python REPL)

```python
from src.extraction.ocr_service import OCRService

service = OCRService()
result = service.extract_from_screenshot("data/screenshots/test.png")
print(f"Success: {result.success}")
print(f"Confidence: {result.confidence}")
print(f"Event: {result.canonical_event}")
```

---

**End of Implementation Guide**
