"""Reconcile logged recommendations with actual results — the tool grades itself.

For each unsettled recommendation we fill the closing odds (the result SP), the outcome, the
realized P&L (for BET decisions, paid at the closing SP), and the closing-line value
(odds_at_rec vs closing). Aggregates let the tool detect if its live behaviour diverges from
the backtest.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..db import Database


def reconcile(db: Database) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = db.execute(
        """SELECT r.rec_id, r.race_id, r.horse_no, r.odds_at_rec, r.decision, r.stake
           FROM recommendation r WHERE r.settled_at IS NULL""").fetchall()
    settled = 0
    for rec_id, race_id, horse_no, odds_at_rec, decision, stake in rows:
        res = db.execute(
            "SELECT finish_pos, win_odds FROM result WHERE race_id=? AND horse_no=?",
            (race_id, horse_no)).fetchone()
        if not res or res[0] is None:
            continue                                 # race not yet resulted
        finish_pos, closing = res[0], res[1]
        won = 1 if finish_pos == 1 else 0
        pnl = 0.0
        if decision == "BET" and stake and closing:
            pnl = (closing - 1.0) * stake if won else -stake
        clv = (odds_at_rec / closing - 1.0) if (odds_at_rec and closing) else None
        db.execute(
            """UPDATE recommendation SET closing_odds=?, finish_pos=?, won=?, pnl=?, clv=?,
               settled_at=? WHERE rec_id=?""",
            (closing, finish_pos, won, round(pnl, 2),
             round(clv, 4) if clv is not None else None, now, rec_id))
        settled += 1
    db.commit()
    return _summary(db, newly_settled=settled)


def _summary(db: Database, newly_settled: int = 0) -> dict:
    total = db.execute("SELECT COUNT(*) FROM recommendation").fetchone()[0]
    bets = db.execute(
        "SELECT COUNT(*), COALESCE(SUM(stake),0), COALESCE(SUM(pnl),0) "
        "FROM recommendation WHERE decision='BET' AND settled_at IS NOT NULL").fetchone()
    n_bets, staked, pnl = bets[0], bets[1], bets[2]
    clv_row = db.execute(
        "SELECT AVG(clv) FROM recommendation WHERE clv IS NOT NULL").fetchone()
    return {
        "newly_settled": newly_settled,
        "total_recommendations": total,
        "settled_bets": n_bets,
        "total_staked": round(staked, 2),
        "total_pnl": round(pnl, 2),
        "roi": round(pnl / staked, 4) if staked else None,
        "avg_clv": round(clv_row[0], 5) if clv_row[0] is not None else None,
    }


def summary(db: Database) -> dict:
    return _summary(db)
