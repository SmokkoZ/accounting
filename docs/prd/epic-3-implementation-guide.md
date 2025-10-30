# Epic 3: Surebet Matching & Safety - Implementation Guide

**Epic Reference**: [epic-3-surebet-matching.md](./epic-3-surebet-matching.md)
**Status**: Ready for Development
**Estimated Effort**: 5-6 days (1 developer)

---

## Overview

This guide provides detailed implementation for Epic 3, the **core intelligence** of the Surebet Accounting System. Follow this sequentially after completing Epic 2 (Bet Review).

**Epic Goal**: Build deterministic matching engine and risk classification system.

**Prerequisites**:
- ✅ Epic 2 complete (verified bets exist)
- ✅ FX system working (Phase 0)
- ✅ Multiple verified bets on opposite sides available for testing

---

## Code Structure

### New/Modified Files for Epic 3

```
Final_App/
├── src/
│   ├── domain/
│   │   ├── matching_engine.py          # NEW: Core matching algorithm
│   │   ├── side_mapper.py              # NEW: Deterministic side assignment
│   │   └── risk_calculator.py          # NEW: ROI and safety classification
│   ├── database/
│   │   └── repositories/
│   │       ├── surebet_repository.py   # NEW: Surebet CRUD operations
│   │       └── bet_repository.py       # UPDATE: Add get_verified_bets()
│   ├── streamlit_app/
│   │   ├── pages/
│   │   │   └── 2_surebets.py           # NEW: Surebet dashboard page
│   │   ├── components/
│   │   │   ├── surebet_card.py         # NEW: Surebet display component
│   │   │   └── risk_badge.py           # NEW: Risk badge component
│   │   └── utils/
│   │       └── currency_converter.py   # NEW: EUR conversion helper
│   └── config/
│       └── matching_rules.py           # NEW: Matching configuration
├── tests/
│   ├── unit/
│   │   ├── test_matching_engine.py     # NEW: Engine tests
│   │   ├── test_side_mapper.py         # NEW: Side assignment tests
│   │   ├── test_risk_calculator.py     # NEW: ROI calculation tests
│   │   └── test_surebet_repository.py  # NEW: Repository tests
│   └── integration/
│       └── test_matching_flow.py       # NEW: End-to-end matching test
└── migrations/
    └── 003_add_surebet_risk_fields.sql # NEW: Add ROI columns to surebets
```

---

## Database Schema Updates

### Task 0: Add Risk Classification Fields to Surebets

**File**: `migrations/003_add_surebet_risk_fields.sql` (NEW)

**Implementation**:
```sql
-- Add risk calculation fields to surebets table
-- These are cached calculations for performance

ALTER TABLE surebets ADD COLUMN worst_case_profit_eur TEXT;  -- Decimal as TEXT
ALTER TABLE surebets ADD COLUMN total_staked_eur TEXT;        -- Decimal as TEXT
ALTER TABLE surebets ADD COLUMN roi REAL;                     -- ROI percentage
ALTER TABLE surebets ADD COLUMN risk_classification TEXT;     -- 'SAFE', 'LOW_ROI', 'UNSAFE'
ALTER TABLE surebets ADD COLUMN calculated_at_utc TEXT;       -- When risk was last calculated

-- Index for filtering by risk
CREATE INDEX idx_surebets_risk ON surebets(risk_classification);

-- Trigger to prevent side updates in surebet_bets (immutability enforcement)
CREATE TRIGGER prevent_surebet_side_update
BEFORE UPDATE OF side ON surebet_bets
BEGIN
  SELECT RAISE(ABORT, 'Side assignment is immutable after creation');
END;
```

**Run Migration**:
```python
from src.database.db import get_session

session = get_session()
with open("migrations/003_add_surebet_risk_fields.sql", 'r') as f:
    for statement in f.read().split(';'):
        if statement.strip():
            session.execute(statement)
session.commit()
print("✅ Migration 003 complete: Risk fields added, side immutability enforced")
```

---

## Story 3.1: Deterministic Matching Engine

### Implementation Tasks

#### Task 3.1.1: Create Side Mapper

**File**: `src/domain/side_mapper.py` (NEW)

**Implementation**:
```python
"""Deterministic side assignment for surebets.

CRITICAL: Side assignments are IMMUTABLE after creation.
This is System Law #7 (implicit).
"""
from enum import Enum
from typing import Optional

class SurebetSide(Enum):
    """Surebet side enum (A or B)."""
    A = "A"
    B = "B"

class BetSide(Enum):
    """Bet side enum (matches database values)."""
    OVER = "OVER"
    UNDER = "UNDER"
    YES = "YES"
    NO = "NO"
    TEAM_A = "TEAM_A"
    TEAM_B = "TEAM_B"

class SideMapper:
    """Maps bet sides to surebet sides deterministically.

    Rules (MUST NEVER CHANGE):
    - Side A: OVER, YES, TEAM_A
    - Side B: UNDER, NO, TEAM_B
    """

    # Immutable mapping
    SIDE_A_BET_SIDES = {BetSide.OVER, BetSide.YES, BetSide.TEAM_A}
    SIDE_B_BET_SIDES = {BetSide.UNDER, BetSide.NO, BetSide.TEAM_B}

    @classmethod
    def get_surebet_side(cls, bet_side: str) -> SurebetSide:
        """Get surebet side for a bet.

        Args:
            bet_side: Bet side string (e.g., "OVER", "UNDER")

        Returns:
            SurebetSide.A or SurebetSide.B

        Raises:
            ValueError: If bet_side is invalid
        """
        try:
            bet_side_enum = BetSide(bet_side)
        except ValueError:
            raise ValueError(f"Invalid bet side: {bet_side}")

        if bet_side_enum in cls.SIDE_A_BET_SIDES:
            return SurebetSide.A
        elif bet_side_enum in cls.SIDE_B_BET_SIDES:
            return SurebetSide.B
        else:
            raise ValueError(f"Bet side {bet_side} not mapped to surebet side")

    @classmethod
    def get_opposite_bet_sides(cls, bet_side: str) -> list:
        """Get opposite bet sides for matching.

        Args:
            bet_side: Bet side string

        Returns:
            List of opposite bet side strings
        """
        surebet_side = cls.get_surebet_side(bet_side)

        if surebet_side == SurebetSide.A:
            # Return Side B bet sides
            return [side.value for side in cls.SIDE_B_BET_SIDES]
        else:
            # Return Side A bet sides
            return [side.value for side in cls.SIDE_A_BET_SIDES]

    @classmethod
    def are_opposite_sides(cls, side1: str, side2: str) -> bool:
        """Check if two bet sides are opposite.

        Args:
            side1: First bet side
            side2: Second bet side

        Returns:
            True if opposite sides
        """
        try:
            surebet_side1 = cls.get_surebet_side(side1)
            surebet_side2 = cls.get_surebet_side(side2)
            return surebet_side1 != surebet_side2
        except ValueError:
            return False
```

