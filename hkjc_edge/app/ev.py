"""Expected-value and stake-sizing math, with hard bankroll guardrails.

Pari-mutuel win odds O already embed the takeout, so for a $1 win bet:
    EV = p_model * O - 1
A bet is only +EV if the model rates the horse enough above the market to clear the takeout.
Stakes use FRACTIONAL Kelly (default 1/4) with hard per-bet, per-race, and total-exposure
caps, plus session-loss and stop-loss limits that REFUSE to size beyond configured limits.
"""
from __future__ import annotations

from dataclasses import dataclass, field


def win_ev(p: float, odds: float) -> float:
    """EV per unit staked on a win bet at decimal odds (takeout embedded in odds)."""
    return p * odds - 1.0


def full_kelly_fraction(p: float, odds: float) -> float:
    """Full-Kelly fraction of bankroll for a win bet. 0 if not +EV."""
    b = odds - 1.0
    if b <= 0:
        return 0.0
    f = (p * b - (1.0 - p)) / b           # == (p*odds - 1) / (odds - 1) == EV / b
    return max(0.0, f)


@dataclass
class BankrollConfig:
    starting_bankroll: float = 1000.0
    kelly_fraction: float = 0.25          # fractional Kelly
    per_bet_cap_frac: float = 0.02        # max stake per bet, fraction of bankroll
    per_race_cap_frac: float = 0.04       # max TOTAL stake in one race (mutually exclusive!)
    total_exposure_cap_frac: float = 0.10  # max concurrent/session staked, fraction of start
    session_loss_limit_frac: float = 0.10  # stop the session after losing this fraction
    stop_loss_frac: float = 0.25          # hard stop if bankroll falls this far below start


@dataclass
class BankrollState:
    cfg: BankrollConfig
    bankroll: float = field(default=0.0)
    session_staked: float = 0.0
    session_pnl: float = 0.0

    def __post_init__(self):
        if self.bankroll == 0.0:
            self.bankroll = self.cfg.starting_bankroll

    # -- limit checks ------------------------------------------------------------------
    def halted_reason(self) -> str | None:
        start = self.cfg.starting_bankroll
        if self.bankroll <= start * (1.0 - self.cfg.stop_loss_frac):
            return "stop-loss hit (bankroll fell past stop_loss_frac)"
        if self.session_pnl <= -start * self.cfg.session_loss_limit_frac:
            return "session loss limit hit"
        if self.session_staked >= start * self.cfg.total_exposure_cap_frac:
            return "total exposure cap hit"
        return None


def size_bet(p: float, odds: float, state: BankrollState,
             *, race_committed: float = 0.0) -> tuple[float, str]:
    """Return (stake, reason). Stake 0 with a reason if blocked by a guardrail.

    race_committed = stake already allocated to OTHER runners in the SAME race (win bets in a
    race are mutually exclusive, so total race stake is capped, not summed independently)."""
    cfg = state.cfg
    halt = state.halted_reason()
    if halt:
        return 0.0, halt
    if win_ev(p, odds) <= 0:
        return 0.0, "not +EV"

    desired = full_kelly_fraction(p, odds) * cfg.kelly_fraction * state.bankroll
    # caps (all in absolute currency)
    per_bet_cap = cfg.per_bet_cap_frac * state.bankroll
    per_race_room = cfg.per_race_cap_frac * state.bankroll - race_committed
    exposure_room = cfg.total_exposure_cap_frac * cfg.starting_bankroll - state.session_staked
    stake = min(desired, per_bet_cap, per_race_room, exposure_room)
    if stake <= 0:
        return 0.0, "blocked by per-race/exposure cap"
    return round(stake, 2), "sized (fractional Kelly, capped)"


def settle_bet(state: BankrollState, stake: float, odds: float, won: bool) -> None:
    """Apply a settled bet to the bankroll/session counters."""
    pnl = (odds - 1.0) * stake if won else -stake
    state.bankroll += pnl
    state.session_staked += stake
    state.session_pnl += pnl
