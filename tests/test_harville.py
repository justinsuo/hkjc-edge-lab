import numpy as np

from hkjc_edge.model.harville import (
    PLSimulation, default_place_k, forecast_prob, harville_place_probs, quinella_prob,
)


def test_place_probs_sum_to_k():
    p = np.array([0.4, 0.3, 0.2, 0.1])
    for k in (1, 2, 3):
        assert abs(harville_place_probs(p, k).sum() - k) < 1e-9


def test_place_k1_equals_win():
    p = np.array([0.5, 0.3, 0.2])
    np.testing.assert_allclose(harville_place_probs(p, 1), p, atol=1e-12)


def test_equal_probs_symmetric():
    p = np.ones(5) / 5
    pl = harville_place_probs(p, 3)
    np.testing.assert_allclose(pl, np.full(5, 3 / 5), atol=1e-9)


def test_quinella_distribution_sums_to_one():
    p = np.array([0.4, 0.3, 0.2, 0.1])
    n = len(p)
    total = sum(quinella_prob(p, i, j) for i in range(n) for j in range(i + 1, n))
    assert abs(total - 1.0) < 1e-9


def test_forecast_sums_to_one():
    p = np.array([0.4, 0.3, 0.2, 0.1])
    n = len(p)
    total = sum(forecast_prob(p, i, j) for i in range(n) for j in range(n) if i != j)
    assert abs(total - 1.0) < 1e-9


def test_naive_multiply_overstates_joint_place():
    # The shared-place-slot correlation: P(both in top-2) from Harville must be LESS than
    # the naive independent product of marginal place probs.
    p = np.array([0.4, 0.3, 0.2, 0.1])
    pl2 = harville_place_probs(p, 2)
    naive = pl2[0] * pl2[1]                    # treat place events as independent (WRONG)
    # exact joint P(both 0 and 1 in top-2) under Harville == quinella prob of the pair
    joint = quinella_prob(p, 0, 1)
    assert joint < naive


def test_simulation_matches_harville():
    p = np.array([0.45, 0.25, 0.18, 0.12])
    sim = PLSimulation(p, n_sims=60000, seed=1)
    np.testing.assert_allclose(sim.win_probs(), p, atol=0.01)
    np.testing.assert_allclose(sim.place_probs(2), harville_place_probs(p, 2), atol=0.02)
    # quinella close between closed form and simulation
    assert abs(sim.quinella_prob(0, 1) - quinella_prob(p, 0, 1)) < 0.02
    assert abs(sim.place_probs(3).sum() - 3.0) < 1e-9


def test_default_place_k():
    assert default_place_k(12) == 3
    assert default_place_k(5) == 2
    assert default_place_k(3) == 0
