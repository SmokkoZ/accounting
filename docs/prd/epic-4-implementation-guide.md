# Epic 4: Coverage Proof & Settlement - Implementation Guide

**Epic Reference:** [Epic 4: Coverage Proof & Settlement](./epic-4-coverage-settlement.md)
**Status:** Ready for Implementation
**Estimated Duration:** 5-7 days
**Developer:** Backend + Frontend

---

## Overview

Epic 4 is the **financial heart** of the system. It implements:
1. **Coverage Proof Distribution** (Story 4.1): Send opposite-side screenshots via Telegram
2. **Settlement Interface** (Story 4.2): UI for grading surebets with manual outcome selection
3. **Equal-Split Preview** (Story 4.3): Show settlement math before committing
4. **Ledger Generation** (Story 4.4): Append-only financial ledger with frozen FX snapshots

**CRITICAL**: Epic 4 enforces **all 6 System Laws**:
- Law #1: Append-only ledger (no UPDATE/DELETE on ledger_entries)
- Law #2: Frozen FX snapshots (rates locked at settlement time)
- Law #3: Equal-split settlement (fair profit/loss distribution)
- Law #4: VOID participation (VOID bets still get seat in split)
- Law #5: Manual grading (operator decides outcomes explicitly)
- Law #6: No silent messaging (explicit operator action required)

**Architecture Principles**:
- Settlement is **irreversible** (append-only ledger)
- Equal-split math must use **Decimal precision** (no float)
- FX rates **frozen at settlement time** (stored in ledger_entries.fx_rate_snapshot)
- Admin gets **N seat** in split (staked if WON/LOST, non-staked if VOID)
- All-VOID surebets handled correctly (admin seat = 0)

---

## Prerequisites

Before starting Epic 4, ensure:
- [x] **Epic 0** complete: Database schema, FX utilities, Telegram bot
- [x] **Epic 1** complete: Bet ingestion pipeline
- [x] **Epic 2** complete: Bet approval workflow
- [x] **Epic 3** complete: Surebet matching with risk classification

**Database State Required**:
- At least 1 surebet in `status="matched"` with `risk_classification="SAFE"`
- FX rates in `fx_rates_daily` for all currencies in matched bets
- Telegram bot configured with multibook chat ID (Story 4.1)

---

## Task Breakdown

### Story 4.1: Coverage Proof Distribution

**Goal**: Send opposite-side screenshots to associates via Telegram multibook chat.

#### Task 4.1.1: Multibook Chat Configuration
**File**: `src/telegram/multibook_config.py`

```python
"""
Multibook chat configuration for coverage proof distribution.
"""
from dataclasses import dataclass
from typing import Optional
import yaml
from pathlib import Path

@dataclass
class MultibookChatConfig:
    """Configuration for multibook Telegram chat."""
    chat_id: int
    chat_name: str
    enabled: bool = True

class MultibookConfigLoader:
    """Load multibook chat configuration from YAML."""

    def __init__(self, config_path: str = "config/multibook_chat.yaml"):
        self.config_path = Path(config_path)
        self._config: Optional[MultibookChatConfig] = None

    def load(self) -> MultibookChatConfig:
        """Load configuration from YAML file."""
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Multibook chat config not found: {self.config_path}\n"
                f"Create config/multibook_chat.yaml with:\n"
                f"  chat_id: YOUR_CHAT_ID\n"
                f"  chat_name: 'Multibook Coverage Group'\n"
                f"  enabled: true"
            )

        with open(self.config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        self._config = MultibookChatConfig(
            chat_id=data['chat_id'],
            chat_name=data.get('chat_name', 'Multibook Chat'),
            enabled=data.get('enabled', True)
        )
        return self._config

    @property
    def config(self) -> MultibookChatConfig:
        """Get loaded config (loads if not already loaded)."""
        if self._config is None:
            return self.load()
        return self._config
```

**Config File**: `config/multibook_chat.yaml`

```yaml
# Multibook Telegram Chat Configuration
# This chat receives coverage proof screenshots for all associates

chat_id: 0  # REPLACE with actual Telegram chat ID
chat_name: "Multibook Coverage Group"
enabled: true

# How to find chat_id:
# 1. Add bot to group chat
# 2. Send a message in the group
# 3. Visit: https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
# 4. Look for "chat":{"id": -1234567890} in response
```

---

#### Task 4.1.2: Coverage Proof Service
**File**: `src/domain/coverage_proof_service.py`

```python
"""
Coverage proof distribution service.
Sends opposite-side screenshots to multibook Telegram chat.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import List, Tuple
import logging

from src.data.repositories.bet_repository import BetRepository
from src.data.repositories.surebet_repository import SurebetRepository
from src.data.models.bet import Bet
from src.data.models.surebet import Surebet
from src.telegram.multibook_config import MultibookConfigLoader
from src.utils.timestamp_utils import format_timestamp_utc

logger = logging.getLogger(__name__)

@dataclass
class CoverageProofMessage:
    """Data for coverage proof message."""
    surebet_id: int
    side_a_bet: Bet
    side_b_bet: Bet
    caption: str
    screenshot_paths: List[Path]

class CoverageProofService:
    """Distributes coverage proof screenshots via Telegram."""

    def __init__(
        self,
        bet_repo: BetRepository,
        surebet_repo: SurebetRepository,
        multibook_config: MultibookConfigLoader
    ):
        self.bet_repo = bet_repo
        self.surebet_repo = surebet_repo
        self.multibook_config = multibook_config

    def prepare_coverage_proof(self, surebet_id: int) -> CoverageProofMessage:
        """
        Prepare coverage proof message for a surebet.

        Args:
            surebet_id: Surebet to send proof for

        Returns:
            CoverageProofMessage with caption and screenshot paths

        Raises:
            ValueError: If surebet not found or not matched
        """
        # Load surebet with bets
        surebet = self.surebet_repo.get_by_id(surebet_id)
        if not surebet:
            raise ValueError(f"Surebet {surebet_id} not found")

        if surebet.status != "matched":
            raise ValueError(
                f"Surebet {surebet_id} status is '{surebet.status}', expected 'matched'"
            )

        bets = self.surebet_repo.get_bets_for_surebet(surebet_id)
        if len(bets) != 2:
            raise ValueError(f"Surebet {surebet_id} has {len(bets)} bets, expected 2")

        # Identify Side A and Side B
        side_a_bet = next((b for b in bets if b.surebet_side == "SIDE_A"), None)
        side_b_bet = next((b for b in bets if b.surebet_side == "SIDE_B"), None)

        if not side_a_bet or not side_b_bet:
            raise ValueError(f"Surebet {surebet_id} missing side assignment")

        # Build caption
        caption = self._build_caption(surebet, side_a_bet, side_b_bet)

        # Collect screenshot paths
        screenshot_paths = []
        if side_a_bet.screenshot_path:
            screenshot_paths.append(Path(side_a_bet.screenshot_path))
        if side_b_bet.screenshot_path:
            screenshot_paths.append(Path(side_b_bet.screenshot_path))

        return CoverageProofMessage(
            surebet_id=surebet_id,
            side_a_bet=side_a_bet,
            side_b_bet=side_b_bet,
            caption=caption,
            screenshot_paths=screenshot_paths
        )

    def _build_caption(self, surebet: Surebet, side_a: Bet, side_b: Bet) -> str:
        """Build human-readable caption for coverage proof."""
        event_name = surebet.canonical_event or "Unknown Event"
        market = surebet.market_code or "Unknown Market"

        caption_lines = [
            f"ðŸ“‹ Coverage Proof - Surebet #{surebet.surebet_id}",
            f"",
            f"Event: {event_name}",
            f"Market: {market}",
            f"",
            f"Side A ({side_a.bet_side}):",
            f"  {side_a.associate_alias} @ {side_a.bookmaker_name}",
            f"  Stake: {side_a.stake} {side_a.native_currency} @ {side_a.odds}",
            f"",
            f"Side B ({side_b.bet_side}):",
            f"  {side_b.associate_alias} @ {side_b.bookmaker_name}",
            f"  Stake: {side_b.stake} {side_b.native_currency} @ {side_b.odds}",
            f"",
            f"Risk: {surebet.risk_classification} (ROI: {surebet.roi:.2%})",
            f"Worst-case profit: â‚¬{surebet.worst_case_profit_eur}",
        ]

        return "\n".join(caption_lines)

    def get_multibook_chat_id(self) -> int:
        """Get configured multibook chat ID."""
        config = self.multibook_config.config
        if not config.enabled:
            raise RuntimeError("Multibook chat is disabled in config")
        return config.chat_id
```

