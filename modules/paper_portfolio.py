"""
Weekly paper DCA + tax-aware TLH ledger for the ETF factor model.

See PAPER_PORTFOLIO.md for policy. This module is designed to run at the end of
main.py after target weights are known, and to upsert summaries into Supabase.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

import config

WEEKLY_CONTRIBUTION = float(getattr(config, "WEEKLY_CONTRIBUTION_USD", 50_000.0 / 13.0))
ETF_TARGET_CAPITAL = float(getattr(config, "ETF_TARGET_CAPITAL_USD", 50_000.0))
DCA_WEEKS = int(getattr(config, "DCA_WEEKS", 13))
MIN_HOLD_DAYS = int(getattr(config, "MIN_HOLD_DAYS", 91))
LONG_TERM_DAYS = int(getattr(config, "LONG_TERM_DAYS", 365))
WASH_SALE_DAYS = int(getattr(config, "WASH_SALE_DAYS", 30))
WEIGHT_EPS = 1e-4

SUBSTANTIALLY_IDENTICAL = {
    "SPY": ["IVV", "VOO", "SPLG", "VV"],
    "IVV": ["SPY", "VOO", "SPLG", "VV"],
    "VOO": ["SPY", "IVV", "SPLG", "VV"],
    "QQQ": ["QQQM", "ONEQ"],
    "QQQM": ["QQQ", "ONEQ"],
    "IWM": ["VTWO", "SCHA"],
    "VTWO": ["IWM", "SCHA"],
    "IJH": ["MDY", "IVOO"],
    "MDY": ["IJH", "IVOO"],
    "EFA": ["IEFA", "VEA", "IDEV"],
    "IEFA": ["EFA", "VEA", "IDEV"],
    "VEA": ["EFA", "IEFA", "IDEV"],
    "EEM": ["IEMG", "VWO"],
    "IEMG": ["EEM", "VWO"],
    "VWO": ["EEM", "IEMG"],
    "AGG": ["BND", "FBND"],
    "BND": ["AGG", "FBND"],
    "GLD": ["IAUM", "IAU", "GLDM"],
    "IAUM": ["GLD", "IAU", "GLDM"],
    "HYG": ["JNK", "SJNK"],
    "LQD": ["VCIT", "USIG"],
}


@dataclass
class Lot:
    id: str
    strategy: str
    ticker: str
    shares: float
    cost_per_share: float
    opened_on: pd.Timestamp
    run_date: pd.Timestamp
    status: str = "open"
    closed_on: Optional[pd.Timestamp] = None
    close_price: Optional[float] = None
    realized_pnl: Optional[float] = None
    close_reason: Optional[str] = None
    replacement_for: Optional[str] = None


@dataclass
class Ledger:
    lots: List[Lot] = field(default_factory=list)
    wash: Dict[str, pd.Timestamp] = field(default_factory=dict)
    cum_realized_gains: float = 0.0
    cum_realized_losses: float = 0.0
    cash_factor: float = 0.0
    cash_voo: float = 0.0
    trades: List[dict] = field(default_factory=list)


def _next_business_day(ts: pd.Timestamp) -> pd.Timestamp:
    d = pd.Timestamp(ts).normalize() + pd.Timedelta(days=1)
    while d.weekday() >= 5:
        d += pd.Timedelta(days=1)
    return d


def _identical_set(ticker: str) -> set[str]:
    t = ticker.upper()
    return {t, *[x.upper() for x in SUBSTANTIALLY_IDENTICAL.get(t, [])]}


def _fetch_daily_opens(tickers: List[str], start: str, end: str) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    raw = yf.download(
        tickers,
        start=start,
        end=(pd.Timestamp(end) + pd.Timedelta(days=2)).strftime("%Y-%m-%d"),
        interval="1d",
        auto_adjust=True,
        progress=False,
        group_by="column",
    )
    if raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        if "Open" in raw.columns.get_level_values(0):
            opens = raw["Open"].copy()
        else:
            opens = raw.xs("Open", axis=1, level=1, drop_level=True)
    else:
        opens = raw[["Open"]].rename(columns={"Open": tickers[0]}) if "Open" in raw.columns else raw
    opens.index = pd.to_datetime(opens.index).tz_localize(None).normalize()
    return opens.sort_index()


def _price_on_or_before(opens: pd.DataFrame, ticker: str, dt: pd.Timestamp) -> Optional[float]:
    if ticker not in opens.columns:
        return None
    series = opens[ticker].dropna()
    if series.empty:
        return None
    dt = pd.Timestamp(dt).normalize()
    eligible = series.loc[:dt]
    if eligible.empty:
        return None
    px = float(eligible.iloc[-1])
    return px if np.isfinite(px) and px > 0 else None


BETA_COLUMNS = ("beta_mkt", "beta_smb", "beta_hml", "beta_rmw", "beta_cma", "beta_wml")


def _category_peers(ticker: str) -> List[str]:
    mapping = getattr(config, "ETF_CATEGORIES", {})
    for peers in mapping.values():
        if ticker in peers:
            return list(peers)
    return []


def _beta_vector_from_frame(df: pd.DataFrame) -> Optional[np.ndarray]:
    """Latest Kalman state, matching the fund scorer's 3-row EWM."""
    if df is None or len(df) < 3:
        return None
    missing = [col for col in BETA_COLUMNS if col not in df.columns]
    if missing:
        return None
    recent = df.tail(3).ewm(span=2).mean().iloc[-1]
    vec = np.array([float(recent[col]) for col in BETA_COLUMNS], dtype=float)
    if not np.isfinite(vec).all():
        return None
    return vec


