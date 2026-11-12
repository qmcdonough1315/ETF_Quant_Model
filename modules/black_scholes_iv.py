"""
Black–Scholes implied volatility from option mid prices.

Used to bootstrap IV Rank from ThetaData free-tier EOD quotes (raw prices only).
"""

from __future__ import annotations

import math
from typing import Literal, Optional

Right = Literal["call", "put", "C", "P", "CALL", "PUT"]


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def black_scholes_price(
    spot: float,
    strike: float,
    time_years: float,
    rate: float,
    vol: float,
    right: Right,
) -> float:
    if spot <= 0 or strike <= 0 or time_years <= 0 or vol <= 0:
        return float("nan")
    sqrt_t = math.sqrt(time_years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * time_years) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    r = str(right).upper()
    if r in {"C", "CALL"}:
        return spot * _norm_cdf(d1) - strike * math.exp(-rate * time_years) * _norm_cdf(d2)
    if r in {"P", "PUT"}:
        return strike * math.exp(-rate * time_years) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
    return float("nan")


def implied_volatility(
    price: float,
    spot: float,
    strike: float,
    time_years: float,
    right: Right,
    rate: float = 0.0,
    *,
    initial_vol: float = 0.2,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> Optional[float]:
    """
    Newton–Raphson IV; falls back to bisection if vega is tiny.
    Returns annualized vol (e.g. 0.18 = 18%), or None if unsolvable.
    """
    if not (
        price > 0
        and spot > 0
        and strike > 0
        and time_years > 0
        and math.isfinite(price)
        and math.isfinite(spot)
        and math.isfinite(strike)
    ):
        return None

    # Intrinsic floor — mid below intrinsic is not invertible under BS.
    r = str(right).upper()
    discounted_k = strike * math.exp(-rate * time_years)
    intrinsic = max(spot - discounted_k, 0.0) if r in {"C", "CALL"} else max(discounted_k - spot, 0.0)
    if price < intrinsic * 0.999:
        return None

    vol = max(initial_vol, 1e-4)
    for _ in range(max_iter):
        model = black_scholes_price(spot, strike, time_years, rate, vol, right)
        if not math.isfinite(model):
            break
        diff = model - price
        if abs(diff) < tol:
            return float(vol)
        sqrt_t = math.sqrt(time_years)
        d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * time_years) / (vol * sqrt_t)
        vega = spot * _norm_pdf(d1) * sqrt_t
        if vega < 1e-12:
            break
        vol = max(vol - diff / vega, 1e-6)
        if vol > 5.0:
            vol = 5.0

    # Bisection fallback
    lo, hi = 1e-6, 5.0
    flo = black_scholes_price(spot, strike, time_years, rate, lo, right) - price
    fhi = black_scholes_price(spot, strike, time_years, rate, hi, right) - price
    if not (math.isfinite(flo) and math.isfinite(fhi)) or flo * fhi > 0:
        return None
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        fmid = black_scholes_price(spot, strike, time_years, rate, mid, right) - price
        if abs(fmid) < tol:
            return float(mid)
        if flo * fmid <= 0:
            hi, fhi = mid, fmid
        else:
            lo, flo = mid, fmid
    return float(0.5 * (lo + hi))


def mid_price(bid: Optional[float], ask: Optional[float], close: Optional[float] = None) -> Optional[float]:
    if bid is not None and ask is not None and bid > 0 and ask > 0 and ask >= bid:
        return 0.5 * (float(bid) + float(ask))
    if close is not None and close > 0:
        return float(close)
    if bid is not None and bid > 0:
        return float(bid)
    if ask is not None and ask > 0:
        return float(ask)
    return None
