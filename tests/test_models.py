"""Conditional-logit and GBM win models: recover signal, normalise per race."""
import numpy as np
import pandas as pd

from hkjc_edge.model.conditional_logit import ConditionalLogit
from hkjc_edge.model.gbm import GBMWinModel


def _synthetic_pl(n_races=400, field=8, seed=0):
    """Generate races where the winner is a Plackett-Luce draw from a known linear utility."""
    rng = np.random.default_rng(seed)
    true_beta = np.array([1.5, -0.8])
    rows = []
    for r in range(n_races):
        X = rng.normal(size=(field, 2))
        u = X @ true_beta
        p = np.exp(u - u.max())
        p /= p.sum()
        winner = rng.choice(field, p=p)
        for h in range(field):
            rows.append({"race_id": r, "x0": X[h, 0], "x1": X[h, 1],
                         "won": 1 if h == winner else 0})
    return pd.DataFrame(rows)


def test_conditional_logit_recovers_signal_and_normalises():
    df = _synthetic_pl()
    X = df[["x0", "x1"]]
    model = ConditionalLogit(l2=0.01).fit(X, df["won"].values, df["race_id"].values)
    # recovered signs match the generating betas
    assert model.beta_[0] > 0 and model.beta_[1] < 0

    p = model.predict_proba(X, df["race_id"].values)
    df = df.assign(p=p)
    sums = df.groupby("race_id")["p"].sum()
    assert np.allclose(sums.values, 1.0, atol=1e-9)

    # beats a uniform model on race-winner log-loss
    def winner_ll(probs):
        lls = []
        for _, g in df.assign(pp=probs).groupby("race_id"):
            lls.append(-np.log(g.loc[g["won"] == 1, "pp"].iloc[0]))
        return np.mean(lls)
    uniform = np.full(len(df), 1 / 8)
    assert winner_ll(p) < winner_ll(uniform)


def test_gbm_normalises_per_race():
    df = _synthetic_pl(n_races=150, field=6, seed=2)
    X = df[["x0", "x1"]]
    gbm = GBMWinModel(max_iter=60).fit(X, df["won"].values, df["race_id"].values)
    p = gbm.predict_proba(X, df["race_id"].values)
    sums = pd.DataFrame({"race_id": df["race_id"], "p": p}).groupby("race_id")["p"].sum()
    assert np.allclose(sums.values, 1.0, atol=1e-9)
    assert ((p >= 0) & (p <= 1)).all()
