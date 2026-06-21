"""SQLite database access layer with provenance helpers.

Every write goes through a Database instance which:
  * applies the schema on first use,
  * records source_fetch rows (provenance) and links data rows to them,
  * provides get-or-create for reference entities (horse/jockey/trainer),
  * tracks ingest_run bookkeeping.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._apply_schema()

    # -- lifecycle ---------------------------------------------------------------------
    def _apply_schema(self) -> None:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
            self.conn.executescript(fh.read())
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- provenance --------------------------------------------------------------------
    def record_fetch(
        self,
        source_name: str,
        *,
        url: Optional[str] = None,
        file_path: Optional[str] = None,
        http_status: Optional[int] = None,
        content: Optional[bytes] = None,
        from_cache: bool = False,
        notes: Optional[str] = None,
    ) -> int:
        """Insert a source_fetch row and return its id. Call once per fetch/import."""
        cur = self.conn.execute(
            """INSERT INTO source_fetch
               (source_name, url, file_path, http_status, fetched_at, content_sha256,
                from_cache, notes)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                source_name, url, file_path, http_status, utc_now_iso(),
                sha256_bytes(content) if content is not None else None,
                1 if from_cache else 0, notes,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def start_run(self, command: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO ingest_run (command, started_at, status) VALUES (?,?,?)",
            (command, utc_now_iso(), "running"),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, *, rows_written: int = 0,
                   requests_made: int = 0, notes: str | None = None) -> None:
        self.conn.execute(
            """UPDATE ingest_run SET finished_at=?, status=?, rows_written=?,
               requests_made=?, notes=? WHERE run_id=?""",
            (utc_now_iso(), status, rows_written, requests_made, notes, run_id),
        )
        self.conn.commit()

    # -- reference entities (get-or-create) --------------------------------------------
    def get_or_create_jockey(self, name: str, fetch_id: int | None = None) -> int:
        return self._get_or_create("jockey", "jockey_id", "name", name, fetch_id)

    def get_or_create_trainer(self, name: str, fetch_id: int | None = None) -> int:
        return self._get_or_create("trainer", "trainer_id", "name", name, fetch_id)

    def _get_or_create(self, table: str, idcol: str, namecol: str, name: str,
                       fetch_id: int | None) -> int:
        name = (name or "").strip()
        row = self.conn.execute(
            f"SELECT {idcol} FROM {table} WHERE {namecol}=?", (name,)
        ).fetchone()
        if row:
            return int(row[0])
        cur = self.conn.execute(
            f"INSERT INTO {table} ({namecol}, source_fetch_id) VALUES (?,?)",
            (name, fetch_id),
        )
        return int(cur.lastrowid)

    def get_or_create_horse(self, *, brand_code: str | None, name: str | None,
                            sire: str | None = None, dam: str | None = None,
                            fetch_id: int | None = None) -> int:
        """Identify a horse by brand_code if present (stable), else by name."""
        if brand_code:
            row = self.conn.execute(
                "SELECT horse_id FROM horse WHERE brand_code=?", (brand_code,)
            ).fetchone()
            if row:
                return int(row[0])
        elif name:
            row = self.conn.execute(
                "SELECT horse_id FROM horse WHERE brand_code IS NULL AND name=?", (name,)
            ).fetchone()
            if row:
                return int(row[0])
        cur = self.conn.execute(
            """INSERT INTO horse (brand_code, name, sire, dam, first_seen, source_fetch_id)
               VALUES (?,?,?,?,?,?)""",
            (brand_code, name, sire, dam, utc_now_iso(), fetch_id),
        )
        return int(cur.lastrowid)

    # -- generic upsert helpers --------------------------------------------------------
    def upsert(self, table: str, row: dict[str, Any], conflict_cols: Iterable[str]) -> int:
        """INSERT ... ON CONFLICT(conflict_cols) DO UPDATE. Returns the affected row's id.

        Uses RETURNING rowid because cur.lastrowid is UNRELIABLE for ON CONFLICT DO UPDATE
        (it can report a phantom autoincrement value, not the existing row), which would
        break foreign keys on re-ingest.
        """
        conflict_cols = list(conflict_cols)
        cols = list(row.keys())
        placeholders = ",".join("?" for _ in cols)
        col_sql = ",".join(cols)
        conflict_sql = ",".join(conflict_cols)
        updates = ",".join(f"{c}=excluded.{c}" for c in cols if c not in conflict_cols)
        action = f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
        sql = (
            f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders}) "
            f"ON CONFLICT({conflict_sql}) {action} RETURNING rowid"
        )
        cur = self.conn.execute(sql, [row[c] for c in cols])
        fetched = cur.fetchone()
        if fetched is not None:
            return int(fetched[0])
        # DO NOTHING on conflict returns no row -> look up the existing row's id.
        where = " AND ".join(f"{c}=?" for c in conflict_cols)
        got = self.conn.execute(
            f"SELECT rowid FROM {table} WHERE {where}", [row[c] for c in conflict_cols]
        ).fetchone()
        return int(got[0]) if got else -1

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, tuple(params))

    def commit(self) -> None:
        self.conn.commit()

    def count(self, table: str) -> int:
        return int(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