**Tests** (`tests/unit/test_side_mapper.py`):
```python
import pytest
from src.domain.side_mapper import SideMapper, SurebetSide, BetSide

def test_get_surebet_side_a():
    assert SideMapper.get_surebet_side("OVER") == SurebetSide.A
    assert SideMapper.get_surebet_side("YES") == SurebetSide.A
    assert SideMapper.get_surebet_side("TEAM_A") == SurebetSide.A

def test_get_surebet_side_b():
    assert SideMapper.get_surebet_side("UNDER") == SurebetSide.B
    assert SideMapper.get_surebet_side("NO") == SurebetSide.B
    assert SideMapper.get_surebet_side("TEAM_B") == SurebetSide.B

def test_invalid_side():
    with pytest.raises(ValueError):
        SideMapper.get_surebet_side("INVALID")

def test_get_opposite_sides():
    opposites = SideMapper.get_opposite_bet_sides("OVER")
    assert "UNDER" in opposites
    assert "OVER" not in opposites

def test_are_opposite_sides():
    assert SideMapper.are_opposite_sides("OVER", "UNDER") == True
    assert SideMapper.are_opposite_sides("YES", "NO") == True
    assert SideMapper.are_opposite_sides("OVER", "YES") == False
```

---

#### Task 3.1.2: Create Surebet Repository

**File**: `src/database/repositories/surebet_repository.py` (NEW)

**Implementation**:
```python
"""Repository for surebet database operations."""
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional, Tuple
from decimal import Decimal
from src.database.models import Surebet, SurebetBet, Bet
from src.utils.timestamp import utc_now_iso

class SurebetRepository:
    """Handles surebet database CRUD operations."""

    def __init__(self, session: Session):
        self.session = session

    def create_surebet(
        self,
        canonical_event_id: int,
        market_code: str,
        period_scope: str,
        line_value: Optional[Decimal],
        kickoff_time_utc: str
    ) -> Surebet:
        """Create a new surebet with status='open'."""
        surebet = Surebet(
            status="open",
            canonical_event_id=canonical_event_id,
            market_code=market_code,
            period_scope=period_scope,
            line_value=str(line_value) if line_value else None,
            kickoff_time_utc=kickoff_time_utc,
            created_at_utc=utc_now_iso()
        )

        self.session.add(surebet)
        self.session.flush()  # Get surebet_id without committing
        return surebet

    def add_bet_to_surebet(
        self,
        surebet_id: int,
        bet_id: int,
        side: str
    ):
        """Link a bet to a surebet with side assignment.

        Args:
            surebet_id: ID of surebet
            bet_id: ID of bet
            side: "A" or "B" (IMMUTABLE after creation)
        """
        surebet_bet = SurebetBet(
            surebet_id=surebet_id,
            bet_id=bet_id,
            side=side,
            created_at_utc=utc_now_iso()
        )

        self.session.add(surebet_bet)
        self.session.flush()

    def find_existing_surebet(
        self,
        canonical_event_id: int,
        market_code: str,
        period_scope: str,
        line_value: Optional[Decimal]
    ) -> Optional[Surebet]:
        """Find existing open surebet matching these criteria.

        Returns:
            Surebet if found, None otherwise
        """
        query = self.session.query(Surebet).filter(
            Surebet.status == "open",
            Surebet.canonical_event_id == canonical_event_id,
            Surebet.market_code == market_code,
            Surebet.period_scope == period_scope
        )

        # Handle line_value (can be NULL)
        if line_value is not None:
            query = query.filter(Surebet.line_value == str(line_value))
        else:
            query = query.filter(Surebet.line_value.is_(None))

        return query.first()

    def get_surebet_bets(self, surebet_id: int) -> List[Tuple[Bet, str]]:
        """Get all bets in a surebet with their sides.

        Returns:
            List of (Bet, side) tuples
        """
        query = self.session.query(Bet, SurebetBet.side)\
            .join(SurebetBet, Bet.bet_id == SurebetBet.bet_id)\
            .filter(SurebetBet.surebet_id == surebet_id)

        return query.all()

    def update_bet_status_to_matched(self, bet_id: int):
        """Update bet status to 'matched'."""
        bet = self.session.query(Bet).filter(Bet.bet_id == bet_id).one()
        bet.status = "matched"
        self.session.flush()

    def update_risk_calculation(
        self,
        surebet_id: int,
        worst_case_profit_eur: Decimal,
        total_staked_eur: Decimal,
        roi: float,
        risk_classification: str
    ):
        """Update surebet with risk calculation results."""
        surebet = self.session.query(Surebet).filter(Surebet.surebet_id == surebet_id).one()

        surebet.worst_case_profit_eur = str(worst_case_profit_eur)
        surebet.total_staked_eur = str(total_staked_eur)
        surebet.roi = roi
        surebet.risk_classification = risk_classification
        surebet.calculated_at_utc = utc_now_iso()

        self.session.flush()

    def get_open_surebets(self) -> List[Surebet]:
        """Get all open surebets ordered by kickoff time."""
        return self.session.query(Surebet)\
            .filter(Surebet.status == "open")\
            .order_by(Surebet.kickoff_time_utc.asc())\
            .all()
```

---

#### Task 3.1.3: Create Matching Engine

**File**: `src/domain/matching_engine.py` (NEW)

