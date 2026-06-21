"""Web layer: ServiceLayer + Flask endpoints over a small seeded DB."""
import numpy as np
import pytest

from hkjc_edge.config import load_config
from hkjc_edge.web.server import create_app
from hkjc_edge.web.service import ServiceLayer


def _seed(db, n_races=8, field=8, seed=1):
    rng = np.random.default_rng(seed)
    fid = db.record_fetch("test", url="x")
    last = None
    for r in range(n_races):
        q = rng.dirichlet(np.ones(field))
        O = 0.825 / q
        winner = int(rng.choice(field, p=q))
        rid = db.upsert("race", {
            "race_date": f"2025-02-{r+1:02d}", "racecourse": "ST", "race_no": 1,
            "distance_m": 1200, "going": "GOOD", "track": "Turf", "class": "Class 4",
            "source_fetch_id": fid, "ingested_at": "t"}, ["race_date", "racecourse", "race_no"])
        last = rid
        for hh in range(field):
            hid = db.get_or_create_horse(brand_code=f"H{hh}", name=f"H{hh}", fetch_id=fid)
            db.upsert("runner", {"race_id": rid, "horse_id": hid, "horse_no": hh + 1,
                                 "draw": hh + 1, "actual_weight": 120,
                                 "jockey_id": db.get_or_create_jockey(f"J{hh}", fid),
                                 "trainer_id": db.get_or_create_trainer(f"T{hh}", fid),
                                 "source_fetch_id": fid, "ingested_at": "t"},
                      ["race_id", "horse_no"])
            db.upsert("result", {"race_id": rid, "horse_no": hh + 1,
                                 "finish_pos": 1 if hh == winner else hh + 2,
                                 "finish_time_s": 69.0 + hh * 0.1, "win_odds": float(O[hh]),
                                 "source_fetch_id": fid, "ingested_at": "t"},
                      ["race_id", "horse_no"])
    db.commit()
    return last


@pytest.fixture
def client(tmp_path, monkeypatch):
    from hkjc_edge.db import Database
    dbp = tmp_path / "web.sqlite"
    db = Database(dbp)
    last = _seed(db)
    db.close()
    cfg = load_config()
    cfg.raw.setdefault("database", {})["path"] = str(dbp)
    svc = ServiceLayer(cfg)
    app = create_app(svc)
    app.config["TESTING"] = True
    c = app.test_client()
    c._last_race = last
    return c


def _data(resp):
    j = resp.get_json()
    assert j["ok"], j.get("error")
    return j["data"]


def test_status_and_meetings(client):
    d = _data(client.get("/api/status"))
    assert d["counts"]["race"] == 8
    assert d["default_action"] == "NO BET"
    m = _data(client.get("/api/meetings"))
    assert m["total"] == 8


def test_races_and_recommend_fallback(client):
    d = _data(client.get("/api/races?date=2025-02-08&course=ST"))
    assert d["races"]
    rid = client._last_race
    rec = _data(client.get(f"/api/races/{rid}/recommend"))
    # too few prior races (<200) -> market fallback, but still a valid NO-BET payload
    assert rec["default_action"] == "NO BET"
    assert all(r["decision"] == "NO BET" for r in rec["runners"])
    assert rec["edge_gate_enabled"] is False


def test_quality_config_feasibility(client):
    q = _data(client.get("/api/dataset/quality"))
    assert q["rows"] == 64 and q["no_lookahead"]["verified_by_tests"] is True
    cfg = _data(client.get("/api/config"))
    assert cfg["edge_gate_enabled"] is False
    fr = _data(client.get("/api/feasibility"))
    assert fr["format"] == "markdown"


def test_edge_gate_toggle_is_session_only(client):
    d = _data(client.post("/api/edge_gate", json={"enabled": True}))
    assert d["edge_gate_enabled"] is True
    assert _data(client.get("/api/config"))["edge_gate_enabled"] is True
    client.post("/api/edge_gate", json={"enabled": False})
    assert _data(client.get("/api/config"))["edge_gate_enabled"] is False


def test_static_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and b"HKJC Edge Lab" in r.data


def test_bad_params_return_400(client):
    assert client.get("/api/races").status_code == 400          # missing date/course
    assert client.get("/api/whatif?prob_col=bogus").status_code == 400


def test_recommend_handles_missing_odds_without_nan(client, tmp_path):
    # A race with one odds-less runner must not NaN-poison the whole race.
    from hkjc_edge.db import Database
    db = Database(tmp_path / "web.sqlite")
    fid = db.record_fetch("t", url="x")
    rid = db.upsert("race", {"race_date": "2025-03-01", "racecourse": "ST", "race_no": 1,
                             "distance_m": 1200, "going": "GOOD", "track": "Turf",
                             "class": "Class 4", "source_fetch_id": fid, "ingested_at": "t"},
                    ["race_date", "racecourse", "race_no"])
    for hn in range(1, 5):
        db.upsert("runner", {"race_id": rid, "horse_no": hn, "draw": hn, "actual_weight": 120,
                             "source_fetch_id": fid, "ingested_at": "t"}, ["race_id", "horse_no"])
        db.upsert("result", {"race_id": rid, "horse_no": hn, "finish_pos": hn,
                             "win_odds": None if hn == 2 else 3.0 + hn,  # horse 2 has no odds
                             "source_fetch_id": fid, "ingested_at": "t"}, ["race_id", "horse_no"])
    db.commit(); db.close()
    rec = _data(client.get(f"/api/races/{rid}/recommend"))
    by = {r["horse_no"]: r for r in rec["runners"]}
    assert by[2]["market_prob"] is None and by[2]["ev"] is None     # odds-less -> None, no NaN
    assert by[1]["market_prob"] is not None
    assert all(r["decision"] == "NO BET" for r in rec["runners"])
