"""ServiceLayer — the snappy, honest core behind the Flask API.

Owns three caches keyed by a master `data_version` fingerprint so invalidation is automatic
(new data => new version => caches miss & refill):
  * DatasetCache  — the build_dataset() frame (built once).
  * ModelCache    — TwoStageModel trained on races strictly before an `as_of` date (leak-free;
                    one model serves every race that day).
  * ResultCache   — validation / eval / what-if / tracking results.

Every payload that mentions a bet/EV carries the verdict + default_action=NO_BET, so the UI
cannot drift from the validated truth (per the honesty checklist).
"""
from __future__ import annotations

import dataclasses
import hashlib
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..app.consistency import cross_pool_place_signal
from ..app.ev import BankrollConfig, BankrollState, size_bet, win_ev
from ..config import load_config
from ..db import Database
from ..model.market import proportional_devig, shin_devig
from ..pipeline.dataset import build_dataset
from ..validation.metrics import bootstrap_margin, clv_report, profit_sim_value, winner_logloss
from ..validation.walkforward import TwoStageModel, walk_forward
from ..validation.whatif import ev_threshold_sweep


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _evaluable(df: pd.DataFrame) -> pd.DataFrame:
    ok = df.groupby("race_id")["market_prob"].transform(lambda s: s.notna().all())
    return df[ok & df["finish_pos"].notna()].copy()


