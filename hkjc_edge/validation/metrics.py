"""Validation metrics: closing-line value, profit simulation, bootstrap CIs.

KEY HONEST MECHANICS:
  * HKJC win odds are pari-mutuel and ALREADY net of takeout. So for a $1 win bet at decimal
    odds O, EV = p_model * O - 1, with the takeout implicitly inside O. If p_model equals the
    de-vigged market prob, EV = (1 - takeout) - 1 = -takeout exactly. To have +EV the model
    must rate a horse enough above the market to clear the ~17.5% takeout hurdle.
  * "Beating the closing line" in a tote = being better calibrated than the closing odds.
    The primary CLV test is therefore the OOS race-winner log-loss of the model vs the market,
    with a bootstrap CI on the margin. No significant improvement => no edge.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---- log-loss / CLV -------------------------------------------------------------------

def per_race_winner_ll(df: pd.DataFrame, col: str) -> dict:
    out = {}
    for rid, g in df.groupby("race_id"):
        w = g[g["label_won"] == 1]
        if len(w):
            out[rid] = -np.log(max(float(w[col].mean()), 1e-12))
    return out


def winner_logloss(df: pd.DataFrame, col: str) -> float:
    v = list(per_race_winner_ll(df, col).values())
    return float(np.mean(v)) if v else float("nan")


def bootstrap_margin(df: pd.DataFrame, model_col: str, market_col: str = "p_market",
                     n_boot: int = 5000, seed: int = 0) -> dict:
    """Bootstrap per-race winner-log-loss margin (market - model). >0 => model better."""
    m = per_race_winner_ll(df, market_col)
    c = per_race_winner_ll(df, model_col)
    rids = sorted(set(m) & set(c))
    diff = np.array([m[r] - c[r] for r in rids])
    if len(diff) == 0:
        return {}
    rng = np.random.default_rng(seed)
    boot = np.array([rng.choice(diff, len(diff), replace=True).mean() for _ in range(n_boot)])
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return {"mean_margin": round(float(diff.mean()), 5),
            "ci95": [round(float(lo), 5), round(float(hi), 5)],
            "p_positive": round(float((boot > 0).mean()), 3),
            "significant_at_95": bool(lo > 0),
            "n_races": int(len(diff))}


def clv_report(oos: pd.DataFrame) -> dict:
    market_ll = winner_logloss(oos, "p_market")
    rep = {"market_winner_logloss": round(market_ll, 5), "models": {}}
    for col in ["p_combined", "p_fund"]:
        if col in oos:
            rep["models"][col] = {
                "winner_logloss": round(winner_logloss(oos, col), 5),
                "bootstrap_vs_market": bootstrap_margin(oos, col),
            }
    return rep


# ---- profit simulation ----------------------------------------------------------------

def profit_sim_value(oos: pd.DataFrame, prob_col: str, *, ev_threshold: float = 0.0,
                     seed: int = 0, n_boot: int = 5000) -> dict:
    """Flat-stake value betting: bet 1 unit on each runner whose model EV > threshold.
    ROI is per unit staked. Bootstrap CI resamples bets."""
    d = oos.dropna(subset=["win_odds", prob_col]).copy()
    d = d[d["win_odds"] > 1.0]
    d["ev"] = d[prob_col] * d["win_odds"] - 1.0
    bets = d[d["ev"] > ev_threshold].copy()
    if len(bets) == 0:
        return {"n_bets": 0, "roi": None, "note": "no bets cleared the EV threshold"}
    bets["pnl"] = np.where(bets["label_won"] == 1, bets["win_odds"] - 1.0, -1.0)
    pnl = bets["pnl"].values
    roi = float(pnl.mean())                         # per unit staked (flat 1u)
    rng = np.random.default_rng(seed)
    boot = np.array([rng.choice(pnl, len(pnl), replace=True).mean() for _ in range(n_boot)])
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return {
        "n_bets": int(len(bets)),
        "win_rate": round(float((bets["label_won"] == 1).mean()), 4),
        "avg_ev_claimed": round(float(bets["ev"].mean()), 4),
        "roi": round(roi, 4),
        "roi_ci95": [round(float(lo), 4), round(float(hi), 4)],
        "roi_significant_positive": bool(lo > 0),
        "total_pnl_units": round(float(pnl.sum()), 2),
        "cum_pnl": np.cumsum(pnl).tolist(),
    }


def fractional_kelly_growth(oos: pd.DataFrame, prob_col: str, *, ev_threshold: float = 0.0,
                            fraction: float = 0.25, per_bet_cap: float = 0.05,
                            bankroll0: float = 1.0) -> dict:
    """Fractional-Kelly bankroll growth in time order. Per-bet stake capped as a fraction of
    current bankroll. Returns final bankroll multiple and the equity curve."""
    d = oos.dropna(subset=["win_odds", prob_col]).copy()
    d = d[d["win_odds"] > 1.0].sort_values(["race_date", "race_id"])
    bank = bankroll0
    curve = []
    n_bets = 0
    for _, r in d.iterrows():
        O = float(r["win_odds"]); p = float(r[prob_col]); b = O - 1.0
        ev = p * O - 1.0
        if ev > ev_threshold and b > 0:
            f = max(0.0, (p * b - (1 - p)) / b)     # full-Kelly fraction
            stake = min(fraction * f, per_bet_cap) * bank
            bank += (O - 1.0) * stake if r["label_won"] == 1 else -stake
            n_bets += 1
        curve.append(bank)
    return {"final_bankroll_multiple": round(bank / bankroll0, 4), "n_bets": n_bets,
            "equity_curve": curve}


# ---- baselines (sanity) ---------------------------------------------------------------

def baseline_bet_all(oos: pd.DataFrame) -> dict:
    """Flat-bet EVERY runner. ROI must be ~ -takeout (the algebraic certainty from Phase 0)."""
    d = oos.dropna(subset=["win_odds"])
    d = d[d["win_odds"] > 1.0]
    pnl = np.where(d["label_won"] == 1, d["win_odds"] - 1.0, -1.0)
    return {"n_bets": int(len(d)), "roi": round(float(pnl.mean()), 4)}


def baseline_bet_favorite(oos: pd.DataFrame) -> dict:
    """Flat-bet the market favourite (shortest odds) in each race. ROI ~ -takeout if efficient."""
    rows = []
    for _, g in oos.dropna(subset=["win_odds"]).groupby("race_id"):
        fav = g.loc[g["win_odds"].idxmin()]
        rows.append(fav["win_odds"] - 1.0 if fav["label_won"] == 1 else -1.0)
    pnl = np.array(rows)
    return {"n_bets": int(len(pnl)), "roi": round(float(pnl.mean()), 4) if len(pnl) else None}
