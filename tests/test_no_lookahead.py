"""The most important test: the dataset builder must not leak future information.

Guarantee verified: a past race's FEATURE values are byte-identical whether or not a
FUTURE race exists in the DB. If any feature changed when we appended a later race, that
feature would be using lookahead information.
"""
import math

import pandas as pd

from hkjc_edge.pipeline.dataset import FEATURE_COLUMNS, LABEL_COLUMNS, build_dataset


def _add_race(db, date_iso, course, race_no, runners, fetch_id):
    """runners: list of dicts {horse, jockey, trainer, no, draw, awt, win_odds, finish_pos}."""
    race_id = db.upsert("race", {
        "race_date": date_iso, "racecourse": course, "race_no": race_no,
        "distance_m": 1200, "going": "GOOD", "track": "Turf", "class": "Class 4",
        "source_fetch_id": fetch_id, "ingested_at": "t",
    }, ["race_date", "racecourse", "race_no"])
    for r in runners:
        hid = db.get_or_create_horse(brand_code=r["horse"], name=r["horse"], fetch_id=fetch_id)
        jid = db.get_or_create_jockey(r["jockey"], fetch_id)
        tid = db.get_or_create_trainer(r["trainer"], fetch_id)
        db.upsert("runner", {
            "race_id": race_id, "horse_id": hid, "horse_no": r["no"], "draw": r["draw"],
            "actual_weight": r["awt"], "jockey_id": jid, "trainer_id": tid,
            "source_fetch_id": fetch_id, "ingested_at": "t",
        }, ["race_id", "horse_no"])
        db.upsert("result", {
            "race_id": race_id, "horse_no": r["no"], "finish_pos": r["finish_pos"],
            "win_odds": r["win_odds"], "source_fetch_id": fetch_id, "ingested_at": "t",
        }, ["race_id", "horse_no"])
    db.commit()
    return race_id


def _seed_three_meetings(db, fetch_id):
    field = lambda winner: [
        {"horse": "A", "jockey": "JK1", "trainer": "TR1", "no": 1, "draw": 1, "awt": 126,
         "win_odds": 3.0, "finish_pos": 1 if winner == "A" else 2},
        {"horse": "B", "jockey": "JK2", "trainer": "TR2", "no": 2, "draw": 2, "awt": 123,
         "win_odds": 4.0, "finish_pos": 1 if winner == "B" else 3},
        {"horse": "C", "jockey": "JK3", "trainer": "TR1", "no": 3, "draw": 3, "awt": 120,
         "win_odds": 6.0, "finish_pos": 1 if winner == "C" else 4},
    ]
    _add_race(db, "2025-01-05", "ST", 1, field("A"), fetch_id)
    _add_race(db, "2025-01-12", "ST", 1, field("B"), fetch_id)
    _add_race(db, "2025-01-19", "ST", 1, field("C"), fetch_id)


def _row(df, horse_brand, date_iso, db):
    hid = db.execute("SELECT horse_id FROM horse WHERE brand_code=?", (horse_brand,)).fetchone()[0]
    sub = df[(df["horse_id"] == hid) & (df["race_date"] == pd.Timestamp(date_iso))]
    assert len(sub) == 1
    return sub.iloc[0]


def _equal(a, b):
    if (isinstance(a, float) and math.isnan(a)) or (a is None) or pd.isna(a):
        return (isinstance(b, float) and math.isnan(b)) or (b is None) or pd.isna(b)
    return a == b


def test_features_and_labels_are_disjoint():
    assert set(FEATURE_COLUMNS).isdisjoint(set(LABEL_COLUMNS))


def test_no_future_leakage(tmp_db):
    fid = tmp_db.record_fetch("test", url="x")
    _seed_three_meetings(tmp_db, fid)

    df_before = build_dataset(tmp_db)
    before = _row(df_before, "A", "2025-01-12", tmp_db)
    snapshot = {c: before[c] for c in FEATURE_COLUMNS if c in df_before.columns}

    # Append a FUTURE meeting with DIFFERENT outcomes.
    future = [
        {"horse": "A", "jockey": "JK1", "trainer": "TR1", "no": 1, "draw": 5, "awt": 130,
         "win_odds": 2.0, "finish_pos": 1},
        {"horse": "B", "jockey": "JK2", "trainer": "TR2", "no": 2, "draw": 6, "awt": 121,
         "win_odds": 9.0, "finish_pos": 2},
        {"horse": "C", "jockey": "JK3", "trainer": "TR1", "no": 3, "draw": 7, "awt": 118,
         "win_odds": 12.0, "finish_pos": 3},
    ]
    _add_race(tmp_db, "2025-02-02", "ST", 1, future, fid)

    df_after = build_dataset(tmp_db)
    after = _row(df_after, "A", "2025-01-12", tmp_db)

    for c, v in snapshot.items():
        assert _equal(v, after[c]), f"feature {c!r} changed after adding a future race: {v!r} -> {after[c]!r}"


def test_form_features_are_prior_only(tmp_db):
    fid = tmp_db.record_fetch("test", url="x")
    _seed_three_meetings(tmp_db, fid)
    df = build_dataset(tmp_db)

    # On A's debut (first meeting) there are no prior runs.
    debut = _row(df, "A", "2025-01-05", tmp_db)
    assert debut["horse_prior_runs"] == 0
    assert pd.isna(debut["horse_prev_finish"])
    assert pd.isna(debut["horse_prior_win_rate"])

    # By the 3rd meeting A has 2 prior runs; A won race 1 then was 2nd -> prior win rate 0.5.
    third = _row(df, "A", "2025-01-19", tmp_db)
    assert third["horse_prior_runs"] == 2
    assert abs(third["horse_prior_win_rate"] - 0.5) < 1e-9


def test_market_prob_normalised_per_race(tmp_db):
    fid = tmp_db.record_fetch("test", url="x")
    _seed_three_meetings(tmp_db, fid)
    df = build_dataset(tmp_db)
    sums = df.groupby("race_id")["market_prob"].sum()
    for s in sums:
        assert abs(s - 1.0) < 1e-9  # de-vigged implied probs sum to 1 within each race
