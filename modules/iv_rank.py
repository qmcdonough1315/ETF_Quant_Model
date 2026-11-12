"""IV Rank helpers from a stored ATM IV history."""

from __future__ import annotations

from typing import Optional

import pandas as pd


def iv_rank_from_series(iv_history: pd.Series, current_iv: Optional[float] = None) -> Optional[float]:
    """
    Classic IV Rank: 100 * (current - min) / (max - min) over the provided window.
    `iv_history` should already be truncated to the lookback (e.g. ~252 sessions).
    """
    s = pd.to_numeric(iv_history, errors="coerce").dropna()
    if s.empty:
        return None
    cur = float(current_iv) if current_iv is not None else float(s.iloc[-1])
    lo = float(s.min())
    hi = float(s.max())
    if hi <= lo or not (cur == cur):
        return None
    return 100.0 * (cur - lo) / (hi - lo)


def rolling_iv_rank(
    history: pd.DataFrame,
    *,
    ticker_col: str = "ticker",
    date_col: str = "as_of_date",
    iv_col: str = "atm_iv",
    lookback_days: int = 365,
) -> pd.DataFrame:
    """
    Compute IV Rank for each row using prior `lookback_days` calendar days inclusive.
    Expects columns ticker / as_of_date / atm_iv.
    """
    if history.empty:
        return history.assign(iv_rank=pd.Series(dtype=float))
    df = history.copy()
    df[date_col] = pd.to_datetime(df[date_col]).dt.normalize()
    df = df.sort_values([ticker_col, date_col])
    ranks: list[Optional[float]] = []
    for _, row in df.iterrows():
        start = row[date_col] - pd.Timedelta(days=lookback_days)
        window = df.loc[
            (df[ticker_col] == row[ticker_col])
            & (df[date_col] >= start)
            & (df[date_col] <= row[date_col]),
            iv_col,
        ]
        ranks.append(iv_rank_from_series(window, current_iv=float(row[iv_col])))
    out = df.copy()
    out["iv_rank"] = ranks
    return out
