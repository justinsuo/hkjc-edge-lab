"""HKJC racing data source: results (+dividends), racecards, sectional times.

Fetching (network + provenance) is separated from parsing (pure, fixture-testable).

IMPORTANT REALITY NOTES (verified June 2026, see research_report.md §4):
  * The RESULTS page (racing.hkjc.com/.../localresults) is fully SERVER-RENDERED and is
    the reliable historical backbone. It yields race conditions, finishing positions,
    draw, weights, jockey, trainer, running position, finish time, and the CLOSING WIN
    ODDS (SP) — i.e. the closing line we want to test CLV against — plus all dividends.
  * The RACECARD runner grid is JS-RENDERED; a plain GET returns no runner table. So
    pre-race RATING and GEAR are NOT available via static fetch. parse_racecard() handles
    a server-rendered grid if present and otherwise returns an empty card (logged). This
    is a documented Phase-1 gap to fill later via the racecard XHR/GraphQL or a headless
    renderer.
  * Historical odds *movement* is not published by HKJC; the SP in results is the close.
"""
from __future__ import annotations

import io
import re
from typing import Optional

import pandas as pd
from bs4 import BeautifulSoup

from ..logging_setup import get_logger
from .http_client import FetchResult, PoliteClient
from .models import (
    Dividend, ParsedRaceCard, ParsedRaceResults, RaceMeta, RunnerEntry, RunnerResult,
    Sectional,
)
from .parse_util import (
    hyphen_date, parse_distance, parse_finish_pos, parse_finish_time, parse_horse_name_code,
    parse_lbw, parse_prize, slash_dmy, to_float, to_int,
)

log = get_logger("hkjc_racing")


def _read_tables(html: str) -> list[pd.DataFrame]:
    """Robustly extract tables; HKJC HTML is sometimes malformed, so try lxml then html5lib."""
    # thousands=None prevents pandas from mangling comma-separated combinations like '1,6'
    # (default thousands=',' would turn it into 16) and from corrupting numeric cells.
    for flavor in ("lxml", "html5lib", "bs4"):
        try:
            tabs = pd.read_html(io.StringIO(html), flavor=flavor, thousands=None)
            if tabs:
                return tabs
        except (ValueError, ImportError):
            continue
    return []


def _flat_cols(df: pd.DataFrame) -> list[str]:
    out = []
    for c in df.columns:
        if isinstance(c, tuple):
            out.append(" ".join(str(x) for x in c))
        else:
            out.append(str(c))
    return out


