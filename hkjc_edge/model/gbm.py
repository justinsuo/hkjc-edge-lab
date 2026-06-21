"""Gradient-boosted win-probability model.

Uses sklearn's HistGradientBoostingClassifier (a LightGBM-style histogram GBM) to avoid
fragile native deps. Predicts P(win) per runner independently, then NORMALISES within each
race so probabilities sum to 1 (a runner's win prob is only meaningful relative to its field).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier


class GBMWinModel:
    def __init__(self, **kwargs):
        params = dict(max_depth=3, max_iter=300, learning_rate=0.05,
                      l2_regularization=1.0, early_stopping=False)
        params.update(kwargs)
        self.clf = HistGradientBoostingClassifier(**params)
        self.columns_: list[str] | None = None

    def fit(self, X: pd.DataFrame, y, groups=None) -> "GBMWinModel":
        self.columns_ = list(X.columns)
        self.clf.fit(np.asarray(X, dtype=float), np.asarray(y, dtype=int))
        return self

    def predict_proba(self, X: pd.DataFrame, groups) -> np.ndarray:
        raw = self.clf.predict_proba(np.asarray(X[self.columns_], dtype=float))[:, 1]
        groups = np.asarray(groups)
        out = np.zeros(len(raw))
        order: dict = {}
        for pos, g in enumerate(groups):
            order.setdefault(g, []).append(pos)
        for idx in order.values():
            idx = np.array(idx)
            s = raw[idx].sum()
            out[idx] = raw[idx] / s if s > 0 else 1.0 / len(idx)
        return out
