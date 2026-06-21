"""Pure parsing helpers for HKJC text fields. Fully unit-testable, no I/O."""
from __future__ import annotations

import re
from typing import Optional

# Lengths-behind-winner abbreviations -> approx lengths.
_LBW_WORDS = {
    "": 0.0, "-": 0.0, "---": 0.0, "N": 0.0,
    "NOSE": 0.05, "SH": 0.1, "SHD": 0.1, "SHT": 0.1, "SHTHD": 0.1,
    "HD": 0.2, "HEAD": 0.2,
    "NK": 0.3, "NECK": 0.3,
    "DH": 0.0,   # dead heat -> same as the horse it dead-heats with
}


def to_int(v) -> Optional[int]:
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    m = re.search(r"-?\d+", s)
    return int(m.group()) if m else None


def to_float(v) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        m = re.search(r"-?\d+(\.\d+)?", s)
        return float(m.group()) if m else None


def parse_horse_name_code(raw: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """'JEDI SPURS (L441)' -> ('JEDI SPURS', 'L441'). Code missing -> (name, None)."""
    if not raw:
        return None, None
    s = str(raw).strip()
    m = re.match(r"^(.*?)\s*\(([A-Z]\d{2,4})\)\s*$", s)
    if m:
        return m.group(1).strip(), m.group(2)
    return s, None


def parse_finish_time(raw: Optional[str]) -> Optional[float]:
    """'0:55.81' or '1:09.20' -> seconds (float). '55.81' -> 55.81."""
    if not raw:
        return None
    s = str(raw).strip()
    if not s or s in {"---", "-"}:
        return None
    if ":" in s:
        parts = s.split(":")
        try:
            mins = float(parts[0])
            secs = float(parts[1])
            return mins * 60.0 + secs
        except ValueError:
            return None
    return to_float(s)


def parse_lbw(raw: Optional[str]) -> Optional[float]:
    """Lengths behind winner. Handles '4-1/2', '1/2', 'SH', 'NK', '---', '8'."""
    if raw is None:
        return None
    s = str(raw).strip().upper()
    if s in _LBW_WORDS:
        return _LBW_WORDS[s]
    # forms like '4-1/2' (= 4.5), '4-3/4', '1/2', '3/4'
    m = re.match(r"^(\d+)-(\d+)/(\d+)$", s)
    if m:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    m = re.match(r"^(\d+)/(\d+)$", s)
    if m:
        return int(m.group(1)) / int(m.group(2))
    return to_float(s)


def parse_finish_pos(raw) -> tuple[Optional[int], str, bool, bool]:
    """Return (finish_pos|None, raw_str, dead_heat, disqualified)."""
    s = str(raw).strip() if raw is not None else ""
    up = s.upper()
    dead_heat = "DH" in up
    disq = "DISQ" in up or up == "DQ"
    # Non-finisher codes
    if up in {"WV", "WV-A", "WX", "WXNR", "PU", "UR", "FE", "DNF", "TNP", "DQ"}:
        return None, s, dead_heat, disq
    pos = to_int(re.sub(r"\s*DH\s*", "", up))
    return pos, s, dead_heat, disq


def parse_distance(raw: Optional[str]) -> Optional[int]:
    """'1200M' / '1200m' / '1,200M' -> 1200."""
    if not raw:
        return None
    m = re.search(r"(\d[\d,]*)\s*[mM]\b", str(raw))
    return int(m.group(1).replace(",", "")) if m else None


def parse_prize(raw: Optional[str]) -> Optional[int]:
    """'HK$ 950,000' -> 950000."""
    if not raw:
        return None
    m = re.search(r"\$\s*([\d,]+)", str(raw))
    return int(m.group(1).replace(",", "")) if m else None


def hyphen_date(date_iso: str) -> str:
    """'2026-06-13' -> '2026/06/13' (HKJC results/racecard format)."""
    return date_iso.replace("-", "/")


def slash_dmy(date_iso: str) -> str:
    """'2026-06-13' -> '13/06/2026' (HKJC sectional-time page format)."""
    y, m, d = date_iso.split("-")
    return f"{d}/{m}/{y}"
