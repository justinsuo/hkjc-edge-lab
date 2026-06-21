"""Honest cross-pool consistency checks — SIGNALS, never arbitrage.

From the WIN pool we derive (via Harville) what the PLACE pool "should" pay, then compare to
the actual place dividends. A horse whose place dividend is far more generous than its win
chances imply is a cross-pool *inconsistency signal* — information, not free money.

WHY THIS IS NOT ARBITRAGE (see research_report.md §3): the pools settle on different events,
each has its own takeout, the dividends are provisional until the pool closes, your bets move
each pool, there is no lay side, and the Win→place mapping depends on the Harville
approximation (biased). So we label these signals and never call them arbitrage.

HKJC dividend convention: dividends are quoted per HK$10 stake, so decimal odds = dividend/10.
"""
from __future__ import annotations

import numpy as np

from ..model.harville import default_place_k, harville_place_probs


def place_decimal(dividend_hkd: float) -> float:
    return dividend_hkd / 10.0


def cross_pool_place_signal(win_probs_market, win_probs_model, place_div_by_horse: dict,
                            horse_nos, *, takeout_place: float = 0.175) -> dict:
    """Compare Win-pool-implied place value to the actual Place pool.

    place_div_by_horse: {horse_no: place_dividend_hkd}. Returns per-horse rows with the
    market/model Harville place prob, the actual place dividend, and the place-bet EV implied
    by each. If pools were perfectly internally consistent + efficient, EV(market) ≈ -takeout
    for every placed horse; large positive deviations are the signal.
    """
    field = len(horse_nos)
    k = default_place_k(field)
    mkt = np.asarray(win_probs_market, float)
    mdl = np.asarray(win_probs_model, float)
    pl_mkt = harville_place_probs(mkt, k) if k else np.zeros(field)
    pl_mdl = harville_place_probs(mdl, k) if k else np.zeros(field)

    rows = []
    for i, hn in enumerate(horse_nos):
        div = place_div_by_horse.get(hn)
        if div is None:
            continue
        D = place_decimal(div)
        rows.append({
            "horse_no": int(hn),
            "win_prob_market": round(float(mkt[i]), 4),
            "place_prob_market": round(float(pl_mkt[i]), 4),
            "place_prob_model": round(float(pl_mdl[i]), 4),
            "place_dividend": round(float(div), 2),
            "place_ev_market": round(float(pl_mkt[i] * D - 1.0), 4),
            "place_ev_model": round(float(pl_mdl[i] * D - 1.0), 4),
        })
    rows.sort(key=lambda r: r["place_ev_market"], reverse=True)
    return {
        "place_slots_k": k,
        "expected_market_ev": round(-takeout_place, 4),
        "note": "SIGNAL only — NOT arbitrage. Harville-approximate; pools provisional, "
                "separate takeouts, no lay side. See research_report.md §3.",
        "rows": rows,
    }
