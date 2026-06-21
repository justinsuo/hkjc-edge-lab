-- HKJC Edge Tool — SQLite schema (v1)
-- =====================================================================================
-- DESIGN PRINCIPLE: NO LOOKAHEAD.
-- Tables are split into two information classes:
--   * BET-TIME tables  — information knowable BEFORE the race is run. Safe as model
--     features for that race.  -> race, runner, odds_snapshot
--   * OUTCOME tables   — information known only AFTER the race. NEVER a feature for the
--     same race; only labels, or features for *strictly later* races.
--                          -> result, dividend, sectional
-- The dataset builder (pipeline/dataset.py) enforces this split. See README §No-lookahead.
--
-- PROVENANCE: every ingested fact references the source_fetch that produced it, so we can
-- always answer "where did this row come from, when, and from what URL/file".
-- =====================================================================================

PRAGMA foreign_keys = ON;

-- ---- Provenance & ingest bookkeeping -------------------------------------------------

-- One row per HTTP fetch or file import. Immutable audit trail.
CREATE TABLE IF NOT EXISTS source_fetch (
    fetch_id      INTEGER PRIMARY KEY,
    source_name   TEXT NOT NULL,            -- e.g. 'hkjc_racing.results', 'csv_import.kaggle'
    url           TEXT,                     -- request URL (NULL for local file imports)
    file_path     TEXT,                     -- local file path for imports
    http_status   INTEGER,                  -- HTTP status, or NULL for imports
    fetched_at    TEXT NOT NULL,            -- ISO-8601 UTC timestamp of fetch
    content_sha256 TEXT,                    -- hash of fetched bytes (dedup / integrity)
    from_cache    INTEGER NOT NULL DEFAULT 0,
    notes         TEXT
);

-- One row per ingest run (a CLI invocation that wrote data). High-level audit.
CREATE TABLE IF NOT EXISTS ingest_run (
    run_id        INTEGER PRIMARY KEY,
    command       TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT,                     -- 'ok' | 'error' | 'partial'
    rows_written  INTEGER DEFAULT 0,
    requests_made INTEGER DEFAULT 0,
    notes         TEXT
);

-- ---- Reference entities --------------------------------------------------------------

CREATE TABLE IF NOT EXISTS horse (
    horse_id      INTEGER PRIMARY KEY,
    brand_code    TEXT UNIQUE,              -- HKJC code, e.g. 'L441' (stable across renames)
    name          TEXT,
    sire          TEXT,
    dam           TEXT,
    country       TEXT,
    sex           TEXT,
    first_seen    TEXT,
    source_fetch_id INTEGER REFERENCES source_fetch(fetch_id)
);
CREATE INDEX IF NOT EXISTS idx_horse_name ON horse(name);

CREATE TABLE IF NOT EXISTS jockey (
    jockey_id     INTEGER PRIMARY KEY,
    name          TEXT UNIQUE NOT NULL,
    source_fetch_id INTEGER REFERENCES source_fetch(fetch_id)
);

CREATE TABLE IF NOT EXISTS trainer (
    trainer_id    INTEGER PRIMARY KEY,
    name          TEXT UNIQUE NOT NULL,
    source_fetch_id INTEGER REFERENCES source_fetch(fetch_id)
);

-- ---- BET-TIME: race conditions & entries --------------------------------------------

