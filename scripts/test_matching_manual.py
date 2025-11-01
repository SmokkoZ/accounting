"""
Manual testing script for Story 3.1: Deterministic Matching Engine

This script demonstrates the matching functionality by:
1. Creating test bets with opposite sides
2. Approving them (triggers automatic matching)
3. Verifying surebets were created correctly
"""

import sys
import sqlite3
from datetime import datetime, UTC
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.database import get_db_connection, initialize_database
from src.services.bet_verification import BetVerificationService
from src.services.surebet_matcher import SurebetMatcher


def create_test_bet(
    conn,
    associate_id=1,
    bookmaker_id=1,
    canonical_event_id=None,
    market_code="TOTAL_GOALS_OVER_UNDER",
    period_scope="FULL_MATCH",
    line_value="2.5",
    side="OVER",
    stake="100.00",
    odds="1.90",
):
    """Create a test bet in incoming status."""
    cursor = conn.execute(
        """
        INSERT INTO bets (
            associate_id, bookmaker_id, status, stake_eur, odds,
            currency, stake_original, odds_original, payout,
            canonical_event_id, market_code, period_scope, line_value,
            side, is_supported, ingestion_source,
            created_at_utc
        )
        VALUES (?, ?, 'incoming', ?, ?, 'EUR', ?, ?, ?, ?, ?, ?, ?, ?, 1, 'manual_upload', ?)
        """,
        (
            associate_id,
            bookmaker_id,
            stake,
            odds,
            stake,
            odds,
            str(float(stake) * float(odds)),
            canonical_event_id,
            market_code,
            period_scope,
            line_value,
            side,
            datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        ),
    )
    conn.commit()
    return cursor.lastrowid


def create_test_event(conn, event_name="Team A vs Team B"):
    """Create a test canonical event."""
    cursor = conn.execute(
        """
        INSERT INTO canonical_events (
            normalized_event_name, sport, league, kickoff_time_utc
        )
        VALUES (?, 'football', 'Premier League', ?)
        """,
        (event_name, "2025-11-15T15:00:00Z"),
    )
    conn.commit()
    return cursor.lastrowid


