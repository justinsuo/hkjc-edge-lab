"""Phase 3 validation: walk-forward backtest, closing-line value, profit simulation,
overfitting checks, and a GO/NO-GO verdict.

This phase decides whether the tool is ALLOWED to recommend bets. The bar is deliberately
high and adversarial: the model must beat the closing line out of sample (primary test) AND
turn a profit after the real takeout, both with bootstrap confidence intervals that exclude
zero. The honest prior (Phase 0) is that it will not — and reporting NO-GO is a success.
"""