class HkjcRacingSource:
    name = "hkjc_racing"

    def __init__(self, client: PoliteClient, cfg):
        self.client = client
        base = cfg.get("sources.hkjc_racing.base_url", "https://racing.hkjc.com")
        self.base = base.rstrip("/")
        self.results_path = cfg.get("sources.hkjc_racing.results_path")
        self.racecard_path = cfg.get("sources.hkjc_racing.racecard_path")
        self.sectional_path = cfg.get("sources.hkjc_racing.sectional_path")

    # -- URL builders ------------------------------------------------------------------
    def results_url(self, date_iso: str, course: str, race_no: int) -> str:
        return (f"{self.base}{self.results_path}?RaceDate={hyphen_date(date_iso)}"
                f"&Racecourse={course}&RaceNo={race_no}")

    def racecard_url(self, date_iso: str, course: str, race_no: int) -> str:
        return (f"{self.base}{self.racecard_path}?RaceDate={hyphen_date(date_iso)}"
                f"&Racecourse={course}&RaceNo={race_no}")

    def sectional_url(self, date_iso: str, course: str, race_no: int) -> str:
        return (f"{self.base}{self.sectional_path}?RaceDate={slash_dmy(date_iso)}"
                f"&Racecourse={course}&RaceNo={race_no}")

    # -- fetchers (network; caller records provenance with the returned FetchResult) ----
    def fetch_results(self, date_iso: str, course: str, race_no: int) -> FetchResult:
        return self.client.get(self.results_url(date_iso, course, race_no))

    def fetch_racecard(self, date_iso: str, course: str, race_no: int) -> FetchResult:
        return self.client.get(self.racecard_url(date_iso, course, race_no))

    def fetch_sectional(self, date_iso: str, course: str, race_no: int) -> FetchResult:
        return self.client.get(self.sectional_url(date_iso, course, race_no))

    # -- discovery ---------------------------------------------------------------------
    @staticmethod
    def discover_race_count(html: str) -> int:
        """Max RaceNo referenced in the meeting nav (0 if none / no meeting)."""
        nums = [int(n) for n in re.findall(r"RaceNo=(\d+)", html)]
        return max(nums) if nums else 0

    # -- parsers (pure) ----------------------------------------------------------------
    @staticmethod
    def parse_meta(html: str, date_iso: str, course: str, race_no: int) -> RaceMeta:
        soup = BeautifulSoup(html, "lxml")
        lines = [l.strip() for l in soup.get_text("\n").splitlines() if l.strip()]
        meta = RaceMeta(race_date=date_iso, racecourse=course, race_no=race_no)
        for i, line in enumerate(lines):
            m = re.match(r"RACE\s*(\d+)\s*\((\d+)\)", line)
            if m and int(m.group(1)) == race_no:
                meta.race_index = int(m.group(2))
                # next line: "<class/name> - <dist>M [ - (band)]"
                if i + 1 < len(lines):
                    detail = lines[i + 1]
                    meta.distance_m = parse_distance(detail)
                    parts = [p.strip() for p in detail.split(" - ")]
                    if parts:
                        meta.class_ = parts[0]
                        meta.race_name = parts[0]
                    band = re.search(r"\((\d+\s*-\s*\d+)\)", detail)
                    if band:
                        meta.rating_band = band.group(1)
                # scan a few following lines for Going / Course / prize
                for j in range(i + 1, min(i + 10, len(lines))):
                    if lines[j].startswith("Going") and j + 1 < len(lines):
                        meta.going = lines[j + 1].strip(": ").strip() or None
                    if lines[j].startswith("Course") and j + 1 < len(lines):
                        cv = lines[j + 1]
                        meta.course = cv
                        if "TURF" in cv.upper():
                            meta.track = "Turf"
                        elif "AWT" in cv.upper() or "ALL WEATHER" in cv.upper():
                            meta.track = "AWT"
                    if "HK$" in lines[j] and meta.prize_money is None:
                        meta.prize_money = parse_prize(lines[j])
                break
        return meta

    @classmethod
    def parse_results(cls, html: str, date_iso: str, course: str,
                      race_no: int) -> ParsedRaceResults:
        meta = cls.parse_meta(html, date_iso, course, race_no)
        tables = _read_tables(html)
        results: list[RunnerResult] = []
        dividends: list[Dividend] = []

        for df in tables:
            cols = _flat_cols(df)
            low = [c.lower() for c in cols]
            # runner results table: has 'pla.' and 'win odds'
            if any("pla" in c for c in low) and any("win odds" in c for c in low):
                results = cls._parse_result_rows(df, cols)
            # dividends table: has 'pool' and 'dividend'
            elif any(c.strip().endswith("pool") or c.strip() == "pool" for c in low) and \
                    any("dividend" in c for c in low):
                dividends = cls._parse_dividend_rows(df, cols)
        return ParsedRaceResults(meta=meta, results=results, dividends=dividends)

    @staticmethod
    def _col(cols: list[str], *needles: str) -> Optional[int]:
        for idx, c in enumerate(cols):
            cl = c.lower()
            if all(n in cl for n in needles):
                return idx
        return None

    @classmethod
    def _parse_result_rows(cls, df: pd.DataFrame, cols: list[str]) -> list[RunnerResult]:
        i_pla = cls._col(cols, "pla")
        i_no = cls._col(cols, "horse no")
        i_horse = cls._col(cols, "horse") if cls._col(cols, "horse no") is None else None
        # 'Horse' is the column literally named horse (not 'horse no')
        for idx, c in enumerate(cols):
            if c.strip().lower() == "horse":
                i_horse = idx
        i_jky = cls._col(cols, "jockey")
        i_trn = cls._col(cols, "trainer")
        i_awt = cls._col(cols, "act", "wt")
        i_dwt = cls._col(cols, "declar")
        i_dr = cls._col(cols, "dr")
        i_lbw = cls._col(cols, "lbw")
        i_run = cls._col(cols, "running position")
        i_ft = cls._col(cols, "finish time")
        i_wo = cls._col(cols, "win odds")
        out: list[RunnerResult] = []
        for _, row in df.iterrows():
            vals = list(row.values)

            def g(i):
                return vals[i] if i is not None and i < len(vals) else None

            name, code = parse_horse_name_code(g(i_horse))
            if name is None and g(i_no) is None:
                continue
            pos, raw, dh, dq = parse_finish_pos(g(i_pla))
            rr = RunnerResult(
                horse_no=to_int(g(i_no)),
                horse_name=name,
                horse_code=code,
                finish_pos=pos,
                finish_pos_raw=raw,
                dead_heat=dh,
                disqualified=dq,
                lengths_behind=parse_lbw(g(i_lbw)),
                running_position=str(g(i_run)).strip() if g(i_run) is not None else None,
                finish_time_s=parse_finish_time(g(i_ft)),
                win_odds=to_float(g(i_wo)),
                jockey=str(g(i_jky)).strip() if g(i_jky) is not None else None,
                trainer=str(g(i_trn)).strip() if g(i_trn) is not None else None,
                draw=to_int(g(i_dr)),
                actual_weight=to_int(g(i_awt)),
                declared_weight=to_int(g(i_dwt)),
            )
            # skip header-ish / empty rows
            if rr.horse_no is None and rr.horse_name in (None, "Horse", "nan"):
                continue
            out.append(rr)
        return out

    @classmethod
    def _parse_dividend_rows(cls, df: pd.DataFrame, cols: list[str]) -> list[Dividend]:
        i_pool = cls._col(cols, "pool")
        i_comb = cls._col(cols, "combination")
        i_div = cls._col(cols, "dividend") if cls._col(cols, "dividend (hk") is None \
            else cls._col(cols, "dividend (hk")
        # prefer the explicit '(hk$)' dividend col
        for idx, c in enumerate(cols):
            if "dividend" in c.lower() and "hk" in c.lower():
                i_div = idx
        out: list[Dividend] = []
        last_pool = None
        for _, row in df.iterrows():
            vals = list(row.values)

            def g(i):
                return vals[i] if i is not None and i < len(vals) else None

            pool = g(i_pool)
            pool = str(pool).strip() if pool is not None and str(pool).strip().lower() != "nan" else None
            if pool:
                last_pool = pool
            pool = pool or last_pool
            if not pool or pool.lower() == "pool":
                continue
            div = to_float(g(i_div))
            comb = g(i_comb)
            comb = str(comb).strip() if comb is not None and str(comb).strip().lower() != "nan" else None
            if div is None and comb is None:
                continue
            out.append(Dividend(pool=pool.upper(), combination=comb, dividend_hkd=div))
        return out

    @staticmethod
    def _deaggregate_splits(times: list[float]) -> list[float]:
        """Drop HKJC's 400m aggregate tokens: any token ~= sum of the next two splits.

        HKJC packs both 400m aggregates and the underlying 200m splits into the cells.
        e.g. [13.37, 20.84, 10.37, 10.47, 21.60, 10.44, 11.16] -> 20.84 == 10.37+10.47 and
        21.60 == 10.44+11.16, leaving [13.37,10.37,10.47,10.44,11.16] (sums to the finish).
        """
        out: list[float] = []
        i = 0
        n = len(times)
        while i < n:
            if i + 2 < n and abs(times[i] - (times[i + 1] + times[i + 2])) <= 0.05:
                i += 1  # skip the aggregate
                continue
            out.append(times[i])
            i += 1
        return out

    @classmethod
    def parse_sectional(cls, html: str, date_iso: str, course: str,
                        race_no: int) -> list[Sectional]:
        """Parse per-section split times from the DOM (cells merge position/margin/time)."""
        soup = BeautifulSoup(html, "lxml")
        target = None
        for t in soup.find_all("table"):
            txt = t.get_text()
            if "Sectional Time" in txt and ("Finishing Order" in txt or "Horse No." in txt) \
                    and len(t.find_all("tr")) >= 4:
                target = t
                break
        if target is None:
            return []
        out: list[Sectional] = []
        time_re = re.compile(r"\b\d{1,2}\.\d{2}\b")
        for tr in target.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 5:
                continue
            for br in tr.find_all("br"):
                br.replace_with(" ")
            texts = [c.get_text(" ", strip=True) for c in cells]
            hn = to_int(texts[1])
            order = to_int(texts[0])
            # data rows start with a numeric finishing order and a numeric horse no
            if hn is None or order is None:
                continue
            section_cells = texts[3:-1]      # between horse name and total time
            lead_pos = None
            times: list[float] = []
            for sc in section_cells:
                if not sc.strip():
                    continue
                if lead_pos is None:
                    lp = re.match(r"^\s*(\d+)\b", sc)
                    lead_pos = int(lp.group(1)) if lp else None
                times.extend(float(x) for x in time_re.findall(sc))
            splits = cls._deaggregate_splits(times)
            for sec_n, t in enumerate(splits, start=1):
                out.append(Sectional(horse_no=hn, section_index=sec_n,
                                     section_time_s=t,
                                     position=lead_pos if sec_n == 1 else None))
        return out

    @classmethod
    def parse_racecard(cls, html: str, date_iso: str, course: str,
                       race_no: int) -> ParsedRaceCard:
        """Parse pre-race entries IF the grid is server-rendered. Returns empty if JS-only."""
        meta = cls.parse_meta(html, date_iso, course, race_no)
        tables = _read_tables(html)
        entries: list[RunnerEntry] = []
        for df in tables:
            cols = _flat_cols(df)
            low = [c.lower() for c in cols]
            if any("horse" in c for c in low) and any("jockey" in c for c in low) \
                    and any("draw" in c or c.strip().lower() == "dr." for c in low):
                i_no = cls._col(cols, "horse no")
                i_draw = cls._col(cols, "draw") or cls._col(cols, "dr")
                i_jky = cls._col(cols, "jockey")
                i_trn = cls._col(cols, "trainer")
                i_wt = cls._col(cols, "wt")
                i_rate = cls._col(cols, "rating") or cls._col(cols, "rtg")
                i_gear = cls._col(cols, "gear")
                i_horse = None
                for idx, c in enumerate(cols):
                    if c.strip().lower() == "horse":
                        i_horse = idx
                for _, row in df.iterrows():
                    vals = list(row.values)

                    def g(i):
                        return vals[i] if i is not None and i < len(vals) else None
                    name, code = parse_horse_name_code(g(i_horse))
                    if name is None and g(i_no) is None:
                        continue
                    entries.append(RunnerEntry(
                        horse_no=to_int(g(i_no)), horse_name=name, horse_code=code,
                        draw=to_int(g(i_draw)),
                        jockey=str(g(i_jky)).strip() if g(i_jky) is not None else None,
                        trainer=str(g(i_trn)).strip() if g(i_trn) is not None else None,
                        actual_weight=to_int(g(i_wt)),
                        rating=to_int(g(i_rate)),
                        gear=str(g(i_gear)).strip() if g(i_gear) is not None else None,
                    ))
                break
        if not entries:
            log.info("racecard %s %s R%d: no server-rendered grid (JS-only) — "
                     "rating/gear unavailable via static fetch", date_iso, course, race_no)
        return ParsedRaceCard(meta=meta, entries=entries)
