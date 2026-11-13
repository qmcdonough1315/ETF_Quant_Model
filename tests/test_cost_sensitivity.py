"""Cost ladder + equity rebalance cost application (#4)."""

from __future__ import annotations

import pandas as pd

from modules.backtest_returns import apply_cost_ladder, cost_from_turnover, net_period_return


def test_cost_from_turnover_scales_with_bps():
    # one-way turnover 0.5 → traded fraction 1.0 → 10 bps = 0.001
    assert abs(cost_from_turnover(0.5, 10.0) - 0.001) < 1e-12
    assert abs(cost_from_turnover(0.5, 5.0) - 0.0005) < 1e-12
    assert abs(cost_from_turnover(0.5, 0.0) - 0.0) < 1e-12


def test_apply_cost_ladder_monotonic_in_bps():
    gross = pd.Series([0.05, 0.02, -0.01])
    turn = pd.Series([0.5, 0.2, 0.3])
    ladder = apply_cost_ladder(gross, turn, (0.0, 5.0, 10.0), initial_capital=10_000.0)
    assert list(ladder["cost_bps_one_way"]) == [0.0, 5.0, 10.0]
    # Higher costs → lower final value / Sharpe for this path
    assert ladder.loc[0, "final_value"] > ladder.loc[1, "final_value"] > ladder.loc[2, "final_value"]
    assert ladder.loc[0, "total_costs"] < ladder.loc[1, "total_costs"] < ladder.loc[2, "total_costs"]
    assert ladder.loc[0, "total_return"] > ladder.loc[2, "total_return"]


def test_net_period_matches_ladder_row():
    w_new = {"AAA": 1.0}
    net, cost, turn = net_period_return(0.04, w_new, None, one_way_bps=5.0)
    ladder = apply_cost_ladder(
        pd.Series([0.04]), pd.Series([turn]), (5.0,), initial_capital=1.0
    )
    assert abs(ladder.loc[0, "total_costs"] - cost) < 1e-12
    assert abs((1 + net) - ladder.loc[0, "final_value"]) < 1e-12
