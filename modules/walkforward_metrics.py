"""
Shared walk-forward / research-card performance metrics.
"""

from __future__ import annotations

from typing import Iterable, Optional

import numpy as np
import pandas as pd


def periods_per_year_from_step(rebalance_step_months: int) -> float:
    return 12.0 / float(rebalance_step_months)


def calculate_sharpe_ratio(
    returns_series: pd.Series,
    risk_free_rate: float = 0.03,
    periods_per_year: float = 4.0,
) -> float:
    """Annualized Sharpe for fixed-horizon period returns."""
    if returns_series is None or len(returns_series) == 0 or float(returns_series.std()) == 0:
        return 0.0
    mean_period_ret = float(returns_series.mean())
    std_period_ret = float(returns_series.std())
    rf_period = (1 + risk_free_rate) ** (1 / periods_per_year) - 1
    return ((mean_period_ret - rf_period) * periods_per_year) / (
        std_period_ret * np.sqrt(periods_per_year)
    )


def annualized_volatility(returns_series: pd.Series, periods_per_year: float = 4.0) -> float:
    if returns_series is None or len(returns_series) == 0:
        return 0.0
    return float(returns_series.std() * np.sqrt(periods_per_year))


def wealth_path(period_returns: Iterable[float], initial_capital: float = 1.0) -> pd.Series:
    value = float(initial_capital)
    out = []
    for r in period_returns:
        value *= 1.0 + float(r)
        out.append(value)
    return pd.Series(out, dtype=float)


def max_drawdown_from_returns(
    period_returns: Iterable[float],
    initial_capital: float = 1.0,
) -> float:
    """Peak-to-trough drawdown on compounded wealth (negative or zero)."""
    path = wealth_path(period_returns, initial_capital=initial_capital)
    if path.empty:
        return 0.0
    peak = path.cummax()
    dd = path / peak - 1.0
    return float(dd.min())


def hit_rate(strategy_returns: pd.Series, benchmark_returns: pd.Series) -> float:
    """Fraction of periods where strategy beats benchmark."""
    s = pd.to_numeric(strategy_returns, errors="coerce")
    b = pd.to_numeric(benchmark_returns, errors="coerce")
    both = pd.concat([s, b], axis=1).dropna()
    if both.empty:
        return float("nan")
    return float((both.iloc[:, 0] > both.iloc[:, 1]).mean())


def total_return_from_path(period_returns: Iterable[float]) -> float:
    value = 1.0
    for r in period_returns:
        value *= 1.0 + float(r)
    return value - 1.0


def summarize_period_returns(
    period_returns: pd.Series,
    *,
    initial_capital: float,
    risk_free_rate: float,
    periods_per_year: float,
    benchmark_returns: Optional[pd.Series] = None,
) -> dict:
    """Roll up a single return series into research-card metrics."""
    rets = pd.to_numeric(period_returns, errors="coerce").fillna(0.0).astype(float)
    tot = total_return_from_path(rets)
    final_value = float(initial_capital) * (1.0 + tot)
    out = {
        "n_periods": int(len(rets)),
        "final_value": final_value,
        "total_return": tot,
        "ann_vol": annualized_volatility(rets, periods_per_year),
        "sharpe": calculate_sharpe_ratio(rets, risk_free_rate, periods_per_year),
        "max_drawdown": max_drawdown_from_returns(rets, initial_capital=1.0),
        "hit_rate_vs_benchmark": float("nan"),
        "excess_total_vs_benchmark": float("nan"),
    }
    if benchmark_returns is not None:
        b = pd.to_numeric(benchmark_returns, errors="coerce").fillna(0.0).astype(float)
        # Align by position when indexes differ but lengths match.
        if len(b) == len(rets):
            b = pd.Series(b.to_numpy(), index=rets.index)
        else:
            b = b.reindex(rets.index).fillna(0.0)
        out["hit_rate_vs_benchmark"] = hit_rate(rets, b)
        out["excess_total_vs_benchmark"] = tot - total_return_from_path(b)
    return out


def blend_period_returns(
    left: pd.Series,
    right: pd.Series,
    *,
    left_weight: float,
    right_weight: float,
) -> pd.Series:
    """Weighted sum of aligned period returns (renormalize if a side is missing)."""
    l = pd.to_numeric(left, errors="coerce")
    r = pd.to_numeric(right, errors="coerce")
    idx = l.index.union(r.index)
    l = l.reindex(idx)
    r = r.reindex(idx)
    out = []
    for i in idx:
        lv = l.loc[i]
        rv = r.loc[i]
        lw, rw = float(left_weight), float(right_weight)
        if pd.isna(lv) and pd.isna(rv):
            out.append(0.0)
            continue
        if pd.isna(lv):
            lw, lv = 0.0, 0.0
            rw = 1.0
        if pd.isna(rv):
            rw, rv = 0.0, 0.0
            if lw > 0:
                lw = 1.0
        wsum = lw + rw
        if wsum <= 0:
            out.append(0.0)
        else:
            out.append((lw * float(lv) + rw * float(rv)) / wsum)
    return pd.Series(out, index=idx, dtype=float)