def betas_from_profiles(beta_profiles: Optional[dict]) -> Dict[str, np.ndarray]:
    """Map ticker -> 6-factor beta vector from Kalman profile frames."""
    out: Dict[str, np.ndarray] = {}
    if not beta_profiles:
        return out
    for ticker, frame in beta_profiles.items():
        if not isinstance(frame, pd.DataFrame):
            continue
        vec = _beta_vector_from_frame(frame)
        if vec is not None:
            out[str(ticker).upper()] = vec
    return out


def _rank_by_beta_distance(
    sold: str,
    peers: List[str],
    betas: Optional[Dict[str, np.ndarray]],
) -> List[str]:
    """
    Prefer the category peer whose factor betas are closest to the sold name.
    Peers without a beta vector keep their category-list order after the ranked names.
    """
    if not betas:
        return list(peers)
    origin = betas.get(sold.upper())
    if origin is None:
        return list(peers)
    ranked: List[Tuple[float, str]] = []
    unranked: List[str] = []
    for peer in peers:
        vec = betas.get(peer.upper())
        if vec is None:
            unranked.append(peer)
            continue
        ranked.append((float(np.linalg.norm(vec - origin)), peer))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [peer for _, peer in ranked] + unranked


def _choose_substitute(
    sold: str,
    as_of: pd.Timestamp,
    ledger: Ledger,
    opens: pd.DataFrame,
    weights: Dict[str, float],
    betas: Optional[Dict[str, np.ndarray]] = None,
) -> Optional[str]:
    banned = _identical_set(sold)
    peers = _rank_by_beta_distance(sold, _category_peers(sold), betas)

    def eligible(peer: str, respect_weight_cap: bool) -> bool:
        if peer in banned:
            return False
        if _is_wash_restricted(ledger, peer, as_of):
            return False
        if _price_on_or_before(opens, peer, as_of) is None:
            return False
        if respect_weight_cap and weights.get(peer, 0.0) > 0.11:
            return False
        return True

    for peer in peers:
        if eligible(peer, respect_weight_cap=True):
            return peer
    for peer in peers:
        if eligible(peer, respect_weight_cap=False):
            return peer
    return None


