"""Schema creation, provenance linkage, and ingest-writes-with-provenance."""
from hkjc_edge.pipeline.ingest import write_results
from hkjc_edge.sources.hkjc_racing import HkjcRacingSource as S


def test_schema_tables_exist(tmp_db):
    tables = {r[0] for r in tmp_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    for t in ["race", "runner", "result", "dividend", "sectional", "horse", "jockey",
              "trainer", "odds_snapshot", "source_fetch", "ingest_run"]:
        assert t in tables
    assert tmp_db.execute(
        "SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0] == "2"
    assert "recommendation" in tables


def test_get_or_create_is_idempotent(tmp_db):
    a = tmp_db.get_or_create_jockey("B Avdulla")
    b = tmp_db.get_or_create_jockey("B Avdulla")
    assert a == b
    assert tmp_db.count("jockey") == 1
    h1 = tmp_db.get_or_create_horse(brand_code="L441", name="JEDI SPURS")
    h2 = tmp_db.get_or_create_horse(brand_code="L441", name="JEDI SPURS (renamed)")
    assert h1 == h2  # identity is the brand_code, stable across renames


def test_ingest_writes_with_provenance(tmp_db, fixtures_dir):
    html = (fixtures_dir / "results_sample.html").read_text()
    parsed = S.parse_results(html, "2026-06-13", "ST", 1)
    fetch_id = tmp_db.record_fetch("hkjc_racing.results", url="http://x", http_status=200,
                                   content=html.encode())
    write_results(tmp_db, parsed, fetch_id)

    assert tmp_db.count("race") == 1
    assert tmp_db.count("runner") == 3
    assert tmp_db.count("result") == 3
    assert tmp_db.count("dividend") == 4

    # EVERY data row must reference a valid source_fetch (provenance guarantee).
    for table in ["race", "runner", "result", "dividend"]:
        orphans = tmp_db.execute(
            f"SELECT COUNT(*) FROM {table} t "
            f"LEFT JOIN source_fetch f ON t.source_fetch_id = f.fetch_id "
            f"WHERE f.fetch_id IS NULL").fetchone()[0]
        assert orphans == 0, f"{table} has rows without provenance"

    # the fetch row recorded a content hash
    row = tmp_db.execute("SELECT content_sha256 FROM source_fetch").fetchone()
    assert row[0] and len(row[0]) == 64


def test_upsert_idempotent(tmp_db, fixtures_dir):
    html = (fixtures_dir / "results_sample.html").read_text()
    parsed = S.parse_results(html, "2026-06-13", "ST", 1)
    fid = tmp_db.record_fetch("hkjc_racing.results", url="http://x", http_status=200)
    write_results(tmp_db, parsed, fid)
    write_results(tmp_db, parsed, fid)  # re-ingest same data
    assert tmp_db.count("race") == 1
    assert tmp_db.count("runner") == 3   # not doubled
    assert tmp_db.count("result") == 3
