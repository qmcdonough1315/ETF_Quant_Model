"""Unit tests for DCA ladder sizing, HIFO ordering, and options signals (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from modules.options_sleeve import build_signal, classify_regime, size_spread_contracts


def test_weekly_contribution_is_fifty_k_over_thirteen():
    assert config.DCA_WEEKS == 13
    assert config.ETF_TARGET_CAPITAL_USD == 50_000.0
    assert abs(config.WEEKLY_CONTRIBUTION_USD - (50_000.0 / 13.0)) < 1e-9


def _sort_lots_least_gain_first(lots, price_by_ticker):
    """Mirror of modules.paper_portfolio._sort_lots_least_gain_first (pure)."""

    def key(lot):
        px = price_by_ticker[lot["ticker"]]
        pnl = lot["shares"] * px - lot["shares"] * lot["cost_per_share"]
        return (pnl, -lot["cost_per_share"], lot["opened_on"], lot["id"])

    return sorted(lots, key=key)


def test_hifo_sells_high_basis_before_low_basis_winner():
    """User example: week-1 QQQ @100 vs week-12 QQQ @200 → sell $200 lot first."""
    low = {
        "id": "w1",
        "ticker": "QQQ",
        "shares": 10,
        "cost_per_share": 100.0,
        "opened_on": "2026-09-21",
    }
    high = {
        "id": "w12",
        "ticker": "QQQ",
        "shares": 10,
        "cost_per_share": 200.0,
        "opened_on": "2026-12-07",
    }
    ordered = _sort_lots_least_gain_first([low, high], {"QQQ": 220.0})
    assert ordered[0] is high
    assert ordered[1] is low


def test_deepest_loss_sorts_first():
    loser = {
        "id": "a",
        "ticker": "XLK",
        "shares": 5,
        "cost_per_share": 100.0,
        "opened_on": "2026-01-01",
    }
    mild = {
        "id": "b",
        "ticker": "XLK",
        "shares": 5,
        "cost_per_share": 90.0,
        "opened_on": "2026-01-08",
    }
    ordered = _sort_lots_least_gain_first([mild, loser], {"XLK": 80.0})
    assert ordered[0] is loser


def test_options_regime_map():
    assert classify_regime(0.9, 55) == "q1_bullish_vol_seller"
    assert classify_regime(-0.8, 55) == "q2_bearish_vol_seller"
    assert classify_regime(0.0, 55) == "q3_neutral_vol"
    assert classify_regime(0.9, 20) == "q4_low_iv"
    signal = build_signal("SPY", 0.9, 55)
    assert signal.structure == "bull_put_spread"
    assert size_spread_contracts(1.0, 5.0, 2000) == 5


if __name__ == "__main__":
    test_weekly_contribution_is_fifty_k_over_thirteen()
    test_hifo_sells_high_basis_before_low_basis_winner()
    test_deepest_loss_sorts_first()
    test_options_regime_map()
    print("ok")
