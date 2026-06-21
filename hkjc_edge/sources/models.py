"""Typed containers for parsed HKJC data. Pure data; no I/O."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RaceMeta:
    race_date: str          # 'YYYY-MM-DD'
    racecourse: str         # 'ST' | 'HV' | 'CH'
    race_no: int
    race_index: Optional[int] = None
    class_: Optional[str] = None
    distance_m: Optional[int] = None
    going: Optional[str] = None
    track: Optional[str] = None
    course: Optional[str] = None
    prize_money: Optional[int] = None
    race_name: Optional[str] = None
    rating_band: Optional[str] = None


@dataclass
class RunnerEntry:
    """Bet-time declared info for a runner (from racecard or recoverable from results)."""
    horse_no: Optional[int]
    horse_name: Optional[str]
    horse_code: Optional[str] = None
    draw: Optional[int] = None
    actual_weight: Optional[int] = None
    declared_weight: Optional[int] = None
    jockey: Optional[str] = None
    trainer: Optional[str] = None
    rating: Optional[int] = None
    gear: Optional[str] = None
    scratched: bool = False


@dataclass
class RunnerResult:
    """Outcome info for a runner."""
    horse_no: Optional[int]
    horse_name: Optional[str]
    horse_code: Optional[str] = None
    finish_pos: Optional[int] = None
    finish_pos_raw: Optional[str] = None
    dead_heat: bool = False
    disqualified: bool = False
    lengths_behind: Optional[float] = None
    running_position: Optional[str] = None
    finish_time_s: Optional[float] = None
    win_odds: Optional[float] = None
    # declared fields that also appear in the results table (bet-time-safe):
    jockey: Optional[str] = None
    trainer: Optional[str] = None
    draw: Optional[int] = None
    actual_weight: Optional[int] = None
    declared_weight: Optional[int] = None


@dataclass
class Dividend:
    pool: str
    combination: Optional[str]
    dividend_hkd: Optional[float]
    pool_total: Optional[float] = None


@dataclass
class Sectional:
    horse_no: int
    section_index: int
    section_time_s: Optional[float] = None
    position: Optional[int] = None
    margin: Optional[float] = None


@dataclass
class ParsedRaceResults:
    meta: RaceMeta
    results: list[RunnerResult] = field(default_factory=list)
    dividends: list[Dividend] = field(default_factory=list)


@dataclass
class ParsedRaceCard:
    meta: RaceMeta
    entries: list[RunnerEntry] = field(default_factory=list)