---

#### Task 4.1.3: Telegram Coverage Proof Handler
**File**: `src/telegram/handlers/coverage_proof_handler.py`

```python
"""
Telegram handler for sending coverage proof to multibook chat.
"""
import logging
from pathlib import Path
from typing import List
from telegram import Bot, InputMediaPhoto
from telegram.error import TelegramError

from src.domain.coverage_proof_service import CoverageProofService, CoverageProofMessage
from src.data.repositories.multibook_message_log_repository import MultibookMessageLogRepository
from src.utils.timestamp_utils import format_timestamp_utc

logger = logging.getLogger(__name__)

class CoverageProofHandler:
    """Handles sending coverage proof screenshots via Telegram."""

    def __init__(
        self,
        bot: Bot,
        coverage_proof_service: CoverageProofService,
        message_log_repo: MultibookMessageLogRepository
    ):
        self.bot = bot
        self.coverage_proof_service = coverage_proof_service
        self.message_log_repo = message_log_repo

    async def send_coverage_proof(self, surebet_id: int) -> bool:
        """
        Send coverage proof for a surebet to multibook chat.

        Args:
            surebet_id: Surebet to send proof for

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            # Prepare message
            proof = self.coverage_proof_service.prepare_coverage_proof(surebet_id)
            chat_id = self.coverage_proof_service.get_multibook_chat_id()

            # Send media group (both screenshots)
            media_group = self._build_media_group(proof)

            if not media_group:
                logger.warning(f"No screenshots for surebet {surebet_id}, sending text only")
                message = await self.bot.send_message(
                    chat_id=chat_id,
                    text=proof.caption,
                    parse_mode="HTML"
                )
                message_ids = [message.message_id]
            else:
                messages = await self.bot.send_media_group(
                    chat_id=chat_id,
                    media=media_group
                )
                message_ids = [msg.message_id for msg in messages]

            # Log to database
            self._log_message(proof, chat_id, message_ids)

            logger.info(f"Sent coverage proof for surebet {surebet_id} to chat {chat_id}")
            return True

        except TelegramError as e:
            logger.error(f"Failed to send coverage proof for surebet {surebet_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending coverage proof: {e}", exc_info=True)
            return False

    def _build_media_group(self, proof: CoverageProofMessage) -> List[InputMediaPhoto]:
        """Build media group from screenshot paths."""
        media_group = []

        for i, screenshot_path in enumerate(proof.screenshot_paths):
            if not screenshot_path.exists():
                logger.warning(f"Screenshot not found: {screenshot_path}")
                continue

            # First photo gets caption
            caption = proof.caption if i == 0 else None

            with open(screenshot_path, 'rb') as photo_file:
                media_group.append(
                    InputMediaPhoto(
                        media=photo_file.read(),
                        caption=caption,
                        parse_mode="HTML"
                    )
                )

        return media_group

    def _log_message(
        self,
        proof: CoverageProofMessage,
        chat_id: int,
        message_ids: List[int]
    ):
        """Log sent message to multibook_message_log table."""
        self.message_log_repo.create(
            surebet_id=proof.surebet_id,
            telegram_chat_id=chat_id,
            telegram_message_ids=",".join(str(mid) for mid in message_ids),
            message_type="coverage_proof",
            sent_at_utc=format_timestamp_utc(),
            sent_by="system"
        )
```

---

#### Task 4.1.4: Multibook Message Log Repository
**File**: `src/data/repositories/multibook_message_log_repository.py`

```python
"""
Repository for multibook_message_log table.
"""
import sqlite3
from typing import Optional, List
from dataclasses import dataclass

@dataclass
class MultibookMessageLog:
    """Represents a multibook message log entry."""
    log_id: int
    surebet_id: int
    telegram_chat_id: int
    telegram_message_ids: str
    message_type: str
    sent_at_utc: str
    sent_by: str

class MultibookMessageLogRepository:
    """Repository for logging multibook Telegram messages."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def create(
        self,
        surebet_id: int,
        telegram_chat_id: int,
        telegram_message_ids: str,
        message_type: str,
        sent_at_utc: str,
        sent_by: str
    ) -> int:
        """
        Create new multibook message log entry.

        Returns:
            log_id of created entry
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO multibook_message_log (
                surebet_id, telegram_chat_id, telegram_message_ids,
                message_type, sent_at_utc, sent_by
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            surebet_id, telegram_chat_id, telegram_message_ids,
            message_type, sent_at_utc, sent_by
        ))

        log_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return log_id

    def get_by_surebet(self, surebet_id: int) -> List[MultibookMessageLog]:
        """Get all message logs for a surebet."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM multibook_message_log
            WHERE surebet_id = ?
            ORDER BY sent_at_utc DESC
        """, (surebet_id,))

        rows = cursor.fetchall()
        conn.close()

        return [MultibookMessageLog(**dict(row)) for row in rows]
```

---

### Story 4.2: Settlement Interface

**Goal**: Build UI for operator to grade surebets with manual outcome selection.

#### Task 4.2.1: Settlement Page Component
**File**: `src/streamlit_app/pages/04_Settlement.py`

