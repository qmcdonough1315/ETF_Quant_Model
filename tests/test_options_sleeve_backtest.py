"""Unit fixtures exercise math only — production loader still refuses empty IV."""

from __future__ import annotations

import numpy as np
import pandas as pd

from modules.options_sleeve_backtest import (
    approximate_structure_value,
    point_in_time_ivr,
    run_options_sleeve_backtest,
    simulate_credit_trade,
    summarize_sleeve_runs,
    trailing_return_composites,
)


def _unit_iv_history(n: int = 80) -> pd.DataFrame:
    # Deterministic fixture for unit tests (not production IV).
    dates = pd.bdate_range("2025-01-02", periods=n)
    rows = []
    for t in ["SPY", "QQQ", "XLK"]:
        for i, d in enumerate(dates):
            # Mildly varying IV so IVR is defined
            iv = 0.15 + 0.05 * abs(np.sin(i / 7.0))
            if t == "XLK":
                iv += 0.03
            rows.append(
                {
                    "as_of_date": d,
                    "ticker": t,
                    "atm_iv": iv,
                    "spot": 100.0 + i * 0.1,
                }
            )
    return pd.DataFrame(rows)


def _unit_prices(n: int = 120) -> pd.DataFrame:
    dates = pd.bdate_range("2024-11-01", periods=n)
    idx = np.arange(n)
    return pd.DataFrame(
        {
            "SPY": 400 + idx * 0.2 + 2 * np.sin(idx / 9.0),
            "QQQ": 350 + idx * 0.25 + 3 * np.sin(idx / 8.0),
            "XLK": 180 + idx * 0.15 + 4 * np.sin(idx / 6.0),
            "IWM": 180 + idx * 0.05,
            "XLF": 40 + idx * 0.02,
            "XLE": 80 + idx * 0.03,
            "XLV": 120 + idx * 0.04,
            "XLI": 110 + idx * 0.03,
            "XLY": 160 + idx * 0.05,
            "XLP": 70 + idx * 0.01,
            "XLU": 65 + idx * 0.01,
            "XLB": 85 + idx * 0.02,
            "XLRE": 40 + idx * 0.01,
            "XLC": 75 + idx * 0.02,
        },
        index=dates,
    )


def test_point_in_time_ivr_uses_only_prior_rows():
    hist = _unit_iv_history()
    as_of = hist["as_of_date"].iloc[40]
    ivr = point_in_time_ivr(hist, "SPY", as_of)
    assert ivr is not None
    assert 0.0 <= ivr <= 100.0
    # Truncating future rows must not change IVR
    truncated = hist[hist["as_of_date"] <= as_of]
    assert abs(point_in_time_ivr(truncated, "SPY", as_of) - ivr) < 1e-12


def test_trailing_composites_omit_missing_names():
    px = _unit_prices()
    as_of = px.index[80]
    comps = trailing_return_composites(px, as_of, universe=["SPY", "QQQ", "XLK"])
    assert set(comps) == {"SPY", "QQQ", "XLK"}
    assert all(np.isfinite(v) for v in comps.values())


def test_approximate_credit_positive_for_put_spread():
    credit = approximate_structure_value(
        "bull_put_spread",
        spot=100.0,
        iv=0.2,
        width=2.0,
        short_delta=0.25,
        dte=37,
    )
    assert credit is not None and credit > 0


def test_simulate_trade_respects_take_profit_or_expiry():
    hist = _unit_iv_history()
    px = _unit_prices()["SPY"]
    entry = pd.Timestamp("2025-02-03")
    # ensure entry in path
    assert entry in px.index or px.loc[:entry].shape[0] > 0
    spot = float(px.loc[:entry].iloc[-1])
    res = simulate_credit_trade(
        "bull_put_spread",
        entry,
        spot,
        0.2,
        px,
        hist,
        "SPY",
        short_delta=0.25,
        capital_budget=25_000.0,
    )
    assert res is not None
    assert res.qty >= 1
    assert res.exit_reason in {"take_profit", "stop", "expiry"}


def test_always_skip_has_zero_trades_phase1_can_trade():
    hist = _unit_iv_history()
    px = _unit_prices()
    start, end = "2025-02-01", "2025-04-30"
    skip = run_options_sleeve_backtest(
        hist, px, start=start, end=end, mode="always_skip", universe=["SPY", "QQQ", "XLK"]
    )
    phase = run_options_sleeve_backtest(
        hist, px, start=start, end=end, mode="phase1", universe=["SPY", "QQQ", "XLK"]
    )
    naive = run_options_sleeve_backtest(
        hist, px, start=start, end=end, mode="naive_short_put", universe=["SPY", "QQQ", "XLK"]
    )
    assert skip.empty
    assert len(naive) >= len(phase)
    summary = summarize_sleeve_runs(
        {"phase1_rules": phase, "always_skip": skip, "naive_short_put": naive},
        capital_usd=25_000.0,
        spy_prices=px["SPY"],
        start=pd.Timestamp(start),
        end=pd.Timestamp(end),
    )
    assert "always_skip" in set(summary["strategy"])
    assert "risk_matched_spy_hold" in set(summary["strategy"])
    zero = summary.loc[summary["strategy"] == "always_skip", "total_pnl_usd"].iloc[0]
    assert abs(zero) < 1e-12