**Implementation**:
```python
"""Deterministic surebet matching engine.

This is the core intelligence of the system.
"""
import logging
from typing import List, Optional
from decimal import Decimal
from sqlalchemy.orm import Session
from src.database.models import Bet
from src.database.repositories.surebet_repository import SurebetRepository
from src.domain.side_mapper import SideMapper

logger = logging.getLogger(__name__)

class MatchingEngine:
    """Handles deterministic bet matching into surebets."""

    def __init__(self, session: Session):
        self.session = session
        self.surebet_repo = SurebetRepository(session)

    def attempt_match_bet(self, bet_id: int) -> Optional[int]:
        """Attempt to match a verified bet into a surebet.

        Args:
            bet_id: ID of bet to match (must be status='verified')

        Returns:
            surebet_id if matched, None otherwise
        """
        # Get the bet
        bet = self.session.query(Bet).filter(Bet.bet_id == bet_id).one()

        # Validate bet is matchable
        if not self._is_bet_matchable(bet):
            logger.info(f"Bet {bet_id} not matchable (status={bet.status}, is_supported={bet.is_supported})")
            return None

        # Find opposite-side candidates
        opposite_bets = self._find_opposite_side_bets(bet)

        if not opposite_bets:
            logger.info(f"Bet {bet_id} has no opposite side candidates yet")
            return None

        # Check if surebet already exists
        existing_surebet = self.surebet_repo.find_existing_surebet(
            canonical_event_id=bet.canonical_event_id,
            market_code=bet.market_code,
            period_scope=bet.period_scope,
            line_value=Decimal(bet.line_value) if bet.line_value else None
        )

        if existing_surebet:
            # Add to existing surebet
            surebet_id = existing_surebet.surebet_id
            logger.info(f"Adding bet {bet_id} to existing surebet {surebet_id}")
        else:
            # Create new surebet
            surebet = self.surebet_repo.create_surebet(
                canonical_event_id=bet.canonical_event_id,
                market_code=bet.market_code,
                period_scope=bet.period_scope,
                line_value=Decimal(bet.line_value) if bet.line_value else None,
                kickoff_time_utc=bet.kickoff_time_utc or "TBD"
            )
            surebet_id = surebet.surebet_id
            logger.info(f"Created new surebet {surebet_id} for bet {bet_id}")

            # Add all opposite-side bets to the surebet
            for opp_bet in opposite_bets:
                opp_side = SideMapper.get_surebet_side(opp_bet.side).value
                self.surebet_repo.add_bet_to_surebet(surebet_id, opp_bet.bet_id, opp_side)
                self.surebet_repo.update_bet_status_to_matched(opp_bet.bet_id)
                logger.info(f"Added opposite bet {opp_bet.bet_id} (side {opp_side}) to surebet {surebet_id}")

        # Add current bet to surebet
        current_side = SideMapper.get_surebet_side(bet.side).value
        self.surebet_repo.add_bet_to_surebet(surebet_id, bet_id, current_side)
        self.surebet_repo.update_bet_status_to_matched(bet_id)
        logger.info(f"Added bet {bet_id} (side {current_side}) to surebet {surebet_id}")

        # Commit transaction
        self.session.commit()

        return surebet_id

    def _is_bet_matchable(self, bet: Bet) -> bool:
        """Check if bet can be matched.

        Returns:
            True if bet is matchable
        """
        # Must be verified
        if bet.status != "verified":
            return False

        # Must be supported (not accumulator)
        if bet.is_supported == 0:
            return False

        # Must have required fields
        required_fields = [
            bet.canonical_event_id,
            bet.market_code,
            bet.period_scope,
            bet.side
        ]
        if not all(required_fields):
            logger.warning(f"Bet {bet.bet_id} missing required fields for matching")
            return False

        return True

    def _find_opposite_side_bets(self, bet: Bet) -> List[Bet]:
        """Find verified bets on opposite side.

        Args:
            bet: Current bet to match

        Returns:
            List of opposite-side bets
        """
        # Get opposite sides
        opposite_sides = SideMapper.get_opposite_bet_sides(bet.side)

        # Query for matches
        query = self.session.query(Bet).filter(
            Bet.status == "verified",
            Bet.canonical_event_id == bet.canonical_event_id,
            Bet.market_code == bet.market_code,
            Bet.period_scope == bet.period_scope,
            Bet.side.in_(opposite_sides),
            Bet.is_supported == 1  # Exclude accumulators
        )

        # Handle line_value (can be NULL)
        if bet.line_value is not None:
            query = query.filter(Bet.line_value == bet.line_value)
        else:
            query = query.filter(Bet.line_value.is_(None))

        return query.all()
```

**Tests** (`tests/unit/test_matching_engine.py`):
```python
import pytest
from decimal import Decimal
from src.domain.matching_engine import MatchingEngine
from src.database.db import get_test_session
from src.database.repositories.bet_repository import BetRepository

def test_match_two_opposite_bets():
    """Test matching two opposite-side bets into new surebet."""
    session = get_test_session()
    engine = MatchingEngine(session)
    bet_repo = BetRepository(session)

    # Create two opposite bets
    bet_a = create_verified_bet(session, side="OVER", line_value="2.5")
    bet_b = create_verified_bet(session, side="UNDER", line_value="2.5")

    # Match bet A
    surebet_id = engine.attempt_match_bet(bet_a.bet_id)

    # Should not create surebet yet (no opposite side)
    assert surebet_id is None
    session.refresh(bet_a)
    assert bet_a.status == "verified"  # Still verified

    # Match bet B (opposite side exists now)
    surebet_id = engine.attempt_match_bet(bet_b.bet_id)

    # Should create surebet
    assert surebet_id is not None

    # Both bets should be matched
    session.refresh(bet_a)
    session.refresh(bet_b)
    assert bet_a.status == "matched"
    assert bet_b.status == "matched"

def test_match_multi_bet_surebet():
    """Test matching A1+A2 vs B into single surebet."""
    session = get_test_session()
    engine = MatchingEngine(session)

    # Create three bets: two on Side A, one on Side B
    bet_a1 = create_verified_bet(session, side="YES")
    bet_a2 = create_verified_bet(session, side="YES")
    bet_b = create_verified_bet(session, side="NO")

    # Match all three
    engine.attempt_match_bet(bet_a1.bet_id)
    engine.attempt_match_bet(bet_a2.bet_id)
    surebet_id = engine.attempt_match_bet(bet_b.bet_id)

    # Should create ONE surebet with all three bets
    assert surebet_id is not None

    # Verify all three linked
    from src.database.repositories.surebet_repository import SurebetRepository
    repo = SurebetRepository(session)
    bet_sides = repo.get_surebet_bets(surebet_id)

    assert len(bet_sides) == 3
    # Two Side A, one Side B
    sides = [side for _, side in bet_sides]
    assert sides.count("A") == 2
    assert sides.count("B") == 1

def test_no_match_same_side():
    """Test that same-side bets don't match."""
    session = get_test_session()
    engine = MatchingEngine(session)

    bet_a1 = create_verified_bet(session, side="OVER")
    bet_a2 = create_verified_bet(session, side="OVER")  # Same side

    surebet_id = engine.attempt_match_bet(bet_a1.bet_id)
    assert surebet_id is None

    surebet_id = engine.attempt_match_bet(bet_a2.bet_id)
    assert surebet_id is None  # Still no match

def test_accumulator_not_matched():
    """Test that accumulators (is_supported=0) are excluded."""
    session = get_test_session()
    engine = MatchingEngine(session)

    bet_multi = create_verified_bet(session, side="OVER", is_supported=0)
    bet_single = create_verified_bet(session, side="UNDER", is_supported=1)

    # Multi bet should not match
    surebet_id = engine.attempt_match_bet(bet_multi.bet_id)
    assert surebet_id is None

    # Single bet also shouldn't match (no valid opposite)
    surebet_id = engine.attempt_match_bet(bet_single.bet_id)
    assert surebet_id is None

# Helper function
def create_verified_bet(session, side="OVER", line_value="2.5", is_supported=1):
    """Create a verified bet for testing."""
    from src.database.models import Bet

    bet = Bet(
        status="verified",
        canonical_event_id=1,
        market_code="TOTAL_GOALS_OVER_UNDER",
        period_scope="FULL_MATCH",
        line_value=line_value,
        side=side,
        stake="100",
        odds="1.90",
        payout="190",
        currency="EUR",
        is_supported=is_supported,
        associate_id=1,
        bookmaker_id=1,
        screenshot_path="test.png",
        ingestion_source="test",
        created_at_utc="2025-01-01T00:00:00Z"
    )
    session.add(bet)
    session.commit()
    session.refresh(bet)
    return bet
```