def _is_wash_restricted(ledger: Ledger, ticker: str, as_of: pd.Timestamp) -> bool:
    for banned in _identical_set(ticker):
        sold_on = ledger.wash.get(banned)
        if sold_on is None:
            continue
        if (pd.Timestamp(as_of).normalize() - pd.Timestamp(sold_on).normalize()).days < WASH_SALE_DAYS:
            return True
    return False


def _unrealized_pnl(lot: Lot, price: float) -> float:
    return lot.shares * price - lot.shares * lot.cost_per_share


def _sort_lots_least_gain_first(lots: List[Lot], price_by_ticker: Dict[str, float]) -> List[Lot]:
    """
    Tax-aware sell order: least unrealized $ gain first (HIFO at a common mark).
    Prefer selling high-basis lots so low-basis winners can season into LTCG.
    """

    def key(lot: Lot) -> Tuple[float, float, str, str]:
        px = price_by_ticker.get(lot.ticker)
        if px is None or not np.isfinite(px):
            # Unpriced lots sort last.
            return (float("inf"), 0.0, lot.opened_on.strftime("%Y-%m-%d"), lot.id)
        pnl = _unrealized_pnl(lot, px)
        # Higher cost basis first on ties → more negative / smaller gain.
        return (pnl, -lot.cost_per_share, lot.opened_on.strftime("%Y-%m-%d"), lot.id)

    return sorted(lots, key=key)


def _record_sale(ledger: Ledger, lot: Lot, dt: pd.Timestamp, price: float, reason: str) -> float:
    proceeds = lot.shares * price
    cost = lot.shares * lot.cost_per_share
    pnl = proceeds - cost
    lot.status = "closed"
    lot.closed_on = dt
    lot.close_price = price
    lot.realized_pnl = pnl
    lot.close_reason = reason
    ledger.trades.append(
        {
            "date": dt.strftime("%Y-%m-%d"),
            "ticker": lot.ticker,
            "side": "sell",
            "shares": lot.shares,
            "price": price,
            "amount": proceeds,
            "reason": reason,
            "strategy": lot.strategy,
            "lot_id": lot.id,
            "cost_per_share": lot.cost_per_share,
        }
    )
    if pnl >= 0:
        ledger.cum_realized_gains += pnl
    else:
        ledger.cum_realized_losses += -pnl
        ledger.wash[lot.ticker] = dt
    return proceeds


def _record_partial_sale(
    ledger: Ledger,
    lot: Lot,
    shares: float,
    dt: pd.Timestamp,
    price: float,
    reason: str,
) -> float:
    """Sell part of a lot (HIFO trim). Remaining shares stay open on the original lot."""
    if shares <= 0 or shares > lot.shares + 1e-12:
        return 0.0
    if shares >= lot.shares - 1e-12:
        return _record_sale(ledger, lot, dt, price, reason)

    proceeds = shares * price
    cost = shares * lot.cost_per_share
    pnl = proceeds - cost
    lot.shares -= shares
    ledger.trades.append(
        {
            "date": dt.strftime("%Y-%m-%d"),
            "ticker": lot.ticker,
            "side": "sell",
            "shares": shares,
            "price": price,
            "amount": proceeds,
            "reason": reason,
            "strategy": lot.strategy,
            "lot_id": lot.id,
            "cost_per_share": lot.cost_per_share,
            "partial": True,
        }
    )
    if pnl >= 0:
        ledger.cum_realized_gains += pnl
    else:
        ledger.cum_realized_losses += -pnl
        ledger.wash[lot.ticker] = dt
    return proceeds


