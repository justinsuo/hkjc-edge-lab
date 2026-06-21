"""Conditional-logit (Plackett-Luce) win-probability model.

Each race is a multinomial choice among its runners: P(i wins) = softmax over utilities
u_j = x_j . beta, normalised WITHIN the race. Fit by penalised maximum likelihood
(L2 ridge for stability on small samples) using scipy L-BFGS. This is the Bolton-Chapman /
Benter baseline. To replicate Benter's central result, fit it three ways (market-only,
fundamental-only, combined) and compare — see model/evaluate.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize


class ConditionalLogit:
    def __init__(self, l2: float = 1.0):
        self.l2 = l2
        self.beta_: np.ndarray | None = None
        self.mean_: np.ndarray | None = None
        self.std_: np.ndarray | None = None
        self.columns_: list[str] | None = None

    # -- helpers -----------------------------------------------------------------------
    def _standardize_fit(self, X: np.ndarray) -> np.ndarray:
        self.mean_ = X.mean(axis=0)
        self.std_ = X.std(axis=0)
        self.std_[self.std_ == 0] = 1.0
        return (X - self.mean_) / self.std_

    def _standardize(self, X: np.ndarray) -> np.ndarray:
        return (X - self.mean_) / self.std_

    @staticmethod
    def _race_index(groups: np.ndarray) -> list[np.ndarray]:
        order: dict = {}
        for pos, g in enumerate(groups):
            order.setdefault(g, []).append(pos)
        return [np.array(v) for v in order.values()]

    # -- fit ---------------------------------------------------------------------------
    def fit(self, X: pd.DataFrame, y, groups) -> "ConditionalLogit":
        self.columns_ = list(X.columns)
        Xv = self._standardize_fit(np.asarray(X, dtype=float))
        y = np.asarray(y, dtype=float)
        groups = np.asarray(groups)
        races = self._race_index(groups)
        # keep only races with at least one winner
        races = [idx for idx in races if y[idx].sum() > 0]
        n_features = Xv.shape[1]

        def neg_ll(beta):
            ll = 0.0
            grad = np.zeros(n_features)
            for idx in races:
                xr = Xv[idx]
                u = xr @ beta
                u -= u.max()
                ex = np.exp(u)
                p = ex / ex.sum()
                winners = np.where(y[idx] > 0)[0]
                exp_x = p @ xr
                for w in winners:               # supports dead heats (multiple winners)
                    ll += np.log(p[w] + 1e-300)
                    grad += xr[w] - exp_x
            # L2 penalty
            ll -= 0.5 * self.l2 * np.dot(beta, beta)
            grad -= self.l2 * beta
            return -ll, -grad

        res = minimize(neg_ll, np.zeros(n_features), jac=True, method="L-BFGS-B")
        self.beta_ = res.x
        return self

    # -- explain -----------------------------------------------------------------------
    def contributions(self, X: pd.DataFrame) -> pd.DataFrame:
        """Exact additive decomposition of each runner's utility: beta_j * standardized x_j.
        Larger positive contribution = that feature pushed this horse's win prob UP. This is
        an exact explanation for the linear model (the utility is literally the row sum)."""
        Xv = self._standardize(np.asarray(X[self.columns_], dtype=float))
        contrib = Xv * self.beta_                      # (n_rows, n_features)
        return pd.DataFrame(contrib, columns=self.columns_, index=X.index)

    def global_importance(self) -> dict:
        """Standardized coefficient magnitude per feature (features are z-scored, so |beta|
        is comparable across features). Returns {feature: |beta|} sorted descending."""
        imp = {c: abs(float(b)) for c, b in zip(self.columns_, self.beta_)}
        return dict(sorted(imp.items(), key=lambda kv: kv[1], reverse=True))

    # -- predict -----------------------------------------------------------------------
    def predict_proba(self, X: pd.DataFrame, groups) -> np.ndarray:
        """Return within-race normalised win probabilities (one per row)."""
        Xv = self._standardize(np.asarray(X[self.columns_], dtype=float))
        u = Xv @ self.beta_
        groups = np.asarray(groups)
        out = np.zeros(len(u))
        for idx in self._race_index(groups):
            uu = u[idx] - u[idx].max()
            ex = np.exp(uu)
            out[idx] = ex / ex.sum()
        return out
