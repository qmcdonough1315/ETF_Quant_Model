"""
Normalize model expected returns into an options-sleeve composite score.

The sleeve regimes use ±0.5 thresholds (see options_sleeve.classify_regime).
We z-score Phase 1 ETF expected returns cross-sectionally each run so the
scale is comparable day to day without demo values.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional

import numpy as np
import pandas as pd

from modules.options_sleeve import PHASE1_OPTIONABLE_ETFS


def normalize_phase1_composites(
    expected_returns: Mapping[str, float],
    universe: Iterable[str] = PHASE1_OPTIONABLE_ETFS,
    *,
    clip: float = 3.0,
) -> dict[str, float]:
    """
    Cross-sectional z-score of expected returns over the Phase 1 universe.

    Tickers missing from `expected_returns` are omitted (no fill / no demo).
    """
    tickers = [t.upper() for t in universe]
    vals: list[float] = []
    keys: list[str] = []
    for t in tickers:
        if t not in expected_returns:
            # also accept original casing keys
            raw = expected_returns.get(t) or expected_returns.get(t.lower())
            if raw is None:
                continue
            v = float(raw)
        else:
            v = float(expected_returns[t])
        if not np.isfinite(v):
            continue
        keys.append(t)
        vals.append(v)

    if len(vals) < 2:
        # Not enough cross-section to standardize — return empty rather than fake scores.
        return {}

    arr = np.asarray(vals, dtype=float)
    mu = float(arr.mean())
    sigma = float(arr.std(ddof=0))
    if sigma <= 1e-12:
        return {k: 0.0 for k in keys}

    out: dict[str, float] = {}
    for k, v in zip(keys, vals):
        z = (v - mu) / sigma
        if clip is not None:
            z = float(np.clip(z, -clip, clip))
        out[k] = float(z)
    return out


def composites_from_scores_df(
    scores_df: pd.DataFrame,
    *,
    ticker_col: str = "Ticker",
    return_col: str = "Total_Expected_Return_3M",
    universe: Iterable[str] = PHASE1_OPTIONABLE_ETFS,
) -> dict[str, float]:
    if scores_df is None or scores_df.empty:
        return {}
    if ticker_col not in scores_df.columns or return_col not in scores_df.columns:
        return {}
    mapping = {
        str(r[ticker_col]).upper(): float(r[return_col])
        for _, r in scores_df.iterrows()
        if pd.notna(r[return_col])
    }
    return normalize_phase1_composites(mapping, universe=universe)
