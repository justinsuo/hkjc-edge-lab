"""Walk-forward (expanding-window) out-of-sample prediction.

Train strictly on the past, predict the future, step forward, repeat. Every test race is
predicted by a model that never saw it or anything after it. The featurizer is re-fit on
each fold's train set only. We collect one OOS prediction per runner across the whole
timeline, which downstream metrics then evaluate against the closing line.

Models produced per runner:
  * p_market   — de-vigged closing odds (the benchmark to beat)
  * p_fund     — fundamental conditional logit (no market input)
  * p_combined — Benter two-stage combination of p_fund with the market
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..model.conditional_logit import ConditionalLogit
from ..model.features import Featurizer


def _combiner_feats(pf, mk):
    return pd.DataFrame({"log_fund": np.log(np.clip(pf, 1e-6, 1)),
                         "log_market": np.log(np.clip(mk, 1e-6, 1))})


class TwoStageModel:
    """Benter two-stage win model: fundamental conditional logit + a combiner that blends its
    output with the market. Fit once, score many races — so the app can cache one model per
    'as-of' date and reuse it for every race that day (snappy + leak-free)."""

    def __init__(self, l2: float = 5.0, l2_combiner: float = 1.0):
        self.l2 = l2
        self.l2_combiner = l2_combiner
        self.fz: Featurizer | None = None
        self.cl: ConditionalLogit | None = None
        self.comb: ConditionalLogit | None = None

    def fit(self, train: pd.DataFrame) -> "TwoStageModel":
        y = (train["label_won"] == 1).astype(int).values
        g = train["race_id"].values
        self.fz = Featurizer(include_market=False).fit(train)
        self.cl = ConditionalLogit(l2=self.l2).fit(self.fz.transform(train), y, g)
        pf = self.cl.predict_proba(self.fz.transform(train), g)
        self.comb = ConditionalLogit(l2=self.l2_combiner).fit(
            _combiner_feats(pf, train["market_prob"].values), y, g)
        return self

    def score(self, test: pd.DataFrame):
        g = test["race_id"].values
        pf = self.cl.predict_proba(self.fz.transform(test), g)
        pc = self.comb.predict_proba(_combiner_feats(pf, test["market_prob"].values), g)
        return pf, pc

    @property
    def combiner_weights(self) -> dict:
        b = self.comb.beta_
        return {"log_fund": round(float(b[0]), 3), "log_market": round(float(b[1]), 3)}


def fit_predict_fold(train: pd.DataFrame, test: pd.DataFrame, l2: float = 5.0,
                     l2_combiner: float = 1.0) -> pd.DataFrame:
    """Fit on `train`, return `test` with p_fund / p_combined / p_market columns."""
    model = TwoStageModel(l2=l2, l2_combiner=l2_combiner).fit(train)
    pf_te, pc_te = model.score(test)
    out = test.copy()
    out["p_market"] = test["market_prob"].values
    out["p_fund"] = pf_te
    out["p_combined"] = pc_te
    return out


def walk_forward(df: pd.DataFrame, *, min_train_races: int = 200, step_races: int = 25,
                 l2: float = 5.0) -> pd.DataFrame:
    """Expanding-window walk-forward. Returns the concatenated OOS prediction frame.

    Only races where every runner has a market prob and a known finish are used (so the
    model-vs-market comparison is fair). Raises if there aren't enough races.
    """
    # keep evaluable races only
    ok = df.groupby("race_id")["market_prob"].transform(lambda s: s.notna().all())
    df = df[ok & df["finish_pos"].notna()].copy()

    ordered = (df[["race_id", "race_date"]].drop_duplicates()
               .sort_values(["race_date", "race_id"])["race_id"].tolist())
    n = len(ordered)
    if n <= min_train_races + 1:
        raise ValueError(f"need > {min_train_races + 1} evaluable races, have {n}")

    folds = []
    for start in range(min_train_races, n, step_races):
        train_ids = set(ordered[:start])
        test_ids = set(ordered[start:start + step_races])
        train = df[df["race_id"].isin(train_ids)]
        test = df[df["race_id"].isin(test_ids)]
        if test.empty or train["label_won"].sum() == 0:
            continue
        fold = fit_predict_fold(train, test, l2=l2)
        fold["fold"] = start
        folds.append(fold)
    if not folds:
        raise ValueError("no folds produced")
    return pd.concat(folds, ignore_index=True)