def _buy(
    ledger: Ledger,
    strategy: str,
    ticker: str,
    dollars: float,
    dt: pd.Timestamp,
    run_date: pd.Timestamp,
    price: float,
    reason: str,
    replacement_for: Optional[str] = None,
) -> None:
    if dollars <= 0 or price <= 0:
        return
    shares = dollars / price
    ledger.lots.append(
        Lot(
            id=str(uuid.uuid4()),
            strategy=strategy,
            ticker=ticker,
            shares=shares,
            cost_per_share=price,
            opened_on=dt,
            run_date=run_date,
            replacement_for=replacement_for,
        )
    )
    ledger.trades.append(
        {
            "date": dt.strftime("%Y-%m-%d"),
            "ticker": ticker,
            "side": "buy",
            "shares": shares,
            "price": price,
            "amount": dollars,
            "reason": reason,
            "strategy": strategy,
        }
    )


def _evaluate_exits(
    ledger: Ledger,
    as_of: pd.Timestamp,
    weights: Dict[str, float],
    opens: pd.DataFrame,
    betas: Optional[Dict[str, np.ndarray]] = None,
) -> None:
    open_factor = [l for l in ledger.lots if l.status == "open" and l.strategy == "factor"]
    priced: Dict[str, float] = {}
    eligible: List[Lot] = []
    for lot in open_factor:
        age = (as_of.normalize() - lot.opened_on.normalize()).days
        if age < MIN_HOLD_DAYS:
            continue
        px = _price_on_or_before(opens, lot.ticker, as_of)
        if px is None:
            continue
        priced[lot.ticker] = px
        eligible.append(lot)

    # Always consider least-gain / highest-basis lots first when reallocating.
    for lot in _sort_lots_least_gain_first(eligible, priced):
        if lot.status != "open":
            continue
        px = priced.get(lot.ticker) or _price_on_or_before(opens, lot.ticker, as_of)
        if px is None:
            continue
        age = (as_of.normalize() - lot.opened_on.normalize()).days
        pnl = _unrealized_pnl(lot, px)
        still = weights.get(lot.ticker, 0.0) > WEIGHT_EPS

        if pnl < 0:
            if not still:
                _record_sale(ledger, lot, as_of, px, "tlh_exit_no_allocation")
                continue
            proceeds = _record_sale(ledger, lot, as_of, px, "tlh_rotate")
            sub = _choose_substitute(lot.ticker, as_of, ledger, opens, weights, betas)
            if sub:
                sub_px = _price_on_or_before(opens, sub, as_of)
                if sub_px is not None:
                    _buy(
                        ledger,
                        "factor",
                        sub,
                        proceeds,
                        as_of,
                        lot.run_date,
                        sub_px,
                        f"tlh_substitute_for_{lot.ticker}",
                        replacement_for=lot.ticker,
                    )
                    continue
            ledger.cash_factor += proceeds
            continue

        if age < LONG_TERM_DAYS:
            offset = max(0.0, ledger.cum_realized_losses - ledger.cum_realized_gains)
            if (not still) and pnl > 0 and offset >= pnl:
                _record_sale(ledger, lot, as_of, px, "gain_offset_by_harvested_losses")
            continue

        if not still:
            _record_sale(ledger, lot, as_of, px, "ltcg_exit_no_allocation")


def _deploy(
    ledger: Ledger,
    run_date: pd.Timestamp,
    fill_date: pd.Timestamp,
    weights: Dict[str, float],
    opens: pd.DataFrame,
) -> None:
    remaining = WEEKLY_CONTRIBUTION + ledger.cash_factor
    ledger.cash_factor = 0.0
    for ticker, weight in weights.items():
        if weight <= WEIGHT_EPS:
            continue
        if _is_wash_restricted(ledger, ticker, fill_date):
            continue
        px = _price_on_or_before(opens, ticker, fill_date)
        if px is None:
            continue
        dollars = min(WEEKLY_CONTRIBUTION * float(weight), remaining)
        if dollars <= 0:
            continue
        _buy(ledger, "factor", ticker, dollars, fill_date, run_date, px, "weekly_dca")
        remaining -= dollars
    ledger.cash_factor += remaining

    voo_cash = WEEKLY_CONTRIBUTION + ledger.cash_voo
    ledger.cash_voo = 0.0
    voo_px = _price_on_or_before(opens, "VOO", fill_date)
    if voo_px is not None:
        _buy(ledger, "voo", "VOO", voo_cash, fill_date, run_date, voo_px, "weekly_voo_dca")
    else:
        ledger.cash_voo = voo_cash


