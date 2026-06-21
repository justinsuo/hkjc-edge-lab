"""Bulk historical importer for the Kaggle 'gdaley/hkracing' format (races.csv + runs.csv).

This is the pragmatic path to a multi-season backtest dataset without a long live scrape.
We CANNOT auto-download it (Kaggle needs credentials); obtain races.csv + runs.csv via the
Kaggle CLI or manual download, then `hkjc import-csv --races races.csv --runs runs.csv`.

The importer is tolerant of column-name variation (different mirrors rename columns) and
records provenance (one source_fetch per file). It maps the dataset's own integer ids to
our reference entities (horse brand_code 'H<id>', jockey 'JK<id>', trainer 'TR<id>').
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from ..db import Database
from ..logging_setup import get_logger
from .parse_util import to_float, to_int

log = get_logger("csv_import")


def _pick(df: pd.DataFrame, *candidates: str) -> Optional[str]:
    """Return the first matching column name (case-insensitive) present in df."""
    lower = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


def _norm_date(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:len(fmt) + 4], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    try:
        return pd.to_datetime(s).strftime("%Y-%m-%d")
    except Exception:
        return None


def import_kaggle_csv(db: Database, races_csv: str | Path, runs_csv: str | Path) -> dict:
    """Import races.csv + runs.csv into the DB. Returns a summary dict."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    races_fetch = db.record_fetch("csv_import.kaggle.races", file_path=str(races_csv),
                                  notes="bulk historical import")
    runs_fetch = db.record_fetch("csv_import.kaggle.runs", file_path=str(runs_csv),
                                 notes="bulk historical import")

    races = pd.read_csv(races_csv)
    runs = pd.read_csv(runs_csv)

    # --- races ---
    c_rid = _pick(races, "race_id", "raceid", "id")
    c_date = _pick(races, "date", "race_date")
    c_venue = _pick(races, "venue", "racecourse", "course_code")
    c_rno = _pick(races, "race_no", "raceno", "race_number")
    c_dist = _pick(races, "distance", "distance_m")
    c_going = _pick(races, "going")
    c_class = _pick(races, "race_class", "class")
    c_surface = _pick(races, "surface", "track")
    c_config = _pick(races, "config", "course")

    ds_to_race: dict = {}
    n_race = 0
    for _, r in races.iterrows():
        date_iso = _norm_date(r[c_date]) if c_date else None
        venue = str(r[c_venue]).strip() if c_venue else None
        rno = to_int(r[c_rno]) if c_rno else None
        if not (date_iso and venue and rno):
            continue
        race_id = db.upsert("race", {
            "race_date": date_iso, "racecourse": venue, "race_no": rno,
            "distance_m": to_int(r[c_dist]) if c_dist else None,
            "going": str(r[c_going]).strip() if c_going and pd.notna(r[c_going]) else None,
            "class": str(r[c_class]).strip() if c_class and pd.notna(r[c_class]) else None,
            "track": str(r[c_surface]).strip() if c_surface and pd.notna(r[c_surface]) else None,
            "course": str(r[c_config]).strip() if c_config and pd.notna(r[c_config]) else None,
            "source_fetch_id": races_fetch, "ingested_at": now,
        }, ["race_date", "racecourse", "race_no"])
        if c_rid:
            ds_to_race[r[c_rid]] = race_id
        n_race += 1

    # --- runs ---
    c_rid2 = _pick(runs, "race_id", "raceid")
    c_hno = _pick(runs, "horse_no", "horseno", "number")
    c_hid = _pick(runs, "horse_id", "horseid")
    c_res = _pick(runs, "result", "finish_pos", "place", "position")
    c_lbw = _pick(runs, "lengths_behind", "behind", "lbw")
    c_draw = _pick(runs, "draw", "barrier")
    c_awt = _pick(runs, "actual_weight", "act_wt")
    c_dwt = _pick(runs, "declared_weight", "body_weight", "decl_wt")
    c_rate = _pick(runs, "horse_rating", "rating")
    c_gear = _pick(runs, "horse_gear", "gear")
    c_ft = _pick(runs, "finish_time", "time")
    c_wo = _pick(runs, "win_odds", "winodds", "sp")
    c_jky = _pick(runs, "jockey_id", "jockeyid")
    c_trn = _pick(runs, "trainer_id", "trainerid")
    c_sire = _pick(runs, "sire")
    c_dam = _pick(runs, "dam")
    sec_time_cols = [c for c in runs.columns if c.lower().startswith("time") and c[-1].isdigit()]
    sec_pos_cols = [c for c in runs.columns if c.lower().startswith("position_sec")]

    n_runner = n_result = n_sec = 0
    for _, r in runs.iterrows():
        ds_rid = r[c_rid2] if c_rid2 else None
        race_id = ds_to_race.get(ds_rid)
        if race_id is None:
            continue
        horse_no = to_int(r[c_hno]) if c_hno else None
        hid = r[c_hid] if c_hid else None
        horse_id = db.get_or_create_horse(
            brand_code=f"H{int(hid)}" if hid is not None and pd.notna(hid) else None,
            name=f"H{int(hid)}" if hid is not None and pd.notna(hid) else None,
            sire=str(r[c_sire]) if c_sire and pd.notna(r[c_sire]) else None,
            dam=str(r[c_dam]) if c_dam and pd.notna(r[c_dam]) else None,
            fetch_id=runs_fetch)
        jky_id = db.get_or_create_jockey(f"JK{int(r[c_jky])}", runs_fetch) \
            if c_jky and pd.notna(r[c_jky]) else None
        trn_id = db.get_or_create_trainer(f"TR{int(r[c_trn])}", runs_fetch) \
            if c_trn and pd.notna(r[c_trn]) else None

        db.upsert("runner", {
            "race_id": race_id, "horse_id": horse_id, "horse_no": horse_no,
            "draw": to_int(r[c_draw]) if c_draw else None,
            "actual_weight": to_int(r[c_awt]) if c_awt else None,
            "declared_weight": to_int(r[c_dwt]) if c_dwt else None,
            "jockey_id": jky_id, "trainer_id": trn_id,
            "rating": to_int(r[c_rate]) if c_rate else None,
            "gear": str(r[c_gear]).strip() if c_gear and pd.notna(r[c_gear]) else None,
            "source_fetch_id": runs_fetch, "ingested_at": now,
        }, ["race_id", "horse_no"])
        n_runner += 1

        finish_pos = to_int(r[c_res]) if c_res else None
        db.upsert("result", {
            "race_id": race_id, "horse_no": horse_no, "finish_pos": finish_pos,
            "finish_pos_raw": str(r[c_res]) if c_res else None,
            "lengths_behind": to_float(r[c_lbw]) if c_lbw else None,
            "finish_time_s": to_float(r[c_ft]) if c_ft else None,
            "win_odds": to_float(r[c_wo]) if c_wo else None,
            "source_fetch_id": runs_fetch, "ingested_at": now,
        }, ["race_id", "horse_no"])
        n_result += 1

        for idx, col in enumerate(sorted(sec_time_cols), start=1):
            t = to_float(r[col]) if pd.notna(r[col]) else None
            if t is None:
                continue
            pos = None
            if idx - 1 < len(sec_pos_cols):
                pos = to_int(r[sorted(sec_pos_cols)[idx - 1]])
            db.upsert("sectional", {
                "race_id": race_id, "horse_no": horse_no, "section_index": idx,
                "section_time_s": t, "position": pos,
                "source_fetch_id": runs_fetch, "ingested_at": now,
            }, ["race_id", "horse_no", "section_index"])
            n_sec += 1

    db.commit()
    summary = {"races": n_race, "runners": n_runner, "results": n_result, "sectionals": n_sec}
    log.info("CSV import complete: %s", summary)
    return summary
