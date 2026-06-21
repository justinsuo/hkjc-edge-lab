"""Flask app for HKJC Edge Lab. Thin routes over ServiceLayer; standard JSON envelope."""
from __future__ import annotations

import time
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import BadRequest

from .jobs import JobManager
from .service import ServiceLayer

STATIC = Path(__file__).resolve().parent / "static"


def envelope(fn):
    def wrapper(*a, **k):
        t0 = time.time()
        try:
            data = fn(*a, **k)
            return jsonify({"ok": True, "data": data, "error": None,
                            "meta": {"compute_ms": int((time.time() - t0) * 1000)}})
        except (BadRequest, ValueError) as e:        # bad/missing params (BadRequestKeyError too)
            return jsonify({"ok": False, "data": None,
                            "error": {"code": "BAD_REQUEST", "message": str(e)}}), 400
        except KeyError as e:                          # genuine not-found (race id, job id)
            return jsonify({"ok": False, "data": None,
                            "error": {"code": "NOT_FOUND", "message": str(e)}}), 404
        except Exception as e:  # noqa: BLE001
            return jsonify({"ok": False, "data": None,
                            "error": {"code": "ERROR", "message": str(e)}}), 500
    wrapper.__name__ = fn.__name__
    return wrapper


def create_app(svc: ServiceLayer | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    svc = svc or ServiceLayer()
    jobs = JobManager()
    app.config["svc"] = svc

    # ---- static frontend ----
    @app.route("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.route("/static/<path:fname>")
    def static_files(fname):
        return send_from_directory(STATIC, fname)

    # ---- API ----
    @app.route("/api/status")
    @envelope
    def status():
        return svc.status()

    @app.route("/api/headline")
    @envelope
    def headline():
        return svc.headline()

    @app.route("/api/config")
    @envelope
    def config():
        return svc.config()

    @app.route("/api/edge_gate", methods=["POST"])
    @envelope
    def edge_gate():
        body = request.get_json(silent=True) or {}
        return svc.set_edge_gate(bool(body.get("enabled", False)))

    @app.route("/api/meetings")
    @envelope
    def meetings():
        return svc.meetings()

    @app.route("/api/races")
    @envelope
    def races():
        date, course = request.args.get("date"), request.args.get("course")
        if not (date and course):
            raise ValueError("query params 'date' and 'course' are required")
        return svc.races(date, course)

    @app.route("/api/races/<int:race_id>/recommend")
    @envelope
    def recommend(race_id):
        bankroll = request.args.get("bankroll", type=float)
        kelly = request.args.get("kelly_fraction", type=float)
        return svc.recommend(race_id, bankroll=bankroll, kelly_fraction=kelly)

    @app.route("/api/races/<int:race_id>/recommend/log", methods=["POST"])
    @envelope
    def recommend_log(race_id):
        return svc.log_recommendation(race_id)

    @app.route("/api/validation/latest")
    @envelope
    def validation_latest():
        r = svc.validation_latest()
        return r or {"verdict": "NOT RUN", "ran": False}

    @app.route("/api/validation/run", methods=["POST"])
    @envelope
    def validation_run():
        mt = request.args.get("min_train", default=350, type=int)
        step = request.args.get("step", default=25, type=int)
        job_id = jobs.submit("validate",
                             lambda prog: (prog(0.2, "walk-forward"),
                                           svc.run_validation(min_train=mt, step=step, force=True))[-1])
        return {"job_id": job_id, "type": "validate"}

    @app.route("/api/models/eval")
    @envelope
    def model_eval():
        return svc.model_eval()

    @app.route("/api/whatif")
    @envelope
    def whatif():
        return svc.whatif(request.args.get("prob_col", "p_combined"))

    @app.route("/api/dataset/quality")
    @envelope
    def quality():
        return svc.data_quality()

    @app.route("/api/tracking")
    @envelope
    def tracking():
        return svc.tracking()

    @app.route("/api/feasibility")
    @envelope
    def feasibility():
        return svc.report()

    @app.route("/api/jobs")
    @envelope
    def jobs_list():
        return {"jobs": jobs.list()}

    @app.route("/api/jobs/<job_id>")
    @envelope
    def job_get(job_id):
        j = jobs.get(job_id)
        if not j:
            raise KeyError("job not found")
        return j

    @app.route("/api/fetch", methods=["POST"])
    @envelope
    def fetch():
        date = request.args.get("date")
        course = request.args.get("course")
        if not (date and course):
            raise ValueError("date and course required")

        def _do(prog):
            from ..config import load_config
            from ..db import Database
            from ..pipeline.ingest import ingest_meeting
            from ..sources.hkjc_racing import HkjcRacingSource
            from ..sources.http_client import PoliteClient
            cfg = load_config()
            client = PoliteClient(
                user_agent=cfg.get("http.user_agent"), cache_dir=cfg.path("http.cache_dir"),
                base_delay_seconds=cfg.get("http.base_delay_seconds", 4.0),
                jitter_seconds=cfg.get("http.jitter_seconds", 2.0),
                respect_robots=cfg.get("http.respect_robots", True))
            prog(0.3, f"fetching {date} {course}")
            with Database(cfg.db_path) as db:
                summary = ingest_meeting(db, HkjcRacingSource(client, cfg), date, course,
                                         with_sectionals=False)
            return summary
        return {"job_id": jobs.submit("fetch", _do), "type": "fetch"}

    # validation plots
    @app.route("/api/validation/plots/<name>.png")
    def plot(name):
        if name not in {"calibration", "pnl", "equity"}:
            return ("not found", 404)
        p = svc.root / "data" / "validation" / f"{name}.png"
        if not p.exists():
            return ("not generated yet", 404)
        return send_file(p, mimetype="image/png")

    return app


def main(host="127.0.0.1", port=8099):  # pragma: no cover
    create_app().run(host=host, port=port, threaded=True)


if __name__ == "__main__":  # pragma: no cover
    main()