def _summary(ledger: Ledger, as_of: pd.Timestamp, opens: pd.DataFrame, run_count: int) -> dict:
    strat_mv = ledger.cash_factor
    strat_cost = 0.0
    voo_mv = ledger.cash_voo
    voo_cost = 0.0
    u_gain = 0.0
    u_loss = 0.0

    for lot in ledger.lots:
        if lot.status != "open":
            continue
        px = _price_on_or_before(opens, lot.ticker, as_of)
        cost = lot.shares * lot.cost_per_share
        mtm = lot.shares * px if px is not None else cost
        pnl = mtm - cost
        if pnl >= 0:
            u_gain += pnl
        else:
            u_loss += -pnl
        if lot.strategy == "voo":
            voo_mv += mtm
            voo_cost += cost
        else:
            strat_mv += mtm
            strat_cost += cost

    contributed = run_count * WEEKLY_CONTRIBUTION
    etf_float = max(0.0, ETF_TARGET_CAPITAL - min(ETF_TARGET_CAPITAL, contributed))
    return {
        "strategy_value": strat_mv,
        "strategy_cost_basis": strat_cost + ledger.cash_factor,
        "strategy_return_pct": ((strat_mv / contributed) - 1.0) * 100.0 if contributed else 0.0,
        "voo_value": voo_mv,
        "voo_cost_basis": voo_cost + ledger.cash_voo,
        "voo_return_pct": ((voo_mv / contributed) - 1.0) * 100.0 if contributed else 0.0,
        "cum_realized_gains": ledger.cum_realized_gains,
        "cum_realized_losses": ledger.cum_realized_losses,
        "net_taxable": ledger.cum_realized_gains - ledger.cum_realized_losses,
        "cum_unrealized_gains": u_gain,
        "cum_unrealized_losses": u_loss,
        "total_contributed": contributed,
        "etf_target_capital": ETF_TARGET_CAPITAL,
        "etf_float_remaining": etf_float,
        "weekly_contribution": WEEKLY_CONTRIBUTION,
        "dca_weeks": DCA_WEEKS,
        "open_factor_lots": sum(1 for l in ledger.lots if l.status == "open" and l.strategy == "factor"),
    }


def process_week(
    run_date: str,
    target_weights: Dict[str, float],
    ledger: Optional[Ledger] = None,
    betas: Optional[Dict[str, np.ndarray]] = None,
    *,
    run_count: int = 1,
) -> Tuple[Ledger, dict]:
    """Advance the ledger through one model run / fill cycle."""
    ledger = ledger or Ledger()
    # Clear per-week trade tape so callers can propose broker sells for this cycle only.
    ledger.trades = []
    run_ts = pd.Timestamp(run_date).normalize()
    fill_ts = _next_business_day(run_ts)

    # Expire wash restrictions
    for t, sold_on in list(ledger.wash.items()):
        if (fill_ts - pd.Timestamp(sold_on).normalize()).days >= WASH_SALE_DAYS:
            del ledger.wash[t]

    # Price the book, open lots, and the closest same-sleeve peers. Ranking
    # before the download keeps a near-beta substitute from being skipped just
    # because it sits late in the category list.
    needed = {str(k).upper() for k in target_weights}
    needed |= {lot.ticker.upper() for lot in ledger.lots if lot.status == "open"}
    needed.add("VOO")
    for lot in ledger.lots:
        if lot.status != "open" or lot.strategy != "factor":
            continue
        ranked = _rank_by_beta_distance(lot.ticker, _category_peers(lot.ticker), betas)
        needed.update(peer.upper() for peer in ranked[:8])
    tickers = sorted(needed)

    end = fill_ts.strftime("%Y-%m-%d")
    # Also need history for MTM of older lots — pull a wider window when summarizing later.
    opens = _fetch_daily_opens(tickers, start=(run_ts - pd.Timedelta(days=420)).strftime("%Y-%m-%d"), end=end)

    weights = {k.upper(): float(v) for k, v in target_weights.items() if float(v) > WEIGHT_EPS}
    total = sum(weights.values())
    if total > 0:
        weights = {k: v / total for k, v in weights.items()}

    _evaluate_exits(ledger, fill_ts, weights, opens, betas)
    _deploy(ledger, run_ts, fill_ts, weights, opens)
    summary = _summary(ledger, fill_ts, opens, run_count=max(1, int(run_count)))
    summary["fill_date"] = fill_ts.strftime("%Y-%m-%d")
    summary["run_count"] = int(run_count)
    return ledger, summary


