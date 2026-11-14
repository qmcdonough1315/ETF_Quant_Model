"""OOS predict-index selection and Ken French point-in-time lag."""

from __future__ import annotations

import pandas as pd
import pytest

import config
from modules.point_in_time import ken_french_asof
from modules.factor_forecaster import (
    build_factor_features,
    build_factor_targets,
    create_factor_features_and_targets,
    select_train_predict_indices,
)


def _synthetic_factor_macro(n_months: int = 24):
    idx = pd.period_range("2018-01", periods=n_months, freq="M")
    factors = pd.DataFrame(
        {col: 0.01 + 0.001 * (i % 5) for i, col in enumerate(config.TARGET_FACTORS)},
        index=idx,
    )
    # Slight time variation so rows are not identical
    for j, col in enumerate(config.TARGET_FACTORS):
        factors[col] = factors[col] + 0.0001 * pd.Series(range(n_months), index=idx)

    macro_cols = [
        "cpi_inflation",
        "yield_curve_slope",
        "wti_oil",
        "usd_index",
        "vix",
        "credit_spread",
        "money_supply_m2",
        "industrial_prod",
    ]
    macro = pd.DataFrame(
        {c: 0.1 + 0.01 * (k % 3) for k, c in enumerate(macro_cols)},
        index=idx,
    )
    return factors, macro


def test_targets_have_trailing_nans_for_horizon():
    factors, _macro = _synthetic_factor_macro(18)
    horizon = config.FORECAST_HORIZON_MONTHS
    Y = build_factor_targets(factors, horizon=horizon)
    # Last `horizon` rows cannot observe the full forward window
    assert Y.iloc[-horizon:].isna().all().all()
    assert Y.iloc[: -horizon].notna().all().all()


def test_select_predict_index_is_decision_date_not_in_train():
    factors, macro = _synthetic_factor_macro(30)
    X, Y = create_factor_features_and_targets(factors, macro)
    train_index, pred_idx = select_train_predict_indices(X, Y)

    assert pred_idx not in train_index
    assert X.loc[pred_idx].notna().all()
    assert Y.loc[pred_idx].isna().any()
    # Decision row should be the latest feature-complete month (end of sample)
    feature_ok = X.notna().all(axis=1)
    assert pred_idx == X.index[feature_ok][-1]
    # Train end is ~horizon months before predict
    assert train_index[-1] < pred_idx


def test_holdout_when_all_targets_complete():
    """If Y is already complete for every feature row, hold out the last row."""
    idx = pd.period_range("2020-01", periods=10, freq="M")
    X = pd.DataFrame({"a": range(10)}, index=idx, dtype=float)
    Y = pd.DataFrame({"y": range(10)}, index=idx, dtype=float)
    train_index, pred_idx = select_train_predict_indices(X, Y)
    assert pred_idx == idx[-1]
    assert list(train_index) == list(idx[:-1])
    assert pred_idx not in train_index


def test_ken_french_asof_drops_decision_month():
    idx = pd.period_range("2020-01", periods=6, freq="M")
    factors = pd.DataFrame({"Mkt_RF": range(6)}, index=idx)
    asof = pd.Period("2020-04", freq="M")
    pit = ken_french_asof(factors, asof, lag_months=1)
    assert pit.index.max() == pd.Period("2020-03", freq="M")
    assert asof not in pit.index
    assert len(pit) == 3


def test_ken_french_asof_respects_config_default():
    idx = pd.period_range("2021-01", periods=4, freq="M")
    factors = pd.DataFrame({"Mkt_RF": [0.01, 0.02, 0.03, 0.04]}, index=idx)
    pit = ken_french_asof(factors, factors.index.max())
    expected = factors.index.max() - int(config.KEN_FRENCH_PUBLICATION_LAG_MONTHS)
    assert pit.index.max() == expected


def test_features_do_not_use_same_month_factor_levels():
    factors, macro = _synthetic_factor_macro(12)
    X = build_factor_features(factors, macro, lookback_lags=3)
    # First usable rows still NaN from lag/roll; first complete row uses only lagged info
    complete = X.dropna()
    assert not complete.empty
    first = complete.index[0]
    # lag1 for Mkt_RF equals prior month factor, not contemporaneous
    assert X.loc[first, "Mkt_RF_lag1"] == pytest.approx(float(factors.loc[first - 1, "Mkt_RF"]))
