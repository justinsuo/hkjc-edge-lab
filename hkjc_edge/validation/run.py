"""Orchestrate Phase 3 validation -> GO/NO-GO verdict + report + plots.

GO requires BOTH (adversarial bar):
  1. the model beats the closing line out of sample — bootstrap CI of the winner-log-loss
     margin vs market excludes zero (PRIMARY test); and
  2. the flat-stake value-betting ROI after real takeout is positive with a bootstrap CI
     excluding zero.
Anything else is NO-GO. A placebo (label-shuffle) run must NOT show an edge.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..db import Database
from ..pipeline.dataset import build_dataset
from .metrics import (
    baseline_bet_all, baseline_bet_favorite, clv_report, fractional_kelly_growth,
    profit_sim_value,
)
from .walkforward import walk_forward


def _placebo(df: pd.DataFrame, *, min_train_races, step_races, l2, ev_threshold,
             seed: int = 0) -> dict:
    """MARKET-CONSISTENT NULL: re-draw each race's winner FROM THE MARKET's own de-vigged
    probabilities, then rerun the whole pipeline. Now the market is calibrated truth by
    construction, so a correctly-built model must NOT beat it and value betting must lose ~the
    takeout. If the pipeline shows an edge here, that edge is an overfit/leakage artifact.

    (NB: drawing winners uniformly would be WRONG — it would make the uniform truth genuinely
    mispriced against skewed odds, manufacturing a real edge that isn't a pipeline artifact.)"""
    rng = np.random.default_rng(seed)
    d = df.copy()
    ok = d.groupby("race_id")["market_prob"].transform(lambda s: s.notna().all())
    d = d[ok & d["finish_pos"].notna()].copy()
    d["label_won"] = 0
    for rid, g in d.groupby("race_id"):
        probs = g["market_prob"].to_numpy(dtype=float)
        probs = probs / probs.sum()
        win_idx = rng.choice(g.index.to_numpy(), p=probs)
        d.loc[g.index, "label_won"] = 0
        d.loc[win_idx, "label_won"] = 1
    try:
        oos = walk_forward(d, min_train_races=min_train_races, step_races=step_races, l2=l2)
    except ValueError:
        return {}
    clv = clv_report(oos)["models"].get("p_combined", {})
    prof = profit_sim_value(oos, "p_combined", ev_threshold=ev_threshold)
    return {"clv_margin": clv.get("bootstrap_vs_market", {}),
            "profit_roi": prof.get("roi"), "n_bets": prof.get("n_bets")}


def run_validation(db: Database, *, min_train_races: int = 200, step_races: int = 25,
                   l2: float = 5.0, ev_threshold: float = 0.0, kelly_fraction: float = 0.25,
                   out_dir: str | Path = "data/validation", seed: int = 0,
                   make_plots: bool = True) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    df = build_dataset(db)
    if df.empty:
        return {"error": "no data"}

    oos = walk_forward(df, min_train_races=min_train_races, step_races=step_races, l2=l2)

    clv = clv_report(oos)
    prof_combined = profit_sim_value(oos, "p_combined", ev_threshold=ev_threshold, seed=seed)
    prof_fund = profit_sim_value(oos, "p_fund", ev_threshold=ev_threshold, seed=seed)
    kelly = fractional_kelly_growth(oos, "p_combined", ev_threshold=ev_threshold,
                                    fraction=kelly_fraction)
    base_all = baseline_bet_all(oos)
    base_fav = baseline_bet_favorite(oos)
    placebo = _placebo(df, min_train_races=min_train_races, step_races=step_races,
                       l2=l2, ev_threshold=ev_threshold, seed=seed)

    clv_combined = clv["models"]["p_combined"]["bootstrap_vs_market"]
    clv_significant = bool(clv_combined.get("significant_at_95"))
    profit_significant = bool(prof_combined.get("roi_significant_positive"))
    go = clv_significant and profit_significant

    results = {
        "n_oos_races": int(oos["race_id"].nunique()),
        "n_oos_runners": int(len(oos)),
        "min_train_races": min_train_races, "step_races": step_races,
        "clv": clv,
        "profit": {"combined": prof_combined, "fundamental": prof_fund,
                   "fractional_kelly_combined": {k: v for k, v in kelly.items()
                                                 if k != "equity_curve"}},
        "baselines": {"bet_all": base_all, "bet_favorite": base_fav},
        "placebo": placebo,
        "verdict": "GO" if go else "NO-GO",
        "verdict_reasons": {
            "clv_beats_market_oos": clv_significant,
            "profit_after_takeout_positive": profit_significant,
        },
    }

    if make_plots:
        try:
            from .plots import calibration_plot, equity_plot, pnl_plot
            calibration_plot(oos, {"market (closing)": "p_market", "model (combined)": "p_combined"},
                             out / "calibration.png")
            series = {}
            if prof_combined.get("cum_pnl"):
                series["combined value bets"] = prof_combined["cum_pnl"]
            if series:
                pnl_plot(series, out / "pnl.png")
            equity_plot(kelly["equity_curve"], out / "equity.png")
            results["plots"] = [str(out / "calibration.png"), str(out / "pnl.png"),
                                str(out / "equity.png")]
        except Exception as e:  # plotting must never break the verdict
            results["plots_error"] = str(e)

    _write_report(results, out / "validation_report.md")
    results["report_path"] = str(out / "validation_report.md")
    return results


def format_verdict(r: dict) -> str:
    if "error" in r:
        return f"Validation error: {r['error']}"
    c = r["clv"]["models"]["p_combined"]["bootstrap_vs_market"]
    p = r["profit"]["combined"]
    lines = [
        f"OOS races: {r['n_oos_races']}  runners: {r['n_oos_runners']}  "
        f"(walk-forward, min_train={r['min_train_races']}, step={r['step_races']})",
        "",
        "PRIMARY TEST — closing-line value (model vs market, OOS winner log-loss):",
        f"  market={r['clv']['market_winner_logloss']}  "
        f"combined={r['clv']['models']['p_combined']['winner_logloss']}  "
        f"fundamental={r['clv']['models']['p_fund']['winner_logloss']}",
        f"  margin vs market = {c.get('mean_margin')} nats/race  CI95 {c.get('ci95')}  "
        f"P(>0)={c.get('p_positive')}  -> {'SIGNIFICANT' if c.get('significant_at_95') else 'not significant'}",
        "",
        "PROFIT SIM (flat 1u value bets, after real takeout embedded in odds):",
        (f"  n_bets={p.get('n_bets')}  ROI={p.get('roi')}  CI95={p.get('roi_ci95')}  "
         f"-> {'POSITIVE & significant' if p.get('roi_significant_positive') else 'not significantly positive'}"
         if p.get("n_bets") else f"  {p.get('note','no bets')}"),
        f"  sanity baselines: bet-all ROI={r['baselines']['bet_all']['roi']} "
        f"(~ -takeout), bet-favourite ROI={r['baselines']['bet_favorite']['roi']}",
        f"  placebo (market-consistent null): margin={r['placebo'].get('clv_margin',{}).get('mean_margin')} "
        f"CI{r['placebo'].get('clv_margin',{}).get('ci95')}  ROI={r['placebo'].get('profit_roi')} "
        f"(expect ~0 margin / ~-takeout ROI)",
        "",
        f"VERDICT: {r['verdict']}",
        f"  closing-line value beats market OOS: {r['verdict_reasons']['clv_beats_market_oos']}",
        f"  profit after takeout positive (sig): {r['verdict_reasons']['profit_after_takeout_positive']}",
    ]
    if r["verdict"] == "NO-GO":
        lines.append("  => Tool must NOT make live bet recommendations. This is the expected, honest outcome.")
    return "\n".join(lines)


def _write_report(r: dict, path: Path) -> None:
    c = r["clv"]["models"]["p_combined"]["bootstrap_vs_market"]
    p = r["profit"]["combined"]
    md = [
        "# Phase 3 Validation Report",
        "",
        f"**Verdict: {r['verdict']}**",
        "",
        f"- OOS races: {r['n_oos_races']} ({r['n_oos_runners']} runners), walk-forward "
        f"(expanding window, min_train={r['min_train_races']}, step={r['step_races']}).",
        "",
        "## 1. Closing-line value (primary test)",
        "",
        "| model | OOS winner log-loss |",
        "|---|---|",
        f"| market (closing, de-vigged) | {r['clv']['market_winner_logloss']} |",
        f"| combined (Benter two-stage) | {r['clv']['models']['p_combined']['winner_logloss']} |",
        f"| fundamental-only | {r['clv']['models']['p_fund']['winner_logloss']} |",
        "",
        f"Margin (market − combined) = **{c.get('mean_margin')} nats/race**, "
        f"95% bootstrap CI **{c.get('ci95')}**, P(>0)={c.get('p_positive')} → "
        f"**{'beats the closing line' if c.get('significant_at_95') else 'does NOT beat the closing line'}**.",
        "",
        "## 2. Profit simulation (after real takeout)",
        "",
        (f"- Flat 1u value bets (EV>{0}): n={p.get('n_bets')}, ROI=**{p.get('roi')}**, "
         f"95% CI {p.get('roi_ci95')} → "
         f"{'positive & significant' if p.get('roi_significant_positive') else 'not significantly positive'}."
         if p.get("n_bets") else f"- {p.get('note','no bets cleared the threshold')}."),
        f"- Fractional-Kelly final bankroll multiple: "
        f"{r['profit']['fractional_kelly_combined'].get('final_bankroll_multiple')} "
        f"({r['profit']['fractional_kelly_combined'].get('n_bets')} bets).",
        f"- Sanity baselines: bet-all ROI {r['baselines']['bet_all']['roi']} (≈ −takeout, "
        f"the Phase-0 algebraic certainty), bet-favourite ROI {r['baselines']['bet_favorite']['roi']}.",
        "",
        "## 3. Adversarial placebo (market-consistent null)",
        "",
        "Winners re-drawn from the market's own de-vigged probabilities, so the market is "
        "calibrated truth by construction. A correctly-built pipeline must show ~0 margin and "
        "~−takeout ROI here.",
        "",
        f"- Margin vs market: {r['placebo'].get('clv_margin',{}).get('mean_margin')} "
        f"CI {r['placebo'].get('clv_margin',{}).get('ci95')}; value-bet ROI {r['placebo'].get('profit_roi')}. "
        "A significant edge here would indicate a leak/overfit artifact.",
        "",
        "## Plots",
        "",
        "- `calibration.png` — model vs closing-line reliability (OOS).",
        "- `pnl.png` — cumulative P&L of value bets.",
        "- `equity.png` — fractional-Kelly bankroll curve.",
        "",
        "## Honest reading",
        "",
        "This is the metric that matters: if the model cannot beat the closing line OOS and "
        "cannot turn a profit after the ~17.5% takeout with a CI excluding zero, it has **no "
        "demonstrated edge**, and the runtime app must default to **NO BET**. Per Phase 0 this "
        "is the expected outcome for public-data, no-rebate retail modelling.",
    ]
    path.write_text("\n".join(md))
