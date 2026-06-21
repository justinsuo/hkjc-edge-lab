"""Phase 4 runtime app — a NO-BET-by-default recommender.

Because Phase 3 returned NO-GO, the edge gate is OFF by default: the recommender shows model
vs market probabilities and honest cross-pool consistency signals, but recommends NO BET. A
user can force the gate on in config (with a loud warning), but the truthful default behaviour
is NO BET. Stake sizing (fractional Kelly) and hard bankroll guardrails exist for the case a
validated edge is ever established — not because one has been.
"""
