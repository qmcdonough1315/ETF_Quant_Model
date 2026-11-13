"""Wave E: IVR fail-closed, liquidity caps, ex-div / pin guards."""

from __future__ import annotations

from datetime import date, datetime, timezone

from modules.options_liquidity import cap_contracts, check_leg_liquidity, liquidity_limits
from modules.options_orders import (
    OptionContractQuote,
    ex_div_blocks_short_calls,
    propose_defined_risk_trade,
)
from modules.options_sleeve import build_signal


def test_missing_ivr_fail_closed():
    sig = build_signal("SPY", 1.0, None, kill_switch_active=False)
    assert sig.structure == "skip_missing_iv"
    assert sig.regime == "missing_iv"


def test_nan_ivr_fail_closed():
    sig = build_signal("QQQ", 0.0, float("nan"), kill_switch_active=False)
    assert sig.structure == "skip_missing_iv"


def test_low_ivr_stands_aside_not_long_vol():
    sig = build_signal("SPY", 1.2, 20.0, kill_switch_active=False)
    assert sig.structure == "skip_low_iv"
    assert "stand aside" in sig.rationale.lower() or "cheap" in sig.rationale.lower()


def test_index_liquidity_looser_than_xlre():
    spy = liquidity_limits("SPY")
    xlre = liquidity_limits("XLRE")
    assert spy["max_contracts"] > xlre["max_contracts"]
    assert spy["max_spread_width"] < xlre["max_spread_width"]


def test_wide_spread_skips():
    reason = check_leg_liquidity(
        ticker="SPY",
        bid=1.0,
        ask=1.50,  # 0.50 wide > SPY max 0.15
        open_interest=10_000,
    )
    assert reason is not None
    assert "bid-ask" in reason.lower() or "width" in reason.lower()


def test_cap_contracts_respects_ticker():
    assert cap_contracts("XLRE", 10) <= 2
    assert cap_contracts("SPY", 10) == 10


def test_ex_div_blocks_short_calls_only():
    as_of = date(2026, 11, 10)
    ex = date(2026, 11, 14)
    assert ex_div_blocks_short_calls("bear_call_spread", next_ex_div=ex, as_of_day=as_of)
    assert ex_div_blocks_short_calls("iron_condor", next_ex_div=ex, as_of_day=as_of)
    assert ex_div_blocks_short_calls("bull_put_spread", next_ex_div=ex, as_of_day=as_of) is None


def _chain(underlying: str = "SPY", *, wide: bool = False, oi: float = 1000) -> list[OptionContractQuote]:
    # ~37 DTE from fixed as_of 2026-11-13 → expiry 2026-12-18
    spread = 0.50 if wide else 0.05
    spot_ref = 500.0
    legs = []
    # puts OTM
    for strike, mid, typ in [
        (480.0, 2.0, "put"),
        (475.0, 1.0, "put"),
        (520.0, 2.0, "call"),
        (525.0, 1.0, "call"),
    ]:
        bid = mid - spread / 2
        ask = mid + spread / 2
        legs.append(
            OptionContractQuote(
                symbol=f"{underlying}{strike}{typ[0].upper()}",
                underlying=underlying,
                expiration_date="2026-12-18",
                strike_price=strike,
                type=typ,  # type: ignore[arg-type]
                mid=mid,
                bid=bid,
                ask=ask,
                delta=-0.25 if typ == "put" else 0.25,
                open_interest=oi,
                tradable=True,
            )
        )
    return legs


def test_propose_skips_missing_ivr():
    as_of = datetime(2026, 11, 13, tzinfo=timezone.utc)
    out = propose_defined_risk_trade(
        "SPY",
        1.0,
        None,
        500.0,
        _chain(),
        as_of=as_of,
        kill_switch_active=False,
    )
    assert out.structure == "skip_missing_iv"


def test_propose_skips_wide_liquidity():
    as_of = datetime(2026, 11, 13, tzinfo=timezone.utc)
    out = propose_defined_risk_trade(
        "SPY",
        1.0,
        55.0,
        500.0,
        _chain(wide=True),
        as_of=as_of,
        kill_switch_active=False,
    )
    from modules.options_orders import TradeProposalSkip

    assert isinstance(out, TradeProposalSkip)
    assert "width" in out.reason.lower() or "bid-ask" in out.reason.lower()


def test_propose_skips_ex_div_for_bear_call():
    as_of = datetime(2026, 11, 13, tzinfo=timezone.utc)
    # Weak composite → bear call; ex-div in 3 days
    out = propose_defined_risk_trade(
        "SPY",
        -1.0,
        60.0,
        500.0,
        _chain(),
        as_of=as_of,
        next_ex_div=date(2026, 11, 16),
        kill_switch_active=False,
    )
    from modules.options_orders import TradeProposalSkip

    assert isinstance(out, TradeProposalSkip)
    assert "ex-div" in out.reason.lower()
