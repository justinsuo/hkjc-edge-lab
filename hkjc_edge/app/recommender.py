"""Runtime recommender. Given a race, show model vs market probabilities, compute EV after
takeout, and recommend a bet ONLY if the edge gate is on AND the bet clears a strict EV
threshold AND guardrails allow it. The edge gate is OFF by default (Phase 3 = NO-GO), so the
honest default output is NO BET.

Replay mode: operates on any race already in the DB, training on all STRICTLY PRIOR races
(walk-forward style) and using the race's closing SP as the odds-at-recommendation proxy.
A truly live race needs the live odds feed (see hkjc_odds.py limitations).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from ..db import Database
from ..pipeline.dataset import build_dataset
from ..validation.walkforward import fit_predict_fold
from .consistency import cross_pool_place_signal
from .ev import BankrollConfig, BankrollState, size_bet, win_ev


@dataclass
class RunnerRec:
    horse_no: int
    model_prob: float
    market_prob: float
    odds: float
    ev: float
    decision: str
    stake: float
    reason: str


@dataclass
class RaceRecommendation:
    race_id: int
    race_date: str
    racecourse: str
    race_no: int
    field_size: int
    edge_gate_enabled: bool
    runners: list[RunnerRec] = field(default_factory=list)
    consistency: dict = field(default_factory=dict)
    n_train_races: int = 0


class Recommender:
    def __init__(self, db: Database, cfg):
        self.db = db
        self.cfg = cfg
        self.edge_gate_enabled = bool(cfg.get("app.edge_gate_enabled", False))
        self.ev_threshold = float(cfg.get("app.ev_threshold", 0.10))
        b = cfg.get("app.bankroll", {}) or {}
        self.bankroll_cfg = BankrollConfig(
            starting_bankroll=float(b.get("starting_bankroll", 1000.0)),
            kelly_fraction=float(b.get("kelly_fraction", 0.25)),
            per_bet_cap_frac=float(b.get("per_bet_cap_frac", 0.02)),
            per_race_cap_frac=float(b.get("per_race_cap_frac", 0.04)),
            total_exposure_cap_frac=float(b.get("total_exposure_cap_frac", 0.10)),
            session_loss_limit_frac=float(b.get("session_loss_limit_frac", 0.10)),
            stop_loss_frac=float(b.get("stop_loss_frac", 0.25)),
        )
        self.takeout_place = float((cfg.get("takeout", {}) or {}).get("PLACE", 0.175))

    def recommend(self, race_id: int, *, state: BankrollState | None = None,
                  log: bool = True, min_train_races: int = 50) -> RaceRecommendation:
        df = build_dataset(self.db)
        race = df[df["race_id"] == race_id]
        if race.empty:
            raise ValueError(f"race_id {race_id} not found / not evaluable")
        race_date = race["race_date"].iloc[0]
        # Train only on EVALUABLE prior races (all runners have a market prob + a known
        # finish) — same filter the validator uses; otherwise log(NaN) poisons the combiner.
        train = df[df["race_date"] < race_date]
        ok = train.groupby("race_id")["market_prob"].transform(lambda s: s.notna().all())
        train = train[ok & train["finish_pos"].notna()].copy()
        n_train_races = int(train["race_id"].nunique())

        test = race.sort_values("horse_no").copy()
        test["p_market"] = test["market_prob"]
        test["p_combined"] = test["market_prob"]        # default fallback
        have_model = n_train_races >= min_train_races and train["label_won"].sum() > 0
        # Only score runners that HAVE a market prob — otherwise log(market)=NaN poisons the
        # combiner softmax and makes p_combined NaN for the whole race.
        evaluable = test["market_prob"].notna()
        if have_model and evaluable.any():
            scored = fit_predict_fold(train, test[evaluable])
            test.loc[evaluable, "p_combined"] = scored["p_combined"].values

        state = state or BankrollState(self.bankroll_cfg)
        rec = RaceRecommendation(
            race_id=int(race_id), race_date=str(race_date.date()),
            racecourse=str(test["racecourse"].iloc[0]), race_no=int(test["race_no"].iloc[0]),
            field_size=int(len(test)), edge_gate_enabled=self.edge_gate_enabled,
            n_train_races=n_train_races)

        race_committed = 0.0
        for _, r in test.iterrows():
            p_model = float(r["p_combined"]) if pd.notna(r["p_combined"]) else None
            p_mkt = float(r["p_market"]) if pd.notna(r["p_market"]) else None
            O = float(r["win_odds"]) if pd.notna(r["win_odds"]) else None
            if O is None or O <= 1:
                continue
            ev = win_ev(p_model, O) if p_model is not None else None
            if not self.edge_gate_enabled:
                decision, stake = "NO BET", 0.0
                reason = "edge gate OFF — Phase 3 verdict is NO-GO (no validated edge)"
            elif ev is not None and ev > self.ev_threshold:
                stake, reason = size_bet(p_model, O, state, race_committed=race_committed)
                decision = "BET" if stake > 0 else "NO BET"
                race_committed += stake
            else:
                decision, stake = "NO BET", 0.0
                reason = (f"EV {ev:+.3f} <= threshold {self.ev_threshold:+.3f}"
                          if ev is not None else "no model/market price")
            rec.runners.append(RunnerRec(
                int(r["horse_no"]),
                round(p_model, 4) if p_model is not None else None,
                round(p_mkt, 4) if p_mkt is not None else None,
                round(O, 2), round(ev, 4) if ev is not None else None,
                decision, stake, reason))

        # cross-pool consistency signal (honest, not arbitrage)
        rec.consistency = self._consistency(race_id, test)

        if log:
            self._log(rec)
        return rec

    def _consistency(self, race_id: int, test: pd.DataFrame) -> dict:
        rows = self.db.execute(
            "SELECT combination, dividend_hkd FROM dividend WHERE race_id=? AND pool='PLACE'",
            (race_id,)).fetchall()
        place_div = {}
        for comb, div in rows:
            try:
                place_div[int(str(comb).strip())] = float(div)
            except (ValueError, TypeError):
                continue
        if not place_div:
            return {"note": "no PLACE dividends available for this race"}
        t = test.sort_values("horse_no")
        return cross_pool_place_signal(
            t["p_market"].fillna(0).values, t["p_combined"].fillna(0).values, place_div,
            t["horse_no"].astype(int).tolist(), takeout_place=self.takeout_place)

    def _log(self, rec: RaceRecommendation) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for rr in rec.runners:
            self.db.execute(
                """INSERT INTO recommendation
                   (created_at, race_id, race_date, racecourse, race_no, horse_no, pool,
                    model_prob, market_prob, odds_at_rec, ev, decision, stake, edge_gate_enabled)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (now, rec.race_id, rec.race_date, rec.racecourse, rec.race_no, rr.horse_no,
                 "WIN", rr.model_prob, rr.market_prob, rr.odds, rr.ev, rr.decision, rr.stake,
                 1 if rec.edge_gate_enabled else 0))
        self.db.commit()


