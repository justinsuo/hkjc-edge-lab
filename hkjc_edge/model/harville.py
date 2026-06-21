"""Derive place / quinella / QPL / forecast / trio probabilities from WIN probabilities.

Two routes, both documented with their biases:

  1. HARVILLE (1973) closed forms. Assumes the finishing order is Plackett-Luce: after the
     winner is removed, the rest race "as if" with probabilities renormalised. This is the
     standard method, but it is BIASED: empirically, beaten favourites "run on" into the
     places more than PL predicts, and longshots less, so Harville tends to OVERSTATE the
     place chances of longshots and understate favourites. Treat outputs as approximations.

  2. MONTE-CARLO Plackett-Luce sampling (Gumbel-max trick). Exact samples from the SAME PL
     model, so it shares Harville's conditional-independence assumption — it is NOT a
     correction for the bias, just a convenient way to get any exotic (forecast/trio/QPL)
     without bespoke closed forms.

IMPORTANT: never derive place probs by naively multiplying win probs — place slots are
SHARED and correlated, so that overstates joint place probability. Use these functions.
"""
from __future__ import annotations

import numpy as np


def _clean(win_probs) -> np.ndarray:
    p = np.asarray(win_probs, dtype=float)
    p = np.clip(p, 1e-12, None)
    return p / p.sum()


def default_place_k(field_size: int) -> int:
    """HKJC place rule: 3 places for fields >= 7, 2 for 4-6, none for < 4."""
    if field_size >= 7:
        return 3
    if field_size >= 4:
        return 2
    return 0


# ---- Harville closed forms ------------------------------------------------------------

def harville_position_prob(p: np.ndarray, i: int, pos: int) -> float:
    """P(horse i finishes exactly at position `pos`, 1-indexed) under Harville. pos<=3."""
    n = len(p)
    if pos == 1:
        return float(p[i])
    if pos == 2:
        s = 0.0
        for a in range(n):
            if a == i:
                continue
            s += p[a] * p[i] / (1.0 - p[a])
        return float(s)
    if pos == 3:
        s = 0.0
        for a in range(n):
            if a == i:
                continue
            for b in range(n):
                if b in (i, a):
                    continue
                denom = 1.0 - p[a] - p[b]
                if denom <= 0:
                    continue
                s += p[a] * (p[b] / (1.0 - p[a])) * (p[i] / denom)
        return float(s)
    raise ValueError("harville_position_prob supports pos in {1,2,3}")


def harville_place_probs(win_probs, k: int) -> np.ndarray:
    """P(horse in top k) for every horse, exact under Harville (k<=3).

    Invariant: sum over horses == k (exactly k horses occupy the top k slots).
    """
    p = _clean(win_probs)
    n = len(p)
    if k <= 0:
        return np.zeros(n)
    k = min(k, n, 3)
    out = np.zeros(n)
    for i in range(n):
        out[i] = sum(harville_position_prob(p, i, pos) for pos in range(1, k + 1))
    return out


def quinella_prob(win_probs, i: int, j: int) -> float:
    """P(i and j are the first two home in ANY order), exact under Harville."""
    p = _clean(win_probs)
    return float(p[i] * p[j] / (1.0 - p[i]) + p[j] * p[i] / (1.0 - p[j]))


def forecast_prob(win_probs, i: int, j: int) -> float:
    """P(i 1st AND j 2nd), exact under Harville (ordered)."""
    p = _clean(win_probs)
    return float(p[i] * p[j] / (1.0 - p[i]))


# ---- Monte-Carlo Plackett-Luce (Gumbel-max trick) -------------------------------------

class PLSimulation:
    """Exact Plackett-Luce finishing-order samples; derive any exotic probability."""

    def __init__(self, win_probs, n_sims: int = 20000, seed: int = 0):
        p = _clean(win_probs)
        self.n = len(p)
        self.n_sims = n_sims
        rng = np.random.default_rng(seed)
        logits = np.log(p)
        gumbel = -np.log(-np.log(rng.uniform(size=(n_sims, self.n))))
        scores = logits[None, :] + gumbel
        # order[s] = horses ranked best-to-worst in sim s
        self.order = np.argsort(-scores, axis=1)

    def win_probs(self) -> np.ndarray:
        return np.bincount(self.order[:, 0], minlength=self.n) / self.n_sims

    def place_probs(self, k: int) -> np.ndarray:
        topk = self.order[:, :k]
        counts = np.zeros(self.n)
        for col in range(k):
            counts += np.bincount(topk[:, col], minlength=self.n)
        return counts / self.n_sims

    def quinella_prob(self, i: int, j: int) -> float:
        top2 = self.order[:, :2]
        hit = ((top2 == i).any(1) & (top2 == j).any(1))
        return float(hit.mean())

    def qpl_prob(self, i: int, j: int, k: int = 3) -> float:
        """Quinella Place: both i and j finish in the top k (default 3)."""
        topk = self.order[:, :k]
        hit = ((topk == i).any(1) & (topk == j).any(1))
        return float(hit.mean())

    def forecast_prob(self, i: int, j: int) -> float:
        return float(((self.order[:, 0] == i) & (self.order[:, 1] == j)).mean())

    def trio_prob(self, i: int, j: int, k: int) -> float:
        top3 = self.order[:, :3]
        hit = ((top3 == i).any(1) & (top3 == j).any(1) & (top3 == k).any(1))
        return float(hit.mean())