def print_separator(title):
    """Print a section separator."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def display_bets(conn, title="Bets"):
    """Display all bets."""
    cursor = conn.execute(
        """
        SELECT
            id, associate_id, status, side, market_code, line_value,
            stake_eur, odds, canonical_event_id
        FROM bets
        ORDER BY id
        """
    )
    bets = cursor.fetchall()

    print(f"\n{title}:")
    print("-" * 80)
    if bets:
        print(f"{'ID':<4} {'Assoc':<6} {'Status':<10} {'Side':<8} {'Market':<25} {'Line':<6} {'Stake':<8} {'Odds':<6} {'Event':<6}")
        print("-" * 80)
        for bet in bets:
            print(
                f"{bet[0]:<4} {bet[1]:<6} {bet[2]:<10} {bet[3] or 'N/A':<8} "
                f"{bet[4] or 'N/A':<25} {bet[5] or 'N/A':<6} {bet[6]:<8} {bet[7]:<6} {bet[8] or 'N/A':<6}"
            )
    else:
        print("  No bets found")


def display_surebets(conn):
    """Display all surebets and their linked bets."""
    cursor = conn.execute(
        """
        SELECT
            s.id, s.canonical_event_id, s.market_code, s.period_scope,
            s.line_value, s.status
        FROM surebets s
        ORDER BY s.id
        """
    )
    surebets = cursor.fetchall()

    print("\nSurebets:")
    print("-" * 80)
    if surebets:
        for surebet in surebets:
            print(f"\nSurebet #{surebet[0]}: {surebet[2]} {surebet[4] or ''} ({surebet[5]})")
            print(f"  Event ID: {surebet[1]}, Period: {surebet[3]}")

            # Get linked bets
            cursor = conn.execute(
                """
                SELECT sb.side, b.id, b.associate_id, b.side as bet_side,
                       b.stake_eur, b.odds, b.status
                FROM surebet_bets sb
                JOIN bets b ON sb.bet_id = b.id
                WHERE sb.surebet_id = ?
                ORDER BY sb.side, b.id
                """,
                (surebet[0],),
            )
            linked_bets = cursor.fetchall()

            print(f"  Linked Bets:")
            for link in linked_bets:
                print(
                    f"    Side {link[0]}: Bet #{link[1]} (Assoc {link[2]}, {link[3]}, "
                    f"€{link[4]} @ {link[5]}, {link[6]})"
                )
    else:
        print("  No surebets found")


def test_scenario_1_basic_over_under_matching(conn):
    """
    Test Scenario 1: Basic OVER/UNDER Matching

    Create two bets with opposite sides and verify they match.
    """
    print_separator("TEST SCENARIO 1: Basic OVER/UNDER Matching")

    # Create canonical event
    event_id = create_test_event(conn, "Man Utd vs Liverpool")
    print(f"\n[OK] Created test event #{event_id}: Man Utd vs Liverpool")

    # Create OVER bet
    bet_over_id = create_test_bet(
        conn,
        associate_id=1,
        canonical_event_id=event_id,
        market_code="TOTAL_GOALS_OVER_UNDER",
        line_value="2.5",
        side="OVER",
        stake="100.00",
        odds="1.90",
    )
    print(f"[OK] Created OVER bet #{bet_over_id}")

    # Create UNDER bet
    bet_under_id = create_test_bet(
        conn,
        associate_id=2,
        canonical_event_id=event_id,
        market_code="TOTAL_GOALS_OVER_UNDER",
        line_value="2.5",
        side="UNDER",
        stake="100.00",
        odds="2.10",
    )
    print(f"[OK] Created UNDER bet #{bet_under_id}")

    display_bets(conn, "Before Approval")

    # Approve OVER bet (should trigger matching)
    print(f"\n-> Approving OVER bet #{bet_over_id}...")
    service = BetVerificationService(conn)
    service.approve_bet(bet_over_id)

    display_bets(conn, "After Approving OVER Bet")

    # Approve UNDER bet (should add to existing surebet)
    print(f"\n-> Approving UNDER bet #{bet_under_id}...")
    service.approve_bet(bet_under_id)

    display_bets(conn, "After Approving UNDER Bet")
    display_surebets(conn)

    # Verify results
    cursor = conn.execute("SELECT COUNT(*) FROM surebets")
    surebet_count = cursor.fetchone()[0]

    cursor = conn.execute("SELECT COUNT(*) FROM surebet_bets")
    link_count = cursor.fetchone()[0]

    cursor = conn.execute("SELECT COUNT(*) FROM bets WHERE status = 'matched'")
    matched_count = cursor.fetchone()[0]

    print("\n[OK] Verification:")
    print(f"  - Surebets created: {surebet_count} (expected: 1)")
    print(f"  - Bet links created: {link_count} (expected: 2)")
    print(f"  - Matched bets: {matched_count} (expected: 2)")

    assert surebet_count == 1, "Should create 1 surebet"
    assert link_count == 2, "Should link 2 bets"
    assert matched_count == 2, "Should mark 2 bets as matched"

    print("\n[PASS] TEST PASSED: Basic OVER/UNDER matching works correctly")


def test_scenario_2_multiple_bets_same_side(conn):
    """
    Test Scenario 2: Multiple Bets on Same Side

    Create A1 + A2 vs B1 and verify all go into one surebet.
    """
    print_separator("TEST SCENARIO 2: Multiple Bets on Same Side (A1 + A2 vs B1)")

    # Create event
    event_id = create_test_event(conn, "Chelsea vs Arsenal")
    print(f"\n[OK] Created test event #{event_id}: Chelsea vs Arsenal")

    # Create two YES bets (Side A)
    bet_yes1_id = create_test_bet(
        conn,
        associate_id=1,
        canonical_event_id=event_id,
        market_code="BOTH_TEAMS_TO_SCORE",
        line_value=None,
        side="YES",
        stake="50.00",
        odds="1.75",
    )
    print(f"[OK] Created YES bet #1: #{bet_yes1_id}")

    bet_yes2_id = create_test_bet(
        conn,
        associate_id=2,
        canonical_event_id=event_id,
        market_code="BOTH_TEAMS_TO_SCORE",
        line_value=None,
        side="YES",
        stake="75.00",
        odds="1.80",
    )
    print(f"[OK] Created YES bet #2: #{bet_yes2_id}")

    # Create one NO bet (Side B)
    bet_no_id = create_test_bet(
        conn,
        associate_id=3,
        canonical_event_id=event_id,
        market_code="BOTH_TEAMS_TO_SCORE",
        line_value=None,
        side="NO",
        stake="100.00",
        odds="2.20",
    )
    print(f"[OK] Created NO bet: #{bet_no_id}")

    display_bets(conn, "Before Approval")

    # Approve all bets
    service = BetVerificationService(conn)

    print(f"\n-> Approving YES bet #1 (#{bet_yes1_id})...")
    service.approve_bet(bet_yes1_id)

    print(f"-> Approving YES bet #2 (#{bet_yes2_id})...")
    service.approve_bet(bet_yes2_id)

    print(f"-> Approving NO bet (#{bet_no_id})...")
    service.approve_bet(bet_no_id)

    display_bets(conn, "After Approving All Bets")
    display_surebets(conn)

    # Verify results - get the second surebet (from this test)
    cursor = conn.execute("SELECT MAX(id) FROM surebets")
    latest_surebet_id = cursor.fetchone()[0]

    cursor = conn.execute("SELECT COUNT(*) FROM surebets")
    surebet_count = cursor.fetchone()[0]

    cursor = conn.execute("SELECT COUNT(*) FROM surebet_bets WHERE surebet_id = ? AND side = 'A'", (latest_surebet_id,))
    side_a_count = cursor.fetchone()[0]

    cursor = conn.execute("SELECT COUNT(*) FROM surebet_bets WHERE surebet_id = ? AND side = 'B'", (latest_surebet_id,))
    side_b_count = cursor.fetchone()[0]

    print("\n[OK] Verification:")
    print(f"  - Surebets created: {surebet_count} (expected: 2 total)")
    print(f"  - Side A bets in surebet #{latest_surebet_id}: {side_a_count} (expected: 2)")
    print(f"  - Side B bets in surebet #{latest_surebet_id}: {side_b_count} (expected: 1)")

    assert side_a_count == 2, "Should have 2 bets on Side A"
    assert side_b_count == 1, "Should have 1 bet on Side B"

    print("\n[PASS] TEST PASSED: Multiple bets on same side handled correctly")


def test_scenario_3_no_match_without_opposite(conn):
    """
    Test Scenario 3: No Match Without Opposite Side

    Create only one side and verify no surebet is created.
    """
    print_separator("TEST SCENARIO 3: No Match Without Opposite Side")

    # Create event
    event_id = create_test_event(conn, "Barcelona vs Real Madrid")
    print(f"\n[OK] Created test event #{event_id}: Barcelona vs Real Madrid")

    # Create only TEAM_A bet
    bet_team_a_id = create_test_bet(
        conn,
        associate_id=1,
        canonical_event_id=event_id,
        market_code="MATCH_WINNER",
        line_value=None,
        side="TEAM_A",
        stake="100.00",
        odds="2.50",
    )
    print(f"[OK] Created TEAM_A bet: #{bet_team_a_id}")

    display_bets(conn, "Before Approval")

    # Count surebets before
    cursor = conn.execute("SELECT COUNT(*) FROM surebets")
    surebets_before = cursor.fetchone()[0]

    # Approve bet
    service = BetVerificationService(conn)
    print(f"\n-> Approving TEAM_A bet (#{bet_team_a_id})...")
    service.approve_bet(bet_team_a_id)

    display_bets(conn, "After Approval")

    # Count surebets after
    cursor = conn.execute("SELECT COUNT(*) FROM surebets")
    surebets_after = cursor.fetchone()[0]

    # Check bet status
    cursor = conn.execute("SELECT status FROM bets WHERE id = ?", (bet_team_a_id,))
    bet_status = cursor.fetchone()[0]

    print("\n[OK] Verification:")
    print(f"  - Surebets before: {surebets_before}")
    print(f"  - Surebets after: {surebets_after}")
    print(f"  - New surebets created: {surebets_after - surebets_before} (expected: 0)")
    print(f"  - Bet status: {bet_status} (expected: verified)")

    assert surebets_after == surebets_before, "Should not create new surebet"
    assert bet_status == "verified", "Bet should remain in verified status"

    print("\n[PASS] TEST PASSED: No match created without opposite side")


def test_scenario_4_idempotency(conn):
    """
    Test Scenario 4: Matching Idempotency

    Verify that re-running match on already matched bet does nothing.
    """
    print_separator("TEST SCENARIO 4: Matching Idempotency")

    # Get a matched bet from previous tests
    cursor = conn.execute("SELECT id FROM bets WHERE status = 'matched' LIMIT 1")
    result = cursor.fetchone()

    if not result:
        print("[WARN] Skipping: No matched bets available from previous tests")
        return

    bet_id = result[0]
    print(f"\n[OK] Using existing matched bet #{bet_id}")

    # Count surebet_bets links before
    cursor = conn.execute("SELECT COUNT(*) FROM surebet_bets WHERE bet_id = ?", (bet_id,))
    links_before = cursor.fetchone()[0]

    # Try matching again
    matcher = SurebetMatcher(conn)
    print(f"\n-> Attempting to match bet #{bet_id} again...")
    surebet_id = matcher.attempt_match(bet_id)

    # Count links after
    cursor = conn.execute("SELECT COUNT(*) FROM surebet_bets WHERE bet_id = ?", (bet_id,))
    links_after = cursor.fetchone()[0]

    print("\n[OK] Verification:")
    print(f"  - Links before: {links_before}")
    print(f"  - Links after: {links_after}")
    print(f"  - Returned surebet_id: {surebet_id}")
    print(f"  - Duplicate links created: {links_after - links_before} (expected: 0)")

    assert links_after == links_before, "Should not create duplicate links"
    assert surebet_id is not None, "Should return existing surebet_id"

    print("\n[PASS] TEST PASSED: Idempotency works correctly")


def run_manual_tests():
    """Run all manual test scenarios."""
    print("\n" + "=" * 80)
    print("  MANUAL TESTING: Story 3.1 - Deterministic Matching Engine")
    print("=" * 80)

    # Initialize fresh test database
    print("\nInitializing test database...")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    from src.core.schema import create_schema
    from src.core.seed_data import insert_seed_data

    create_schema(conn)
    insert_seed_data(conn)
    print("[OK] Database initialized with seed data")

    try:
        # Run test scenarios
        test_scenario_1_basic_over_under_matching(conn)
        test_scenario_2_multiple_bets_same_side(conn)
        test_scenario_3_no_match_without_opposite(conn)
        test_scenario_4_idempotency(conn)

        # Final summary
        print_separator("MANUAL TESTING COMPLETE")
        print("\n[PASS] ALL TEST SCENARIOS PASSED")
        print("\nSummary:")
        display_bets(conn, "Final Bets State")
        display_surebets(conn)

    except AssertionError as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        raise
    except Exception as e:
        print(f"\n[FAIL] ERROR: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run_manual_tests()
