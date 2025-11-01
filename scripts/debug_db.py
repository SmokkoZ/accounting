import os
import sqlite3
import json


def main():
    db_path = os.getenv("DB_PATH", "data/surebet.db")
    print(f"DB: {db_path} exists: {os.path.exists(db_path)}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    print("\nOpen surebets (latest 10):")
    rows = conn.execute(
        """
        SELECT id, canonical_event_id, market_code, period_scope, line_value,
               worst_case_profit_eur, total_staked_eur, roi, risk_classification,
               created_at_utc, updated_at_utc
        FROM surebets
        WHERE status='open'
        ORDER BY id DESC
        LIMIT 10
        """
    ).fetchall()
    for r in rows:
        print(json.dumps(dict(r), indent=2))

    print("\nSurebet -> bets (latest surebet):")
    sid_row = conn.execute("SELECT id FROM surebets ORDER BY id DESC LIMIT 1").fetchone()
    if sid_row:
        sid = sid_row["id"]
        links = conn.execute(
            """
            SELECT sb.surebet_id, sb.side, b.id as bet_id, b.associate_id, b.bookmaker_id,
                   b.currency, b.stake_original, b.odds_original, b.stake_eur
            FROM surebet_bets sb
            JOIN bets b ON b.id = sb.bet_id
            WHERE sb.surebet_id = ?
            ORDER BY sb.side, b.associate_id
            """,
            (sid,),
        ).fetchall()
        for r in links:
            print(json.dumps(dict(r), indent=2))

    print("\nSchema: surebets")
    for r in conn.execute("PRAGMA table_info(surebets)").fetchall():
        print(r)

    print("\nSchema: bets")
    for r in conn.execute("PRAGMA table_info(bets)").fetchall():
        print(r)

    conn.close()


if __name__ == "__main__":
    main()

