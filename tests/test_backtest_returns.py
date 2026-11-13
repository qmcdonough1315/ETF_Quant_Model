"""Unit tests for weighted vs equal-weight period returns and cost hook."""

from __future__ import annotations

import pandas as pd

from modules.backtest_returns import (
    equity_rebalance_cost,
    net_period_return,
    one_way_turnover,
    portfolio_period_return,
)


def test_weighted_return_differs_from_equal_weight_mean():
    # Two months, two names: A flat then +10%, B +10% then flat → both compound +10%.
    # Unequal weights must still differ once compounded paths diverge.
    period = pd.DataFrame(
        {
            "AAA": [0.00, 0.20],  # compound 20%
            "BBB": [0.10, 0.00],  # compound 10%
        }
    )
    weights = pd.Series({"AAA": 0.8, "BBB": 0.2})
    weighted = portfolio_period_return(period, weights, equal_weight=False)
    equal = portfolio_period_return(period, weights, equal_weight=True)
    assert abs(weighted - (0.8 * 0.20 + 0.2 * 0.10)) < 1e-12
    assert abs(equal - 0.15) < 1e-12
    assert abs(weighted - equal) > 1e-9


def test_equal_weight_flag_ignores_production_weights():
    period = pd.DataFrame({"AAA": [0.1], "BBB": [-0.1]})
    weights = {"AAA": 0.99, "BBB": 0.01}
    assert abs(portfolio_period_return(period, weights, equal_weight=True) - 0.0) < 1e-12


def test_turnover_and_cost_from_cash():
    w = {"AAA": 0.6, "BBB": 0.4}
    # From cash: one-way turnover = 0.5; traded fraction = 1.0
    assert abs(one_way_turnover(w, None) - 0.5) < 1e-12
    assert abs(equity_rebalance_cost(w, None, one_way_bps=10.0) - 0.001) < 1e-12


def test_net_period_return_subtracts_cost():
    w_new = {"AAA": 1.0}
    net, cost, turn = net_period_return(0.05, w_new, None, one_way_bps=10.0)
    assert abs(cost - 0.001) < 1e-12
    assert abs(net - 0.049) < 1e-12
    assert abs(turn - 0.5) < 1e-12
