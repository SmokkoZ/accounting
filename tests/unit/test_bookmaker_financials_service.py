"""
Unit tests for BookmakerFinancialsService.
"""

import sqlite3
from decimal import Decimal

from src.services.bookmaker_financials_service import BookmakerFinancialsService


class TestBookmakerFinancialsService:
    """Validate bookmaker financial enrichment logic."""

    def setup_method(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        self._seed_base_data()

    def teardown_method(self) -> None:
        self.conn.close()

    def _create_tables(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE associates (
                id INTEGER PRIMARY KEY,
                display_alias TEXT,
                home_currency TEXT
            );
            CREATE TABLE bookmakers (
                id INTEGER PRIMARY KEY,
                associate_id INTEGER NOT NULL,
                bookmaker_name TEXT NOT NULL,
                parsing_profile TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at_utc TEXT,
                updated_at_utc TEXT
            );
            CREATE TABLE bets (
                id INTEGER PRIMARY KEY,
                associate_id INTEGER,
                bookmaker_id INTEGER,
                status TEXT,
                stake_eur TEXT
            );
            CREATE TABLE ledger_entries (
                id INTEGER PRIMARY KEY,
                type TEXT,
                associate_id INTEGER,
                bookmaker_id INTEGER,
                amount_eur TEXT,
                principal_returned_eur TEXT,
                per_surebet_share_eur TEXT
            );
            CREATE TABLE fx_rates_daily (
                id INTEGER PRIMARY KEY,
                currency_code TEXT,
                rate_to_eur TEXT,
                fetched_at_utc TEXT,
                date TEXT,
                created_at_utc TEXT
            );
            CREATE TABLE bookmaker_balance_checks (
                id INTEGER PRIMARY KEY,
                associate_id INTEGER,
                bookmaker_id INTEGER,
                balance_native TEXT,
                native_currency TEXT,
                balance_eur TEXT,
                fx_rate_used TEXT,
                check_date_utc TEXT
            );
            """
        )

    def _seed_base_data(self) -> None:
        self.conn.executemany(
            "INSERT INTO associates (id, display_alias, home_currency) VALUES (?, ?, ?)",
            [
                (1, "Alpha", "EUR"),
                (2, "Bravo", "GBP"),
            ],
        )
        self.conn.executemany(
            """
            INSERT INTO bookmakers (id, associate_id, bookmaker_name, parsing_profile, is_active, created_at_utc, updated_at_utc)
            VALUES (?, ?, ?, ?, 1, '2025-01-01T00:00:00Z', '2025-01-01T00:00:00Z')
            """,
            [
                (10, 1, "BetMax", '{"ocr": "hint"}'),
                (20, 2, "SureHold", None),
            ],
        )

    def test_financial_snapshot_with_balance_checks(self) -> None:
        """Service aggregates balances, deposits, and profits with FX hints."""
        self.conn.execute(
            """
            INSERT INTO bookmaker_balance_checks (
                associate_id, bookmaker_id, balance_native, native_currency,
                balance_eur, fx_rate_used, check_date_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, 10, "1500.00", "USD", "750.00", "0.50", "2025-01-09T12:00:00Z"),
        )
        # Pending bets (sum 150)
        self.conn.executemany(
            """
            INSERT INTO bets (associate_id, bookmaker_id, status, stake_eur)
            VALUES (?, ?, ?, ?)
            """,
            [
                (1, 10, "verified", "100.00"),
                (1, 10, "matched", "50.00"),
            ],
        )
        # Funding entries: deposit 200, withdrawal 50 => net 150
        self.conn.executemany(
            """
            INSERT INTO ledger_entries (
                type, associate_id, bookmaker_id, amount_eur, principal_returned_eur, per_surebet_share_eur
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("DEPOSIT", 1, 10, "200.00", None, None),
                ("WITHDRAWAL", 1, 10, "50.00", None, None),
                ("BET_RESULT", 1, 10, "0.00", "300.00", "120.00"),
            ],
        )

        service = BookmakerFinancialsService(self.conn)
        snapshots = service.get_financials_for_associate(1)
        assert len(snapshots) == 1
        snap = snapshots[0]

        assert snap.balance_eur == Decimal("750.00")
        assert snap.balance_native == Decimal("1500.00")
        assert snap.pending_balance_eur == Decimal("150.00")
        assert snap.pending_balance_native == Decimal("300.00")
        assert snap.net_deposits_eur == Decimal("150.00")
        assert snap.net_deposits_native == Decimal("300.00")
        assert snap.profits_eur == Decimal("270.00")
        assert snap.profits_native == Decimal("540.00")
        assert snap.native_currency == "USD"
        assert snap.latest_balance_check_date == "2025-01-09T12:00:00Z"

    def test_financial_snapshot_uses_fx_cache_without_balance_check(self) -> None:
        """Service falls back to fx_rates_daily when no balance hints exist."""
        self.conn.execute(
            """
            INSERT INTO fx_rates_daily (
                currency_code, rate_to_eur, fetched_at_utc, date, created_at_utc
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("GBP", "1.25", "2025-01-01T00:00:00Z", "2025-01-01", "2025-01-01T00:00:00Z"),
        )
        self.conn.execute(
            """
            INSERT INTO bets (associate_id, bookmaker_id, status, stake_eur)
            VALUES (?, ?, ?, ?)
            """,
            (2, 20, "verified", "20.00"),
        )
        self.conn.executemany(
            """
            INSERT INTO ledger_entries (
                type, associate_id, bookmaker_id, amount_eur, principal_returned_eur, per_surebet_share_eur
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("DEPOSIT", 2, 20, "100.00", None, None),
                ("BET_RESULT", 2, 20, "0.00", "120.00", "30.00"),
            ],
        )

        service = BookmakerFinancialsService(self.conn)
        snapshots = service.get_financials_for_associate(2)
        assert len(snapshots) == 1
        snap = snapshots[0]

        assert snap.balance_eur is None
        assert snap.balance_native is None
        assert snap.pending_balance_eur == Decimal("20.00")
        assert snap.pending_balance_native == Decimal("16.00")  # 20 / 1.25
        assert snap.net_deposits_eur == Decimal("100.00")
        assert snap.net_deposits_native == Decimal("80.00")
        assert snap.profits_eur == Decimal("50.00")
        assert snap.profits_native == Decimal("40.00")
        assert snap.native_currency == "GBP"
        assert snap.latest_balance_check_date is None
