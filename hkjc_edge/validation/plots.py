"""Calibration and P&L plots (matplotlib, Agg backend so it works headless)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def calibration_plot(oos: pd.DataFrame, cols: dict, out_png: str | Path, n_bins: int = 10):
    """cols: {label: column_name}. Reliability diagram (mean predicted vs empirical win rate)."""
    y = (oos["label_won"] == 1).astype(float).values
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="perfect")
    bins = np.linspace(0, 1, n_bins + 1)
    for label, col in cols.items():
        p = oos[col].values
        idx = np.clip(np.digitize(p, bins) - 1, 0, n_bins - 1)
        xs, ys = [], []
        for b in range(n_bins):
            m = idx == b
            if m.sum() >= 5:
                xs.append(p[m].mean()); ys.append(y[m].mean())
        ax.plot(xs, ys, "o-", label=label, alpha=0.8)
    ax.set_xlabel("mean predicted win probability")
    ax.set_ylabel("empirical win rate")
    ax.set_title("Calibration (out-of-sample)")
    ax.legend()
    ax.set_xlim(0, max(0.6, oos[list(cols.values())].max().max()))
    ax.set_ylim(0, 1)
    fig.tight_layout()
    fig.savefig(out_png, dpi=110)
    plt.close(fig)


def pnl_plot(series: dict, out_png: str | Path):
    """series: {label: list_of_cumulative_pnl}. Flat-stake cumulative P&L in bet order."""
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.axhline(0, color="k", lw=1)
    for label, cum in series.items():
        if cum:
            ax.plot(range(1, len(cum) + 1), cum, label=label, alpha=0.85)
    ax.set_xlabel("bet number (time order)")
    ax.set_ylabel("cumulative P&L (units, flat 1u stakes)")
    ax.set_title("Profit simulation after real takeout")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_png, dpi=110)
    plt.close(fig)


def equity_plot(curve: list, out_png: str | Path, label: str = "fractional-Kelly bankroll"):
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.axhline(1.0, color="k", lw=1, ls="--")
    ax.plot(range(1, len(curve) + 1), curve, label=label)
    ax.set_xlabel("race (time order)")
    ax.set_ylabel("bankroll multiple")
    ax.set_title("Bankroll equity curve")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_png, dpi=110)
    plt.close(fig)