---

#### Task 3.1.4: Integrate Matching into Approval Workflow

**File**: `src/domain/bet_approval.py` (UPDATE from Epic 2)

Add matching trigger after approval:

```python
# At the end of approve_bet() method, add:

def approve_bet(self, bet_id: int, edited_fields: Dict[str, Any]) -> Tuple[bool, str]:
    """Approve bet with matching trigger."""
    try:
        # ... existing approval logic ...

        self.session.commit()

        # NEW: Trigger matching engine
        from src.domain.matching_engine import MatchingEngine

        matching_engine = MatchingEngine(self.session)
        surebet_id = matching_engine.attempt_match_bet(bet_id)

        if surebet_id:
            logger.info(f"Bet {bet_id} matched into surebet {surebet_id}")
            message = f"Bet #{bet_id} approved and matched into Surebet #{surebet_id}"
        else:
            message = f"Bet #{bet_id} approved (no match yet)"

        return True, message

    except Exception as e:
        self.session.rollback()
        return False, f"Error approving bet: {str(e)}"
```

---

## Story 3.2: Worst-Case EUR Profit Calculation

### Implementation Tasks

#### Task 3.2.1: Create Currency Converter Helper

**File**: `src/streamlit_app/utils/currency_converter.py` (NEW)

**Implementation**:
```python
"""Currency conversion utilities for surebets."""
from decimal import Decimal
from typing import Dict
from src.database.db import get_session

class CurrencyConverter:
    """Helper for converting currencies to EUR."""

    def __init__(self):
        self.session = get_session()
        self._fx_cache: Dict[str, Decimal] = {}

    def get_fx_rate(self, currency: str) -> Decimal:
        """Get EUR per 1 unit of currency.

        Args:
            currency: Currency code (e.g., "AUD", "GBP")

        Returns:
            Decimal FX rate (EUR per 1 unit)
        """
        if currency == "EUR":
            return Decimal("1.0")

        # Check cache
        if currency in self._fx_cache:
            return self._fx_cache[currency]

        # Query database (from Phase 0 fx_rates_daily table)
        query = """
            SELECT rate
            FROM fx_rates_daily
            WHERE currency = :currency
            ORDER BY date DESC
            LIMIT 1
        """

        result = self.session.execute(query, {'currency': currency}).fetchone()

        if result:
            rate = Decimal(result.rate)
            self._fx_cache[currency] = rate
            return rate
        else:
            # Fallback to 1.0 if no rate found (log warning)
            import logging
            logging.warning(f"No FX rate found for {currency}, using 1.0")
            return Decimal("1.0")

    def to_eur(self, amount: Decimal, currency: str) -> Decimal:
        """Convert amount to EUR.

        Args:
            amount: Amount in native currency
            currency: Currency code

        Returns:
            Amount in EUR
        """
        fx_rate = self.get_fx_rate(currency)
        return amount * fx_rate
```

---

#### Task 3.2.2: Create Risk Calculator

**File**: `src/domain/risk_calculator.py` (NEW)

