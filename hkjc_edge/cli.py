"""Command-line interface for the HKJC edge tool (Phase 1: data pipeline)."""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from .config import load_config
from .db import Database
from .logging_setup import get_logger
from .pipeline.dataset import FEATURE_COLUMNS, LABEL_COLUMNS, build_dataset
from .pipeline.ingest import ingest_meeting
from .sources.csv_import import import_kaggle_csv
from .sources.hkjc_racing import HkjcRacingSource
from .sources.http_client import PoliteClient

log = get_logger("cli")


def _client(cfg) -> PoliteClient:
    return PoliteClient(
        user_agent=cfg.get("http.user_agent"),
        cache_dir=cfg.path("http.cache_dir"),
        base_delay_seconds=cfg.get("http.base_delay_seconds", 4.0),
        jitter_seconds=cfg.get("http.jitter_seconds", 2.0),
        timeout_seconds=cfg.get("http.timeout_seconds", 30.0),
        max_retries=cfg.get("http.max_retries", 3),
        backoff_factor=cfg.get("http.backoff_factor", 2.0),
        respect_robots=cfg.get("http.respect_robots", True),
        cache_ttl_hours=cfg.get("http.cache_ttl_hours", 336.0),
        max_requests_per_run=cfg.get("http.max_requests_per_run", 600),
    )


def cmd_init_db(args, cfg) -> int:
    db = Database(cfg.db_path)
    print(f"Initialized SQLite DB at {cfg.db_path}")
    print(f"schema_version = "
          f"{db.execute('SELECT value FROM schema_meta WHERE key=\"schema_version\"').fetchone()[0]}")
    db.close()
    return 0


def cmd_fetch_meeting(args, cfg) -> int:
    db = Database(cfg.db_path)
    client = _client(cfg)
    source = HkjcRacingSource(client, cfg)
    run_id = db.start_run(f"fetch-meeting {args.date} {args.course}")
    try:
        summary = ingest_meeting(db, source, args.date, args.course,
                                 with_sectionals=not args.no_sectionals)
        db.finish_run(run_id, "ok", rows_written=summary["rows"],
                      requests_made=client.requests_made, notes=str(summary))
        print(f"Ingested {args.date} {args.course}: {summary}")
        print(f"(network requests this run: {client.requests_made})")
    except Exception as e:
        db.finish_run(run_id, "error", requests_made=client.requests_made, notes=str(e))
        log.error("fetch-meeting failed: %s", e)
        return 1
    finally:
        db.close()
    return 0


def cmd_fetch_range(args, cfg) -> int:
    """Try each date in [start,end]; HKJC races only on some days, so empty days are skipped."""
    db = Database(cfg.db_path)
    client = _client(cfg)
    source = HkjcRacingSource(client, cfg)
    courses = args.courses.split(",") if args.courses else cfg.get("ingest.default_racecourses", ["ST", "HV"])
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    run_id = db.start_run(f"fetch-range {args.start}..{args.end} {courses}")
    total = {"races": 0, "rows": 0, "sectionals": 0, "meetings": 0}
    d = start
    try:
        while d <= end:
            for course in courses:
                try:
                    s = ingest_meeting(db, source, d.isoformat(), course,
                                       with_sectionals=not args.no_sectionals)
                    if s["races"]:
                        total["meetings"] += 1
                        for k in ("races", "rows", "sectionals"):
                            total[k] += s[k]
                        print(f"  {d} {course}: {s['races']} races")
                except Exception as e:  # one bad meeting shouldn't kill the range
                    log.warning("%s %s failed: %s", d, course, e)
            d += timedelta(days=1)
        db.finish_run(run_id, "ok", rows_written=total["rows"],
                      requests_made=client.requests_made, notes=str(total))
        print(f"Range complete: {total} (network requests: {client.requests_made})")
    except Exception as e:
        db.finish_run(run_id, "error", requests_made=client.requests_made, notes=str(e))
        log.error("fetch-range failed: %s", e)
        return 1
    finally:
        db.close()
    return 0


def cmd_import_csv(args, cfg) -> int:
    db = Database(cfg.db_path)
    run_id = db.start_run(f"import-csv {args.races} {args.runs}")
    try:
        summary = import_kaggle_csv(db, args.races, args.runs)
        db.finish_run(run_id, "ok", rows_written=sum(summary.values()), notes=str(summary))
        print(f"Imported: {summary}")
    except Exception as e:
        db.finish_run(run_id, "error", notes=str(e))
        log.error("import-csv failed: %s", e)
        return 1
    finally:
        db.close()
    return 0


def cmd_build_dataset(args, cfg) -> int:
    db = Database(cfg.db_path)
    df = build_dataset(db)
    db.close()
    if df.empty:
        print("No data in DB. Ingest a meeting or import CSVs first.")
        return 1
    out = args.out or str(cfg.root / "data" / "dataset.csv")
    df.to_csv(out, index=False)
    print(f"Built no-lookahead dataset: {len(df)} rows, {df['race_id'].nunique()} races")
    print(f"  features: {[c for c in FEATURE_COLUMNS if c in df.columns]}")
    print(f"  labels:   {[c for c in LABEL_COLUMNS if c in df.columns]}")
    print(f"  written to {out}")
    return 0


def cmd_train(args, cfg) -> int:
    import json

    from .model.evaluate import format_report, run_eval
    db = Database(cfg.db_path)
    r = run_eval(db, test_frac=args.test_frac, l2=args.l2)
    db.close()
    print(format_report(r))
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(r, fh, indent=2, default=str)
        print(f"\nmetrics written to {args.out}")
    return 0


