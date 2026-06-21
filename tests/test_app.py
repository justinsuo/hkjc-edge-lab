"""Phase 4: EV/Kelly math, bankroll guardrails, cross-pool consistency, NO-BET default."""
import numpy as np

from hkjc_edge.app.consistency import cross_pool_place_signal
from hkjc_edge.app.ev import (
    BankrollConfig, BankrollState, full_kelly_fraction, settle_bet, size_bet, win_ev,
)
from hkjc_edge.model.harville import default_place_k, harville_place_probs


def test_win_ev_and_kelly():
    assert abs(win_ev(0.5, 3.0) - 0.5) < 1e-12
    assert win_ev(0.2, 3.0) < 0
    # full Kelly for p=0.5, O=3 (b=2): (0.5*2 - 0.5)/2 = 0.25
    assert abs(full_kelly_fraction(0.5, 3.0) - 0.25) < 1e-12
    assert full_kelly_fraction(0.2, 3.0) == 0.0   # not +EV -> 0


def _state(**over):
    cfg = BankrollConfig(**over)
    return BankrollState(cfg)


def test_size_bet_applies_per_bet_cap():
    st = _state()
    stake, reason = size_bet(0.5, 3.0, st)
    # desired = 0.25*0.25*1000 = 62.5, capped by per_bet 2% = 20
    assert stake == 20.0 and "Kelly" in reason


def test_size_bet_not_positive_ev():
    st = _state()
    stake, reason = size_bet(0.2, 3.0, st)
    assert stake == 0.0 and reason == "not +EV"


def test_size_bet_per_race_cap():
    st = _state()
    stake, _ = size_bet(0.5, 3.0, st, race_committed=39.0)  # per-race room = 40-39 = 1
    assert stake == 1.0


def test_size_bet_exposure_cap():
    st = _state()
    st.session_staked = 99.0                              # exposure room = 100-99 = 1
    stake, _ = size_bet(0.5, 3.0, st)
    assert stake == 1.0


def test_stop_loss_halts():
    st = _state()
    st.bankroll = 700.0                                   # threshold = 1000*0.75 = 750
    stake, reason = size_bet(0.5, 3.0, st)
    assert stake == 0.0 and "stop-loss" in reason


def test_session_loss_halts():
    st = _state()
    st.session_pnl = -100.0                               # limit = -1000*0.10 = -100
    stake, reason = size_bet(0.5, 3.0, st)
    assert stake == 0.0 and "session loss" in reason


def test_settle_updates_bankroll():
    st = _state()
    settle_bet(st, stake=10.0, odds=3.0, won=True)
    assert st.bankroll == 1020.0 and st.session_pnl == 20.0
    settle_bet(st, stake=10.0, odds=3.0, won=False)
    assert st.bankroll == 1010.0


def test_consistency_is_minus_takeout_when_pools_agree():
    # Construct place dividends consistent with the market's Harville place probs.
    t = 0.175
    win = np.array([0.30, 0.22, 0.15, 0.12, 0.09, 0.06, 0.04, 0.02])
    horse_nos = list(range(1, 9))
    k = default_place_k(len(win))
    place_p = harville_place_probs(win, k)
    # dividend (per HK$10) that gives EV == -takeout: div/10 = (1-t)/place_p
    place_div = {hn: 10 * (1 - t) / place_p[i] for i, hn in enumerate(horse_nos)}
    sig = cross_pool_place_signal(win, win, place_div, horse_nos, takeout_place=t)
    assert "NOT arbitrage" in sig["note"]
    for row in sig["rows"]:
        assert abs(row["place_ev_market"] - (-t)) < 1e-6   # internally consistent => -takeout


def _seed(db, n_races=6, field=6, seed=1):
    import numpy as np
    rng = np.random.default_rng(seed)
    fid = db.record_fetch("test", url="x")
    for r in range(n_races):
        q = rng.dirichlet(np.ones(field))
        O = 0.825 / q
        winner = int(rng.choice(field, p=q))
        race_id = db.upsert("race", {
            "race_date": f"2025-01-{r+1:02d}", "racecourse": "ST", "race_no": 1,
            "distance_m": 1200, "going": "GOOD", "track": "Turf", "class": "Class 4",
            "source_fetch_id": fid, "ingested_at": "t"}, ["race_date", "racecourse", "race_no"])
        for h in range(field):
            hid = db.get_or_create_horse(brand_code=f"H{h}", name=f"H{h}", fetch_id=fid)
            jid = db.get_or_create_jockey(f"JK{h}", fid)
            tid = db.get_or_create_trainer(f"TR{h}", fid)
            db.upsert("runner", {"race_id": race_id, "horse_id": hid, "horse_no": h + 1,
                                 "draw": h + 1, "actual_weight": 120, "jockey_id": jid,
                                 "trainer_id": tid, "source_fetch_id": fid, "ingested_at": "t"},
                      ["race_id", "horse_no"])
            db.upsert("result", {"race_id": race_id, "horse_no": h + 1,
                                 "finish_pos": 1 if h == winner else h + 2,
                                 "finish_time_s": 69.0 + h * 0.1, "win_odds": float(O[h]),
                                 "source_fetch_id": fid, "ingested_at": "t"},
                      ["race_id", "horse_no"])
    db.commit()
    return race_id


def test_recommender_no_bet_by_default_and_logs(tmp_db):
    from hkjc_edge.config import load_config
    from hkjc_edge.app.recommender import Recommender
    last_race = _seed(tmp_db, n_races=6)
    cfg = load_config()                       # real config: edge gate is OFF
    rec = Recommender(tmp_db, cfg).recommend(last_race, min_train_races=2)
    assert rec.edge_gate_enabled is False
    assert len(rec.runners) == 6
    assert all(r.decision == "NO BET" for r in rec.runners)   # gate off => always NO BET
    # all recommendations were logged
    assert tmp_db.count("recommendation") == 6


def test_consistency_flags_generous_place_spot():
    t = 0.175
    win = np.array([0.30, 0.22, 0.15, 0.12, 0.09, 0.06, 0.04, 0.02])
    horse_nos = list(range(1, 9))
    k = default_place_k(len(win))
    place_p = harville_place_probs(win, k)
    place_div = {hn: 10 * (1 - t) / place_p[i] for i, hn in enumerate(horse_nos)}
    place_div[5] *= 1.5                                    # make horse 5's place pay 50% more
    sig = cross_pool_place_signal(win, win, place_div, horse_nos, takeout_place=t)
    assert sig["rows"][0]["horse_no"] == 5                 # most generous -> sorted first
    assert sig["rows"][0]["place_ev_market"] > -t
