"""Orchestrate HKJC source -> SQLite with provenance.

Critically: although the RESULTS page carries both pre-race fields (draw, weight, jockey,
trainer) and outcomes, we split them into the BET-TIME table (runner) and the OUTCOME
tables (result, dividend, sectional) on write — preserving the no-lookahead separation
the dataset builder relies on.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..db import Database
from ..logging_setup import get_logger
from ..sources.hkjc_racing import HkjcRacingSource
from ..sources.models import ParsedRaceResults

log = get_logger("ingest")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_results(db: Database, parsed: ParsedRaceResults, fetch_id: int) -> int:
    """Persist one race's parsed results. Returns number of rows written."""
    m = parsed.meta
    now = _now()
    rows = 0
    race_id = db.upsert("race", {
        "race_date": m.race_date, "racecourse": m.racecourse, "race_no": m.race_no,
        "race_index": m.race_index, "class": m.class_, "distance_m": m.distance_m,
        "going": m.going, "track": m.track, "course": m.course,
        "prize_money": m.prize_money, "race_name": m.race_name,
        "rating_band": m.rating_band, "source_fetch_id": fetch_id, "ingested_at": now,
    }, ["race_date", "racecourse", "race_no"])
    rows += 1

    for r in parsed.results:
        if r.horse_no is None:
            continue
        horse_id = db.get_or_create_horse(brand_code=r.horse_code, name=r.horse_name,
                                          fetch_id=fetch_id)
        jky_id = db.get_or_create_jockey(r.jockey, fetch_id) if r.jockey else None
        trn_id = db.get_or_create_trainer(r.trainer, fetch_id) if r.trainer else None

        # BET-TIME row (declared/entry info recoverable from results) -> runner
        db.upsert("runner", {
            "race_id": race_id, "horse_id": horse_id, "horse_no": r.horse_no,
            "draw": r.draw, "actual_weight": r.actual_weight,
            "declared_weight": r.declared_weight, "jockey_id": jky_id,
            "trainer_id": trn_id, "horse_name_raw": r.horse_name,
            "scratched": 0, "source_fetch_id": fetch_id, "ingested_at": now,
        }, ["race_id", "horse_no"])

        # OUTCOME row -> result
        db.upsert("result", {
            "race_id": race_id, "horse_no": r.horse_no, "finish_pos": r.finish_pos,
            "finish_pos_raw": r.finish_pos_raw, "dead_heat": 1 if r.dead_heat else 0,
            "disqualified": 1 if r.disqualified else 0, "lengths_behind": r.lengths_behind,
            "running_position": r.running_position, "finish_time_s": r.finish_time_s,
            "win_odds": r.win_odds, "source_fetch_id": fetch_id, "ingested_at": now,
        }, ["race_id", "horse_no"])
        rows += 2

    for d in parsed.dividends:
        db.execute(
            """INSERT INTO dividend (race_id, pool, combination, dividend_hkd,
               source_fetch_id, ingested_at) VALUES (?,?,?,?,?,?)""",
            (race_id, d.pool, d.combination, d.dividend_hkd, fetch_id, now),
        )
        rows += 1
    db.commit()
    return rows


def write_sectionals(db: Database, race_id: int, sectionals, fetch_id: int) -> int:
    now = _now()
    n = 0
    for s in sectionals:
        db.upsert("sectional", {
            "race_id": race_id, "horse_no": s.horse_no, "section_index": s.section_index,
            "section_time_s": s.section_time_s, "position": s.position, "margin": s.margin,
            "source_fetch_id": fetch_id, "ingested_at": now,
        }, ["race_id", "horse_no", "section_index"])
        n += 1
    db.commit()
    return n


def ingest_meeting(db: Database, source: HkjcRacingSource, date_iso: str, course: str,
                   *, with_sectionals: bool = True, max_races: int = 14) -> dict:
    """Fetch + persist a full race meeting. Returns a summary dict."""
    summary = {"date": date_iso, "course": course, "races": 0, "rows": 0, "sectionals": 0}

    # Fetch race 1 first to discover the number of races on the card.
    first = source.fetch_results(date_iso, course, 1)
    if first.status != 200 or not first.text.strip():
        log.warning("no meeting found for %s %s", date_iso, course)
        return summary
    n_races = HkjcRacingSource.discover_race_count(first.text) or 0
    if n_races == 0:
        log.warning("no races discovered for %s %s", date_iso, course)
        return summary
    n_races = min(n_races, max_races)
    log.info("%s %s: %d races", date_iso, course, n_races)

    for race_no in range(1, n_races + 1):
        fr = first if race_no == 1 else source.fetch_results(date_iso, course, race_no)
        fetch_id = db.record_fetch("hkjc_racing.results", url=fr.url,
                                   http_status=fr.status, content=fr.content,
                                   from_cache=fr.from_cache)
        parsed = HkjcRacingSource.parse_results(fr.text, date_iso, course, race_no)
        if not parsed.results:
            log.info("  race %d: no results parsed (skipping)", race_no)
            continue
        summary["rows"] += write_results(db, parsed, fetch_id)
        summary["races"] += 1

        if with_sectionals:
            try:
                fs = source.fetch_sectional(date_iso, course, race_no)
                sfetch = db.record_fetch("hkjc_racing.sectional", url=fs.url,
                                         http_status=fs.status, content=fs.content,
                                         from_cache=fs.from_cache)
                secs = HkjcRacingSource.parse_sectional(fs.text, date_iso, course, race_no)
                if secs:
                    rid = db.execute(
                        "SELECT race_id FROM race WHERE race_date=? AND racecourse=? AND race_no=?",
                        (date_iso, course, race_no)).fetchone()[0]
                    summary["sectionals"] += write_sectionals(db, rid, secs, sfetch)
            except Exception as e:  # sectionals are best-effort
                log.warning("  race %d: sectional fetch/parse failed: %s", race_no, e)
    return summary
