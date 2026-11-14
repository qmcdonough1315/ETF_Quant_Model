"""Unit tests for walk-forward metrics and research-card blends."""

from __future__ import annotations

import math

import pandas as pd

from modules.research_card import (
    build_card_envelope,
    markdown_period_table,
    options_pnl_to_period_returns,
    render_report_markdown,
    research_assumptions,
)
from modules.walkforward_metrics import (
    blend_period_returns,
    hit_rate,
    max_drawdown_from_returns,
    summarize_period_returns,
    total_return_from_path,
)


def test_max_drawdown_and_total_return():
    rets = [0.10, -0.20, 0.05]
    assert abs(total_return_from_path(rets) - ((1.1 * 0.8 * 1.05) - 1)) < 1e-12
    # Peak at 1.1, trough at 1.1*0.8=0.88 → DD = 0.88/1.1 - 1 = -0.2
    assert abs(max_drawdown_from_returns(rets) - (-0.20)) < 1e-12


def test_hit_rate_and_summary():
    s = pd.Series([0.05, -0.02, 0.04])
    b = pd.Series([0.01, 0.00, 0.03])
    # Wins periods 0 and 2 → 2/3
    assert abs(hit_rate(s, b) - (2 / 3)) < 1e-12
    summary = summarize_period_returns(
        s,
        initial_capital=50_000,
        risk_free_rate=0.0,
        periods_per_year=4.0,
        benchmark_returns=b,
    )
    assert summary["n_periods"] == 3
    assert summary["hit_rate_vs_benchmark"] == hit_rate(s, b)
    assert math.isfinite(summary["sharpe"])


def test_blend_50_50():
    left = pd.Series([0.10, 0.00], index=["a", "b"])
    right = pd.Series([0.00, 0.10], index=["a", "b"])
    out = blend_period_returns(left, right, left_weight=0.5, right_weight=0.5)
    assert abs(out.loc["a"] - 0.05) < 1e-12
    assert abs(out.loc["b"] - 0.05) < 1e-12


def test_options_pnl_binning_by_exit():
    trades = pd.DataFrame(
        {
            "exit_date": ["2020-03-15", "2020-06-20", "2020-09-10"],
            "pnl_usd": [1000.0, -500.0, 250.0],
        }
    )
    reb = ["2020-01", "2020-04", "2020-07"]
    windows = [("2020-02", "2020-04"), ("2020-05", "2020-07"), ("2020-08", "2020-10")]
    rets = options_pnl_to_period_returns(
        trades, reb, windows, options_book_usd=50_000.0
    )
    assert abs(rets.iloc[0] - 1000 / 50_000) < 1e-12
    assert abs(rets.iloc[1] - (-500 / 50_000)) < 1e-12
    assert abs(rets.iloc[2] - 250 / 50_000) < 1e-12


def test_write_json_rejects_bare_nan(tmp_path):
    import json
    from modules.research_card import write_json

    path = tmp_path / "card.json"
    write_json(path, {"hit_rate_vs_benchmark": float("nan"), "ok": 1.0})
    raw = path.read_text()
    assert "NaN" not in raw
    loaded = json.loads(raw)
    assert loaded["hit_rate_vs_benchmark"] is None
    assert loaded["ok"] == 1.0


def test_research_assumptions_50_50_and_report_renders():
    a = research_assumptions(cost_bps_one_way=5.0)
    assert a["total_capital_usd"] == 100_000.0
    assert a["etf_weight"] == 0.5
    assert a["options_weight"] == 0.5
    assert a["options_book_includes_cash_reserve"] is True
    assert a["headline_peer"] == "VOO_JEPI_50_50"

    card = build_card_envelope(
        [
            {
                "period_id": "COVID",
                "label": "Crash + rebound",
                "start": "2020-01-31",
                "end": "2020-12-31",
                "coverage": 0.9,
                "etf": {"total_return": 0.1, "sharpe": 0.5, "avg_turnover": 0.2},
                "options": {"status": "uncovered", "total_return": 0.0, "n_trades": 0},
                "combined": {
                    "total_return": 0.05,
                    "sharpe": 0.4,
                    "max_drawdown": -0.1,
                    "hit_rate_vs_benchmark": 0.5,
                    "excess_total_vs_benchmark": 0.01,
                },
                "benchmarks": {
                    "VOO_JEPI_50_50": {"total_return": 0.04, "sharpe": 0.3},
                    "VOO": {"total_return": 0.03, "sharpe": 0.25},
                },
            }
        ],
        assumptions=a,
    )
    md = render_report_markdown(card)
    assert "50/50" in md or "50/" in md
    assert "VOO_JEPI_50_50" in md
    assert "COVID" in markdown_period_table(card)