**Implementation**:
```python
"""Risk calculation for surebets (worst-case profit and ROI)."""
import logging
from decimal import Decimal
from typing import Dict, Tuple
from sqlalchemy.orm import Session
from src.database.repositories.surebet_repository import SurebetRepository
from src.streamlit_app.utils.currency_converter import CurrencyConverter

logger = logging.getLogger(__name__)

class RiskClassification:
    """Risk classification constants."""
    SAFE = "SAFE"
    LOW_ROI = "LOW_ROI"
    UNSAFE = "UNSAFE"

class RiskCalculator:
    """Calculates worst-case profit and ROI for surebets."""

    # Configurable threshold (1.0%)
    ROI_THRESHOLD = 1.0

    def __init__(self, session: Session):
        self.session = session
        self.surebet_repo = SurebetRepository(session)
        self.converter = CurrencyConverter()

    def calculate_surebet_risk(self, surebet_id: int) -> Dict[str, any]:
        """Calculate risk metrics for a surebet.

        Returns:
            Dict with:
                - worst_case_profit_eur: Decimal
                - total_staked_eur: Decimal
                - roi: float (percentage)
                - risk_classification: str
                - profit_if_a_wins: Decimal
                - profit_if_b_wins: Decimal
        """
        # Get all bets in surebet
        bets_with_sides = self.surebet_repo.get_surebet_bets(surebet_id)

        if not bets_with_sides:
            raise ValueError(f"No bets found for surebet {surebet_id}")

        # Convert all amounts to EUR
        side_a_bets = []
        side_b_bets = []

        for bet, side in bets_with_sides:
            stake_eur = self.converter.to_eur(Decimal(bet.stake), bet.currency)
            payout_eur = self.converter.to_eur(Decimal(bet.payout), bet.currency)

            bet_eur = {
                'stake_eur': stake_eur,
                'payout_eur': payout_eur
            }

            if side == "A":
                side_a_bets.append(bet_eur)
            else:
                side_b_bets.append(bet_eur)

        # Calculate total staked (all bets)
        total_staked_eur = sum(
            b['stake_eur'] for b in side_a_bets + side_b_bets
        )

        # Calculate profit if Side A wins
        profit_if_a_wins = (
            sum(b['payout_eur'] for b in side_a_bets) - total_staked_eur
        )

        # Calculate profit if Side B wins
        profit_if_b_wins = (
            sum(b['payout_eur'] for b in side_b_bets) - total_staked_eur
        )

        # Worst-case profit
        worst_case_profit_eur = min(profit_if_a_wins, profit_if_b_wins)

        # ROI (as percentage)
        if total_staked_eur > 0:
            roi = float((worst_case_profit_eur / total_staked_eur) * 100)
        else:
            roi = 0.0

        # Risk classification
        risk_classification = self._classify_risk(worst_case_profit_eur, roi)

        logger.info(
            f"Surebet {surebet_id} risk: "
            f"worst_case={worst_case_profit_eur:.2f} EUR, "
            f"roi={roi:.2f}%, "
            f"classification={risk_classification}"
        )

        return {
            'worst_case_profit_eur': worst_case_profit_eur,
            'total_staked_eur': total_staked_eur,
            'roi': roi,
            'risk_classification': risk_classification,
            'profit_if_a_wins': profit_if_a_wins,
            'profit_if_b_wins': profit_if_b_wins
        }

    def _classify_risk(self, worst_case_profit: Decimal, roi: float) -> str:
        """Classify risk level.

        Args:
            worst_case_profit: Worst-case profit in EUR
            roi: ROI percentage

        Returns:
            Risk classification string
        """
        if worst_case_profit < 0:
            return RiskClassification.UNSAFE
        elif roi < self.ROI_THRESHOLD:
            return RiskClassification.LOW_ROI
        else:
            return RiskClassification.SAFE

    def update_surebet_risk(self, surebet_id: int):
        """Calculate and store risk for a surebet.

        This should be called:
        - When surebet is created/updated
        - When FX rates change
        """
        try:
            risk_data = self.calculate_surebet_risk(surebet_id)

            # Update surebet table
            self.surebet_repo.update_risk_calculation(
                surebet_id=surebet_id,
                worst_case_profit_eur=risk_data['worst_case_profit_eur'],
                total_staked_eur=risk_data['total_staked_eur'],
                roi=risk_data['roi'],
                risk_classification=risk_data['risk_classification']
            )

            self.session.commit()

        except Exception as e:
            logger.error(f"Error updating surebet {surebet_id} risk: {e}", exc_info=True)
            self.session.rollback()
```

**Tests** (`tests/unit/test_risk_calculator.py`):
```python
import pytest
from decimal import Decimal
from src.domain.risk_calculator import RiskCalculator, RiskClassification
from src.database.db import get_test_session

def test_calculate_safe_surebet():
    """Test calculation for safe surebet (positive ROI)."""
    session = get_test_session()
    calculator = RiskCalculator(session)

    # Create test surebet with positive ROI
    surebet_id = create_test_surebet(
        session,
        side_a_stake=95, side_a_odds=2.05, side_a_currency="EUR",
        side_b_stake=100, side_b_odds=2.00, side_b_currency="EUR"
    )

    risk = calculator.calculate_surebet_risk(surebet_id)

    # Total staked: 195 EUR
    assert risk['total_staked_eur'] == Decimal("195")

    # If A wins: 95*2.05 - 195 = 194.75 - 195 = -0.25
    # If B wins: 100*2.00 - 195 = 200 - 195 = +5
    # Worst case: -0.25
    assert risk['worst_case_profit_eur'] == Decimal("-0.25")

    # ROI: -0.25/195 * 100 ≈ -0.13%
    assert risk['roi'] < 0

    # Classification: UNSAFE (negative)
    assert risk['risk_classification'] == RiskClassification.UNSAFE

def test_calculate_low_roi_surebet():
    """Test surebet with positive but low ROI."""
    session = get_test_session()
    calculator = RiskCalculator(session)

    # Create test surebet: +€2 profit on €200 staked (1% ROI - exactly at threshold)
    surebet_id = create_test_surebet(
        session,
        side_a_stake=100, side_a_odds=2.02, side_a_currency="EUR",
        side_b_stake=100, side_b_odds=2.02, side_b_currency="EUR"
    )

    risk = calculator.calculate_surebet_risk(surebet_id)

    # Worst case: +€2
    assert risk['worst_case_profit_eur'] > 0

    # ROI: 1.0%
    assert abs(risk['roi'] - 1.0) < 0.1

    # Classification: SAFE (at threshold)
    assert risk['risk_classification'] == RiskClassification.SAFE

def test_multi_currency_conversion():
    """Test ROI calculation with multi-currency bets."""
    session = get_test_session()
    calculator = RiskCalculator(session)

    # Assume FX rates: AUD 0.60, GBP 1.15
    surebet_id = create_test_surebet(
        session,
        side_a_stake=150, side_a_odds=1.90, side_a_currency="AUD",  # €90 staked
        side_b_stake=100, side_b_odds=2.00, side_b_currency="GBP"   # €115 staked
    )

    risk = calculator.calculate_surebet_risk(surebet_id)

    # Total staked: 90 + 115 = €205
    assert risk['total_staked_eur'] > Decimal("200")

    # Verify EUR conversion happened
    assert risk['profit_if_a_wins'] is not None
    assert risk['profit_if_b_wins'] is not None
```

---

#### Task 3.2.3: Integrate Risk Calculation into Matching

**File**: `src/domain/matching_engine.py` (UPDATE)

Add risk calculation after matching:

```python
def attempt_match_bet(self, bet_id: int) -> Optional[int]:
    """Attempt to match bet and calculate risk."""
    # ... existing matching logic ...

    self.session.commit()

    # NEW: Calculate risk for the surebet
    from src.domain.risk_calculator import RiskCalculator

    risk_calculator = RiskCalculator(self.session)
    risk_calculator.update_surebet_risk(surebet_id)

    logger.info(f"Risk calculated for surebet {surebet_id}")

    return surebet_id
```

