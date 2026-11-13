"""
Defined-risk options order construction for Alpaca paper mleg.

Maps OptionsSignal + option chain → credit multi-leg payload.
Keep aligned with quirk_macro_web_dev/src/lib/options-orders.ts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Literal, Optional

from modules.options_sleeve import (
    OptionsSignal,
    Structure,
    build_signal,
    max_name_margin_usd,
    size_spread_contracts,
)
import config

FillSide = Literal["buy", "sell"]
Right = Literal["C", "P"]
ContractType = Literal["call", "put"]


@dataclass(frozen=True)
class OptionContractQuote:
    symbol: str
    underlying: str
    expiration_date: str
    strike_price: float
    type: ContractType
    mid: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    delta: Optional[float] = None
    tradable: bool = True


@dataclass(frozen=True)
class OrderLegSpec:
    symbol: str
    side: FillSide
    position_intent: Literal["buy_to_open", "sell_to_open"]
    ratio_qty: int
    strike: float
    right: Right
    mid: Optional[float]
    delta: Optional[float]


@dataclass(frozen=True)
class TradeProposal:
    ticker: str
    structure: Structure
    signal: OptionsSignal
    expiration_date: str
    dte: int
    qty: int
    legs: tuple[OrderLegSpec, ...]
    credit_per_share: float
    limit_price: float
    width: float
    max_loss_per_contract: float
    estimated_bp: float
    underlying_price: float
    notes: tuple[str, ...]


@dataclass(frozen=True)
class TradeProposalSkip:
    ticker: str
    structure: Structure
    signal: OptionsSignal
    reason: str


def _parse_ymd(ymd: str) -> date:
    return date.fromisoformat(ymd)


def _today(as_of: Optional[datetime] = None) -> date:
    if as_of is None:
        return datetime.now(timezone.utc).date()
    if as_of.tzinfo is None:
        return as_of.date()
    return as_of.astimezone(timezone.utc).date()


def _mid_of(c: OptionContractQuote) -> Optional[float]:
    if c.mid is not None and c.mid > 0:
        return float(c.mid)
    if c.bid is not None and c.ask is not None and c.bid > 0 and c.ask > 0:
        return (float(c.bid) + float(c.ask)) / 2.0
    if c.bid is not None and c.bid > 0:
        return float(c.bid)
    if c.ask is not None and c.ask > 0:
        return float(c.ask)
    return None


def leg_conservative_price(c: OptionContractQuote, side: FillSide) -> Optional[float]:
    """
    Fill assumption for credit packaging:
    - sell-to-open → bid (worse than mid for the seller)
    - buy-to-open → ask (worse than mid for the buyer)
    Falls back to mid when the preferred side is missing.
    """
    mid = _mid_of(c)
    if side == "sell":
        if c.bid is not None and c.bid > 0:
            return float(c.bid)
        return mid
    if c.ask is not None and c.ask > 0:
        return float(c.ask)
    return mid


def preferred_width(underlying: str, spot: float) -> float:
    u = underlying.upper()
    if u in {"SPY", "QQQ", "IWM"}:
        return 5.0
    if spot >= 80:
        return 3.0
    if spot >= 40:
        return 2.0
    return 1.0


def default_fill_credit_fraction() -> float:
    return float(getattr(config, "OPTIONS_FILL_CREDIT_FRACTION", 0.92))


def credit_limit_price(
    credit_per_share: float,
    fill_fraction: Optional[float] = None,
) -> float:
    """
    Alpaca mleg: negative limit_price = credit.

    Softens the estimated package credit by `fill_fraction` (default
    config.OPTIONS_FILL_CREDIT_FRACTION ≈ 0.92) so the working limit does
    not assume a full mid fill.
    """
    if credit_per_share <= 0:
        return 0.0
    if fill_fraction is None:
        fill_fraction = default_fill_credit_fraction()
    frac = min(max(float(fill_fraction), 0.5), 1.0)
    softened = credit_per_share * frac
    return -round(max(softened, 0.01), 2)


def estimate_package_credit(
    legs: list[OrderLegSpec] | tuple[OrderLegSpec, ...],
    contracts_by_symbol: Optional[dict[str, OptionContractQuote]] = None,
    *,
    conservative_side: Optional[bool] = None,
) -> Optional[float]:
    """
    Net credit per share for the multi-leg package.

    When conservative_side is True (default from config) and quotes are
    available, sells mark at bid and buys at ask. Otherwise uses leg.mid.
    """
    if conservative_side is None:
        conservative_side = bool(getattr(config, "OPTIONS_CREDIT_CONSERVATIVE_SIDE", True))
    credit = 0.0
    for leg in legs:
        px: Optional[float] = None
        if conservative_side and contracts_by_symbol is not None:
            quote = contracts_by_symbol.get(leg.symbol)
            if quote is not None:
                px = leg_conservative_price(quote, leg.side)
        if px is None:
            px = leg.mid
        if px is None:
            return None
        credit += px if leg.side == "sell" else -px
    return float(credit)


def _pick_expiration(
    contracts: list[OptionContractQuote],
    dte_min: int,
    dte_max: int,
    as_of: Optional[datetime],
) -> Optional[tuple[str, int]]:
    today = _today(as_of)
    by_exp: dict[str, int] = {}
    for c in contracts:
        if not c.tradable:
            continue
        dte = (_parse_ymd(c.expiration_date) - today).days
        if dte < dte_min or dte > dte_max:
            continue
        by_exp[c.expiration_date] = dte
    if not by_exp:
        return None
    target = (dte_min + dte_max) / 2.0
    best_exp = min(by_exp.items(), key=lambda kv: abs(kv[1] - target))
    return best_exp[0], best_exp[1]


def _closest_by_delta(
    candidates: list[OptionContractQuote], target_abs_delta: float
) -> Optional[OptionContractQuote]:
    best = None
    best_dist = float("inf")
    for c in candidates:
        if c.delta is None:
            continue
        dist = abs(abs(c.delta) - target_abs_delta)
        if dist < best_dist:
            best = c
            best_dist = dist
    return best


def _closest_by_strike(
    candidates: list[OptionContractQuote], target_strike: float
) -> Optional[OptionContractQuote]:
    if not candidates:
        return None
    return min(candidates, key=lambda c: abs(c.strike_price - target_strike))


def _pick_short(
    chain: list[OptionContractQuote],
    right: ContractType,
    spot: float,
    target_abs_delta: float,
) -> Optional[OptionContractQuote]:
    if right == "put":
        otm = [c for c in chain if c.type == "put" and c.strike_price < spot]
    else:
        otm = [c for c in chain if c.type == "call" and c.strike_price > spot]
    if not otm:
        return None
    by_delta = _closest_by_delta(otm, target_abs_delta)
    if by_delta is not None:
        return by_delta
    otm_pct = 0.045 if target_abs_delta >= 0.22 else 0.065
    target = spot * (1 - otm_pct) if right == "put" else spot * (1 + otm_pct)
    return _closest_by_strike(otm, target)


def _pick_wing(
    chain: list[OptionContractQuote],
    short_strike: float,
    right: ContractType,
    width: float,
) -> Optional[OptionContractQuote]:
    target = short_strike - width if right == "put" else short_strike + width
    if right == "put":
        side = [c for c in chain if c.type == "put" and c.strike_price < short_strike]
    else:
        side = [c for c in chain if c.type == "call" and c.strike_price > short_strike]
    return _closest_by_strike(side, target)


def _leg_spec(contract: OptionContractQuote, side: FillSide) -> OrderLegSpec:
    return OrderLegSpec(
        symbol=contract.symbol,
        side=side,
        position_intent="buy_to_open" if side == "buy" else "sell_to_open",
        ratio_qty=1,
        strike=contract.strike_price,
        right="P" if contract.type == "put" else "C",
        mid=_mid_of(contract),
        delta=contract.delta,
    )


def build_mleg_payload(proposal: TradeProposal) -> dict[str, Any]:
    return {
        "order_class": "mleg",
        "qty": str(proposal.qty),
        "type": "limit",
        "limit_price": str(proposal.limit_price),
        "time_in_force": "day",
        "legs": [
            {
                "symbol": leg.symbol,
                "ratio_qty": str(leg.ratio_qty),
                "side": leg.side,
                "position_intent": leg.position_intent,
            }
            for leg in proposal.legs
        ],
    }


def propose_defined_risk_trade(
    ticker: str,
    composite_score: float,
    iv_rank: float,
    underlying_price: float,
    contracts: list[OptionContractQuote],
    *,
    as_of: Optional[datetime] = None,
    capital_budget_usd: Optional[float] = None,
    fill_credit_fraction: Optional[float] = None,
) -> TradeProposal | TradeProposalSkip:
    signal = build_signal(ticker, composite_score, iv_rank)
    if signal.structure in {"skip_low_iv", "skip_kill_switch"}:
        return TradeProposalSkip(
            ticker=signal.ticker,
            structure=signal.structure,
            signal=signal,
            reason=signal.rationale,
        )

    underlying = signal.ticker.upper()
    spot = float(underlying_price)
    if spot <= 0:
        return TradeProposalSkip(underlying, signal.structure, signal, "Underlying price unavailable.")

    chain = [
        c
        for c in contracts
        if c.underlying.upper() == underlying and c.tradable and c.strike_price > 0
    ]
    picked = _pick_expiration(chain, signal.dte_min, signal.dte_max, as_of)
    if picked is None:
        return TradeProposalSkip(
            underlying,
            signal.structure,
            signal,
            f"No contracts in {signal.dte_min}–{signal.dte_max} DTE window.",
        )
    expiration_date, dte = picked
    dated = [c for c in chain if c.expiration_date == expiration_date]
    width = preferred_width(underlying, spot)
    notes: list[str] = []
    legs: list[OrderLegSpec] = []

    if signal.structure in {"bull_put_spread", "iron_condor"}:
        short_put = _pick_short(dated, "put", spot, signal.short_delta)
        if short_put is None:
            return TradeProposalSkip(underlying, signal.structure, signal, "No OTM short put candidate.")
        long_put = _pick_wing(dated, short_put.strike_price, "put", width)
        if long_put is None:
            return TradeProposalSkip(
                underlying, signal.structure, signal, "No long put wing for defined risk."
            )
        legs.extend([_leg_spec(short_put, "sell"), _leg_spec(long_put, "buy")])
        if short_put.delta is None:
            notes.append("Put short strike via OTM % proxy (no delta).")

    if signal.structure in {"bear_call_spread", "iron_condor"}:
        target_delta = (
            signal.wing_delta if signal.structure == "iron_condor" and signal.wing_delta is not None else signal.short_delta
        )
        short_call = _pick_short(dated, "call", spot, target_delta)
        if short_call is None:
            return TradeProposalSkip(underlying, signal.structure, signal, "No OTM short call candidate.")
        long_call = _pick_wing(dated, short_call.strike_price, "call", width)
        if long_call is None:
            return TradeProposalSkip(
                underlying, signal.structure, signal, "No long call wing for defined risk."
            )
        legs.extend([_leg_spec(short_call, "sell"), _leg_spec(long_call, "buy")])
        if short_call.delta is None:
            notes.append("Call short strike via OTM % proxy (no delta).")

    by_symbol = {c.symbol: c for c in dated}
    credit = estimate_package_credit(legs, by_symbol)
    if credit is None:
        return TradeProposalSkip(
            underlying, signal.structure, signal, "Missing bid/ask mids for credit estimate."
        )
    if credit <= 0:
        return TradeProposalSkip(
            underlying, signal.structure, signal, "Estimated net debit — refusing non-credit structure."
        )
    if bool(getattr(config, "OPTIONS_CREDIT_CONSERVATIVE_SIDE", True)):
        notes.append("Credit marked sell@bid / buy@ask when quotes present (conservative vs mid).")

    widths: list[float] = []
    puts = [l for l in legs if l.right == "P"]
    calls = [l for l in legs if l.right == "C"]
    if len(puts) >= 2:
        widths.append(abs(puts[0].strike - puts[1].strike))
    if len(calls) >= 2:
        widths.append(abs(calls[0].strike - calls[1].strike))
    actual_width = max(widths) if widths else width

    budget = capital_budget_usd
    if budget is None:
        options_cap = float(getattr(config, "OPTIONS_PAPER_CAPITAL_USD", 25_000))
        budget = min(max_name_margin_usd(), options_cap)
    qty = size_spread_contracts(credit, actual_width, budget)
    if qty < 1:
        return TradeProposalSkip(
            underlying, signal.structure, signal, f"Max loss exceeds capital budget ({budget:.0f})."
        )
    qty = min(qty, 5)

    if fill_credit_fraction is None:
        fill_credit_fraction = default_fill_credit_fraction()
    limit_price = credit_limit_price(credit, fill_credit_fraction)
    notes.append(
        f"Limit softens mid/side credit by fill_fraction={fill_credit_fraction:.2f} "
        f"(limit_price={limit_price})."
    )
    max_loss = max(actual_width - credit, 0.0) * 100.0
    return TradeProposal(
        ticker=underlying,
        structure=signal.structure,
        signal=signal,
        expiration_date=expiration_date,
        dte=dte,
        qty=qty,
        legs=tuple(legs),
        credit_per_share=round(credit, 2),
        limit_price=limit_price,
        width=actual_width,
        max_loss_per_contract=round(max_loss, 2),
        estimated_bp=round(max_loss * qty, 2),
        underlying_price=spot,
        notes=tuple(notes),
    )