```python
"""
Settlement page for grading matched surebets.
"""
import streamlit as st
from datetime import datetime
from typing import Optional

from src.data.database import get_db_connection
from src.data.repositories.surebet_repository import SurebetRepository
from src.data.repositories.bet_repository import BetRepository
from src.streamlit_app.components.settlement.settlement_queue import render_settlement_queue
from src.streamlit_app.components.settlement.settlement_form import render_settlement_form
from src.domain.settlement_service import SettlementService

st.set_page_config(
    page_title="Settlement - Surebet Accounting",
    page_icon="ðŸ’°",
    layout="wide"
)

st.title("ðŸ’° Settlement")
st.caption("Grade matched surebets and generate ledger entries")

# Initialize repositories and services
db_path = "data/surebet.db"
surebet_repo = SurebetRepository(db_path)
bet_repo = BetRepository(db_path)
settlement_service = SettlementService(surebet_repo, bet_repo)

# Session state for selected surebet
if 'selected_surebet_id' not in st.session_state:
    st.session_state.selected_surebet_id = None

# Layout: Queue (left) + Settlement Form (right)
col_queue, col_form = st.columns([1, 2])

with col_queue:
    st.subheader("Settlement Queue")
    st.caption("Matched surebets sorted by kickoff time")

    # Render queue and get selected surebet
    selected_id = render_settlement_queue(surebet_repo)

    if selected_id:
        st.session_state.selected_surebet_id = selected_id

with col_form:
    if st.session_state.selected_surebet_id:
        st.subheader(f"Settle Surebet #{st.session_state.selected_surebet_id}")

        # Render settlement form
        render_settlement_form(
            surebet_id=st.session_state.selected_surebet_id,
            settlement_service=settlement_service,
            surebet_repo=surebet_repo,
            bet_repo=bet_repo
        )
    else:
        st.info("ðŸ‘ˆ Select a surebet from the queue to begin settlement")
```

---

#### Task 4.2.2: Settlement Queue Component
**File**: `src/streamlit_app/components/settlement/settlement_queue.py`

```python
"""
Settlement queue component - shows matched surebets sorted by kickoff.
"""
import streamlit as st
from typing import Optional
from datetime import datetime

from src.data.repositories.surebet_repository import SurebetRepository

def render_settlement_queue(surebet_repo: SurebetRepository) -> Optional[int]:
    """
    Render settlement queue and return selected surebet ID.

    Returns:
        Selected surebet_id or None
    """
    # Load matched surebets sorted by earliest kickoff
    surebets = surebet_repo.get_all_matched_sorted_by_kickoff()

    if not surebets:
        st.warning("No matched surebets ready for settlement")
        return None

    st.caption(f"**{len(surebets)} surebets** ready for settlement")

    # Render as selectable list
    selected_id = None

    for sb in surebets:
        # Parse kickoff time
        kickoff_str = sb.kickoff_time_utc or "Unknown"
        if sb.kickoff_time_utc:
            try:
                kickoff_dt = datetime.fromisoformat(sb.kickoff_time_utc.replace('Z', '+00:00'))
                kickoff_display = kickoff_dt.strftime("%Y-%m-%d %H:%M UTC")
            except:
                kickoff_display = kickoff_str
        else:
            kickoff_display = "No kickoff time"

        # Risk badge
        risk_badge = {
            "SAFE": "âœ…",
            "LOW_ROI": "ðŸŸ¡",
            "UNSAFE": "âŒ"
        }.get(sb.risk_classification, "â“")

        # Render selectable card
        with st.container():
            col1, col2 = st.columns([3, 1])

            with col1:
                st.markdown(f"""
                **Surebet #{sb.surebet_id}** {risk_badge}
                {sb.canonical_event or 'Unknown Event'}
                {sb.market_code} - Kickoff: {kickoff_display}
                """)

            with col2:
                if st.button("Select", key=f"select_sb_{sb.surebet_id}"):
                    selected_id = sb.surebet_id

        st.divider()

    return selected_id
```

---

#### Task 4.2.3: Settlement Form Component
**File**: `src/streamlit_app/components/settlement/settlement_form.py`

```python
"""
Settlement form component - outcome selection and preview.
"""
import streamlit as st
from typing import Dict, Optional
from decimal import Decimal

from src.data.repositories.surebet_repository import SurebetRepository
from src.data.repositories.bet_repository import BetRepository
from src.domain.settlement_service import SettlementService
from src.domain.models import BetOutcome

def render_settlement_form(
    surebet_id: int,
    settlement_service: SettlementService,
    surebet_repo: SurebetRepository,
    bet_repo: BetRepository
):
    """Render settlement form for a surebet."""

    # Load surebet and bets
    surebet = surebet_repo.get_by_id(surebet_id)
    bets = surebet_repo.get_bets_for_surebet(surebet_id)

    if not surebet or len(bets) != 2:
        st.error("Invalid surebet or missing bets")
        return

    # Identify Side A and Side B
    side_a_bet = next((b for b in bets if b.surebet_side == "SIDE_A"), None)
    side_b_bet = next((b for b in bets if b.surebet_side == "SIDE_B"), None)

    # Display surebet info
    st.markdown(f"""
    **Event:** {surebet.canonical_event}
    **Market:** {surebet.market_code}
    **Risk:** {surebet.risk_classification} (ROI: {surebet.roi:.2%})
    """)

    st.divider()

    # Settlement inputs
    st.subheader("Outcome Selection")

    # Base outcome (determines surebet result)
    base_outcome = st.radio(
        "Base Outcome (applies to entire surebet)",
        options=["Side A WON", "Side B WON"],
        help="Select which side won the bet. Individual overrides available below."
    )

    # Derive base outcomes for each bet
    if base_outcome == "Side A WON":
        base_side_a = BetOutcome.WON
        base_side_b = BetOutcome.LOST
    else:
        base_side_a = BetOutcome.LOST
        base_side_b = BetOutcome.WON

    st.divider()

    # Individual bet overrides
    st.subheader("Individual Bet Overrides (Optional)")
    st.caption("Override individual bets if needed (e.g., bookmaker voided)")

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown(f"**Side A: {side_a_bet.bet_side}**")
        st.caption(f"{side_a_bet.associate_alias} @ {side_a_bet.bookmaker_name}")
        st.caption(f"Stake: {side_a_bet.stake} {side_a_bet.native_currency} @ {side_a_bet.odds}")

        side_a_override = st.selectbox(
            "Side A Outcome",
            options=["(Use base)", "WON", "LOST", "VOID"],
            key="side_a_override"
        )

        if side_a_override == "(Use base)":
            final_side_a = base_side_a
        else:
            final_side_a = BetOutcome[side_a_override]

    with col_b:
        st.markdown(f"**Side B: {side_b_bet.bet_side}**")
        st.caption(f"{side_b_bet.associate_alias} @ {side_b_bet.bookmaker_name}")
        st.caption(f"Stake: {side_b_bet.stake} {side_b_bet.native_currency} @ {side_b_bet.odds}")

        side_b_override = st.selectbox(
            "Side B Outcome",
            options=["(Use base)", "WON", "LOST", "VOID"],
            key="side_b_override"
        )

        if side_b_override == "(Use base)":
            final_side_b = base_side_b
        else:
            final_side_b = BetOutcome[side_b_override]

    st.divider()

    # Preview settlement
    st.subheader("Settlement Preview")

    try:
        preview = settlement_service.preview_settlement(
            surebet_id=surebet_id,
            outcomes={
                side_a_bet.bet_id: final_side_a,
                side_b_bet.bet_id: final_side_b
            }
        )

        # Display preview
        _render_settlement_preview(preview)

        # Confirm button
        st.divider()

        if st.button("âœ… Confirm Settlement", type="primary", width="stretch"):
            # Execute settlement
            settlement_service.execute_settlement(
                surebet_id=surebet_id,
                outcomes={
                    side_a_bet.bet_id: final_side_a,
                    side_b_bet.bet_id: final_side_b
                }
            )

            st.success(f"âœ… Surebet #{surebet_id} settled successfully!")
            st.balloons()

            # Clear selection
            st.session_state.selected_surebet_id = None
            st.rerun()

    except Exception as e:
        st.error(f"Settlement preview failed: {e}")

def _render_settlement_preview(preview: Dict):
    """Render settlement preview."""
    st.markdown("### Equal-Split Calculation")

    # Per-bet net gains
    st.markdown("**Per-Bet Net Gains:**")
    for bet_id, net_gain_eur in preview['per_bet_net_gains'].items():
        outcome = preview['per_bet_outcomes'][bet_id]
        st.markdown(f"- Bet #{bet_id} ({outcome.value}): â‚¬{net_gain_eur}")

    # Surebet profit
    st.markdown(f"**Surebet Profit:** â‚¬{preview['surebet_profit_eur']}")

    # Participants
    st.markdown(f"**Participants (N={preview['num_participants']}):**")
    for participant in preview['participants']:
        st.markdown(f"- {participant['associate_alias']} ({participant['seat_type']} seat)")

    # Per-surebet shares
    st.markdown(f"**Per-Surebet Share:** â‚¬{preview['per_surebet_share_eur']}")

    # Ledger entries preview
    st.markdown("### Ledger Entries to Create:")

    for entry in preview['ledger_entries']:
        st.markdown(f"""
        - **{entry['associate_alias']}** @ {entry['bookmaker_name']}
          Principal: â‚¬{entry['principal_returned_eur']}
          Share: â‚¬{entry['per_surebet_share_eur']}
          Total: â‚¬{entry['amount_eur']} (FX: {entry['fx_rate_snapshot']})
        """)
```

