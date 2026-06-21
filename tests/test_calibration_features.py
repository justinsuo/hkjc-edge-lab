"""Calibration utilities and the Featurizer (no-leakage transform)."""
import numpy as np
import pandas as pd

from hkjc_edge.model.calibration import (
    IsotonicCalibrator, PlattCalibrator, brier_score, calibration_report, log_loss_safe,
)
from hkjc_edge.model.features import Featurizer


def test_isotonic_improves_miscalibrated():
    rng = np.random.default_rng(0)
    # true prob = t; predicted = t**2 (systematically under-confident at high t)
    t = rng.uniform(size=4000)
    y = (rng.uniform(size=4000) < t).astype(int)
    p_bad = t ** 2
    cal = IsotonicCalibrator().fit(p_bad, y)
    p_cal = cal.transform(p_bad)
    assert ((p_cal >= 0) & (p_cal <= 1)).all()
    assert log_loss_safe(y, p_cal) <= log_loss_safe(y, p_bad) + 1e-9
    assert brier_score(y, p_cal) <= brier_score(y, p_bad) + 1e-9


def test_platt_outputs_probabilities():
    rng = np.random.default_rng(1)
    t = rng.uniform(size=2000)
    y = (rng.uniform(size=2000) < t).astype(int)
    p = PlattCalibrator().fit(t, y).transform(t)
    assert ((p >= 0) & (p <= 1)).all()


def test_calibration_report_structure():
    y = np.array([0, 1, 0, 1, 1, 0])
    p = np.array([0.1, 0.9, 0.2, 0.8, 0.6, 0.3])
    rep = calibration_report(y, p, n_bins=5)
    assert set(rep) == {"brier", "log_loss", "ece", "reliability"}
    assert isinstance(rep["reliability"], list)


def _df():
    return pd.DataFrame({
        "distance_m": [1200, 1200, 1400, 1400],
        "field_size": [2, 2, 2, 2],
        "draw": [1, 2, 3, 4],
        "actual_weight": [126, 123, 120, 118],
        "declared_weight": [1100, 1050, 1080, 1020],
        "horse_prior_runs": [0, 3, 5, 0],
        "horse_days_since": [np.nan, 14, 21, np.nan],
        "horse_prev_finish": [np.nan, 2, 1, np.nan],
        "horse_prior_win_rate": [np.nan, 0.3, 0.5, np.nan],
        "horse_prior_avg_finish": [np.nan, 3.0, 2.0, np.nan],
        "horse_prior_avg_winodds": [np.nan, 5.0, 3.0, np.nan],
        "jockey_prior_win_rate": [np.nan, 0.1, 0.2, 0.15],
        "trainer_prior_win_rate": [np.nan, 0.12, 0.18, 0.2],
        "track": ["Turf", "Turf", "AWT", "AWT"],
        "going": ["GOOD", "GOOD", "WET SLOW", "WET SLOW"],
        "class": ["Class 4", "Class 4", "Class 3", "Class 3"],
        "market_prob": [0.6, 0.4, 0.55, 0.45],
    })


def test_featurizer_no_nan_and_market_flag():
    df = _df()
    fz = Featurizer(include_market=False).fit(df)
    X = fz.transform(df)
    assert not X.isna().any().any()
    assert "log_market_prob" not in X.columns
    # missing indicators present for form features
    assert "horse_prior_win_rate__missing" in X.columns
    assert X["horse_prior_win_rate__missing"].tolist() == [1.0, 0.0, 0.0, 1.0]

    fzc = Featurizer(include_market=True).fit(df)
    Xc = fzc.transform(df)
    assert "log_market_prob" in Xc.columns


def test_featurizer_handles_unseen_category():
    df = _df()
    fz = Featurizer().fit(df)
    df2 = df.copy()
    df2.loc[0, "going"] = "NEVER_SEEN"
    X2 = fz.transform(df2)
    # unseen category -> all known one-hot columns 0 for that row, no crash, columns stable
    assert list(X2.columns) == fz.columns_
    assert not X2.isna().any().any()
