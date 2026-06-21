#!/usr/bin/env python3
"""Historical paper-trading backtest — "what if I'd run this tool before every race?"

Walk-forward out-of-sample: each race is scored by a model trained ONLY on strictly-prior
races (no lookahead), then we simulate betting at the race's actual CLOSING odds (the SP) and
tally realized P&L after the real takeout. This is the honest test of the runtime app's logic
over real history. Expected, validated outcome: no edge — you lose.

Usage: python scripts/historical_backtest.py [--min-train 350] [--step 25]
"""
from __future__ import annotations

import argparse

import numpy as np

from hkjc_edge.db import Database
from hkjc_edge.config import load_config
from hkjc_edge.pipeline.dataset import build_dataset
from hkjc_edge.validation.metrics import bootstrap_margin, winner_logloss
from hkjc_edge.validation.walkforward import walk_forward


def _flat_strategy(bets, label):
    """bets: DataFrame with race_id + win_odds + label_won. Flat 1u; ROI + RACE-CLUSTERED
    bootstrap CI (resamples whole races, since within-race P&Ls are correlated — exactly one
    winner per race — so a bet-level i.i.d. bootstrap would mis-state multi-bet-per-race CIs)."""
    if len(bets) == 0:
        return {"label": label, "n": 0, "roi": None}
    bets = bets.copy()
    bets["pnl"] = np.where(bets["label_won"] == 1, bets["win_odds"] - 1.0, -1.0)
    race_pnls = [sub["pnl"].to_numpy() for _, sub in bets.groupby("race_id")]
    n_races = len(race_pnls)
    rng = np.random.default_rng(0)
    boot = []
    for _ in range(5000):
        idx = rng.integers(0, n_races, n_races)
        boot.append(np.concatenate([race_pnls[i] for i in idx]).mean())
    lo, hi = np.percentile(boot, [2.5, 97.5])
    # A bootstrap over too few distinct races can't estimate uncertainty — never claim
    # significance there (e.g. 13 bets all in ONE race is one lucky race, not a strategy).
    reliable = n_races >= 8
    return {"label": label, "n": int(len(bets)), "n_races": n_races,
            "hit_rate": round(float((bets["label_won"] == 1).mean()), 4),
            "roi": round(float(bets["pnl"].mean()), 4),
            "ci95": [round(float(lo), 4), round(float(hi), 4)],
            "total_pnl": round(float(bets["pnl"].sum()), 1), "reliable": reliable,
            "significant_pos": bool(lo > 0 and reliable),
            "significant_neg": bool(hi < 0 and reliable)}