---

### Story 4.3: Equal-Split Preview & Story 4.4: Ledger Generation

#### Task 4.3.1: Settlement Service (Core Logic)
**File**: `src/domain/settlement_service.py`

```python
"""
Settlement service - handles equal-split calculation and ledger generation.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional

from src.data.repositories.surebet_repository import SurebetRepository
from src.data.repositories.bet_repository import BetRepository
from src.data.repositories.ledger_repository import LedgerEntryRepository
from src.utils.fx_utils import get_fx_rate, convert_to_eur
from src.utils.timestamp_utils import format_timestamp_utc

class BetOutcome(Enum):
    """Possible bet outcomes."""
    WON = "WON"
    LOST = "LOST"
    VOID = "VOID"

@dataclass
class Participant:
    """Participant in equal-split."""
    bet_id: int
    associate_id: int
    associate_alias: str
    bookmaker_id: int
    bookmaker_name: str
    seat_type: str  # "staked" or "non_staked"
    outcome: BetOutcome

@dataclass
class SettlementPreview:
    """Preview of settlement calculation."""
    surebet_id: int
    per_bet_outcomes: Dict[int, BetOutcome]
    per_bet_net_gains: Dict[int, Decimal]
    surebet_profit_eur: Decimal
    num_participants: int
    participants: List[Dict]
    per_surebet_share_eur: Decimal
    ledger_entries: List[Dict]

class SettlementService:
    """Service for settling surebets with equal-split logic."""

    def __init__(
        self,
        surebet_repo: SurebetRepository,
        bet_repo: BetRepository,
        ledger_repo: Optional[LedgerEntryRepository] = None
    ):
        self.surebet_repo = surebet_repo
        self.bet_repo = bet_repo
        self.ledger_repo = ledger_repo

    def preview_settlement(
        self,
        surebet_id: int,
        outcomes: Dict[int, BetOutcome]
    ) -> SettlementPreview:
        """
        Preview settlement calculation without committing to ledger.

        Args:
            surebet_id: Surebet to settle
            outcomes: Mapping of bet_id -> BetOutcome

        Returns:
            SettlementPreview with all calculated values
        """
        # Load surebet and bets
        surebet = self.surebet_repo.get_by_id(surebet_id)
        bets = self.surebet_repo.get_bets_for_surebet(surebet_id)

        if not surebet or len(bets) != 2:
            raise ValueError(f"Invalid surebet {surebet_id}")

        # Calculate per-bet net gains
        per_bet_net_gains = {}
        for bet in bets:
            outcome = outcomes[bet.bet_id]
            net_gain_eur = self._calculate_net_gain(bet, outcome)
            per_bet_net_gains[bet.bet_id] = net_gain_eur

        # Calculate surebet profit
        surebet_profit_eur = sum(per_bet_net_gains.values())

        # Determine participants
        participants = self._determine_participants(bets, outcomes)
        num_participants = len(participants)

        # Calculate per-surebet share
        if num_participants == 0:
            # All-VOID edge case: admin seat = 0
            per_surebet_share_eur = Decimal("0.00")
        else:
            per_surebet_share_eur = (surebet_profit_eur / num_participants).quantize(Decimal("0.01"))

        # Build ledger entry previews
        ledger_entries = []
        for bet in bets:
            outcome = outcomes[bet.bet_id]
            participant = next((p for p in participants if p.bet_id == bet.bet_id), None)

            # Principal returned
            if outcome == BetOutcome.WON:
                principal_returned_eur = convert_to_eur(
                    bet.stake,
                    bet.native_currency,
                    get_fx_rate(bet.native_currency, datetime.utcnow().date())
                )
            else:
                principal_returned_eur = Decimal("0.00")

            # Per-surebet share
            share_eur = per_surebet_share_eur if participant and participant.seat_type == "staked" else Decimal("0.00")

            # Total amount
            amount_eur = principal_returned_eur + share_eur

            # FX snapshot
            fx_rate_snapshot = get_fx_rate(bet.native_currency, datetime.utcnow().date())

            ledger_entries.append({
                'bet_id': bet.bet_id,
                'associate_id': bet.associate_id,
                'associate_alias': bet.associate_alias,
                'bookmaker_id': bet.bookmaker_id,
                'bookmaker_name': bet.bookmaker_name,
                'outcome': outcome.value,
                'principal_returned_eur': str(principal_returned_eur),
                'per_surebet_share_eur': str(share_eur),
                'amount_eur': str(amount_eur),
                'fx_rate_snapshot': str(fx_rate_snapshot),
                'native_currency': bet.native_currency
            })

        return SettlementPreview(
            surebet_id=surebet_id,
            per_bet_outcomes=outcomes,
            per_bet_net_gains=per_bet_net_gains,
            surebet_profit_eur=surebet_profit_eur,
            num_participants=num_participants,
            participants=[{
                'bet_id': p.bet_id,
                'associate_alias': p.associate_alias,
                'seat_type': p.seat_type,
                'outcome': p.outcome.value
            } for p in participants],
            per_surebet_share_eur=per_surebet_share_eur,
            ledger_entries=ledger_entries
        )

    def execute_settlement(
        self,
        surebet_id: int,
        outcomes: Dict[int, BetOutcome]
    ):
        """
        Execute settlement and write to append-only ledger.

        CRITICAL: This is irreversible. Ledger entries cannot be edited or deleted.

        Args:
            surebet_id: Surebet to settle
            outcomes: Mapping of bet_id -> BetOutcome
        """
        if not self.ledger_repo:
            raise RuntimeError("LedgerEntryRepository required for execute_settlement")

        # Generate preview
        preview = self.preview_settlement(surebet_id, outcomes)

        # Generate settlement batch ID
        settlement_batch_id = str(uuid.uuid4())
        timestamp_utc = format_timestamp_utc()

        # Write ledger entries (transactional)
        for entry_data in preview.ledger_entries:
            self.ledger_repo.create_bet_result(
                bet_id=entry_data['bet_id'],
                associate_id=entry_data['associate_id'],
                bookmaker_id=entry_data['bookmaker_id'],
                surebet_id=surebet_id,
                settlement_batch_id=settlement_batch_id,
                settlement_state=entry_data['outcome'],
                amount_native=None,  # Not stored (derived from principal + share)
                native_currency=entry_data['native_currency'],
                fx_rate_snapshot=Decimal(entry_data['fx_rate_snapshot']),
                amount_eur=Decimal(entry_data['amount_eur']),
                principal_returned_eur=Decimal(entry_data['principal_returned_eur']),
                per_surebet_share_eur=Decimal(entry_data['per_surebet_share_eur']),
                created_at_utc=timestamp_utc,
                created_by="local_user",
                note=f"Settlement: {entry_data['outcome']}"
            )

        # Update surebet status
        self.surebet_repo.update_status(surebet_id, "settled")

        # Update bet statuses
        for bet_id in outcomes.keys():
            outcome = outcomes[bet_id]
            self.bet_repo.update_status_and_outcome(bet_id, "settled", outcome.value)

    def _calculate_net_gain(self, bet, outcome: BetOutcome) -> Decimal:
        """Calculate net gain for a bet in EUR."""
        if outcome == BetOutcome.WON:
            payout_native = bet.stake * bet.odds
            net_gain_native = payout_native - bet.stake
        elif outcome == BetOutcome.LOST:
            net_gain_native = -bet.stake
        else:  # VOID
            net_gain_native = Decimal("0.00")

        # Convert to EUR
        fx_rate = get_fx_rate(bet.native_currency, datetime.utcnow().date())
        net_gain_eur = convert_to_eur(net_gain_native, bet.native_currency, fx_rate)

        return net_gain_eur

    def _determine_participants(
        self,
        bets: List,
        outcomes: Dict[int, BetOutcome]
    ) -> List[Participant]:
        """
        Determine participants and seat types.

        - WON/LOST bets get staked seat
        - VOID bets get non-staked seat (still participate!)
        """
        participants = []

        for bet in bets:
            outcome = outcomes[bet.bet_id]

            if outcome == BetOutcome.VOID:
                seat_type = "non_staked"
            else:
                seat_type = "staked"

            participants.append(Participant(
                bet_id=bet.bet_id,
                associate_id=bet.associate_id,
                associate_alias=bet.associate_alias,
                bookmaker_id=bet.bookmaker_id,
                bookmaker_name=bet.bookmaker_name,
                seat_type=seat_type,
                outcome=outcome
            ))

        return participants
```