def export_paper_summary_to_supabase(as_of: str, summary: dict) -> None:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("Supabase credentials not found. Skipping paper portfolio export.")
        return
    try:
        from supabase import create_client
    except Exception as exc:
        print(f"Supabase client unavailable: {exc}")
        return

    client = create_client(url, key)
    records = []
    for metric, value in summary.items():
        records.append(
            {
                "execution_date": as_of,
                "data_type": "paper_summary",
                "ticker_or_factor": metric,
                "value": float(value),
            }
        )
    try:
        client.table("paper_portfolio").insert(records).execute()
        print(f"Exported {len(records)} paper_portfolio summary rows for {as_of}")
    except Exception as exc:
        print(f"paper_portfolio export failed (create table via supabase_paper_portfolio.sql?): {exc}")


def run_paper_portfolio_step(
    portfolio_df: pd.DataFrame,
    run_date: Optional[str] = None,
    beta_profiles: Optional[dict] = None,
    ledger: Optional[Ledger] = None,
    *,
    persist: bool = True,
    propose_sells: bool = True,
) -> dict:
    """Convenience entrypoint for main.py with optional Supabase continuity."""
    run_date = run_date or datetime.now().strftime("%Y-%m-%d")
    if portfolio_df is None or portfolio_df.empty:
        return {}
    weights = {
        str(r["Ticker"]).upper(): float(r["Target_Weight"])
        for _, r in portfolio_df.iterrows()
        if float(r["Target_Weight"]) > WEIGHT_EPS
    }
    betas = betas_from_profiles(beta_profiles)

    prior_run_count = 0
    if ledger is None and persist:
        from modules.paper_ledger_store import load_ledger_from_supabase

        ledger, prior_run_count = load_ledger_from_supabase()
    ledger = ledger or Ledger()
    run_count = prior_run_count + 1

    ledger, summary = process_week(
        run_date, weights, ledger, betas=betas, run_count=run_count
    )
    summary["open_factor_lots"] = sum(
        1 for l in ledger.lots if l.status == "open" and l.strategy == "factor"
    )

    if propose_sells:
        from modules.etf_orders import maybe_place_paper_sells, propose_tlh_sells

        sell_proposal = propose_tlh_sells(ledger.trades)
        summary["sell_proposals"] = sell_proposal
        place_result = maybe_place_paper_sells(sell_proposal)
        summary["sell_place_result"] = place_result
        n_sells = len(sell_proposal.get("sells") or [])
        print(
            f"  • TLH/HIFO sell proposals: {n_sells} "
            f"(auto_place={place_result.get('auto_place')})"
        )

    if persist:
        from modules.paper_ledger_store import save_ledger_to_supabase

        save_ledger_to_supabase(ledger, run_count=run_count)

    export_paper_summary_to_supabase(run_date, summary)
    return summary
