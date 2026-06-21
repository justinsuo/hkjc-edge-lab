"""Feature engineering: turn the no-lookahead dataset into a numeric model matrix.

The Featurizer follows fit/transform discipline so that ALL learned quantities (category
mappings, imputation medians) come from TRAIN only — never the test set. This preserves the
no-lookahead guarantee through the modelling step (critical for honest Phase 3 validation).

Raw jockey_id / trainer_id are intentionally DROPPED as model inputs: they are high-cardinality
identifiers whose signal is already captured (leak-free) by jockey_prior_win_rate /
trainer_prior_win_rate computed from strictly-prior rides.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Numeric features used by the models (bet-time, leak-free).
NUMERIC_FEATURES = [
    "distance_m", "class_level", "field_size", "draw", "actual_weight", "declared_weight",
    "horse_prior_runs", "horse_days_since", "horse_prev_finish",
    "horse_prior_win_rate", "horse_prior_avg_finish", "horse_prior_avg_winodds",
    "horse_prior_avg_speed", "horse_last_speed", "horse_best_speed",
    "jockey_prior_win_rate", "trainer_prior_win_rate",
]
# Form features that are NaN before a horse/jockey/trainer has history -> add missing flags.
FORM_FEATURES = [
    "horse_days_since", "horse_prev_finish", "horse_prior_win_rate",
    "horse_prior_avg_finish", "horse_prior_avg_winodds",
    "horse_prior_avg_speed", "horse_last_speed", "horse_best_speed",
    "jockey_prior_win_rate", "trainer_prior_win_rate", "class_level",
]
CATEGORICAL_FEATURES = ["track", "going", "class"]
MARKET_COLUMN = "market_prob"


class Featurizer:
    def __init__(self, include_market: bool = False):
        self.include_market = include_market
        self.medians_: dict[str, float] = {}
        self.categories_: dict[str, list] = {}
        self.columns_: list[str] = []
        self.fitted_ = False

    def fit(self, df: pd.DataFrame) -> "Featurizer":
        for col in NUMERIC_FEATURES:
            vals = pd.to_numeric(df[col], errors="coerce").to_numpy() if col in df else np.array([])
            med = np.nanmedian(vals) if vals.size and not np.all(np.isnan(vals)) else 0.0
            self.medians_[col] = float(med)
        for col in CATEGORICAL_FEATURES:
            vals = sorted(df[col].dropna().astype(str).unique().tolist()) if col in df else []
            self.categories_[col] = vals
        self.fitted_ = True
        # Build the output column list by transforming the head once.
        self.columns_ = list(self._transform_frame(df.head(1)).columns)
        return self

    def _transform_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=df.index)
        for col in NUMERIC_FEATURES:
            s = pd.to_numeric(df[col], errors="coerce") if col in df else pd.Series(np.nan, df.index)
            out[col] = s.fillna(self.medians_.get(col, 0.0))
        for col in FORM_FEATURES:
            src = pd.to_numeric(df[col], errors="coerce") if col in df else pd.Series(np.nan, df.index)
            out[f"{col}__missing"] = src.isna().astype(float)
        for col in CATEGORICAL_FEATURES:
            cats = self.categories_.get(col, [])
            sval = df[col].astype(str) if col in df else pd.Series("", df.index)
            for c in cats:
                out[f"{col}={c}"] = (sval == c).astype(float)
        if self.include_market:
            mp = pd.to_numeric(df[MARKET_COLUMN], errors="coerce").clip(1e-6, 1 - 1e-6) \
                if MARKET_COLUMN in df else pd.Series(np.nan, df.index)
            mp = mp.fillna(self.medians_.get("__mp__", mp.median() if len(mp) else 0.1))
            out["log_market_prob"] = np.log(mp)
        return out

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.fitted_:
            raise RuntimeError("Featurizer not fitted")
        out = self._transform_frame(df)
        # Align to training columns (fill any missing category cols with 0).
        for c in self.columns_:
            if c not in out:
                out[c] = 0.0
        return out[self.columns_]

    def fit_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        return self.fit(df).transform(df)


def market_only_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Single-feature matrix = log de-vigged market prob (the benchmark model)."""
    mp = pd.to_numeric(df[MARKET_COLUMN], errors="coerce").clip(1e-6, 1 - 1e-6)
    mp = mp.fillna(mp.median())
    return pd.DataFrame({"log_market_prob": np.log(mp)}, index=df.index)