---

#### Task 4.4.1: Ledger Entry Repository (Append-Only)
**File**: `src/data/repositories/ledger_repository.py`

```python
"""
Repository for ledger_entries table (append-only).
"""
import sqlite3
from decimal import Decimal
from typing import Optional, List
from dataclasses import dataclass

@dataclass
class LedgerEntry:
    """Represents a ledger entry."""
    entry_id: int
    entry_type: str
    associate_id: int
    bookmaker_id: Optional[int]
    surebet_id: Optional[int]
    bet_id: Optional[int]
    settlement_batch_id: Optional[str]
    settlement_state: Optional[str]
    amount_native: Optional[Decimal]
    native_currency: Optional[str]
    fx_rate_snapshot: Decimal
    amount_eur: Decimal
    principal_returned_eur: Optional[Decimal]
    per_surebet_share_eur: Optional[Decimal]
    created_at_utc: str
    created_by: str
    note: Optional[str]

class LedgerEntryRepository:
    """Repository for append-only ledger_entries table."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def create_bet_result(
        self,
        bet_id: int,
        associate_id: int,
        bookmaker_id: int,
        surebet_id: int,
        settlement_batch_id: str,
        settlement_state: str,
        amount_native: Optional[Decimal],
        native_currency: str,
        fx_rate_snapshot: Decimal,
        amount_eur: Decimal,
        principal_returned_eur: Decimal,
        per_surebet_share_eur: Decimal,
        created_at_utc: str,
        created_by: str,
        note: Optional[str] = None
    ) -> int:
        """
        Create BET_RESULT ledger entry.

        CRITICAL: This is append-only. No UPDATE or DELETE allowed.

        Returns:
            entry_id of created entry
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO ledger_entries (
                entry_type, associate_id, bookmaker_id, surebet_id, bet_id,
                settlement_batch_id, settlement_state,
                amount_native, native_currency,
                fx_rate_snapshot, amount_eur,
                principal_returned_eur, per_surebet_share_eur,
                created_at_utc, created_by, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "BET_RESULT",
            associate_id,
            bookmaker_id,
            surebet_id,
            bet_id,
            settlement_batch_id,
            settlement_state,
            str(amount_native) if amount_native else None,
            native_currency,
            str(fx_rate_snapshot),
            str(amount_eur),
            str(principal_returned_eur),
            str(per_surebet_share_eur),
            created_at_utc,
            created_by,
            note
        ))

        entry_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return entry_id

    def get_all(self) -> List[LedgerEntry]:
        """Get all ledger entries (for export/audit)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM ledger_entries
            ORDER BY created_at_utc DESC
        """)

        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_entry(dict(row)) for row in rows]

    def _row_to_entry(self, row: dict) -> LedgerEntry:
        """Convert row dict to LedgerEntry."""
        return LedgerEntry(
            entry_id=row['entry_id'],
            entry_type=row['entry_type'],
            associate_id=row['associate_id'],
            bookmaker_id=row['bookmaker_id'],
            surebet_id=row['surebet_id'],
            bet_id=row['bet_id'],
            settlement_batch_id=row['settlement_batch_id'],
            settlement_state=row['settlement_state'],
            amount_native=Decimal(row['amount_native']) if row['amount_native'] else None,
            native_currency=row['native_currency'],
            fx_rate_snapshot=Decimal(row['fx_rate_snapshot']),
            amount_eur=Decimal(row['amount_eur']),
            principal_returned_eur=Decimal(row['principal_returned_eur']) if row['principal_returned_eur'] else None,
            per_surebet_share_eur=Decimal(row['per_surebet_share_eur']) if row['per_surebet_share_eur'] else None,
            created_at_utc=row['created_at_utc'],
            created_by=row['created_by'],
            note=row['note']
        )
```

---

#### Task 4.4.2: Database Migration (Append-Only Trigger)
**File**: `migrations/004_append_only_ledger_trigger.sql`

```sql
-- Migration 004: Enforce append-only ledger
-- Creates trigger to prevent UPDATE/DELETE on ledger_entries

-- CRITICAL: This enforces System Law #1 (Append-Only Ledger)

CREATE TRIGGER IF NOT EXISTS prevent_ledger_update
BEFORE UPDATE ON ledger_entries
BEGIN
    SELECT RAISE(ABORT, 'ledger_entries is append-only: UPDATE not allowed');
END;

CREATE TRIGGER IF NOT EXISTS prevent_ledger_delete
BEFORE DELETE ON ledger_entries
BEGIN
    SELECT RAISE(ABORT, 'ledger_entries is append-only: DELETE not allowed');
END;

-- Add index for performance
CREATE INDEX IF NOT EXISTS idx_ledger_entries_surebet_id
ON ledger_entries(surebet_id);

CREATE INDEX IF NOT EXISTS idx_ledger_entries_settlement_batch_id
ON ledger_entries(settlement_batch_id);
```

