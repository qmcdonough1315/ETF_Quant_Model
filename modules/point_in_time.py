"""Point-in-time helpers for research / live decision inputs."""

from __future__ import annotations

import pandas as pd

import config


def ken_french_asof(
    factors: pd.DataFrame,
    asof,
    lag_months: int | None = None,
) -> pd.DataFrame:
    """
    Point-in-time Ken French slice for a decision dated `asof`.

    Official monthly FF for calendar month T is typically released early in T+1,
    so a month-end T decision may only use factors through T - lag (default 1).
    """
    if factors.empty:
        return factors.copy()

    lag = (
        int(config.KEN_FRENCH_PUBLICATION_LAG_MONTHS)
        if lag_months is None
        else int(lag_months)
    )
    if lag < 0:
        raise ValueError("lag_months must be >= 0")

    out = factors.copy()
    if not isinstance(out.index, pd.PeriodIndex):
        out.index = pd.to_datetime(out.index).to_period("M")

    asof_period = asof if isinstance(asof, pd.Period) else pd.Period(asof, freq="M")
    cutoff = asof_period - lag
    return out.loc[:cutoff].copy()
