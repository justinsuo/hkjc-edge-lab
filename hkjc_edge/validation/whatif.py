"""Interactive what-if analysis over a fixed set of walk-forward OOS predictions.

Powers the app's "experiment" view: sweep the EV threshold (and optionally a probability
shrinkage toward the market) and see how many bets clear it and what the after-takeout ROI +
bootstrap CI would have been. Honest by construction — it reuses the same profit simulation as
Phase 3, so nothing here can conjure profit that the backtest didn't actually contain.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import profit_sim_value


def ev_threshold_sweep(oos: pd.DataFrame, prob_col: str = "p_combined",
                       thresholds=None, seed: int = 0) -> list[dict]:
    """For each EV threshold, return n_bets / ROI / CI / significance from the OOS backtest."""
    if thresholds is None:
        thresholds = [round(x, 3) for x in np.arange(-0.05, 0.41, 0.025)]
    out = []
    for t in thresholds:
        r = profit_sim_value(oos, prob_col, ev_threshold=float(t), seed=seed, n_boot=2000)
        out.append({
            "threshold": float(t),
            "n_bets": r.get("n_bets", 0),
            "roi": r.get("roi"),
            "roi_ci95": r.get("roi_ci95"),
            "roi_significant_positive": r.get("roi_significant_positive", False),
            "win_rate": r.get("win_rate"),
        })
    return out


def shrink_to_market(oos: pd.DataFrame, prob_col: str, weight: float) -> pd.DataFrame:
    """Blend model probs toward the market: p = w*model + (1-w)*market, renormalised per race.
    weight=1 -> pure model, weight=0 -> pure market. Lets the UI explore the bias/variance
    trade-off honestly (more market weight = closer to the unbeatable benchmark)."""
    d = oos.copy()
    blended = weight * d[prob_col] + (1.0 - weight) * d["p_market"]
    race_sum = blended.groupby(d["race_id"]).transform("sum")
    d["p_blend"] = blended / race_sum
    return d