---

### Testing

#### Task 4.5.1: Unit Tests for Settlement Service
**File**: `tests/unit/domain/test_settlement_service.py`

```python
"""
Unit tests for SettlementService.
"""
import pytest
from decimal import Decimal
from datetime import datetime

from src.domain.settlement_service import SettlementService, BetOutcome
from src.data.repositories.surebet_repository import SurebetRepository
from src.data.repositories.bet_repository import BetRepository

class MockSurebetRepo:
    """Mock surebet repository."""

    def get_by_id(self, surebet_id):
        return type('Surebet', (), {
            'surebet_id': surebet_id,
            'status': 'matched',
            'canonical_event': 'Test Match',
            'market_code': 'TOTAL_GOALS_OVER_UNDER'
        })()

    def get_bets_for_surebet(self, surebet_id):
        return [
            type('Bet', (), {
                'bet_id': 1,
                'surebet_side': 'SIDE_A',
                'associate_id': 1,
                'associate_alias': 'Admin',
                'bookmaker_id': 1,
                'bookmaker_name': 'Bet365',
                'stake': Decimal('100.00'),
                'odds': Decimal('1.90'),
                'native_currency': 'EUR'
            })(),
            type('Bet', (), {
                'bet_id': 2,
                'surebet_side': 'SIDE_B',
                'associate_id': 2,
                'associate_alias': 'Partner A',
                'bookmaker_id': 2,
                'bookmaker_name': 'Pinnacle',
                'stake': Decimal('100.00'),
                'odds': Decimal('2.10'),
                'native_currency': 'EUR'
            })()
        ]

def test_preview_settlement_side_a_wins():
    """Test settlement preview when Side A wins."""
    service = SettlementService(
        surebet_repo=MockSurebetRepo(),
        bet_repo=None
    )

    preview = service.preview_settlement(
        surebet_id=1,
        outcomes={
            1: BetOutcome.WON,
            2: BetOutcome.LOST
        }
    )

    # Side A net gain: (100 * 1.90) - 100 = 90
    assert preview.per_bet_net_gains[1] == Decimal('90.00')

    # Side B net gain: -100
    assert preview.per_bet_net_gains[2] == Decimal('-100.00')

    # Surebet profit: 90 + (-100) = -10
    assert preview.surebet_profit_eur == Decimal('-10.00')

    # 2 participants (both staked)
    assert preview.num_participants == 2

    # Per-surebet share: -10 / 2 = -5
    assert preview.per_surebet_share_eur == Decimal('-5.00')

def test_preview_settlement_with_void():
    """Test settlement when one bet is VOID."""
    service = SettlementService(
        surebet_repo=MockSurebetRepo(),
        bet_repo=None
    )

    preview = service.preview_settlement(
        surebet_id=1,
        outcomes={
            1: BetOutcome.VOID,
            2: BetOutcome.LOST
        }
    )

    # Side A net gain: 0 (VOID)
    assert preview.per_bet_net_gains[1] == Decimal('0.00')

    # Side B net gain: -100
    assert preview.per_bet_net_gains[2] == Decimal('-100.00')

    # Surebet profit: 0 + (-100) = -100
    assert preview.surebet_profit_eur == Decimal('-100.00')

    # 2 participants (VOID gets non-staked seat)
    assert preview.num_participants == 2

    # Per-surebet share: -100 / 2 = -50
    assert preview.per_surebet_share_eur == Decimal('-50.00')

    # Verify seat types
    participants = {p['bet_id']: p for p in preview.participants}
    assert participants[1]['seat_type'] == 'non_staked'
    assert participants[2]['seat_type'] == 'staked'

def test_preview_settlement_all_void():
    """Test settlement when both bets are VOID (edge case)."""
    service = SettlementService(
        surebet_repo=MockSurebetRepo(),
        bet_repo=None
    )

    preview = service.preview_settlement(
        surebet_id=1,
        outcomes={
            1: BetOutcome.VOID,
            2: BetOutcome.VOID
        }
    )

    # Both net gains: 0
    assert preview.per_bet_net_gains[1] == Decimal('0.00')
    assert preview.per_bet_net_gains[2] == Decimal('0.00')

    # Surebet profit: 0
    assert preview.surebet_profit_eur == Decimal('0.00')

    # 2 participants (both non-staked)
    assert preview.num_participants == 2

    # Per-surebet share: 0 / 2 = 0
    assert preview.per_surebet_share_eur == Decimal('0.00')
```

---

#### Task 4.5.2: Integration Test for Settlement Flow
**File**: `tests/integration/test_settlement_flow.py`