---

## Story 3.3: Surebet Safety Dashboard UI

### Implementation Tasks

#### Task 3.3.1: Create Risk Badge Component

**File**: `src/streamlit_app/components/risk_badge.py` (NEW)

**Implementation**:
```python
"""Risk badge component for displaying surebet safety."""
import streamlit as st
from src.domain.risk_calculator import RiskClassification

def render_risk_badge(risk_classification: str, roi: float):
    """Render colored risk badge with emoji.

    Args:
        risk_classification: SAFE, LOW_ROI, or UNSAFE
        roi: ROI percentage
    """
    if risk_classification == RiskClassification.SAFE:
        st.success(f"✅ **SAFE** ({roi:+.2f}%)")
    elif risk_classification == RiskClassification.LOW_ROI:
        st.warning(f"🟡 **Low ROI** ({roi:+.2f}%)")
    else:  # UNSAFE
        st.error(f"❌ **UNSAFE** ({roi:+.2f}%)")

def get_risk_color(risk_classification: str) -> str:
    """Get CSS color for risk level."""
    if risk_classification == RiskClassification.SAFE:
        return "#28a745"  # Green
    elif risk_classification == RiskClassification.LOW_ROI:
        return "#ffc107"  # Yellow
    else:
        return "#dc3545"  # Red
```

---

#### Task 3.3.2: Create Surebet Card Component

**File**: `src/streamlit_app/components/surebet_card.py` (NEW)

**Implementation**:
```python
"""Surebet card component for dashboard."""
import streamlit as st
from decimal import Decimal
from typing import Dict, Any, List, Tuple
from src.streamlit_app.components.risk_badge import render_risk_badge, get_risk_color
from src.streamlit_app.utils.formatters import format_currency_amount

def render_surebet_card(surebet: Dict[str, Any], bets_with_sides: List[Tuple]):
    """Render a surebet card with sides, bets, and risk info.

    Args:
        surebet: Dict containing surebet data
        bets_with_sides: List of (Bet, side) tuples
    """
    # Container with colored border based on risk
    risk_color = get_risk_color(surebet.get('risk_classification', 'UNSAFE'))

    with st.container():
        # Apply border color via markdown CSS
        st.markdown(
            f'<div style="border-left: 5px solid {risk_color}; padding-left: 10px;">',
            unsafe_allow_html=True
        )

        # Header: Event + Risk Badge
        col1, col2 = st.columns([3, 1])

        with col1:
            st.markdown(f"### Surebet #{surebet['surebet_id']}")
            st.markdown(f"**{surebet['event_name']}**")
            st.caption(f"{surebet['market_code']} • {surebet['period_scope']}")
            if surebet.get('line_value'):
                st.caption(f"Line: {surebet['line_value']}")

        with col2:
            # Risk badge
            if surebet.get('risk_classification'):
                render_risk_badge(
                    surebet['risk_classification'],
                    surebet.get('roi', 0.0)
                )

        st.markdown("---")

        # Bets grouped by side
        col_a, col_b = st.columns(2)

        side_a_bets = [(bet, side) for bet, side in bets_with_sides if side == "A"]
        side_b_bets = [(bet, side) for bet, side in bets_with_sides if side == "B"]

        with col_a:
            st.markdown("#### 🔵 Side A")
            _render_bet_list(side_a_bets)

        with col_b:
            st.markdown("#### 🔴 Side B")
            _render_bet_list(side_b_bets)

        st.markdown("---")

        # EUR Calculations
        st.markdown("#### 💰 Financial Summary")
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(
                "Worst-Case Profit",
                f"€{float(surebet.get('worst_case_profit_eur', 0)):.2f}",
                delta=None
            )

        with col2:
            st.metric(
                "Total Staked",
                f"€{float(surebet.get('total_staked_eur', 0)):.2f}"
            )

        with col3:
            st.metric(
                "ROI",
                f"{surebet.get('roi', 0.0):+.2f}%"
            )

        # Drill-down expander
        with st.expander("🔍 Detailed Calculation"):
            _render_detailed_calculation(surebet, bets_with_sides)

        # Actions (placeholder for Epic 4)
        col1, col2 = st.columns(2)
        with col1:
            st.button(
                "📤 Send Coverage Proof",
                key=f"coverage_{surebet['surebet_id']}",
                disabled=True,
                help="Epic 4 feature"
            )
        with col2:
            st.button(
                "✅ Settle Surebet",
                key=f"settle_{surebet['surebet_id']}",
                disabled=True,
                help="Epic 4 feature"
            )

        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown("---")

def _render_bet_list(bets_with_sides: List[Tuple]):
    """Render list of bets for one side."""
    if not bets_with_sides:
        st.info("No bets on this side yet")
        return

    for bet, side in bets_with_sides:
        # Format: "Admin @ Bet365: $100 @ 1.90"
        st.write(
            f"**{bet.associate.display_alias}** @ {bet.bookmaker.name}:  \n"
            f"{format_currency_amount(Decimal(bet.stake), bet.currency)} @ {bet.odds}"
        )
        # Screenshot link
        if st.button(f"📸 View Screenshot", key=f"screenshot_{bet.bet_id}"):
            st.image(bet.screenshot_path, use_column_width=True)

def _render_detailed_calculation(surebet: Dict[str, Any], bets_with_sides: List[Tuple]):
    """Render detailed EUR calculation breakdown."""
    st.markdown("**Scenario Analysis:**")

    # Would need to recalculate or store these separately
    # For now, show formula
    st.code("""
If Side A wins:
    Profit = (Sum of Side A payouts in EUR) - (Total stakes in EUR)

If Side B wins:
    Profit = (Sum of Side B payouts in EUR) - (Total stakes in EUR)

Worst-case profit = min(profit_if_A_wins, profit_if_B_wins)
ROI = (worst_case_profit / total_staked) * 100
    """)

    # Show FX rates used
    st.markdown("**FX Rates:**")
    # Could query fx_rates_daily table here
    st.caption("EUR rates as of today")
```

---

#### Task 3.3.3: Create Surebets Dashboard Page

**File**: `src/streamlit_app/pages/2_surebets.py` (NEW)

