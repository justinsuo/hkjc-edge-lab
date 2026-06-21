"""Probability calibration (isotonic / Platt) and explicit calibration diagnostics.

A model can rank well yet be mis-calibrated (its "0.30" horses don't win 30% of the time).
Calibration matters here because EV math multiplies probabilities by payouts — biased
probabilities produce biased EV. We calibrate on TRAIN and report calibration on TEST.
"""
from __future__ import annotations

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


def _logit(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


class IsotonicCalibrator:
    def __init__(self):
        self.iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)

    def fit(self, p, y):
        self.iso.fit(np.asarray(p, float), np.asarray(y, float))
        return self

    def transform(self, p):
        return self.iso.predict(np.asarray(p, float))


class PlattCalibrator:
    """Platt scaling: logistic regression on the logit of the predicted probability."""

    def __init__(self):
        self.lr = LogisticRegression(C=1e6, solver="lbfgs")

    def fit(self, p, y):
        self.lr.fit(_logit(p).reshape(-1, 1), np.asarray(y, int))
        return self

    def transform(self, p):
        return self.lr.predict_proba(_logit(p).reshape(-1, 1))[:, 1]


def brier_score(y, p) -> float:
    y = np.asarray(y, float)
    p = np.asarray(p, float)
    return float(np.mean((p - y) ** 2))


def log_loss_safe(y, p) -> float:
    y = np.asarray(y, float)
    p = np.clip(np.asarray(p, float), 1e-12, 1 - 1e-12)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def expected_calibration_error(y, p, n_bins: int = 10) -> float:
    y = np.asarray(y, float)
    p = np.asarray(p, float)
    bins = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(p, bins) - 1, 0, n_bins - 1)
    ece = 0.0
    for b in range(n_bins):
        m = idx == b
        if m.any():
            ece += (m.mean()) * abs(p[m].mean() - y[m].mean())
    return float(ece)


def calibration_report(y, p, n_bins: int = 10) -> dict:
    y = np.asarray(y, float)
    p = np.asarray(p, float)
    bins = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(p, bins) - 1, 0, n_bins - 1)
    table = []
    for b in range(n_bins):
        m = idx == b
        if m.any():
            table.append({"bin": f"[{bins[b]:.2f},{bins[b+1]:.2f})",
                          "n": int(m.sum()),
                          "mean_pred": round(float(p[m].mean()), 4),
                          "emp_rate": round(float(y[m].mean()), 4)})
    return {
        "brier": round(brier_score(y, p), 5),
        "log_loss": round(log_loss_safe(y, p), 5),
        "ece": round(expected_calibration_error(y, p, n_bins), 5),
        "reliability": table,
    }