```python
"""
Integration test for full settlement flow.
"""
import pytest
import sqlite3
from decimal import Decimal
from pathlib import Path

from src.domain.settlement_service import SettlementService, BetOutcome
from src.data.repositories.surebet_repository import SurebetRepository
from src.data.repositories.bet_repository import BetRepository
from src.data.repositories.ledger_repository import LedgerEntryRepository

@pytest.fixture
def test_db(tmp_path):
    """Create test database with schema."""
    db_path = tmp_path / "test_settlement.db"

    # Run schema creation
    # (Assumes schema.sql exists)
    with open("schema.sql", 'r') as f:
        schema = f.read()

    conn = sqlite3.connect(str(db_path))
    conn.executescript(schema)
    conn.close()

    return str(db_path)

def test_full_settlement_flow(test_db):
    """Test complete settlement flow from preview to ledger."""

    # Setup: Insert test data (associates, bookmakers, bets, surebet)
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()

    # Insert associates
    cursor.execute("INSERT INTO associates (associate_id, display_alias) VALUES (1, 'Admin')")
    cursor.execute("INSERT INTO associates (associate_id, display_alias) VALUES (2, 'Partner A')")

    # Insert bookmakers
    cursor.execute("INSERT INTO bookmakers (bookmaker_id, associate_id, name, currency) VALUES (1, 1, 'Bet365', 'EUR')")
    cursor.execute("INSERT INTO bookmakers (bookmaker_id, associate_id, name, currency) VALUES (2, 2, 'Pinnacle', 'EUR')")

    # Insert bets
    cursor.execute("""
        INSERT INTO bets (
            bet_id, associate_id, bookmaker_id, status,
            stake, odds, native_currency,
            canonical_event, market_code, bet_side
        ) VALUES (1, 1, 1, 'matched', '100.00', '1.90', 'EUR', 'Test Match', 'TOTAL_GOALS', 'OVER')
    """)
    cursor.execute("""
        INSERT INTO bets (
            bet_id, associate_id, bookmaker_id, status,
            stake, odds, native_currency,
            canonical_event, market_code, bet_side
        ) VALUES (2, 2, 2, 'matched', '100.00', '2.10', 'EUR', 'Test Match', 'TOTAL_GOALS', 'UNDER')
    """)

    # Insert surebet
    cursor.execute("""
        INSERT INTO surebets (
            surebet_id, status, canonical_event, market_code,
            risk_classification, roi, worst_case_profit_eur
        ) VALUES (1, 'matched', 'Test Match', 'TOTAL_GOALS', 'SAFE', 0.05, '5.00')
    """)

    # Insert surebet_bets
    cursor.execute("INSERT INTO surebet_bets (surebet_id, bet_id, side) VALUES (1, 1, 'SIDE_A')")
    cursor.execute("INSERT INTO surebet_bets (surebet_id, bet_id, side) VALUES (1, 2, 'SIDE_B')")

    # Insert FX rate
    cursor.execute("INSERT INTO fx_rates_daily (currency, rate, date) VALUES ('EUR', '1.00', date('now'))")

    conn.commit()
    conn.close()

    # Initialize services
    surebet_repo = SurebetRepository(test_db)
    bet_repo = BetRepository(test_db)
    ledger_repo = LedgerEntryRepository(test_db)

    service = SettlementService(surebet_repo, bet_repo, ledger_repo)

    # Execute: Settle surebet (Side A wins)
    service.execute_settlement(
        surebet_id=1,
        outcomes={
            1: BetOutcome.WON,
            2: BetOutcome.LOST
        }
    )

    # Verify: Ledger entries created
    ledger_entries = ledger_repo.get_all()
    assert len(ledger_entries) == 2

    # Verify: Entry for Side A (WON)
    side_a_entry = next(e for e in ledger_entries if e.bet_id == 1)
    assert side_a_entry.entry_type == "BET_RESULT"
    assert side_a_entry.settlement_state == "WON"
    assert side_a_entry.principal_returned_eur == Decimal('100.00')
    assert side_a_entry.per_surebet_share_eur == Decimal('-5.00')  # Loss split
    assert side_a_entry.amount_eur == Decimal('95.00')  # 100 - 5

    # Verify: Entry for Side B (LOST)
    side_b_entry = next(e for e in ledger_entries if e.bet_id == 2)
    assert side_b_entry.entry_type == "BET_RESULT"
    assert side_b_entry.settlement_state == "LOST"
    assert side_b_entry.principal_returned_eur == Decimal('0.00')
    assert side_b_entry.per_surebet_share_eur == Decimal('-5.00')  # Loss split
    assert side_b_entry.amount_eur == Decimal('-5.00')  # 0 - 5

    # Verify: Surebet status updated
    surebet = surebet_repo.get_by_id(1)
    assert surebet.status == "settled"

    # Verify: Bet statuses updated
    bet1 = bet_repo.get_by_id(1)
    assert bet1.status == "settled"
    assert bet1.outcome == "WON"

    bet2 = bet_repo.get_by_id(2)
    assert bet2.status == "settled"
    assert bet2.outcome == "LOST"
```

---

### Manual Testing

#### Task 4.6: Manual UAT Procedures
**File**: `docs/testing/epic-4-uat-procedures.md`

```markdown
# Epic 4: Settlement - User Acceptance Testing Procedures

## Prerequisites
- Database with at least 2 matched surebets (1 SAFE, 1 LOW_ROI)
- Telegram bot configured with multibook chat
- FX rates populated for all currencies

---

## Scenario 1: Coverage Proof Distribution

**Objective**: Verify coverage proof sends correctly to multibook chat.

### Steps:
1. Open Settlement page
2. Select SAFE surebet from queue
3. Click "Send Coverage Proof" button (if available, or send manually via service)
4. Check multibook Telegram chat

### Expected Results:
- âœ… Message received in multibook chat
- âœ… Both screenshots attached (Side A and Side B)
- âœ… Caption shows:
  - Surebet ID
  - Event name
  - Market code
  - Stake amounts and odds
  - Risk classification
- âœ… Entry logged in `multibook_message_log` table

### SQL Verification:
```sql
SELECT * FROM multibook_message_log
WHERE surebet_id = <SUREBET_ID>;
```

---

## Scenario 2: Settlement Preview (Side A Wins)

**Objective**: Verify equal-split calculation shows correct values.

### Steps:
1. Open Settlement page
2. Select surebet from queue
3. Set Base Outcome: "Side A WON"
4. Do not override individual bets
5. Review settlement preview

### Expected Results:
- âœ… Per-bet net gains calculated correctly:
  - Side A: (stake Ã— odds) - stake
  - Side B: -stake
- âœ… Surebet profit = sum of net gains
- âœ… Participants = 2 (both staked)
- âœ… Per-surebet share = profit / 2
- âœ… Ledger entries preview shows:
  - Side A: principal + share
  - Side B: 0 + share
- âœ… FX snapshots displayed

### Manual Calculation:
Use calculator to verify math independently.

---

## Scenario 3: Settlement with VOID Bet

**Objective**: Verify VOID bet gets non-staked seat in split.

### Steps:
1. Open Settlement page
2. Select surebet from queue
3. Set Base Outcome: "Side A WON"
4. Override Side A: "VOID"
5. Review settlement preview

### Expected Results:
- âœ… Side A net gain = 0.00 (VOID)
- âœ… Side B net gain = -stake (LOST)
- âœ… Surebet profit = Side B net gain
- âœ… Participants = 2:
  - Side A: non-staked seat
  - Side B: staked seat
- âœ… Per-surebet share = profit / 2
- âœ… Ledger entries:
  - Side A: 0 (VOID gets no principal or share for non-staked)
  - Side B: 0 + share

---

## Scenario 4: Confirm Settlement (Irreversible)

**Objective**: Verify ledger entries created correctly and are immutable.

### Steps:
1. Complete Scenario 2 or 3
2. Click "âœ… Confirm Settlement"
3. Verify success message
4. Check database

### Expected Results:
- âœ… Success message displayed
- âœ… Surebet removed from settlement queue
- âœ… Surebet status = "settled"
- âœ… Bet statuses = "settled"
- âœ… Bet outcomes recorded (WON/LOST/VOID)
- âœ… 2 ledger entries created (entry_type = "BET_RESULT")
- âœ… Ledger entries have:
  - Unique entry_id
  - Same settlement_batch_id (UUID)
  - Frozen FX snapshots
  - Correct EUR amounts
  - Correct principal_returned_eur
  - Correct per_surebet_share_eur

### SQL Verification:
```sql
SELECT * FROM ledger_entries
WHERE surebet_id = <SUREBET_ID>
ORDER BY entry_id;
```

### Immutability Test:
```sql
-- This should FAIL with error:
UPDATE ledger_entries
SET amount_eur = '999.99'
WHERE entry_id = <ENTRY_ID>;

-- Expected error: "ledger_entries is append-only: UPDATE not allowed"
```

---

## Scenario 5: Multi-Currency Settlement

**Objective**: Verify FX conversion works correctly for non-EUR bets.

### Prerequisites:
- 1 surebet with bets in different currencies (e.g., AUD and GBP)
- FX rates populated for both currencies

### Steps:
1. Open Settlement page
2. Select multi-currency surebet
3. Set Base Outcome: "Side A WON"
4. Review preview

### Expected Results:
- âœ… All amounts displayed in EUR
- âœ… FX snapshots shown for each bet
- âœ… Net gains calculated using snapshot rates
- âœ… Per-surebet share in EUR
- âœ… After settlement:
  - Ledger entries have frozen FX snapshots
  - amount_eur matches preview
  - native_currency recorded

### Manual Calculation:
```
Side A (AUD):
  Stake: 150 AUD @ odds 1.90
  Payout: 285 AUD
  Net gain: 285 - 150 = 135 AUD
  FX rate (AUD->EUR): 0.60
  Net gain EUR: 135 * 0.60 = 81.00 EUR