**Implementation**:
```python
"""Surebets dashboard - displays open surebets with risk classification."""
import streamlit as st
from src.database.db import get_session
from src.database.repositories.surebet_repository import SurebetRepository
from src.streamlit_app.components.surebet_card import render_surebet_card

st.set_page_config(page_title="Surebets", layout="wide")

st.title("⚖️ Surebets Dashboard")

# Get repository
session = get_session()
repo = SurebetRepository(session)

# Counters
counts_query = """
    SELECT
        COUNT(*) as total_open,
        SUM(CASE WHEN risk_classification='UNSAFE' THEN 1 ELSE 0 END) as unsafe_count
    FROM surebets
    WHERE status='open'
"""
counts = session.execute(counts_query).fetchone()

col1, col2 = st.columns(2)
col1.metric("Open Surebets", counts.total_open or 0)
col2.metric("⚠️ Unsafe Surebets", counts.unsafe_count or 0, delta=None)

st.markdown("---")

# Filters
with st.expander("🔍 Filters & Sorting", expanded=False):
    col1, col2 = st.columns(2)

    with col1:
        risk_filter = st.selectbox(
            "Filter by Risk",
            options=["All", "Safe Only", "Low ROI Only", "Unsafe Only"],
            index=0
        )

    with col2:
        sort_by = st.selectbox(
            "Sort by",
            options=["Kickoff Time (earliest first)", "ROI (lowest first)", "Total Staked (largest first)"],
            index=0
        )

st.markdown("---")

# Build query
query = """
    SELECT
        s.surebet_id,
        s.canonical_event_id,
        s.market_code,
        s.period_scope,
        s.line_value,
        s.kickoff_time_utc,
        s.worst_case_profit_eur,
        s.total_staked_eur,
        s.roi,
        s.risk_classification,
        ce.event_name
    FROM surebets s
    JOIN canonical_events ce ON s.canonical_event_id = ce.canonical_event_id
    WHERE s.status='open'
"""

# Apply risk filter
if risk_filter == "Safe Only":
    query += " AND s.risk_classification='SAFE'"
elif risk_filter == "Low ROI Only":
    query += " AND s.risk_classification='LOW_ROI'"
elif risk_filter == "Unsafe Only":
    query += " AND s.risk_classification='UNSAFE'"

# Apply sorting
if sort_by == "Kickoff Time (earliest first)":
    query += " ORDER BY s.kickoff_time_utc ASC"
elif sort_by == "ROI (lowest first)":
    query += " ORDER BY s.roi ASC"
elif sort_by == "Total Staked (largest first)":
    query += " ORDER BY s.total_staked_eur DESC"

# Execute query
surebets = session.execute(query).fetchall()

if not surebets:
    st.info("✨ No open surebets found! Approve opposite-side bets to create surebets.")
else:
    st.caption(f"Showing {len(surebets)} surebet(s)")

    # Render each surebet card
    for surebet in surebets:
        surebet_dict = dict(surebet._mapping)

        # Get bets for this surebet
        bets_with_sides = repo.get_surebet_bets(surebet_dict['surebet_id'])

        render_surebet_card(surebet_dict, bets_with_sides)

# Auto-refresh
st.markdown("---")
if st.checkbox("🔄 Auto-refresh every 30 seconds"):
    import time
    time.sleep(30)
    st.rerun()
```

---

## Integration Testing

### End-to-End Matching Test

**File**: `tests/integration/test_matching_flow.py` (NEW)

**Implementation**:
```python
"""Integration test for full matching and risk calculation flow."""
import pytest
from decimal import Decimal
from src.database.db import get_test_session
from src.domain.matching_engine import MatchingEngine
from src.domain.risk_calculator import RiskCalculator
from src.database.repositories.bet_repository import BetRepository

def test_full_matching_and_risk_flow():
    """Test complete flow: verify bets → match → calculate risk."""
    session = get_test_session()

    # Step 1: Create two opposite-side verified bets
    bet_over = create_verified_bet(
        session,
        side="OVER",
        line_value="2.5",
        stake="100",
        odds="1.95",
        currency="EUR"
    )

    bet_under = create_verified_bet(
        session,
        side="UNDER",
        line_value="2.5",
        stake="100",
        odds="2.05",
        currency="EUR"
    )

    assert bet_over.status == "verified"
    assert bet_under.status == "verified"

    # Step 2: Match bets using engine
    engine = MatchingEngine(session)

    # First bet creates no surebet yet
    surebet_id = engine.attempt_match_bet(bet_over.bet_id)
    assert surebet_id is None

    # Second bet triggers match
    surebet_id = engine.attempt_match_bet(bet_under.bet_id)
    assert surebet_id is not None

    # Step 3: Verify bets are matched
    session.refresh(bet_over)
    session.refresh(bet_under)

    assert bet_over.status == "matched"
    assert bet_under.status == "matched"

    # Step 4: Verify risk calculation
    from src.database.repositories.surebet_repository import SurebetRepository
    repo = SurebetRepository(session)

    surebet = session.query(Surebet).filter_by(surebet_id=surebet_id).one()

    assert surebet.worst_case_profit_eur is not None
    assert surebet.total_staked_eur is not None
    assert surebet.roi is not None
    assert surebet.risk_classification is not None

    # Step 5: Verify calculation correctness
    # Total staked: 200 EUR
    assert Decimal(surebet.total_staked_eur) == Decimal("200")

    # If OVER wins: 100*1.95 - 200 = -5
    # If UNDER wins: 100*2.05 - 200 = +5
    # Worst case: -5 (ROI: -2.5%)
    assert Decimal(surebet.worst_case_profit_eur) == Decimal("-5")
    assert surebet.roi < 0
    assert surebet.risk_classification == "UNSAFE"

    print("✅ Full matching and risk flow test passed!")
    print(f"   Surebet #{surebet_id}")
    print(f"   Worst-case profit: €{surebet.worst_case_profit_eur}")
    print(f"   ROI: {surebet.roi:.2f}%")
    print(f"   Classification: {surebet.risk_classification}")

# Helper (reuse from unit tests)
def create_verified_bet(session, side, line_value, stake, odds, currency):
    from src.database.models import Bet

    bet = Bet(
        status="verified",
        canonical_event_id=1,
        market_code="TOTAL_GOALS_OVER_UNDER",
        period_scope="FULL_MATCH",
        line_value=line_value,
        side=side,
        stake=stake,
        odds=odds,
        payout=str(Decimal(stake) * Decimal(odds)),
        currency=currency,
        is_supported=1,
        associate_id=1,
        bookmaker_id=1,
        screenshot_path="test.png",
        ingestion_source="test",
        created_at_utc="2025-01-01T00:00:00Z"
    )
    session.add(bet)
    session.commit()
    session.refresh(bet)
    return bet
```

