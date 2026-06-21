"""Live odds collector via HKJC's internal GraphQL endpoint (going-forward odds movement).

HONEST STATUS (verified June 2026):
  The endpoint https://info.cld.hkjc.com/graphql/base/ exists but only serves WHITELISTED
  queries — an arbitrary query returns {"errors":[{"message":"... WHITELIST_ERROR"}]}. So a
  valid persisted query / operation must be supplied (community wrappers such as
  Bobosky2005/hkjc-api carry working operations that may change without notice).

  Therefore this collector is DISABLED BY DEFAULT (config sources.hkjc_odds.enabled=false).
  It is NOT needed for the historical backtest: the closing WIN odds (SP) come for free in
  the results table (result.win_odds). This collector exists to capture *odds movement* for
  UPCOMING races going forward (for live closing-line-value tracking in Phase 4).

  When enabled, supply `query` (a whitelisted GraphQL doc) via the collector and it will
  parse a best-effort response into time-stamped odds_snapshot rows. If the server returns
  a whitelist error, it logs and returns an empty list rather than crashing.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ..logging_setup import get_logger
from .http_client import PoliteClient
from .models import RaceMeta  # noqa: F401  (kept for type parity / future use)

log = get_logger("hkjc_odds")


class OddsSnapshotRow:
    __slots__ = ("race_no", "horse_no", "pool", "odds", "captured_at", "is_final")

    def __init__(self, race_no, horse_no, pool, odds, captured_at, is_final=False):
        self.race_no = race_no
        self.horse_no = horse_no
        self.pool = pool
        self.odds = odds
        self.captured_at = captured_at
        self.is_final = is_final


class HkjcOddsCollector:
    name = "hkjc_odds"

    def __init__(self, client: PoliteClient, cfg):
        self.client = client
        self.url = cfg.get("sources.hkjc_odds.graphql_url",
                           "https://info.cld.hkjc.com/graphql/base/")
        self.enabled = bool(cfg.get("sources.hkjc_odds.enabled", False))
        self.operation_name = cfg.get("sources.hkjc_odds.operation_name", "racing")

    def capture(self, *, date_iso: str, course: str, query: str | None = None,
                variables: dict | None = None) -> tuple[list[OddsSnapshotRow], dict]:
        """Capture a live odds snapshot. Returns (rows, raw_response). Empty if disabled
        or whitelist-blocked. `query` must be a whitelisted GraphQL document."""
        if not self.enabled:
            log.info("odds collector disabled (config). Skipping live capture.")
            return [], {}
        if not query:
            log.warning("no whitelisted GraphQL query supplied; cannot capture live odds. "
                        "See module docstring. Returning empty.")
            return [], {}
        payload = {"operationName": self.operation_name, "query": query,
                   "variables": variables or {}}
        resp = self.client.post_json(self.url, payload,
                                     headers={"Referer": "https://bet.hkjc.com/"})
        try:
            data = json.loads(resp.content)
        except json.JSONDecodeError:
            log.warning("odds response not JSON (status %s)", resp.status)
            return [], {}
        if data.get("errors"):
            log.warning("GraphQL error (likely whitelist): %s", data["errors"])
            return [], data
        captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = self._parse(data, captured_at)
        return rows, data

    @staticmethod
    def _parse(data: dict, captured_at: str) -> list[OddsSnapshotRow]:
        """Best-effort parse of the expected raceMeetings->races->...->odds shape.

        The exact schema is undocumented; this walks defensively and yields what it finds.
        """
        rows: list[OddsSnapshotRow] = []
        root = data.get("data") or {}
        meetings = root.get("raceMeetings") or root.get("raceMeeting") or []
        if isinstance(meetings, dict):
            meetings = [meetings]
        for mt in meetings:
            races = (mt or {}).get("races") or []
            for rc in races:
                race_no = rc.get("no") or rc.get("raceNo")
                # win/place odds nodes vary by schema; check common shapes
                for pool_key, pool in (("winOdds", "WIN"), ("placeOdds", "PLACE")):
                    nodes = rc.get(pool_key) or []
                    for nd in nodes:
                        rows.append(OddsSnapshotRow(
                            race_no=race_no,
                            horse_no=nd.get("number") or nd.get("horseNo"),
                            pool=pool,
                            odds=_to_float(nd.get("odds") or nd.get("oddsValue")),
                            captured_at=captured_at,
                        ))
        return rows


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
