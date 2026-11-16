"""Unit tests for live-run realism diagnostics (no network)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import config
from modules.realism_diagnostics import (
    annualized_sharpe_equivalent,
    compounded_horizon_returns,
    empirical_percentile,
    evaluate_factor_forecasts,
    evaluate_portfolio,
    format_realism_report,
    run_realism_diagnostics,
)


def test_compounded_horizon_returns_matches_manual():
    idx = pd.period_range("2020-01", periods=6, freq="M")
    s = pd.Series([0.01, 0.02, -0.01, 0.03, 0.00, 0.01], index=idx)
    out = compounded_horizon_returns(s, 3)
    assert len(out) == 4
    manual = (1.01 * 1.02 * 0.99) - 1.0
    assert float(out.iloc[0]) == pytest.approx(manual)


def test_empirical_percentile_ends():
    hist = pd.Series(np.linspace(-0.1, 0.1, 21))
    assert empirical_percentile(hist, -0.1) == pytest.approx(1.0 / 21.0)
    assert empirical_percentile(hist, 0.1) == pytest.approx(1.0)
    assert empirical_percentile(hist, 0.0) == pytest.approx(11.0 / 21.0)


def test_annualized_sharpe_scales_horizon_ratio():
    # 3M ret 6%, vol 3% → horizon Sharpe 2; ann equiv should be higher.
    ann = annualized_sharpe_equivalent(0.06, 0.03, horizon_months=3, risk_free_annual=0.0)
    assert ann == pytest.approx(2.0 * np.sqrt(4.0))


def test_factor_forecast_tail_flag():
    idx = pd.period_range("2000-01", periods=120, freq="M")
    # Quiet history around 0; extreme forecast should land in the tail.
    factors = pd.DataFrame(
        {f: np.random.default_rng(0).normal(0.0, 0.01, size=len(idx)) for f in config.TARGET_FACTORS},
        index=idx,
    )
    preds = {f: 0.0 for f in config.TARGET_FACTORS}
    preds["Mkt_RF"] = 0.25  # absurd 3M market excess
    flags = evaluate_factor_forecasts(preds, factors, horizon=3)
    tails = [f for f in flags if f.code.startswith("factor_forecast_tail:Mkt_RF")]
    assert tails and tails[0].severity == "warn"


def test_portfolio_extreme_gates_fail():
    holdings = pd.DataFrame(
        {
            "Ticker": ["AAA", "BBB"],
            "Total_Expected_Return_3M": [0.20, 0.18],
            "Volatility": [0.10, 0.10],
            "Target_Weight": [0.5, 0.5],
        }
    )
    prices = pd.DataFrame(
        {
            "AAA": np.random.default_rng(1).normal(0.01, 0.04, size=60),
            "BBB": np.random.default_rng(2).normal(0.01, 0.04, size=60),
            "SPY": np.random.default_rng(3).normal(0.008, 0.04, size=60),
        },
        index=pd.period_range("2018-01", periods=60, freq="M"),
    )
    flags, meta = evaluate_portfolio(
        holdings,
        prices,
        port_return=0.19,
        port_vol=0.05,
        port_sharpe=3.8,
    )
    codes = {f.code for f in flags}
    assert "portfolio_expected_extreme" in codes
    assert "horizon_sharpe_high" in codes
    assert "annualized_sharpe_high" in codes
    assert meta["annualized_sharpe_equivalent"] > 2.0


def test_run_and_format_report_smoke():
    idx = pd.period_range("2015-01", periods=100, freq="M")
    rng = np.random.default_rng(4)
    factors = pd.DataFrame(
        {f: rng.normal(0.0, 0.02, size=len(idx)) for f in config.TARGET_FACTORS},
        index=idx,
    )
    # Include RF for completeness (unused by realism factor hist).
    factors["RF"] = 0.002
    prices = pd.DataFrame(
        {
            "SPY": rng.normal(0.008, 0.04, size=len(idx)),
            "AAA": rng.normal(0.01, 0.05, size=len(idx)),
        },
        index=idx,
    )
    # Minimal beta profile path: build a tiny fake state history.
    beta_profiles = {
        "AAA": pd.DataFrame(
            {
                "alpha": [0.001] * 5,
                "beta_mkt": [1.2] * 5,
                "beta_smb": [0.2] * 5,
                "beta_hml": [-1.0] * 5,
                "beta_rmw": [-0.5] * 5,
                "beta_cma": [-0.8] * 5,
                "beta_wml": [0.1] * 5,
            },
            index=idx[-5:],
        )
    }
    holdings = pd.DataFrame(
        {
            "Ticker": ["AAA"],
            "Total_Expected_Return_3M": [0.16],
            "Volatility": [0.08],
            "Target_Weight": [1.0],
        }
    )
    scores = holdings.copy()
    scores = pd.concat(
        [
            scores,
            pd.DataFrame(
                {
                    "Ticker": ["SPY"],
                    "Total_Expected_Return_3M": [0.04],
                    "Volatility": [0.07],
                    "Target_Weight": [0.0],
                }
            ),
        ],
        ignore_index=True,
    )
    preds = {
        "Mkt_RF": 0.05,
        "SMB": 0.01,
        "HML": -0.06,
        "RMW": -0.02,
        "CMA": -0.03,
        "WML": 0.01,
    }
    report = run_realism_diagnostics(
        predictions=preds,
        factors=factors,
        holdings=holdings,
        scores_df=scores,
        beta_profiles=beta_profiles,
        prices=prices,
        port_return=0.16,
        port_vol=0.05,
        port_sharpe=3.2,
    )
    assert report["severity"] in {"warn", "fail"}
    text = format_realism_report(report)
    assert "MODEL REALISM DIAGNOSTICS" in text
    assert "FAIL" in text or "WARN" in text
