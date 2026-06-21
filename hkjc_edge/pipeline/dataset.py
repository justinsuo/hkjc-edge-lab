"""No-lookahead dataset builder.

Produces one row per (race, runner) for backtesting. The contract:

  * FEATURES use ONLY information available at bet time for that race:
      - race conditions (distance, going, track, class, field size)
      - the runner's declared fields (draw, weights, jockey, trainer)
      - FORM features aggregated from STRICTLY PRIOR runs (earlier date, or same day but
        an earlier race — both are known before this race goes off)
      - market_prob: de-vigged implied win probability from the CLOSING win odds. This is
        the market estimate the model must BEAT (Phase 3 CLV test). It is bet-time-usable
        (you can bet at the close) and is the strongest single feature (see Phase 0).
  * LABELS are OUTCOMES, never used as features for the same race:
      - label_won, finish_pos, lengths_behind, finish_time_s

The function `build_dataset` guarantees that a row's features depend only on rows with
(date, race_no) strictly earlier than that row — verified by tests/test_no_lookahead.py
(adding a FUTURE race must not change any past row's features).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..db import Database

# Columns that are SAFE to use as model features (bet-time information).
FEATURE_COLUMNS = [
    "distance_m", "going", "track", "class", "class_level", "field_size",
    "draw", "actual_weight", "declared_weight", "jockey_id", "trainer_id",
    "horse_prior_runs", "horse_days_since", "horse_prev_finish",
    "horse_prior_win_rate", "horse_prior_avg_finish", "horse_prior_avg_winodds",
    "horse_prior_avg_speed", "horse_last_speed", "horse_best_speed",
    "jockey_prior_win_rate", "trainer_prior_win_rate",
    "market_prob",
]

_CLASS_MAP = {"group one": 0, "group two": -1, "group three": -2, "group 1": 0,
              "group 2": -1, "group 3": -2}


def _class_to_level(c):
    """Map a class string to an ordinal (lower = higher class). NaN if not parseable."""
    if c is None:
        return float("nan")
    s = str(c).strip().lower()
    if s in _CLASS_MAP:
        return _CLASS_MAP[s]
    import re
    m = re.search(r"class\s*(\d)", s)
    if m:
        return int(m.group(1))
    return float("nan")
# Columns that are OUTCOMES (labels) — must never be features for the same race.
LABEL_COLUMNS = ["label_won", "finish_pos", "lengths_behind", "finish_time_s"]


def _load_base(db: Database) -> pd.DataFrame:
    sql = """
        SELECT r.race_id, r.race_date, r.racecourse, r.race_no, r.distance_m, r.going,
               r.track, r.class AS class,
               ru.horse_no, ru.horse_id, ru.draw, ru.actual_weight, ru.declared_weight,
               ru.jockey_id, ru.trainer_id,
               res.finish_pos, res.lengths_behind, res.finish_time_s, res.win_odds
        FROM race r
        JOIN runner ru ON ru.race_id = r.race_id
        LEFT JOIN result res ON res.race_id = r.race_id AND res.horse_no = ru.horse_no
    """
    df = pd.read_sql_query(sql, db.conn)
    if df.empty:
        return df
    df["race_date"] = pd.to_datetime(df["race_date"])
    return df


def build_dataset(db: Database) -> pd.DataFrame:
    """Build the no-lookahead feature/label table. Returns a DataFrame."""
    df = _load_base(db)
    if df.empty:
        return df

    # Deterministic chronological order. Same-day ordering by race_no is the true bet-time
    # order (earlier races on a card are decided before later ones).
    df = df.sort_values(["race_date", "race_no", "horse_no"]).reset_index(drop=True)

    # --- labels (outcomes) ---
    df["label_won"] = (df["finish_pos"] == 1).astype("Int64")

    # --- race-level bet-time features ---
    df["field_size"] = df.groupby("race_id")["horse_no"].transform("count")

    # --- market estimate (bet-time): de-vigged implied win prob from closing odds ---
    inv = 1.0 / df["win_odds"].where(df["win_odds"] > 0)
    df["inv_odds"] = inv
    race_inv_sum = df.groupby("race_id")["inv_odds"].transform("sum")
    df["market_prob"] = df["inv_odds"] / race_inv_sum

    # --- class level (lower number = higher class): bet-time static feature ---
    df["class_level"] = df["class"].map(_class_to_level)

    # --- leak-free SPEED FIGURE (an OUTCOME of each race; used ONLY as prior form below) ---
    # velocity = distance / finishing time; compared to a "par" = mean race-velocity at the
    # same (distance, track) over STRICTLY PRIOR races, so par carries no lookahead.
    df["_velocity"] = df["distance_m"] / df["finish_time_s"]
    # Sort by true bet-time order (race_date, race_no) — NOT race_id — so the prior-only par
    # can never include a same-day later race even if race_ids aren't monotonic in race_no.
    _rv = (df.groupby("race_id")
           .agg(race_date=("race_date", "first"), race_no=("race_no", "first"),
                distance_m=("distance_m", "first"),
                track=("track", "first"), rv=("_velocity", "mean"))
           .reset_index().sort_values(["race_date", "race_no", "race_id"]))
    _rv["par"] = (_rv.groupby(["distance_m", "track"])["rv"]
                  .transform(lambda s: s.shift().expanding().mean()))
    df = df.merge(_rv[["race_id", "par"]], on="race_id", how="left")
    df["_speed_fig"] = df["_velocity"] - df["par"]          # >0 = faster than prior par

    # --- horse form from STRICTLY PRIOR runs ---
    df = df.sort_values(["horse_id", "race_date", "race_no"]).reset_index(drop=True)
    gh = df.groupby("horse_id", sort=False)
    df["horse_prior_runs"] = gh.cumcount()                                  # 0 on debut
    df["horse_prev_date"] = gh["race_date"].shift()
    df["horse_days_since"] = (df["race_date"] - df["horse_prev_date"]).dt.days
    df["horse_prev_finish"] = gh["finish_pos"].shift()
    won_num = df["label_won"].astype("float")
    df["_won_f"] = won_num
    df["horse_prior_win_rate"] = (
        df.groupby("horse_id")["_won_f"].transform(lambda s: s.shift().expanding().mean()))
    df["horse_prior_avg_finish"] = (
        df.groupby("horse_id")["finish_pos"].transform(lambda s: s.shift().expanding().mean()))
    df["horse_prior_avg_winodds"] = (
        df.groupby("horse_id")["win_odds"].transform(lambda s: s.shift().expanding().mean()))
    # speed-figure form (each prior race's leak-free speed fig; all strictly historical)
    df["horse_prior_avg_speed"] = (
        df.groupby("horse_id")["_speed_fig"].transform(lambda s: s.shift().expanding().mean()))
    df["horse_last_speed"] = df.groupby("horse_id")["_speed_fig"].shift()
    df["horse_best_speed"] = (
        df.groupby("horse_id")["_speed_fig"].transform(lambda s: s.shift().expanding().max()))

    # --- jockey / trainer prior strike rate (strictly prior rides, same-day-earlier OK) ---
    df = df.sort_values(["race_date", "race_no", "horse_no"]).reset_index(drop=True)
    df["jockey_prior_win_rate"] = (
        df.groupby("jockey_id")["_won_f"].transform(lambda s: s.shift().expanding().mean()))
    df["trainer_prior_win_rate"] = (
        df.groupby("trainer_id")["_won_f"].transform(lambda s: s.shift().expanding().mean()))

    df = df.drop(columns=["_won_f", "horse_prev_date", "inv_odds",
                          "_velocity", "par", "_speed_fig"])
    df["information_asof"] = df["race_date"]      # explicit bet-time marker

    # Final tidy ordering.
    df = df.sort_values(["race_date", "race_no", "horse_no"]).reset_index(drop=True)
    return df


def feature_label_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Convenience: return (X with only FEATURE_COLUMNS, y=label_won)."""
    X = df[[c for c in FEATURE_COLUMNS if c in df.columns]].copy()
    y = df["label_won"].astype("float") if "label_won" in df else pd.Series(dtype=float)
    return X, y