def cmd_validate(args, cfg) -> int:
    import json

    from .validation.run import format_verdict, run_validation
    db = Database(cfg.db_path)
    r = run_validation(db, min_train_races=args.min_train, step_races=args.step,
                       l2=args.l2, ev_threshold=args.ev_threshold,
                       kelly_fraction=args.kelly_fraction,
                       out_dir=str(cfg.root / "data" / "validation"),
                       make_plots=not args.no_plots)
    db.close()
    print(format_verdict(r))
    with open(cfg.root / "data" / "validation" / "metrics.json", "w") as fh:
        json.dump(r, fh, indent=2, default=str)
    print(f"\nReport + plots in {cfg.root / 'data' / 'validation'}")
    return 0


def _resolve_race_id(db, args):
    if args.race_id is not None:
        return args.race_id
    row = db.execute(
        "SELECT race_id FROM race WHERE race_date=? AND racecourse=? AND race_no=?",
        (args.date, args.course, args.race)).fetchone()
    return row[0] if row else None


def cmd_recommend(args, cfg) -> int:
    from .app.recommender import Recommender, format_recommendation
    db = Database(cfg.db_path)
    race_id = _resolve_race_id(db, args)
    if race_id is None:
        print("Race not found in DB. Ingest it first (fetch-meeting), or pass --race-id.")
        db.close()
        return 1
    rec = Recommender(db, cfg).recommend(race_id, log=not args.no_log)
    print(format_recommendation(rec))
    db.close()
    return 0


def cmd_track(args, cfg) -> int:
    from .app.tracking import reconcile
    db = Database(cfg.db_path)
    summary = reconcile(db)
    db.close()
    print("Self-tracking (recommendation log reconciled with results):")
    for k, v in summary.items():
        print(f"  {k:24s}: {v}")
    return 0


def cmd_status(args, cfg) -> int:
    db = Database(cfg.db_path)
    print(f"DB: {cfg.db_path}")
    for t in ["race", "runner", "result", "dividend", "sectional", "horse", "jockey",
              "trainer", "odds_snapshot", "source_fetch", "ingest_run"]:
        try:
            print(f"  {t:14s}: {db.count(t):>8d} rows")
        except Exception:
            print(f"  {t:14s}: (missing)")
    rows = db.execute(
        "SELECT command, started_at, status, rows_written, requests_made "
        "FROM ingest_run ORDER BY run_id DESC LIMIT 5").fetchall()
    if rows:
        print("\nRecent ingest runs:")
        for r in rows:
            print(f"  [{r['status']}] {r['started_at']} | {r['command']} "
                  f"| rows={r['rows_written']} reqs={r['requests_made']}")
    db.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hkjc", description="HKJC edge tool — Phase 1 data pipeline")
    p.add_argument("--config", default=None, help="path to config.yaml")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="create the SQLite DB and apply schema")

    fm = sub.add_parser("fetch-meeting", help="fetch + store one race meeting from HKJC")
    fm.add_argument("--date", required=True, help="YYYY-MM-DD")
    fm.add_argument("--course", required=True, choices=["ST", "HV", "CH"])
    fm.add_argument("--no-sectionals", action="store_true")

    fr = sub.add_parser("fetch-range", help="fetch a date range (empty days skipped)")
    fr.add_argument("--start", required=True, help="YYYY-MM-DD")
    fr.add_argument("--end", required=True, help="YYYY-MM-DD")
    fr.add_argument("--courses", default=None, help="comma list, e.g. ST,HV")
    fr.add_argument("--no-sectionals", action="store_true")

    ic = sub.add_parser("import-csv", help="bulk import Kaggle gdaley/hkracing CSVs")
    ic.add_argument("--races", required=True)
    ic.add_argument("--runs", required=True)

    bd = sub.add_parser("build-dataset", help="build the no-lookahead backtest dataset")
    bd.add_argument("--out", default=None)

    tr = sub.add_parser("train", help="Phase 2: fit win models and compare to the market (OOS)")
    tr.add_argument("--test-frac", type=float, default=0.3, dest="test_frac")
    tr.add_argument("--l2", type=float, default=5.0)
    tr.add_argument("--out", default=None, help="write metrics JSON")

    va = sub.add_parser("validate", help="Phase 3: walk-forward, CLV, profit sim, GO/NO-GO")
    va.add_argument("--min-train", type=int, default=200, dest="min_train")
    va.add_argument("--step", type=int, default=25)
    va.add_argument("--l2", type=float, default=5.0)
    va.add_argument("--ev-threshold", type=float, default=0.0, dest="ev_threshold")
    va.add_argument("--kelly-fraction", type=float, default=0.25, dest="kelly_fraction")
    va.add_argument("--no-plots", action="store_true")

    rc = sub.add_parser("recommend", help="Phase 4: model vs market + EV for a race (NO-BET default)")
    rc.add_argument("--race-id", type=int, default=None, dest="race_id")
    rc.add_argument("--date", default=None, help="YYYY-MM-DD (with --course --race)")
    rc.add_argument("--course", default=None, choices=["ST", "HV", "CH"])
    rc.add_argument("--race", type=int, default=None)
    rc.add_argument("--no-log", action="store_true")

    sub.add_parser("track", help="Phase 4: reconcile logged recommendations -> CLV & P&L")

    sub.add_parser("status", help="show DB row counts and recent runs")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    dispatch = {
        "init-db": cmd_init_db, "fetch-meeting": cmd_fetch_meeting,
        "fetch-range": cmd_fetch_range, "import-csv": cmd_import_csv,
        "build-dataset": cmd_build_dataset, "train": cmd_train,
        "validate": cmd_validate, "recommend": cmd_recommend, "track": cmd_track,
        "status": cmd_status,
    }
    return dispatch[args.command](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
