"""De-vigging methods: turn gross win odds into true-probability estimates.

  * proportional — normalise 1/O across the field (simple, the project default).
  * shin — Shin (1992/93): infers an insider-trading proportion z, correcting the mild
    favourite-longshot structure of the overround. Usually a touch better calibrated, which
    makes the market an even harder benchmark to beat.
"""
from __future__ import annotations

import numpy as np


def proportional_devig(odds) -> np.ndarray:
    b = 1.0 / np.asarray(odds, dtype=float)
    return b / b.sum()


def shin_devig(odds, tol: float = 1e-10, max_iter: int = 200) -> np.ndarray:
    """Shin de-vig. Returns true-prob estimates summing to 1.

    p_i = (sqrt(z^2 + 4(1-z) b_i^2 / B) - z) / (2(1-z)), with B = sum_j b_j, z solved so the
    probabilities sum to 1. Falls back to proportional if degenerate.
    """
    b = 1.0 / np.asarray(odds, dtype=float)
    B = b.sum()
    if B <= 1.0 or len(b) < 2:
        return b / B

    def probs(z):
        return (np.sqrt(z * z + 4 * (1 - z) * b * b / B) - z) / (2 * (1 - z))

    lo, hi = 0.0, 0.5
    # sum(probs) decreases in z; find z making sum == 1 by bisection
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        s = probs(mid).sum()
        if abs(s - 1.0) < tol:
            break
        if s > 1.0:
            lo = mid
        else:
            hi = mid
    p = probs(0.5 * (lo + hi))
    p = np.clip(p, 1e-12, None)
    return p / p.sum()