def format_recommendation(rec: RaceRecommendation) -> str:
    lines = [
        f"Race {rec.race_date} {rec.racecourse} R{rec.race_no}  "
        f"(field {rec.field_size}, model trained on {rec.n_train_races} prior races)",
        f"edge gate: {'ON' if rec.edge_gate_enabled else 'OFF (Phase 3 = NO-GO -> NO BET default)'}",
        "",
        f"{'#':>2} {'model':>7} {'market':>7} {'odds':>6} {'EV':>8}  decision",
    ]
    for rr in sorted(rec.runners, key=lambda x: x.market_prob, reverse=True):
        flag = "  <== BET" if rr.decision == "BET" else ""
        lines.append(f"{rr.horse_no:>2} {rr.model_prob:>7.3f} {rr.market_prob:>7.3f} "
                     f"{rr.odds:>6.1f} {rr.ev:>+8.3f}  {rr.decision}{flag}")
    bets = [r for r in rec.runners if r.decision == "BET"]
    lines.append("")
    if bets:
        lines.append(f"{len(bets)} bet(s) recommended, total stake "
                     f"{sum(b.stake for b in bets):.2f}.")
    else:
        lines.append("NO BET. " + (rec.runners[0].reason if rec.runners else ""))
    # consistency signal
    c = rec.consistency
    if c.get("rows"):
        top = c["rows"][0]
        lines.append("")
        lines.append(f"Cross-pool signal (NOT arbitrage): place EV vs market baseline "
                     f"{c['expected_market_ev']:+.3f}; most generous place spot = horse "
                     f"{top['horse_no']} (place EV {top['place_ev_market']:+.3f}).")
    return "\n".join(lines)