Side B (GBP):
  Stake: 80 GBP @ odds 2.10
  Net gain: -80 GBP
  FX rate (GBP->EUR): 1.15
  Net gain EUR: -80 * 1.15 = -92.00 EUR

Surebet profit EUR: 81.00 + (-92.00) = -11.00 EUR
Per-surebet share: -11.00 / 2 = -5.50 EUR
```

---

## Scenario 6: All-VOID Edge Case

**Objective**: Verify system handles both bets VOID correctly.

### Steps:
1. Open Settlement page
2. Select surebet
3. Override both bets: "VOID"
4. Review preview

### Expected Results:
- âœ… Both net gains = 0.00
- âœ… Surebet profit = 0.00
- âœ… Participants = 2 (both non-staked)
- âœ… Per-surebet share = 0.00
- âœ… Ledger entries:
  - Both bets: 0 principal, 0 share
  - amount_eur = 0.00

---

## Post-Testing Validation

After completing all scenarios:

1. **Ledger Integrity Check:**
```sql
SELECT COUNT(*) FROM ledger_entries;
-- Should match number of settled bets Ã— 2
```

2. **Settlement Batch IDs Unique:**
```sql
SELECT settlement_batch_id, COUNT(*)
FROM ledger_entries
WHERE entry_type = 'BET_RESULT'
GROUP BY settlement_batch_id;
-- Each batch should have exactly 2 entries
```

3. **Immutability Confirmed:**
```sql
-- These should ALL FAIL:
UPDATE ledger_entries SET amount_eur = '0.00' WHERE entry_id = 1;
DELETE FROM ledger_entries WHERE entry_id = 1;
```

4. **FX Snapshots Frozen:**
- Change FX rate in `fx_rates_daily`
- Verify old ledger entries still have original snapshot values

---

## Sign-Off

- [ ] All 6 scenarios passed
- [ ] Ledger integrity verified
- [ ] Immutability tested
- [ ] Multi-currency working
- [ ] VOID participation confirmed
- [ ] All-VOID edge case handled

**Tester Signature:** _______________
**Date:** _______________
```

---

## Deployment Checklist

### Pre-Deployment

- [ ] All migrations applied (especially 004_append_only_ledger_trigger.sql)
- [ ] Multibook chat configured in `config/multibook_chat.yaml`
- [ ] FX rates populated for all active currencies
- [ ] At least 2 matched surebets for testing
- [ ] Telegram bot running and connected

### Code Deployment

- [ ] All Story 4.1-4.4 files created
- [ ] Dependencies installed (no new packages for Epic 4)
- [ ] Unit tests pass (test_settlement_service.py)
- [ ] Integration test passes (test_settlement_flow.py)

### Database Validation

- [ ] Append-only triggers active:
```sql
-- Test this BEFORE production:
UPDATE ledger_entries SET amount_eur = '0.00' WHERE entry_id = 1;
-- Should fail with: "ledger_entries is append-only"
```

- [ ] Indexes created:
```sql
SELECT name FROM sqlite_master
WHERE type='index'
AND tbl_name='ledger_entries';
```

### Post-Deployment

- [ ] Run Scenario 1 (Coverage Proof) successfully
- [ ] Run Scenario 2 (Settlement Preview) successfully
- [ ] Run Scenario 4 (Confirm Settlement) successfully
- [ ] Verify ledger entries created
- [ ] Verify immutability (UPDATE/DELETE fails)
- [ ] Settlement page loads without errors

---

## Troubleshooting Guide

### Issue: "Multibook chat is disabled in config"

**Cause:** `enabled: false` in `config/multibook_chat.yaml`

**Fix:**
1. Open `config/multibook_chat.yaml`
2. Set `enabled: true`
3. Verify `chat_id` is correct (not 0)

---

### Issue: "Invalid surebet X or missing bets"

**Cause:** Surebet has fewer than 2 bets linked

**Fix:**
```sql
SELECT surebet_id, COUNT(*) as num_bets
FROM surebet_bets
GROUP BY surebet_id
HAVING COUNT(*) != 2;
```
- If surebet has != 2 bets, it's corrupted
- Update surebet status to 'error' and investigate

---

### Issue: "FX rate not found for currency X"

**Cause:** Missing FX rate in `fx_rates_daily`

**Fix:**
```sql
INSERT INTO fx_rates_daily (currency, rate, date)
VALUES ('AUD', '0.60', date('now'));
```

---

### Issue: Decimal precision errors (e.g., 5.0000000001 instead of 5.00)

**Cause:** Float conversion somewhere in chain

**Fix:**
- Ensure all Decimal values use `.quantize(Decimal("0.01"))`
- Check no accidental float() calls
- Verify database stores as TEXT, not REAL

---

### Issue: Settlement preview shows but Confirm fails

**Cause:** LedgerEntryRepository not initialized

**Fix:**
```python
# In src/streamlit_app/pages/04_Settlement.py
from src.data.repositories.ledger_repository import LedgerEntryRepository

ledger_repo = LedgerEntryRepository(db_path)
settlement_service = SettlementService(surebet_repo, bet_repo, ledger_repo)
```

---

### Issue: All-VOID settlement crashes with division by zero

**Cause:** Attempting to divide by N=0 participants

**Fix:**
- Check `_determine_participants()` returns non-staked seats for VOID
- Verify all-VOID case handled explicitly:
```python
if num_participants == 0:
    per_surebet_share_eur = Decimal("0.00")
else:
    per_surebet_share_eur = (surebet_profit_eur / num_participants).quantize(Decimal("0.01"))
```

---

## Success Criteria

Epic 4 is complete when:

### Functional
- [x] Coverage proof sends to multibook chat successfully
- [x] Settlement UI displays matched surebets sorted by kickoff
- [x] Base outcome selection works (Side A WON / Side B WON)
- [x] Individual bet overrides work (WON/LOST/VOID)
- [x] Settlement preview shows all equal-split calculations
- [x] Confirm settlement writes to ledger (irreversible)
- [x] Ledger entries have frozen FX snapshots
- [x] VOID bets participate with non-staked seats
- [x] All-VOID edge case handled correctly

### Technical
- [x] Append-only trigger prevents UPDATE/DELETE on ledger_entries
- [x] Settlement batch ID links related entries
- [x] Decimal precision maintained throughout (no float)
- [x] UTC timestamps with "Z" suffix
- [x] Transaction atomicity (all entries or none)
- [x] Multi-currency conversion works correctly

### Quality
- [x] All unit tests pass
- [x] Integration test passes
- [x] All 6 UAT scenarios pass
- [x] Immutability verified (triggers block edits)
- [x] No errors in Streamlit logs

---

## Related Documents

- [Epic 4: Coverage Proof & Settlement](./epic-4-coverage-settlement.md)
- [PRD: Settlement (FR-6)](../prd.md#fr-6-settlement-equal-split)
- [PRD: System Laws](../prd.md#system-laws)
- [Architecture: Ledger Design](../architecture/ledger-design.md) *(if exists)*
- [Epic 5: Corrections & Reconciliation](./epic-5-corrections-reconciliation.md)

---

**End of Epic 4 Implementation Guide**
