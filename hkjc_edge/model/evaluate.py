"""Phase 2 evaluation: compare model win-probabilities to the MARKET, out of sample.

This is a Phase-2 *teaser*, not the Phase-3 verdict. It does a single chronological
train/test split (not full walk-forward + bootstrap) and reports, for each model, the
race-winner log-loss on the test races versus the de-vigged market's log-loss. The honest
benchmark is the market: a model only has value if it beats the market's log-loss out of
sample. Replicates the Benter setup (market-only / fundamental-only / combined).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..db import Database
from ..pipeline.dataset import build_dataset
from .calibration import IsotonicCalibrator, calibration_report
from .conditional_logit import ConditionalLogit
from .features import Featurizer, market_only_matrix
from .gbm import GBMWinModel


def _per_race_winner_ll(df: pd.DataFrame, prob_col: str) -> dict:
    """race_id -> -log(prob assigned to the actual winner)."""
    out = {}
    for rid, g in df.groupby("race_id"):
        winners = g[g["label_won"] == 1]
        if len(winners) == 0:
            continue
        p = float(winners[prob_col].mean())          # avg handles dead heats
        out[rid] = -np.log(max(p, 1e-12))
    return out


def _race_winner_logloss(df: pd.DataFrame, prob_col: str) -> float:
    """-mean over races of log(prob assigned to the actual winner). Proper for win models."""
    vals = list(_per_race_winner_ll(df, prob_col).values())
    return float(np.mean(vals)) if vals else float("nan")


def _bootstrap_margin_ci(df: pd.DataFrame, model_col: str, market_col: str,
                         n_boot: int = 5000, seed: int = 0) -> dict:
    """Bootstrap the per-race winner-log-loss margin (market - model). >0 => model better.
    Reports the 95% CI and P(margin>0) so a 'win' can be judged against variance."""
    m = _per_race_winner_ll(df, market_col)
    c = _per_race_winner_ll(df, model_col)
    rids = sorted(set(m) & set(c))
    diff = np.array([m[r] - c[r] for r in rids])
    if len(diff) == 0:
        return {}
    rng = np.random.default_rng(seed)
    boot = np.array([rng.choice(diff, len(diff), replace=True).mean() for _ in range(n_boot)])
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return {
        "mean_margin": round(float(diff.mean()), 5),
        "ci95": [round(float(lo), 5), round(float(hi), 5)],
        "p_positive": round(float((boot > 0).mean()), 3),
        "significant_at_95": bool(lo > 0),
        "n_races": len(diff),
    }


def _eval_races_only_with_odds(df: pd.DataFrame) -> pd.DataFrame:
    """Keep races where every runner has a market prob (fair model-vs-market comparison)."""
    ok = df.groupby("race_id")["market_prob"].transform(lambda s: s.notna().all())
    return df[ok].copy()


def _combiner_feats(pf, mk):
    return pd.DataFrame({
        "log_fund": np.log(np.clip(pf, 1e-6, 1)),
        "log_market": np.log(np.clip(mk, 1e-6, 1)),
    })


def _two_stage_combine(p_fund_tr, mkt_tr, y_tr, g_tr, p_fund_te, mkt_te, g_te, l2):
    """Benter's two-stage combiner: a 2-feature conditional logit on
    [log(fundamental_prob), log(market_prob)]. Far more stable than dumping the market in
    as one of many features, and it directly estimates how much weight the fundamental model
    deserves on top of the market. Returns (p_train, p_test, beta)."""
    comb = ConditionalLogit(l2=l2).fit(_combiner_feats(p_fund_tr, mkt_tr), y_tr, g_tr)
    p_tr = comb.predict_proba(_combiner_feats(p_fund_tr, mkt_tr), g_tr)
    p_te = comb.predict_proba(_combiner_feats(p_fund_te, mkt_te), g_te)
    return p_tr, p_te, comb.beta_


def run_eval(db: Database, *, test_frac: float = 0.3, l2: float = 5.0) -> dict:
    df = build_dataset(db)
    if df.empty:
        return {"error": "no data"}
    df = _eval_races_only_with_odds(df)
    df = df[df["finish_pos"].notna()].copy()

    # chronological split by race
    races = df[["race_id", "race_date"]].drop_duplicates().sort_values(["race_date", "race_id"])
    n_test = max(1, int(len(races) * test_frac))
    test_ids = set(races["race_id"].tail(n_test))
    train = df[~df["race_id"].isin(test_ids)].copy()
    test = df[df["race_id"].isin(test_ids)].copy()

    y_tr = (train["label_won"] == 1).astype(int).values
    g_tr, g_te = train["race_id"].values, test["race_id"].values

    results: dict = {"n_races_train": train["race_id"].nunique(),
                     "n_races_test": test["race_id"].nunique(),
                     "n_runners_train": len(train), "n_runners_test": len(test),
                     "models": {}}

    # --- 0) MARKET baseline (the number to beat) ---
    test["p_market"] = test["market_prob"].values
    train["p_market"] = train["market_prob"].values
    results["market_test_winner_logloss"] = _race_winner_logloss(test, "p_market")
    results["market_train_winner_logloss"] = _race_winner_logloss(train, "p_market")

    def record(name, p_train, p_test):
        train[f"p_{name}"] = p_train
        test[f"p_{name}"] = p_test
        wll = _race_winner_logloss(test, f"p_{name}")
        wll_tr = _race_winner_logloss(train, f"p_{name}")
        cal = calibration_report(test["label_won"].astype(float).values, p_test, n_bins=8)
        results["models"][name] = {
            "train_winner_logloss": round(wll_tr, 5),     # gap to test => overfitting
            "test_winner_logloss": round(wll, 5),
            "vs_market": round(wll - results["market_test_winner_logloss"], 5),
            "binary_log_loss": cal["log_loss"], "brier": cal["brier"], "ece": cal["ece"],
        }

    # --- 1) Conditional logit: market-only (should ~reproduce the market) ---
    Xtr_m, Xte_m = market_only_matrix(train), market_only_matrix(test)
    cl_m = ConditionalLogit(l2=l2).fit(Xtr_m, y_tr, g_tr)
    record("cl_market_only", cl_m.predict_proba(Xtr_m, g_tr), cl_m.predict_proba(Xte_m, g_te))

    # --- 2) Conditional logit: fundamental-only (no market) ---
    fz = Featurizer(include_market=False).fit(train)
    cl_f = ConditionalLogit(l2=l2).fit(fz.transform(train), y_tr, g_tr)
    pf_tr = cl_f.predict_proba(fz.transform(train), g_tr)
    pf_te = cl_f.predict_proba(fz.transform(test), g_te)
    record("cl_fundamental", pf_tr, pf_te)

    # --- 3) Two-stage COMBINED (Benter): combine fundamental CL prob with market ---
    cl_comb_tr, cl_comb_te, beta_c = _two_stage_combine(
        pf_tr, train["market_prob"].values, y_tr, g_tr,
        pf_te, test["market_prob"].values, g_te, l2=1.0)
    record("cl_combined_2stage", cl_comb_tr, cl_comb_te)
    results["models"]["cl_combined_2stage"]["combiner_beta"] = \
        {"log_fund": round(float(beta_c[0]), 3), "log_market": round(float(beta_c[1]), 3)}

    # --- 4) GBM: fundamental-only ---
    gbm = GBMWinModel().fit(fz.transform(train), y_tr, g_tr)
    pg_tr = gbm.predict_proba(fz.transform(train), g_tr)
    pg_te = gbm.predict_proba(fz.transform(test), g_te)
    record("gbm_fundamental", pg_tr, pg_te)

    # --- 5) GBM two-stage combined with market ---
    gbm_comb_tr, gbm_comb_te, _ = _two_stage_combine(
        pg_tr, train["market_prob"].values, y_tr, g_tr,
        pg_te, test["market_prob"].values, g_te, l2=1.0)
    record("gbm_combined_2stage", gbm_comb_tr, gbm_comb_te)

    # honest verdict (this split only; NOT Phase-3 validation)
    best = min(results["models"].items(), key=lambda kv: kv[1]["test_winner_logloss"])
    results["best_model"] = best[0]
    results["best_beats_market"] = bool(best[1]["test_winner_logloss"]
                                        < results["market_test_winner_logloss"])
    # Quantify whether the best model's margin over the market is distinguishable from noise.
    results["best_vs_market_bootstrap"] = _bootstrap_margin_ci(
        test, f"p_{best[0]}", "p_market")
    return results


def format_report(r: dict) -> str:
    if "error" in r:
        return f"Eval error: {r['error']}"
    lines = []
    lines.append(f"Train races: {r['n_races_train']} ({r['n_runners_train']} runners) | "
                 f"Test races: {r['n_races_test']} ({r['n_runners_test']} runners)")
    lines.append(f"MARKET winner log-loss  train={r['market_train_winner_logloss']:.5f}  "
                 f"test={r['market_test_winner_logloss']:.5f}   (benchmark to beat)")
    lines.append("")
    lines.append(f"{'model':22s} {'trainLL':>9s} {'testLL':>9s} {'vs_market':>10s} "
                 f"{'brier':>8s} {'ece':>7s}")
    for name, m in r["models"].items():
        flag = "  <= beats market (OOS)" if m["vs_market"] < 0 else ""
        lines.append(f"{name:22s} {m['train_winner_logloss']:>9.4f} {m['test_winner_logloss']:>9.4f} "
                     f"{m['vs_market']:>+10.5f} {m['brier']:>8.4f} {m['ece']:>7.4f}{flag}")
    lines.append("(trainLL << testLL  =>  overfitting)")
    lines.append("")
    verdict = ("edges market on point estimate" if r["best_beats_market"]
               else "does NOT beat market")
    lines.append(f"Best model: {r['best_model']} — {verdict}.")
    bs = r.get("best_vs_market_bootstrap") or {}
    if bs:
        sig = "STATISTICALLY SIGNIFICANT" if bs["significant_at_95"] else "NOT significant (CI includes 0)"
        lines.append(f"  margin vs market = {bs['mean_margin']:+.5f} nats/race "
                     f"95% CI [{bs['ci95'][0]:+.5f}, {bs['ci95'][1]:+.5f}]  "
                     f"P(>0)={bs['p_positive']:.2f}  -> {sig}")
    lines.append("NOTE: single split, small sample, log-loss only (NOT profit after the "
                 "17.5% takeout). This is NOT the Phase-3 verdict (walk-forward + CLV). Do not bet.")
    return "\n".join(lines)
