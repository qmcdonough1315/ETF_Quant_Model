"""Unit tests for DCA ladder sizing, HIFO ordering, and options signals (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from datetime import datetime, timezone

from modules.options_orders import (
    OptionContractQuote,
    build_mleg_payload,
    credit_limit_price,
    propose_defined_risk_trade,
)
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


def _spy_chain() -> list[OptionContractQuote]:
    return [
        OptionContractQuote("SPY260417P00485000", "SPY", "2026-04-17", 485, "put", mid=3.2, delta=-0.25),
        OptionContractQuote("SPY260417P00480000", "SPY", "2026-04-17", 480, "put", mid=2.1, delta=-0.12),
        OptionContractQuote("SPY260417P00475000", "SPY", "2026-04-17", 475, "put", mid=1.4, delta=-0.08),
        OptionContractQuote("SPY260417C00520000", "SPY", "2026-04-17", 520, "call", mid=2.8, delta=0.25),
        OptionContractQuote("SPY260417C00525000", "SPY", "2026-04-17", 525, "call", mid=1.7, delta=0.15),
        OptionContractQuote("SPY260417C00530000", "SPY", "2026-04-17", 530, "call", mid=1.0, delta=0.10),
    ]


def test_options_order_builder():
    assert credit_limit_price(1.25) == -1.15
    as_of = datetime(2026, 3, 11, tzinfo=timezone.utc)
    bull = propose_defined_risk_trade(
        "SPY", 0.9, 55, 500.0, _spy_chain(), as_of=as_of, capital_budget_usd=2000
    )
    assert getattr(bull, "structure", None) == "bull_put_spread"
    assert bull.legs[0].side == "sell" and bull.legs[0].strike == 485
    assert bull.limit_price < 0
    payload = build_mleg_payload(bull)
    assert payload["order_class"] == "mleg"
    assert float(payload["limit_price"]) < 0

    skip = propose_defined_risk_trade(
        "QQQ",
        0.7,
        22,
        500.0,
        [OptionContractQuote(c.symbol.replace("SPY", "QQQ"), "QQQ", c.expiration_date, c.strike_price, c.type, mid=c.mid, delta=c.delta) for c in _spy_chain()],
        as_of=as_of,
    )
    assert skip.structure == "skip_low_iv"


if __name__ == "__main__":
    test_weekly_contribution_is_fifty_k_over_thirteen()
    test_hifo_sells_high_basis_before_low_basis_winner()
    test_deepest_loss_sorts_first()
    test_options_regime_map()
    test_options_order_builder()
    print("ok")