-- A race (one row per race per meeting). All columns here are knowable before the off.
CREATE TABLE IF NOT EXISTS race (
    race_id       INTEGER PRIMARY KEY,
    race_date     TEXT NOT NULL,            -- 'YYYY-MM-DD' (HKT)
    racecourse    TEXT NOT NULL,            -- 'ST' | 'HV' | 'CH'
    race_no       INTEGER NOT NULL,
    race_index    INTEGER,                  -- HKJC race index e.g. 774, if available
    class         TEXT,                     -- e.g. 'Class 4', 'Group 1'
    distance_m    INTEGER,                  -- metres
    going         TEXT,                     -- track condition, e.g. 'GOOD', 'GOOD TO FIRM'
    track         TEXT,                     -- 'Turf' | 'AWT'
    course        TEXT,                     -- e.g. '"A" Course'
    surface       TEXT,
    prize_money   INTEGER,                  -- HK$
    race_name     TEXT,
    race_time     TEXT,                     -- scheduled off time if known
    rating_band   TEXT,
    -- bet-time discipline: this race's static conditions are a feature; outcomes are NOT here.
    source_fetch_id INTEGER REFERENCES source_fetch(fetch_id),
    ingested_at   TEXT,
    UNIQUE(race_date, racecourse, race_no)
);
CREATE INDEX IF NOT EXISTS idx_race_date ON race(race_date);

-- A runner = a horse entered in a race. Pre-race / declared info only (bet-time features).
CREATE TABLE IF NOT EXISTS runner (
    runner_id     INTEGER PRIMARY KEY,
    race_id       INTEGER NOT NULL REFERENCES race(race_id) ON DELETE CASCADE,
    horse_id      INTEGER REFERENCES horse(horse_id),
    horse_no      INTEGER,                  -- saddle/program number
    draw          INTEGER,                  -- barrier
    actual_weight INTEGER,                  -- handicap weight carried (lb)
    declared_weight INTEGER,                -- declared body weight (lb)
    jockey_id     INTEGER REFERENCES jockey(jockey_id),
    trainer_id    INTEGER REFERENCES trainer(trainer_id),
    rating        INTEGER,                  -- official rating at entry
    gear          TEXT,                     -- gear/equipment codes
    horse_name_raw TEXT,                    -- as scraped, for audit
    scratched     INTEGER NOT NULL DEFAULT 0,
    source_fetch_id INTEGER REFERENCES source_fetch(fetch_id),
    ingested_at   TEXT,
    UNIQUE(race_id, horse_no)
);
CREATE INDEX IF NOT EXISTS idx_runner_race ON runner(race_id);
CREATE INDEX IF NOT EXISTS idx_runner_horse ON runner(horse_id);

-- Time-stamped odds snapshots (for ODDS MOVEMENT / closing line). captured_at makes the
-- bet-time discipline explicit: a snapshot is a valid feature only at/after captured_at.
-- 'is_final' marks the closing/SP odds (also recoverable from result.win_odds historically).
CREATE TABLE IF NOT EXISTS odds_snapshot (
    snapshot_id   INTEGER PRIMARY KEY,
    race_id       INTEGER NOT NULL REFERENCES race(race_id) ON DELETE CASCADE,
    horse_no      INTEGER NOT NULL,
    pool          TEXT NOT NULL,            -- 'WIN' | 'PLACE' | 'QIN' | ...
    odds          REAL,                     -- decimal odds (dividend per unit incl. stake)
    captured_at   TEXT NOT NULL,            -- ISO-8601 UTC; the information-as-of time
    is_final      INTEGER NOT NULL DEFAULT 0,
    source_fetch_id INTEGER REFERENCES source_fetch(fetch_id)
);
CREATE INDEX IF NOT EXISTS idx_odds_race ON odds_snapshot(race_id, pool, captured_at);

-- ---- OUTCOME tables (known only after the race) -------------------------------------

