from hkjc_edge.sources.parse_util import (
    hyphen_date, parse_distance, parse_finish_pos, parse_finish_time, parse_horse_name_code,
    parse_lbw, parse_prize, slash_dmy, to_float, to_int,
)


def test_horse_name_code():
    assert parse_horse_name_code("JEDI SPURS (L441)") == ("JEDI SPURS", "L441")
    assert parse_horse_name_code("NO CODE HORSE") == ("NO CODE HORSE", None)
    assert parse_horse_name_code(None) == (None, None)


def test_finish_time():
    assert parse_finish_time("0:55.81") == 55.81
    assert parse_finish_time("1:09.20") == 69.20
    assert parse_finish_time("55.81") == 55.81
    assert parse_finish_time("---") is None


def test_lbw():
    assert parse_lbw("---") == 0.0
    assert parse_lbw("4-1/2") == 4.5
    assert parse_lbw("3/4") == 0.75
    assert parse_lbw("SH") == 0.1
    assert parse_lbw("8") == 8.0


def test_finish_pos():
    assert parse_finish_pos("1")[0] == 1
    pos, raw, dh, dq = parse_finish_pos("2 DH")
    assert pos == 2 and dh is True
    assert parse_finish_pos("WV")[0] is None


def test_misc():
    assert parse_distance("1200M") == 1200
    assert parse_distance("1,200m") == 1200
    assert parse_prize("HK$ 950,000") == 950000
    assert to_int("121") == 121
    assert to_float("1.6") == 1.6
    assert hyphen_date("2026-06-13") == "2026/06/13"
    assert slash_dmy("2026-06-13") == "13/06/2026"