class ServiceLayer:
    MIN_PRIOR_RACES = 200

    def __init__(self, cfg=None):
        self.cfg = cfg or load_config()
        self.db_path = self.cfg.db_path
        self.root = self.cfg.root
        self._lock = threading.RLock()
        self._dataset_cache: tuple[str, pd.DataFrame] | None = None
        self._oos_cache: dict[str, pd.DataFrame] = {}
        self._model_cache: "OrderedDict[tuple, TwoStageModel]" = OrderedDict()
        self._result_cache: dict[str, dict] = {}
        self._model_cap = 24
        self._edge_gate_override: bool | None = None   # session-only; resets on relaunch

    def edge_gate_enabled(self) -> bool:
        if self._edge_gate_override is not None:
            return self._edge_gate_override
        return bool(self.cfg.get("app.edge_gate_enabled", False))

    def set_edge_gate(self, enabled: bool) -> dict:
        self._edge_gate_override = bool(enabled)
        return {"edge_gate_enabled": self._edge_gate_override,
                "note": "session-only override; resets to config default on relaunch"}

    # -- db / versioning ---------------------------------------------------------------
    def _db(self) -> Database:
        return Database(self.db_path)

    def data_version(self) -> str:
        # COUNT + MAX(rowid) per table, so delete+insert (same count) also invalidates caches.
        sig = []
        with self._db() as db:
            for t in ("race", "runner", "result", "dividend", "sectional"):
                try:
                    row = db.execute(f"SELECT COUNT(*), COALESCE(MAX(rowid),0) FROM {t}").fetchone()
                    sig.append(f"{row[0]}:{row[1]}")
                except Exception:
                    sig.append("0:0")
        return "v" + hashlib.sha1("-".join(sig).encode()).hexdigest()[:12]

    # -- dataset cache -----------------------------------------------------------------
    def dataset(self) -> pd.DataFrame:
        ver = self.data_version()
        with self._lock:
            if self._dataset_cache and self._dataset_cache[0] == ver:
                return self._dataset_cache[1]
        with self._db() as db:
            df = build_dataset(db)
        with self._lock:
            self._dataset_cache = (ver, df)
        return df

    def evaluable(self) -> pd.DataFrame:
        return _evaluable(self.dataset())

    # -- model cache (by as_of date) ---------------------------------------------------
    def model_for(self, as_of: pd.Timestamp) -> tuple[TwoStageModel | None, int]:
        """Return (model trained on races strictly before as_of, n_train_races). model None
        if too little prior history."""
        ver = self.data_version()
        key = (ver, str(pd.Timestamp(as_of).date()))
        with self._lock:
            if key in self._model_cache:
                self._model_cache.move_to_end(key)
                m = self._model_cache[key]
                return m, m._n_train
        ev = self.evaluable()
        train = ev[ev["race_date"] < as_of]
        n_train = int(train["race_id"].nunique())
        if n_train < self.MIN_PRIOR_RACES:
            return None, n_train
        model = TwoStageModel().fit(train)
        model._n_train = n_train
        with self._lock:
            self._model_cache[key] = model
            while len(self._model_cache) > self._model_cap:
                self._model_cache.popitem(last=False)
        return model, n_train

    # -- OOS walk-forward cache --------------------------------------------------------
    def oos(self, min_train: int = 350, step: int = 25) -> pd.DataFrame:
        key = f"{self.data_version()}-{min_train}-{step}"
        with self._lock:
            if key in self._oos_cache:
                return self._oos_cache[key]
        oos = walk_forward(self.dataset(), min_train_races=min_train, step_races=step)
        with self._lock:
            self._oos_cache[key] = oos
        return oos

    # ==================================================================================
    # Public read methods (return JSON-friendly dicts)
    # ==================================================================================
    def status(self) -> dict:
        with self._db() as db:
            counts = {t: db.count(t) for t in
                      ("race", "runner", "result", "dividend", "sectional",
                       "recommendation", "source_fetch", "ingest_run")}
            span = db.execute("SELECT MIN(race_date), MAX(race_date) FROM race").fetchone()
            last_fetch = db.execute(
                "SELECT MAX(fetched_at) FROM source_fetch").fetchone()[0]
        v = self._cached_validation_summary()
        return {
            "db_path": str(self.db_path),
            "counts": counts,
            "date_range": {"first": span[0], "last": span[1]},
            "last_fetch_at": last_fetch,
            "data_version": self.data_version(),
            "verdict": v["verdict"], "default_action": "NO BET",
            "edge_gate_enabled": self.edge_gate_enabled(),
            "takeout_pct": round(float(self.cfg.get("takeout.WIN", 0.175)) * 100, 1),
        }

    def headline(self) -> dict:
        return self._cached_validation_summary()

    def _cached_validation_summary(self) -> dict:
        with self._lock:
            r = self._result_cache.get("validation::" + self.data_version())
        if not r or "clv" not in r or "profit" not in r:   # None, or the {'error':...} sentinel
            return {"verdict": "NOT RUN",
                    "headline": "No validation on record → NO BET (absence of GO = NO-GO).",
                    "clv_margin": None, "clv_ci": None, "ci_includes_zero": True,
                    "default_action": "NO BET", "ran": False}
        c = r["clv"]["models"]["p_combined"]["bootstrap_vs_market"]
        return {
            "verdict": r["verdict"],
            "headline": ("HKJC market is efficient — no demonstrated edge."
                         if r["verdict"] == "NO-GO" else "Edge established — review carefully."),
            "clv_margin": c.get("mean_margin"), "clv_ci": c.get("ci95"),
            "ci_includes_zero": not c.get("significant_at_95", False),
            "plus_ev_bets": r["profit"]["combined"].get("n_bets", 0),
            "default_action": "NO BET", "ran": True,
            "run_at": r.get("run_at"),
        }

    def meetings(self) -> dict:
        with self._db() as db:
            rows = db.execute(
                """SELECT race_date, racecourse, COUNT(*) AS n,
                          SUM(CASE WHEN EXISTS(SELECT 1 FROM result rs WHERE rs.race_id=r.race_id)
                                   THEN 1 ELSE 0 END) AS resulted,
                          MAX(going) AS going
                   FROM race r GROUP BY race_date, racecourse
                   ORDER BY race_date DESC, racecourse""").fetchall()
        meetings = [{"meeting_id": f"{r[0]}_{r[1]}", "date": r[0], "course": r[1],
                     "race_count": r[2], "has_results": bool(r[3]), "going": r[4]}
                    for r in rows]
        return {"meetings": meetings, "total": len(meetings)}

    def races(self, date: str, course: str) -> dict:
        from ..pipeline.dataset import _class_to_level
        with self._db() as db:
            rows = db.execute(
                """SELECT r.race_id, r.race_no, r.distance_m, r.going, r.track, r.class,
                          (SELECT COUNT(*) FROM runner ru WHERE ru.race_id=r.race_id),
                          EXISTS(SELECT 1 FROM result rs WHERE rs.race_id=r.race_id)
                   FROM race r WHERE r.race_date=? AND r.racecourse=? ORDER BY r.race_no""",
                (date, course)).fetchall()
        races = [{"race_id": r[0], "race_no": r[1], "distance": r[2], "going": r[3],
                  "track": r[4], "class": r[5], "class_level": _class_to_level(r[5]),
                  "field_size": r[6], "has_result": bool(r[7])} for r in rows]
        return {"date": date, "course": course, "races": races}

    # -- recommendation (model vs market + EV + consistency), cached model --------------
    def recommend(self, race_id: int, *, bankroll: float | None = None,
                  kelly_fraction: float | None = None) -> dict:
        df = self.dataset()
        race = df[df["race_id"] == race_id]
        if race.empty:
            raise KeyError("race not found")
        race_date = race["race_date"].iloc[0]
        # score only evaluable runners (need market prob); keep all for display
        model, n_train = self.model_for(race_date)
        test = race.sort_values("horse_no").copy()
        edge_gate = self.edge_gate_enabled()
        ev_threshold = float(self.cfg.get("app.ev_threshold", 0.10))

        # market + model probs; score ONLY runners with a market prob (else log(NaN) poisons
        # the combiner), falling back to market for any odds-less runner.
        evaluable_mask = test["market_prob"].notna()
        test["p_market"] = test["market_prob"]
        test["p_combined"] = test["market_prob"]
        insufficient = model is None
        if model is not None and evaluable_mask.any():
            _, pc = model.score(test[evaluable_mask])
            test.loc[evaluable_mask, "p_combined"] = pc

        bcfg = self._bankroll_cfg(bankroll, kelly_fraction)
        state = BankrollState(bcfg)
        runners = []
        race_committed = 0.0
        for _, r in test.iterrows():
            O = float(r["win_odds"]) if pd.notna(r["win_odds"]) else None
            p_model = float(r["p_combined"]) if pd.notna(r["p_combined"]) else None
            p_mkt = float(r["p_market"]) if pd.notna(r["p_market"]) else None
            ev = win_ev(p_model, O) if (p_model is not None and O) else None
            kelly = stake = 0.0
            if not edge_gate:
                decision, reason = "NO BET", "edge gate OFF — validation verdict is NO-GO"
            elif ev is not None and ev > ev_threshold:
                stake, reason = size_bet(p_model, O, state, race_committed=race_committed)
                decision = "BET" if stake > 0 else "NO BET"
                race_committed += stake
            else:
                decision = "NO BET"
                reason = (f"EV {ev:+.3f} ≤ threshold {ev_threshold:+.3f}"
                          if ev is not None else "no odds")
            edge_nats = (float(np.log(p_model / p_mkt)) if (p_model and p_mkt) else None)
            runners.append({
                "horse_no": int(r["horse_no"]),
                "model_prob": round(p_model, 4) if p_model is not None else None,
                "market_prob": round(p_mkt, 4) if p_mkt is not None else None,
                "win_odds": round(O, 2) if O else None,
                "edge_nats": round(edge_nats, 4) if edge_nats is not None else None,
                "ev": round(ev, 4) if ev is not None else None,
                "kelly_stake": round(stake, 2),
                "decision": decision, "reason": reason,
                "finish_pos": int(r["finish_pos"]) if pd.notna(r["finish_pos"]) else None,
            })
        runners.sort(key=lambda x: (x["market_prob"] is None, -(x["market_prob"] or 0)))

        return {
            "race_id": int(race_id),
            "race_date": str(pd.Timestamp(race_date).date()),
            "racecourse": str(test["racecourse"].iloc[0]),
            "race_no": int(test["race_no"].iloc[0]),
            "distance": int(test["distance_m"].iloc[0]) if pd.notna(test["distance_m"].iloc[0]) else None,
            "going": test["going"].iloc[0], "class": test["class"].iloc[0],
            "field_size": int(len(test)),
            "edge_gate_enabled": edge_gate,
            "verdict": self._cached_validation_summary()["verdict"],
            "default_action": "NO BET",
            "n_train_races": n_train,
            "insufficient_history": insufficient,
            "combiner_weights": model.combiner_weights if model else None,
            "takeout_pct": round(float(self.cfg.get("takeout.WIN", 0.175)) * 100, 1),
            "runners": runners,
            "consistency": self._consistency(race_id, test),
            "plus_ev_count": sum(1 for x in runners if x["ev"] is not None and x["ev"] > 0),
        }

    def _consistency(self, race_id: int, test: pd.DataFrame) -> dict:
        with self._db() as db:
            rows = db.execute(
                "SELECT combination, dividend_hkd FROM dividend WHERE race_id=? AND pool='PLACE'",
                (race_id,)).fetchall()
        place_div = {}
        for comb, div in rows:
            try:
                place_div[int(str(comb).strip())] = float(div)
            except (ValueError, TypeError):
                continue
        if not place_div:
            return {"available": False,
                    "note": "Cross-pool consistency signal (information, NOT arbitrage). "
                            "No PLACE dividends for this race."}
        t = test.sort_values("horse_no")
        sig = cross_pool_place_signal(
            t["p_market"].fillna(0).values, t["p_combined"].fillna(0).values, place_div,
            t["horse_no"].astype(int).tolist(),
            takeout_place=float(self.cfg.get("takeout.PLACE", 0.175)))
        sig["available"] = True
        return sig

    def _bankroll_cfg(self, bankroll, kelly_fraction) -> BankrollConfig:
        b = self.cfg.get("app.bankroll", {}) or {}
        return BankrollConfig(
            starting_bankroll=float(bankroll if bankroll else b.get("starting_bankroll", 1000.0)),
            kelly_fraction=float(kelly_fraction if kelly_fraction else b.get("kelly_fraction", 0.25)),
            per_bet_cap_frac=float(b.get("per_bet_cap_frac", 0.02)),
            per_race_cap_frac=float(b.get("per_race_cap_frac", 0.04)),
            total_exposure_cap_frac=float(b.get("total_exposure_cap_frac", 0.10)),
            session_loss_limit_frac=float(b.get("session_loss_limit_frac", 0.10)),
            stop_loss_frac=float(b.get("stop_loss_frac", 0.25)))

    # -- validation (slow; cached, or run via job) -------------------------------------
    def run_validation(self, *, min_train: int = 350, step: int = 25, force: bool = False) -> dict:
        from ..validation.run import run_validation as _rv
        key = "validation::" + self.data_version()
        with self._lock:
            if not force and key in self._result_cache:
                return self._result_cache[key]
        with self._db() as db:
            r = _rv(db, min_train_races=min_train, step_races=step,
                    out_dir=str(self.root / "data" / "validation"), make_plots=True)
        r["run_at"] = _now()
        if "error" not in r:                         # never cache the no-data sentinel
            with self._lock:
                self._result_cache[key] = r
        return r

    def validation_latest(self) -> dict | None:
        with self._lock:
            return self._result_cache.get("validation::" + self.data_version())

    # -- model eval / calibration / feature importance ---------------------------------
    def model_eval(self) -> dict:
        key = "eval::" + self.data_version()
        with self._lock:
            if key in self._result_cache:
                return self._result_cache[key]
        try:
            oos = self.oos()
        except ValueError as e:
            return {"insufficient_data": True, "message": str(e)}
        from ..model.calibration import calibration_report
        rep = {"market": winner_logloss(oos, "p_market"),
               "combined": winner_logloss(oos, "p_combined"),
               "fundamental": winner_logloss(oos, "p_fund"),
               "clv": clv_report(oos)["models"]["p_combined"]["bootstrap_vs_market"],
               "n_oos_races": int(oos["race_id"].nunique())}
        y = (oos["label_won"] == 1).astype(float).values
        rep["calibration"] = {
            "market": calibration_report(y, oos["p_market"].values, 10),
            "combined": calibration_report(y, oos["p_combined"].values, 10),
        }
        # global feature importance from a model trained on the bulk of history
        ev = self.evaluable()
        cutoff = ev["race_date"].quantile(0.7)
        model, _ = self.model_for(ev[ev["race_date"] >= cutoff]["race_date"].min())
        if model is not None:
            imp = model.cl.global_importance()
            rep["feature_importance"] = [{"feature": k, "weight": round(v, 4)}
                                         for k, v in list(imp.items())[:14]]
            rep["combiner_weights"] = model.combiner_weights
        with self._lock:
            self._result_cache[key] = rep
        return rep

    # -- what-if sweep -----------------------------------------------------------------
    def whatif(self, prob_col: str = "p_combined") -> dict:
        if prob_col not in ("p_combined", "p_fund", "p_market"):
            raise ValueError("prob_col must be one of p_combined, p_fund, p_market")
        try:
            oos = self.oos()
        except ValueError as e:
            return {"insufficient_data": True, "message": str(e), "sweep": []}
        sweep = ev_threshold_sweep(oos, prob_col)
        return {"prob_col": prob_col, "sweep": sweep, "n_oos_races": int(oos["race_id"].nunique()),
                "note": "Frozen out-of-sample backtest. Raising the threshold cherry-picks "
                        "fewer, noisier bets — always read the CI, never just the ROI."}

    # -- data quality / coverage -------------------------------------------------------
    def data_quality(self) -> dict:
        df = self.dataset()
        n = len(df)
        ev = self.evaluable()
        cols = ["market_prob", "horse_prior_avg_speed", "horse_best_speed",
                "horse_prior_win_rate", "class_level", "finish_time_s"]
        missing = []
        for c in cols:
            if c in df:
                missing.append({"column": c, "pct_null": round(float(df[c].isna().mean()), 4)})
        return {
            "data_version": self.data_version(),
            "rows": int(n), "races": int(df["race_id"].nunique()),
            "evaluable_races": int(ev["race_id"].nunique()),
            "win_rate": round(float((df["finish_pos"] == 1).mean()), 4),
            "avg_field_size": round(float(df.groupby("race_id")["horse_no"].count().mean()), 2),
            "missingness": missing,
            "no_lookahead": {"verified_by_tests": True,
                             "note": "All features use only strictly-prior races; speed ratings "
                                     "use a prior-only par. Enforced by tests/test_no_lookahead.py."},
        }

    # -- tracking (self-scoreboard) ----------------------------------------------------
    def tracking(self) -> dict:
        from ..app.tracking import reconcile
        with self._db() as db:
            summary = reconcile(db)
            recs = db.execute(
                """SELECT race_date, racecourse, race_no, horse_no, model_prob, market_prob,
                          odds_at_rec, ev, decision, stake, closing_odds, finish_pos, won, pnl,
                          clv, edge_gate_enabled
                   FROM recommendation ORDER BY rec_id DESC LIMIT 200""").fetchall()
            clvs = [row[0] for row in db.execute(
                "SELECT clv FROM recommendation WHERE clv IS NOT NULL").fetchall()]
        ci = None
        replay_note = None
        if len(clvs) >= 10:
            arr = np.array(clvs, float)
            if arr.std() < 1e-9:
                # replay logs use the closing SP as odds-at-rec, so CLV is 0 by construction
                replay_note = ("CLV is 0 by construction in replay mode (odds-at-rec = closing "
                               "SP). A real CLV needs a pre-close odds snapshot.")
            else:
                rng = np.random.default_rng(0)
                boot = np.array([rng.choice(arr, len(arr), True).mean() for _ in range(3000)])
                ci = [round(float(np.percentile(boot, 2.5)), 5),
                      round(float(np.percentile(boot, 97.5)), 5)]
        elif clvs:
            replay_note = "Too few settled recommendations (<10) for a CLV confidence interval."
        items = [{"race_date": r[0], "racecourse": r[1], "race_no": r[2], "horse_no": r[3],
                  "model_prob": r[4], "market_prob": r[5], "odds_at_rec": r[6], "ev": r[7],
                  "decision": r[8], "stake": r[9], "closing_odds": r[10], "finish_pos": r[11],
                  "won": r[12], "pnl": r[13], "clv": r[14], "edge_gate_enabled": bool(r[15])}
                 for r in recs]
        return {"summary": summary, "clv_ci95": ci, "n_clv": len(clvs),
                "replay_note": replay_note, "recommendations": items}

    def log_recommendation(self, race_id: int) -> dict:
        from ..app.recommender import Recommender
        with self._db() as db:
            rec = Recommender(db, self.cfg).recommend(int(race_id), log=True)
        return {"logged": True, "race_id": int(race_id), "runners": len(rec.runners)}

    # -- feasibility report ------------------------------------------------------------
    def report(self) -> dict:
        path = self.root / "research_report.md"
        md = path.read_text() if path.exists() else "# Research report not found"
        return {"format": "markdown", "markdown": md}

    def config(self) -> dict:
        b = self.cfg.get("app.bankroll", {}) or {}
        return {
            "takeout_pct": round(float(self.cfg.get("takeout.WIN", 0.175)) * 100, 1),
            "edge_gate_enabled": self.edge_gate_enabled(),
            "ev_threshold": float(self.cfg.get("app.ev_threshold", 0.10)),
            "min_prior_races": self.MIN_PRIOR_RACES,
            "guardrails": b,
            "http": {"base_delay_seconds": self.cfg.get("http.base_delay_seconds"),
                     "respect_robots": self.cfg.get("http.respect_robots"),
                     "user_agent": self.cfg.get("http.user_agent")},
        }
