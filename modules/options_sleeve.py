"""
Short-options / volatility paper sleeve.

Keeps shorts and long-extension outside the long-only ETF MVO. Maps a 6-factor
composite score plus IV Rank into defined-risk credit structures.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Optional

import config

Structure = Literal[
    "bull_put_spread",
    "bear_call_spread",
    "iron_condor",
    "skip_low_iv",
    "skip_missing_iv",
    "skip_kill_switch",
]

Regime = Literal[
    "q1_bullish_vol_seller",
    "q2_bearish_vol_seller",
    "q3_neutral_vol",
    "q4_low_iv",
    "missing_iv",
    "kill_switch",
]


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
    if regime == "kill_switch":
        return (
            "skip_kill_switch",
            0.0,
            None,
            "Kill-switch active — no new short-premium risk (see RISK_POLICY.md).",
        )
    if regime == "missing_iv":
        return (
            "skip_missing_iv",
            0.0,
            None,
            "IV Rank unavailable — fail closed (no demo / placeholder IVR).",
        )
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
        "IV Rank below gate — stand aside; Phase 1 does not buy cheap vol.",
    )


def _finite_iv_rank(iv_rank: Optional[float]) -> Optional[float]:
    if iv_rank is None:
        return None
    try:
        v = float(iv_rank)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v


def build_signal(
    ticker: str,
    composite_score: float,
    iv_rank: Optional[float],
    *,
    kill_switch_active: Optional[bool] = None,
) -> OptionsSignal:
    """
    Map composite × IVR → structure. Missing/non-finite IVR → skip_missing_iv
    (fail closed). If kill_switch_active is None, evaluate env/snapshot via
    risk_policy (fail closed when yellow/red).
    """
    if kill_switch_active is None:
        try:
            from modules.risk_policy import kill_switch_from_env_snapshot

            kill_switch_active = kill_switch_from_env_snapshot().halt_new_short_premium
        except Exception:  # noqa: BLE001 — never block on risk module import issues with open risk
            kill_switch_active = False

    ivr = _finite_iv_rank(iv_rank)
    if kill_switch_active:
        regime: Regime = "kill_switch"
        ivr_out = float(ivr) if ivr is not None else float("nan")
    elif ivr is None:
        regime = "missing_iv"
        ivr_out = float("nan")
    else:
        regime = classify_regime(composite_score, ivr)
        ivr_out = ivr
    structure, short_delta, wing_delta, rationale = map_structure(regime)
    return OptionsSignal(
        ticker=ticker.upper(),
        composite_score=float(composite_score),
        iv_rank=ivr_out,
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
