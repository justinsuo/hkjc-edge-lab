import numpy as np

from hkjc_edge.model.market import proportional_devig, shin_devig


def test_proportional_sums_to_one():
    odds = [2.0, 4.0, 6.0, 10.0]
    p = proportional_devig(odds)
    assert abs(p.sum() - 1.0) < 1e-12


def test_shin_sums_to_one_and_removes_overround():
    # overround > 1 (takeout). Shin probs must still sum to 1.
    odds = [1.8, 3.5, 5.0, 8.0, 15.0]
    p = shin_devig(odds)
    assert abs(p.sum() - 1.0) < 1e-8
    assert (p > 0).all()


def test_shin_vs_proportional_shapes_match():
    odds = [2.5, 3.0, 4.0]
    assert len(shin_devig(odds)) == len(proportional_devig(odds)) == 3


def test_shin_handads_no_overround_gracefully():
    # If booksum <= 1 (no vig), fall back to proportional without crashing.
    p = shin_devig([3.0, 3.0, 3.0])
    assert abs(p.sum() - 1.0) < 1e-8