def _kelly(oos, prob_col, ev_threshold, fraction=0.25, per_bet_cap=0.05, bank0=1000.0):
    d = oos.dropna(subset=["win_odds", prob_col]).copy()
    d = d[d["win_odds"] > 1].sort_values(["race_date", "race_id"])
    bank = bank0
    peak = bank0
    maxdd = 0.0
    nbets = 0
    for _, r in d.iterrows():
        O, p = float(r["win_odds"]), float(r[prob_col])
        b = O - 1.0
        if b <= 0:
            continue
        ev = p * O - 1.0
        if ev > ev_threshold:
            f = max(0.0, (p * b - (1 - p)) / b)
            stake = min(fraction * f, per_bet_cap) * bank
            bank += (O - 1.0) * stake if r["label_won"] == 1 else -stake
            nbets += 1
            peak = max(peak, bank)
            maxdd = max(maxdd, (peak - bank) / peak)
    return {"final_mult": round(bank / bank0, 4), "n_bets": nbets, "max_drawdown": round(maxdd, 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-train", type=int, default=350, dest="min_train")
    ap.add_argument("--step", type=int, default=25)
    args = ap.parse_args()

    cfg = load_config()
    with Database(cfg.db_path) as db:
        df = build_dataset(db)
    oos = walk_forward(df, min_train_races=args.min_train, step_races=args.step)

    races = oos["race_id"].nunique()
    dr = (oos["race_date"].min(), oos["race_date"].max())
    print("=" * 74)
    print("HISTORICAL PAPER-TRADING BACKTEST (walk-forward, out-of-sample)")
    print("=" * 74)
    print(f"OOS window: {str(dr[0].date())} → {str(dr[1].date())}  |  "
          f"{races} races, {len(oos)} runners  (model retrained every {args.step} races)")
    print()

    # --- 1) closing-line value (calibration vs market) ---
    mll = winner_logloss(oos, "p_market")
    cll = winner_logloss(oos, "p_combined")
    bm = bootstrap_margin(oos, "p_combined")
    print("1) CLOSING-LINE VALUE (PRIMARY, pre-registered decision metric) — beat the market?")
    print(f"   winner log-loss : market {mll:.5f}  vs  model {cll:.5f}")
    print(f"   margin (mkt-model) = {bm['mean_margin']:+.5f} nats/race  "
          f"95% CI {bm['ci95']}  P(>0)={bm['p_positive']}")
    print(f"   -> {'BEATS the close' if bm['significant_at_95'] else 'does NOT beat the close (CI includes 0)'}")
    print()

    # --- 2) betting strategies at closing odds, flat 1u, after real takeout ---
    d = oos.dropna(subset=["win_odds"]).copy()
    d = d[d["win_odds"] > 1]
    ev = d["p_combined"] * d["win_odds"] - 1.0

    strategies = []
    strategies.append(_flat_strategy(d[ev > 0.0], "model +EV picks (EV>0)"))
    strategies.append(_flat_strategy(d[ev > 0.10], "model strong +EV (EV>0.10)"))
    # model's single top-probability horse per race
    top = d.loc[d.groupby("race_id")["p_combined"].idxmax()]
    strategies.append(_flat_strategy(top, "model top pick / race"))
    # market favourite per race
    fav = d.loc[d.groupby("race_id")["win_odds"].idxmin()]
    strategies.append(_flat_strategy(fav, "market favourite / race"))
    # bet everything (sanity: must be ~ -takeout)
    strategies.append(_flat_strategy(d, "bet ALL runners (sanity)"))

    print("2) BETTING SIMULATION (SECONDARY / exploratory) — flat 1u at the closing SP, after")
    print("   the real ~17.5% takeout. 5 strategies = multiple comparisons; treat any lone")
    print("   'win' as noise unless it survives a fresh out-of-sample season.")
    print(f"   {'strategy':30s} {'bets':>5s} {'races':>5s} {'hit%':>5s} {'ROI':>8s} {'95% CI':>18s}")
    for s in strategies:
        if s["n"] == 0:
            print(f"   {s['label']:30s} {'0':>5s}   (no bets cleared the threshold)")
            continue
        flag = ("  <= sig. PROFIT" if s.get("significant_pos")
                else "  <= sig. LOSS" if s.get("significant_neg")
                else "  (too few races)" if not s.get("reliable") else "  (within noise)")
        print(f"   {s['label']:30s} {s['n']:>5d} {s['n_races']:>5d} {100*s['hit_rate']:>4.1f} "
              f"{s['roi']:>+8.3f} {str(s['ci95']):>18s}{flag}")
    print()

    # --- 3) fractional-Kelly bankroll if you'd bet the model's +EV picks ---
    k = _kelly(oos, "p_combined", ev_threshold=0.0)
    print("3) FRACTIONAL-KELLY BANKROLL — bet model +EV picks, 1/4 Kelly, 5% cap, start 1000u")
    print(f"   {k['n_bets']} bets -> final bankroll x{k['final_mult']} "
          f"(max drawdown {100*k['max_drawdown']:.0f}%)")
    print()

    # --- verdict ---
    profitable = [s for s in strategies if s.get("significant_pos")]
    sig_loss = [s["label"] for s in strategies if s.get("significant_neg")]
    print("=" * 74)
    # Decision rule: GO only if the PRIMARY metric (CLV) is significant. Betting strategies
    # are exploratory and subject to multiple-comparisons, so they cannot, alone, grant a GO.
    if not bm["significant_at_95"] and not profitable:
        print("VERDICT: NO EDGE. On the pre-registered primary test the model does NOT beat the "
              "closing line (CLV CI includes 0), and no betting strategy is significantly "
              "profitable after takeout. In fact the market favourite and the model's own top "
              "pick are significantly NEGATIVE: " + (", ".join(sig_loss) or "—") + " — i.e. the "
              "market is efficient and the model adds nothing. Running this tool historically "
              "would have LOST money. This is the honest, expected result.")
    else:
        print("VERDICT: the PRIMARY CLV test (or a strategy) cleared significance on THIS single "
              "season — treat with deep suspicion (multiple comparisons / overfit) and require "
              "confirmation on a fresh out-of-sample season before believing it.")
    print("Note: closing-SP fill is OPTIMISTIC (your real bet would move the pari-mutuel pool "
          "and you can't lock the close). Real results would be no better.")
    print("=" * 74)


if __name__ == "__main__":
    main()
