"""Phase 3 validation: profit-sim math, CLV detection, walk-forward normalisation.

We synthesise races with a known true win distribution q and market odds O_i = (1-t)/m_i
where m is the market's (possibly wrong) belief. Then de-vigged market prob == m, and a $1
win bet at q has EV = q_i*O_i - 1 = (1-t)*q_i/m_i - 1.  If model==market==truth, EV = -t.
"""
import numpy as np
import pandas as pd

from hkjc_edge.validation.metrics import (
    baseline_bet_all, bootstrap_margin, profit_sim_value,
)
from hkjc_edge.validation.walkforward import walk_forward

TAKEOUT = 0.175


def _make_oos(n_races=400, field=8, seed=0, model="true", market="true"):
    rng = np.random.default_rng(seed)
    rows = []
    for r in range(n_races):
        q = rng.dirichlet(np.ones(field) * 0.7)              # true win probs
        if market == "true":
            m = q.copy()
        else:                                                # mis-calibrated market (flattened)
            m = 0.5 * q + 0.5 * (np.ones(field) / field)
            m /= m.sum()
        O = (1 - TAKEOUT) / m                                 # decimal odds (de-vig == m)
        pm = (1 / O) / (1 / O).sum()                          # == m
        pc = q if model == "true" else pm
        winner = rng.choice(field, p=q)
        for h in range(field):
            rows.append({"race_id": r, "race_date": pd.Timestamp("2025-01-01") + pd.Timedelta(days=r),
                         "horse_no": h + 1, "win_odds": float(O[h]),
                         "p_market": float(pm[h]), "p_combined": float(pc[h]),
                         "p_fund": float(pc[h]),
                         "label_won": 1 if h == winner else 0,
                         "finish_pos": 1 if h == winner else 2})
    return pd.DataFrame(rows)


def test_bet_all_roi_is_minus_takeout():
    # Fixed, moderate odds structure (no extreme longshots) so the realized mean converges
    # tightly to the analytic EV of -takeout. (With heavy-tailed odds the identity still
    # holds in expectation but the estimator is high-variance.)
    rng = np.random.default_rng(0)
    q = np.array([6, 5, 4, 3, 2, 1], float)
    q /= q.sum()
    O = (1 - TAKEOUT) / q
    rows = []
    for r in range(6000):
        winner = rng.choice(len(q), p=q)
        for h in range(len(q)):
            rows.append({"race_id": r, "win_odds": float(O[h]),
                         "label_won": 1 if h == winner else 0})
    roi = baseline_bet_all(pd.DataFrame(rows))["roi"]
    assert abs(roi - (-TAKEOUT)) < 0.02, f"bet-all ROI {roi} should be ~ -{TAKEOUT}"


def test_following_market_makes_no_value_bets():
    oos = _make_oos(n_races=300, model="market", market="true")
    res = profit_sim_value(oos, "p_combined", ev_threshold=0.0)
    # EV = -takeout for every runner -> nothing clears EV>0
    assert res["n_bets"] == 0


def test_clv_no_edge_not_significant():
    oos = _make_oos(n_races=300, model="market", market="true")
    bm = bootstrap_margin(oos, "p_combined")
    assert not bm["significant_at_95"]
    assert bm["ci95"][0] <= 0 <= bm["ci95"][1]


def test_clv_detects_real_edge_and_profit():
    # model knows the truth; market is mis-calibrated -> model should beat the closing line
    oos = _make_oos(n_races=600, model="true", market="wrong", seed=3)
    bm = bootstrap_margin(oos, "p_combined")
    assert bm["mean_margin"] > 0 and bm["significant_at_95"], bm
    prof = profit_sim_value(oos, "p_combined", ev_threshold=0.0)
    assert prof["n_bets"] > 0
    assert prof["roi"] > 0  # a genuine edge turns a profit after takeout


def _make_dataset(n_races=60, field=8, seed=1):
    """Minimal build_dataset-shaped frame for walk_forward."""
    rng = np.random.default_rng(seed)
    rows = []
    for r in range(n_races):
        q = rng.dirichlet(np.ones(field))
        O = (1 - TAKEOUT) / q
        pm = (1 / O) / (1 / O).sum()
        winner = rng.choice(field, p=q)
        for h in range(field):
            rows.append({"race_id": r, "race_date": pd.Timestamp("2025-01-01") + pd.Timedelta(days=r),
                         "horse_no": h + 1, "horse_id": h + 1, "draw": h + 1,
                         "actual_weight": 120, "declared_weight": 1050,
                         "jockey_id": 1, "trainer_id": 1, "distance_m": 1200,
                         "going": "GOOD", "track": "Turf", "class": "Class 4",
                         "field_size": field, "market_prob": float(pm[h]),
                         "win_odds": float(O[h]), "label_won": 1 if h == winner else 0,
                         "finish_pos": 1 if h == winner else 2})
    return pd.DataFrame(rows)


def test_walk_forward_runs_and_normalises():
    df = _make_dataset(n_races=60)
    oos = walk_forward(df, min_train_races=20, step_races=10, l2=5.0)
    assert oos["race_id"].nunique() >= 30           # races after the initial train window
    for col in ["p_market", "p_combined", "p_fund"]:
        sums = oos.groupby("race_id")[col].sum()
        assert np.allclose(sums.values, 1.0, atol=1e-6)
