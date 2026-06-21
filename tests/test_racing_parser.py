from collections import defaultdict

from hkjc_edge.sources.hkjc_racing import HkjcRacingSource as S


def test_parse_results_meta_and_rows(fixtures_dir):
    html = (fixtures_dir / "results_sample.html").read_text()
    pr = S.parse_results(html, "2026-06-13", "ST", 1)
    m = pr.meta
    assert m.race_index == 774
    assert m.distance_m == 1200
    assert m.going == "GOOD"
    assert m.track == "Turf"
    assert m.prize_money == 1000000
    assert m.rating_band == "60-40"

    assert len(pr.results) == 3
    winner = pr.results[0]
    assert winner.finish_pos == 1
    assert winner.horse_no == 6
    assert winner.horse_name == "JEDI SPURS"
    assert winner.horse_code == "L441"
    assert winner.jockey == "B Avdulla"
    assert winner.trainer == "D A Hayes"
    assert winner.draw == 6
    assert winner.actual_weight == 121
    assert winner.declared_weight == 1131
    assert winner.win_odds == 1.6
    assert winner.finish_time_s == 55.81
    assert winner.lengths_behind == 0.0
    assert pr.results[1].lengths_behind == 4.5


def test_parse_dividends(fixtures_dir):
    html = (fixtures_dir / "results_sample.html").read_text()
    pr = S.parse_results(html, "2026-06-13", "ST", 1)
    pools = {(d.pool, d.combination): d.dividend_hkd for d in pr.dividends}
    assert pools[("WIN", "6")] == 16.0
    assert pools[("QUINELLA", "1,6")] == 65.5
    assert ("PLACE", "1") in pools


def test_discover_race_count(fixtures_dir):
    html = (fixtures_dir / "results_sample.html").read_text()
    assert S.discover_race_count(html) == 3


def test_parse_sectional_deaggregates(fixtures_dir):
    html = (fixtures_dir / "sectional_sample.html").read_text()
    secs = S.parse_sectional(html, "2026-06-13", "ST", 1)
    byh = defaultdict(list)
    for s in secs:
        byh[s.horse_no].append(s.section_time_s)
    # winner's de-aggregated 200m splits sum exactly to the finish time (55.81)
    assert byh[6] == [13.37, 10.37, 10.47, 10.44, 11.16]
    assert round(sum(byh[6]), 2) == 55.81
    # horse 7 too (different cell packing) -> 56.53
    assert round(sum(byh[7]), 2) == 56.53


def test_deaggregate_unit():
    out = S._deaggregate_splits([13.37, 20.84, 10.37, 10.47, 21.60, 10.44, 11.16])
    assert out == [13.37, 10.37, 10.47, 10.44, 11.16]