Run: `pytest tests/integration/test_matching_flow.py -v`

---

## Deployment Checklist

### Prerequisites

- [ ] Epic 2 complete (verified bets exist)
- [ ] Phase 0 FX system populated (`fx_rates_daily` table has rates)
- [ ] Canonical events table has test data

### Database Migration

```bash
# Run migration 003
python -c "
from src.database.db import get_session
session = get_session()
with open('migrations/003_add_surebet_risk_fields.sql') as f:
    for stmt in f.read().split(';'):
        if stmt.strip():
            session.execute(stmt)
session.commit()
print('✅ Migration 003 complete')
"
```

### Testing Sequence

1. **Unit tests** (individual components)
2. **Integration test** (full flow)
3. **Manual UAT** (all 4 scenarios from epic)

---

## Manual Testing Guide

### Test Scenario 1: Perfect Match (Two Bets)

**Setup**: Two verified bets, opposite sides, same event/market/line

**Steps**:
1. Verify bet A (OVER 2.5)
2. Check Surebets page - no surebet yet
3. Verify bet B (UNDER 2.5)
4. Check Surebets page - surebet appears!
5. Verify both bets now `status="matched"`
6. Check risk badge color

**Expected**: Surebet created, risk calculated, both bets matched

---

### Test Scenario 2: Multi-Bet Surebet

**Setup**: Three bets (A1, A2 on one side, B on other)

**Steps**:
1. Verify bet A1 (YES)
2. Verify bet A2 (YES) - same side
3. Verify bet B (NO) - opposite side
4. Check Surebets page
5. Expand surebet card
6. Verify Side A shows 2 bets, Side B shows 1 bet

**Expected**: Single surebet with 3 bets total

---

### Test Scenario 3: Unsafe Surebet Detection

**Setup**: Intentionally unbalanced bets (negative worst-case)

**Steps**:
1. Create OVER bet: €100 @ 1.85
2. Create UNDER bet: €100 @ 1.85
3. Match both
4. Check risk badge: should be ❌ UNSAFE
5. View detailed calculation
6. Verify worst-case profit is negative

**Expected**: System flags unsafe surebet prominently

---

### Test Scenario 4: Multi-Currency ROI

**Setup**: Bets in different currencies (AUD, GBP)

**Steps**:
1. Create OVER bet: 150 AUD @ 1.90
2. Create UNDER bet: 100 GBP @ 2.00
3. Match both
4. Check EUR conversions in surebet card
5. Verify FX rates used correctly

**Expected**: EUR conversion accurate, ROI calculated in EUR

---

## Troubleshooting

### Issue: Bets not matching

**Symptoms**: Opposite-side bets stay `status="verified"`

**Checks**:
1. Same event? `SELECT canonical_event_id FROM bets WHERE bet_id IN (...)`
2. Same market/period/line? Check all matching fields
3. Opposite sides? Verify side mapping
4. Matching triggered? Check logs

**Fix**: Verify matching rules, check database indexes

---

### Issue: Risk calculation fails

**Symptoms**: Surebet created but risk fields NULL

**Checks**:
1. FX rates available? `SELECT * FROM fx_rates_daily`
2. Currency fields valid?
3. Decimal conversion errors? Check logs

**Fix**: Seed FX rates, verify Decimal handling

---

### Issue: Side immutability not enforced

**Symptoms**: Can update `surebet_bets.side` in database

**Checks**:
1. Trigger created? `SELECT name FROM sqlite_master WHERE type='trigger'`
2. Try UPDATE manually: should fail

**Fix**: Re-run migration 003

---

### Issue: Dashboard shows wrong risk color

**Symptoms**: Green badge for negative ROI

**Checks**:
1. Risk classification logic correct?
2. Threshold configured? (1.0%)
3. Database values correct?

**Fix**: Verify classification logic in RiskCalculator

---

## Performance Optimization

### Database Indexes

Epic 3 benefits from these indexes (from PRD):

```sql
-- Matching performance
CREATE INDEX idx_bets_matching ON bets(
    status, canonical_event_id, market_code,
    period_scope, line_value, side
);

-- Risk filtering
CREATE INDEX idx_surebets_risk ON surebets(risk_classification);

-- Kickoff sorting
CREATE INDEX idx_surebets_kickoff ON surebets(kickoff_time_utc);
```

### Caching Strategy

**FX Rates**: Cache in memory for session
**Surebets Query**: Cache with TTL=5s in Streamlit
**Risk Calculations**: Store in database (avoid recalculating)

---

## Next Steps

### After Epic 3 Completion

1. **Run Definition of Done** checklist
2. **Measure Success Metrics**:
   - Match accuracy: 100%?
   - False positive rate: 0%?
   - Risk detection: All unsafe flagged?
3. **Demo to stakeholders**: Show surebet dashboard
4. **Prepare for Epic 4**: Settlement workflow

### Epic 4 Preview

Epic 4 (Settlement) depends on:
- ✅ `status="open"` surebets exist
- ✅ Risk classifications available
- ✅ Side assignments (A/B) immutable

---

## Appendix: Quick Commands

### Check Matched Bets

```bash
sqlite3 data/surebet.db "SELECT bet_id, status, side FROM bets WHERE status='matched';"
```

### View Surebets with Risk

```bash
sqlite3 data/surebet.db "SELECT surebet_id, worst_case_profit_eur, roi, risk_classification FROM surebets WHERE status='open';"
```

### Test Side Immutability

```bash
# This should FAIL (trigger prevents it)
sqlite3 data/surebet.db "UPDATE surebet_bets SET side='B' WHERE side='A' LIMIT 1;"
```

### Check Matching Performance

```python
import time
from src.domain.matching_engine import MatchingEngine
from src.database.db import get_session

session = get_session()
engine = MatchingEngine(session)

start = time.time()
surebet_id = engine.attempt_match_bet(bet_id)
elapsed = time.time() - start

print(f"Matching took {elapsed:.3f}s")
# Target: <1s
```

---

**End of Implementation Guide**
