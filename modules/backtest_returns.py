"""
Walk-forward period return helpers.

Production path compounds Σ w_i r_i using Target_Weight from the MVO.
Equal-weight mean is retained only as an explicit ablation.
"""

from __future__ import annotations

from typing import Mapping, Optional, Union

import numpy as np
import pandas as pd


WeightLike = Union[pd.Series, Mapping[str, float]]


def normalize_weights(weights: WeightLike, tickers: Optional[list[str]] = None) -> pd.Series:
    """Return non-negative weights indexed by ticker that sum to 1 (or empty)."""
    if isinstance(weights, pd.Series):
        w = weights.astype(float).copy()
    else:
        w = pd.Series({str(k): float(v) for k, v in dict(weights).items()}, dtype=float)
    w.index = w.index.map(lambda x: str(x).upper())
    if tickers is not None:
        w = w.reindex([t.upper() for t in tickers]).fillna(0.0)
    w = w.clip(lower=0.0)
    total = float(w.sum())
    if total <= 0:
        return w * 0.0
    return w / total


def compounded_ticker_returns(period_returns: pd.DataFrame) -> pd.Series:
    """Compound each column over the holding window: Π(1+r) - 1."""
    if period_returns is None or period_returns.empty:
        return pd.Series(dtype=float)
    return (1.0 + period_returns.astype(float)).prod(axis=0) - 1.0


def portfolio_period_return(
    period_returns: pd.DataFrame,
    weights: Optional[WeightLike] = None,
    *,
    equal_weight: bool = False,
) -> float:
    """
    Holding-window portfolio return.

    Default: Σ w_i r_i with production weights (renormalized over available names).
    If equal_weight=True (ablation), use the arithmetic mean of compounded ticker returns.
    """
    if period_returns is None or period_returns.empty:
        return 0.0

    r = compounded_ticker_returns(period_returns)
    r = r.replace([np.inf, -np.inf], np.nan).dropna()
    if r.empty:
        return 0.0

    if equal_weight or weights is None:
        return float(r.mean())

    w = normalize_weights(weights, tickers=list(r.index))
    if float(w.sum()) <= 0:
        return float(r.mean())
    return float((r * w.reindex(r.index).fillna(0.0)).sum())


def one_way_turnover(weights_new: WeightLike, weights_old: Optional[WeightLike] = None) -> float:
    """
    Classic one-way turnover: 0.5 * Σ |w_new - w_old|.

    First invest from cash (weights_old empty) → turnover ≈ 0.5.
    """
    w_new = normalize_weights(weights_new)
    if weights_old is None:
        w_old = pd.Series(0.0, index=w_new.index, dtype=float)
    else:
        w_old = normalize_weights(weights_old)
    idx = sorted(set(w_new.index) | set(w_old.index))
    a = w_new.reindex(idx).fillna(0.0)
    b = w_old.reindex(idx).fillna(0.0)
    return float(0.5 * np.abs(a - b).sum())


def equity_rebalance_cost(
    weights_new: WeightLike,
    weights_old: Optional[WeightLike] = None,
    *,
    one_way_bps: float = 0.0,
) -> float:
    """
    Cost as a fraction of NAV deducted from the period return.

    Interprets `one_way_bps` as the cost charged once per dollar traded on each side:
    cost = (Σ |Δw|) * bps / 10_000 = (2 * one_way_turnover) * bps / 10_000.
    """
    bps = float(one_way_bps)
    if bps <= 0:
        return 0.0
    traded = 2.0 * one_way_turnover(weights_new, weights_old)
    return float(traded * (bps / 10_000.0))


def net_period_return(
    gross_return: float,
    weights_new: WeightLike,
    weights_old: Optional[WeightLike] = None,
    *,
    one_way_bps: float = 0.0,
) -> tuple[float, float, float]:
    """Return (net_return, cost, turnover)."""
    turnover = one_way_turnover(weights_new, weights_old)
    cost = equity_rebalance_cost(weights_new, weights_old, one_way_bps=one_way_bps)
    return float(gross_return) - cost, cost, turnover
