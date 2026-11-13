"""Options mid→limit / bid-ask conservatism (#4)."""

from __future__ import annotations

from modules.options_orders import (
    OptionContractQuote,
    OrderLegSpec,
    credit_limit_price,
    estimate_package_credit,
    leg_conservative_price,
)


def _quote(sym: str, *, bid: float, ask: float) -> OptionContractQuote:
    mid = 0.5 * (bid + ask)
    return OptionContractQuote(
        symbol=sym,
        underlying="SPY",
        expiration_date="2026-12-18",
        strike_price=500.0,
        type="put",
        mid=mid,
        bid=bid,
        ask=ask,
        delta=-0.25,
        tradable=True,
    )


def test_credit_limit_softens_mid():
    # 1.00 mid credit → 0.92 limit magnitude, negative sign for Alpaca credit
    assert credit_limit_price(1.0, 0.92) == -0.92


def test_leg_conservative_uses_bid_ask():
    q = _quote("P1", bid=1.0, ask=1.2)
    assert leg_conservative_price(q, "sell") == 1.0
    assert leg_conservative_price(q, "buy") == 1.2


def test_estimate_package_credit_tighter_than_mid():
    short = _quote("SHORT", bid=2.0, ask=2.2)  # mid 2.1
    wing = _quote("LONG", bid=0.8, ask=1.0)  # mid 0.9
    legs = (
        OrderLegSpec(
            symbol="SHORT",
            side="sell",
            position_intent="sell_to_open",
            ratio_qty=1,
            strike=500.0,
            right="P",
            mid=2.1,
            delta=-0.25,
        ),
        OrderLegSpec(
            symbol="LONG",
            side="buy",
            position_intent="buy_to_open",
            ratio_qty=1,
            strike=495.0,
            right="P",
            mid=0.9,
            delta=-0.15,
        ),
    )
    by_sym = {"SHORT": short, "LONG": wing}
    mid_credit = estimate_package_credit(legs, by_sym, conservative_side=False)
    cons_credit = estimate_package_credit(legs, by_sym, conservative_side=True)
    assert mid_credit is not None and cons_credit is not None
    assert abs(mid_credit - 1.2) < 1e-9  # 2.1 - 0.9
    assert abs(cons_credit - 1.0) < 1e-9  # 2.0 - 1.0
    assert cons_credit < mid_credit
