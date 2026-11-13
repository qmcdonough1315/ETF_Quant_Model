"""Per-ticker liquidity / capacity filters for Phase 1 options proposals (#12)."""

from __future__ import annotations

from typing import Any, Mapping, Optional

import config
from modules.options_sleeve import PHASE1_OPTIONABLE_ETFS


INDEX_NAMES = frozenset({"SPY", "QQQ", "IWM"})


def liquidity_limits(ticker: str) -> dict[str, float]:
    t = ticker.upper()
    by = dict(getattr(config, "OPTIONS_LIQUIDITY_BY_TICKER", {}) or {})
    if t in by:
        base = dict(by[t])
    elif t in INDEX_NAMES:
        base = dict(getattr(config, "OPTIONS_LIQUIDITY_INDEX_DEFAULTS", {}))
    else:
        base = dict(getattr(config, "OPTIONS_LIQUIDITY_SECTOR_DEFAULTS", {}))
    return {
        "max_contracts": float(base.get("max_contracts", 3)),
        "max_spread_width": float(base.get("max_spread_width", 0.35)),
        "min_open_interest": float(base.get("min_open_interest", 0)),
    }


def mid_spread_width(bid: Optional[float], ask: Optional[float], mid: Optional[float] = None) -> Optional[float]:
    if bid is not None and ask is not None and ask >= bid and bid >= 0:
        return float(ask - bid)
    return None


def check_leg_liquidity(
    *,
    ticker: str,
    bid: Optional[float],
    ask: Optional[float],
    open_interest: Optional[float] = None,
    limits: Optional[Mapping[str, float]] = None,
) -> Optional[str]:
    """Return skip reason if liquidity fails, else None."""
    lim = dict(limits) if limits is not None else liquidity_limits(ticker)
    width = mid_spread_width(bid, ask)
    max_w = float(lim.get("max_spread_width", 0.35))
    if width is not None and width > max_w + 1e-12:
        return f"Leg bid-ask width {width:.2f} > max {max_w:.2f} for {ticker.upper()}."
    min_oi = float(lim.get("min_open_interest", 0))
    if min_oi > 0 and open_interest is not None and float(open_interest) < min_oi:
        return (
            f"Open interest {int(open_interest)} < min {int(min_oi)} for {ticker.upper()}."
        )
    return None


def cap_contracts(ticker: str, qty: int) -> int:
    lim = liquidity_limits(ticker)
    return max(0, min(int(qty), int(lim["max_contracts"])))


def phase1_liquidity_table() -> list[dict[str, Any]]:
    rows = []
    for t in PHASE1_OPTIONABLE_ETFS:
        lim = liquidity_limits(t)
        rows.append({"ticker": t, **lim})
    return rows
