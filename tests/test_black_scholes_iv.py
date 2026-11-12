import math

from modules.black_scholes_iv import black_scholes_price, implied_volatility, mid_price
from modules.options_composite import normalize_phase1_composites
from modules.iv_rank import iv_rank_from_series
import pandas as pd


def test_iv_round_trip_call():
    spot, strike, t, rate, vol = 100.0, 100.0, 30 / 365.0, 0.0, 0.25
    px = black_scholes_price(spot, strike, t, rate, vol, "call")
    recovered = implied_volatility(px, spot, strike, t, "call", rate=rate)
    assert recovered is not None
    assert abs(recovered - vol) < 1e-4


def test_iv_round_trip_put():
    spot, strike, t, rate, vol = 100.0, 100.0, 30 / 365.0, 0.01, 0.18
    px = black_scholes_price(spot, strike, t, rate, vol, "put")
    recovered = implied_volatility(px, spot, strike, t, "put", rate=rate)
    assert recovered is not None
    assert abs(recovered - vol) < 1e-4


def test_mid_prefers_bid_ask():
    assert mid_price(1.0, 1.2, 9.0) == 1.1
    assert mid_price(None, None, 2.5) == 2.5


def test_iv_rank_basic():
    s = pd.Series([0.10, 0.20, 0.30])
    assert abs(iv_rank_from_series(s, current_iv=0.20) - 50.0) < 1e-9


def test_normalize_phase1_composites_zscore():
    raw = {"SPY": 0.10, "QQQ": 0.20, "IWM": 0.00, "XLK": 0.15}
    # Restrict universe to these four for a deterministic test.
    out = normalize_phase1_composites(raw, universe=list(raw.keys()))
    assert set(out) == set(raw)
    mean = sum(out.values()) / len(out)
    assert abs(mean) < 1e-9
    assert out["QQQ"] > out["IWM"]


def test_normalize_requires_cross_section():
    assert normalize_phase1_composites({"SPY": 0.1}, universe=["SPY"]) == {}
