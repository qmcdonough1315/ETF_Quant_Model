"""
Short-options / volatility paper sleeve.

Keeps shorts and long-extension outside the long-only ETF MVO. Maps a 6-factor
composite score plus IV Rank into defined-risk credit structures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import config

Structure = Literal[
    "bull_put_spread",
    "bear_call_spread",
    "iron_condor",
    "skip_low_iv",
]

Regime = Literal["q1_bullish_vol_seller", "q2_bearish_vol_seller", "q3_neutral_vol", "q4_low_iv"]


@dataclass(frozen=True)
class OptionsSignal:
    ticker: str
    composite_score: float
    iv_rank: float
    regime: Regime
    structure: Structure
    dte_min: int
    dte_max: int
    short_delta: float
    wing_delta: Optional[float]
    rationale: str


def classify_regime(composite_score: float, iv_rank: float) -> Regime:
    """Quadrant map from the Short Option Overview."""
    ivr_min = float(getattr(config, "OPTIONS_IVR_MIN", 30.0))
    if iv_rank < ivr_min:
        return "q4_low_iv"
    if composite_score >= 0.5:
        return "q1_bullish_vol_seller"
    if composite_score <= -0.5:
        return "q2_bearish_vol_seller"
    return "q3_neutral_vol"


def map_structure(regime: Regime) -> tuple[Structure, float, Optional[float], str]:
    if regime == "q1_bullish_vol_seller":
        return (
            "bull_put_spread",
            0.25,
            None,
            "High factor score + elevated IVR → defined-risk long extension via short put spread.",
        )
    if regime == "q2_bearish_vol_seller":
        return (
            "bear_call_spread",
            0.25,
            None,
            "Weak factor score + elevated IVR → short expression via short call spread.",
        )
    if regime == "q3_neutral_vol":
        return (
            "iron_condor",
            0.18,
            0.18,
            "Neutral factor score + elevated IVR → double-ended theta / vol premium.",
        )
    return (
        "skip_low_iv",
        0.0,
        None,
        "IV Rank below gate — do not sell cheap volatility.",
    )


def build_signal(ticker: str, composite_score: float, iv_rank: float) -> OptionsSignal:
    regime = classify_regime(composite_score, iv_rank)
    structure, short_delta, wing_delta, rationale = map_structure(regime)
    return OptionsSignal(
        ticker=ticker.upper(),
        composite_score=float(composite_score),
        iv_rank=float(iv_rank),
        regime=regime,
        structure=structure,
        dte_min=int(getattr(config, "OPTIONS_DTE_MIN", 30)),
        dte_max=int(getattr(config, "OPTIONS_DTE_MAX", 45)),
        short_delta=short_delta,
        wing_delta=wing_delta,
        rationale=rationale,
    )


def max_name_margin_usd(total_book_usd: float = 100_000.0) -> float:
    pct = float(getattr(config, "OPTIONS_MAX_NAME_MARGIN_PCT", 0.02))
    return total_book_usd * pct


def max_sector_margin_usd(options_plus_cash_usd: float = 50_000.0) -> float:
    pct = float(getattr(config, "OPTIONS_MAX_SECTOR_MARGIN_PCT", 0.12))
    return options_plus_cash_usd * pct


def size_spread_contracts(
    credit_per_share: float,
    width: float,
    capital_budget: float,
) -> int:
    """
    Defined-risk credit spread sizing by max loss.
    Max loss per contract ≈ (width - credit) * 100.
    """
    if credit_per_share < 0 or width <= 0 or capital_budget <= 0:
        return 0
    max_loss = max(width - credit_per_share, 0.01) * 100.0
    return int(capital_budget // max_loss)


# Liquid ETF underlyings for Phase 1 paper trading.
PHASE1_OPTIONABLE_ETFS = (
    "SPY",
    "QQQ",
    "IWM",
    "XLK",
    "XLF",
    "XLE",
    "XLV",
    "XLI",
    "XLY",
    "XLP",
    "XLU",
    "XLB",
    "XLRE",
    "XLC",
)
