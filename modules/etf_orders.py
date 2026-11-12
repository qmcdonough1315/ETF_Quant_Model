"""
Pure ETF DCA order construction for Alpaca paper equity buys.

Maps target weights → weekly notional buys for the $50k / 13-week ladder.
No network I/O — keep aligned with quirk_macro_web_dev/src/lib/etf-orders.ts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional
from uuid import uuid4

import config

WEEKLY_CONTRIBUTION = float(getattr(config, "WEEKLY_CONTRIBUTION_USD", 50_000.0 / 13.0))
ETF_TARGET_CAPITAL = float(getattr(config, "ETF_TARGET_CAPITAL_USD", 50_000.0))
DCA_WEEKS = int(getattr(config, "DCA_WEEKS", 13))
WEIGHT_EPS = 1e-4
# Alpaca fractional notional buys typically require >= $1.
MIN_NOTIONAL_USD = 1.0


@dataclass(frozen=True)
class EtfBuyAllocation:
    ticker: str
    weight: float  # fraction 0–1
    notional: float
    reason: str = "weekly_dca"


@dataclass(frozen=True)
class EquityBuyPayload:
    symbol: str
    notional: str
    side: str = "buy"
    type: str = "market"
    time_in_force: str = "day"

    def to_dict(self) -> dict[str, str]:
        return {
            "symbol": self.symbol,
            "notional": self.notional,
            "side": self.side,
            "type": self.type,
            "time_in_force": self.time_in_force,
        }


def normalize_weights(weights: Mapping[str, float]) -> dict[str, float]:
    """Accept fraction (sum≈1) or percent (sum≈100) maps; drop non-positive / tiny weights."""
    cleaned: dict[str, float] = {}
    for raw_ticker, raw_w in weights.items():
        ticker = str(raw_ticker).strip().upper()
        try:
            w = float(raw_w)
        except (TypeError, ValueError):
            continue
        if not ticker or w <= WEIGHT_EPS:
            continue
        cleaned[ticker] = w
    if not cleaned:
        return {}
    total = sum(cleaned.values())
    if total <= 0:
        return {}
    # Heuristic: portfolio weights stored as percent sum near 100.
    scale = 100.0 if total > 1.5 else 1.0
    out = {t: (w / scale) for t, w in cleaned.items() if (w / scale) > WEIGHT_EPS}
    renorm = sum(out.values())
    if renorm <= 0:
        return {}
    return {t: w / renorm for t, w in out.items()}


def allocate_weekly_dca(
    weights: Mapping[str, float],
    *,
    weekly_contribution: float = WEEKLY_CONTRIBUTION,
    min_notional: float = MIN_NOTIONAL_USD,
    reason: str = "weekly_dca",
) -> list[EtfBuyAllocation]:
    """
    Split weekly_contribution across normalized target weights.
    Skips legs below min_notional (remainder stays undeployed for this step).
    """
    if weekly_contribution <= 0:
        return []
    norm = normalize_weights(weights)
    buys: list[EtfBuyAllocation] = []
    for ticker, weight in sorted(norm.items(), key=lambda kv: (-kv[1], kv[0])):
        notional = round(weekly_contribution * weight, 2)
        if notional < min_notional:
            continue
        buys.append(
            EtfBuyAllocation(
                ticker=ticker,
                weight=weight,
                notional=notional,
                reason=reason,
            )
        )
    return buys


def build_equity_buy_payload(ticker: str, notional: float) -> EquityBuyPayload:
    if notional < MIN_NOTIONAL_USD:
        raise ValueError(f"notional must be >= {MIN_NOTIONAL_USD}")
    symbol = ticker.strip().upper()
    if not symbol:
        raise ValueError("ticker required")
    return EquityBuyPayload(symbol=symbol, notional=f"{float(notional):.2f}")


def propose_weekly_etf_buys(
    weights: Mapping[str, float],
    *,
    weekly_contribution: float = WEEKLY_CONTRIBUTION,
    include_voo: bool = False,
) -> dict[str, Any]:
    """Pure proposal: factor sleeve (+ optional parallel VOO sleeve)."""
    factor = allocate_weekly_dca(weights, weekly_contribution=weekly_contribution)
    factor_payloads = [
        {
            "ticker": b.ticker,
            "weight": b.weight,
            "notional": b.notional,
            "reason": b.reason,
            "order": build_equity_buy_payload(b.ticker, b.notional).to_dict(),
        }
        for b in factor
    ]
    voo: Optional[dict[str, Any]] = None
    if include_voo and weekly_contribution >= MIN_NOTIONAL_USD:
        voo = {
            "ticker": "VOO",
            "weight": 1.0,
            "notional": round(weekly_contribution, 2),
            "reason": "weekly_voo_dca",
            "order": build_equity_buy_payload("VOO", weekly_contribution).to_dict(),
        }
    deployed = sum(b["notional"] for b in factor_payloads)
    return {
        "weekly_contribution": weekly_contribution,
        "etf_target_capital": ETF_TARGET_CAPITAL,
        "dca_weeks": DCA_WEEKS,
        "buys": factor_payloads,
        "voo_buy": voo,
        "deployed_notional": round(deployed, 2),
        "undeployed_notional": round(max(0.0, weekly_contribution - deployed), 2),
    }


def lot_from_alpaca_fill(
    *,
    ticker: str,
    shares: float,
    price: float,
    filled_at: Optional[str] = None,
    order_id: Optional[str] = None,
    strategy: str = "factor",
    reason: str = "weekly_dca",
    run_date: Optional[str] = None,
) -> dict[str, Any]:
    """
    Map an Alpaca equity fill into our paper tax-lot shape.
    HIFO/TLH sell path continues to operate on these lots; this only opens buys.
    """
    if shares <= 0 or price <= 0:
        raise ValueError("shares and price must be positive")
    opened = (filled_at or datetime.now(timezone.utc).isoformat()).replace("Z", "+00:00")
    # Prefer calendar date for lot opened_on.
    try:
        opened_on = datetime.fromisoformat(opened).date().isoformat()
    except ValueError:
        opened_on = opened[:10]
    return {
        "id": order_id or str(uuid4()),
        "strategy": strategy,
        "ticker": ticker.strip().upper(),
        "shares": float(shares),
        "cost_per_share": float(price),
        "opened_on": opened_on,
        "run_date": run_date or opened_on,
        "status": "open",
        "source": "alpaca_fill",
        "order_id": order_id,
        "reason": reason,
    }