-- Finishing result for each runner. OUTCOME — never a feature for the same race.
CREATE TABLE IF NOT EXISTS result (
    result_id     INTEGER PRIMARY KEY,
    race_id       INTEGER NOT NULL REFERENCES race(race_id) ON DELETE CASCADE,
    runner_id     INTEGER REFERENCES runner(runner_id),
    horse_no      INTEGER,
    finish_pos    INTEGER,                  -- 1 = winner; NULL if DNF/DQ/WV
    finish_pos_raw TEXT,                    -- e.g. '1', 'DH', 'WV', 'PU'
    dead_heat     INTEGER NOT NULL DEFAULT 0,
    disqualified  INTEGER NOT NULL DEFAULT 0,
    lengths_behind REAL,                    -- LBW parsed to lengths
    running_position TEXT,                  -- e.g. '1 1 1'
    finish_time_s REAL,                     -- seconds
    win_odds      REAL,                     -- starting/closing WIN odds (decimal). OUTCOME-time SP.
    source_fetch_id INTEGER REFERENCES source_fetch(fetch_id),
    ingested_at   TEXT,
    UNIQUE(race_id, horse_no)
);
CREATE INDEX IF NOT EXISTS idx_result_race ON result(race_id);

-- Dividends per pool per race. OUTCOME.
CREATE TABLE IF NOT EXISTS dividend (
    dividend_id   INTEGER PRIMARY KEY,
    race_id       INTEGER NOT NULL REFERENCES race(race_id) ON DELETE CASCADE,
    pool          TEXT NOT NULL,            -- 'WIN','PLACE','QUINELLA','QUINELLA PLACE','FORECAST',...
    combination   TEXT,                     -- winning combination string
    dividend_hkd  REAL,                     -- payout per HK$10 (HKJC convention)
    pool_total    REAL,                     -- pool size if available
    source_fetch_id INTEGER REFERENCES source_fetch(fetch_id),
    ingested_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_dividend_race ON dividend(race_id, pool);

-- Sectional times per runner per section. OUTCOME.
CREATE TABLE IF NOT EXISTS sectional (
    sectional_id  INTEGER PRIMARY KEY,
    race_id       INTEGER NOT NULL REFERENCES race(race_id) ON DELETE CASCADE,
    horse_no      INTEGER NOT NULL,
    section_index INTEGER NOT NULL,         -- 1..N
    section_time_s REAL,
    position      INTEGER,                  -- running position at end of section
    margin        REAL,                     -- lengths behind leader at section
    source_fetch_id INTEGER REFERENCES source_fetch(fetch_id),
    ingested_at   TEXT,
    UNIQUE(race_id, horse_no, section_index)
);

-- ---- Phase 4 runtime: recommendation log (the tool grades ITSELF) --------------------
-- Every recommendation is logged with the odds at recommendation time; `track` later fills
-- the closing odds + result so the tool measures its own closing-line value and realized P&L.
CREATE TABLE IF NOT EXISTS recommendation (
    rec_id        INTEGER PRIMARY KEY,
    created_at    TEXT NOT NULL,
    race_id       INTEGER REFERENCES race(race_id),
    race_date     TEXT, racecourse TEXT, race_no INTEGER,
    horse_no      INTEGER, pool TEXT,
    model_prob    REAL, market_prob REAL,
    odds_at_rec   REAL,                      -- decimal odds when recommended
    ev            REAL,
    decision      TEXT,                      -- 'BET' | 'NO BET'
    stake         REAL,
    edge_gate_enabled INTEGER,
    -- filled later by `track`:
    closing_odds  REAL,
    finish_pos    INTEGER,
    won           INTEGER,
    pnl           REAL,
    clv           REAL,                      -- closing-line value: odds_at_rec vs closing
    settled_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_rec_race ON recommendation(race_id);

-- ---- Schema metadata -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', '2');

-- Convenience view: a fully bet-time-safe entry view (race conditions + declared runner
-- info), with NO outcome columns. Use this as the basis for features.
CREATE VIEW IF NOT EXISTS v_bettime_entry AS
SELECT
    r.race_id, r.race_date, r.racecourse, r.race_no, r.class, r.distance_m,
    r.going, r.track, r.course,
    ru.runner_id, ru.horse_no, ru.horse_id, ru.draw, ru.actual_weight,
    ru.declared_weight, ru.jockey_id, ru.trainer_id, ru.rating, ru.gear, ru.scratched
FROM race r
JOIN runner ru ON ru.race_id = r.race_id;
