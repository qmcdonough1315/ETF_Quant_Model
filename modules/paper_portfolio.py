"""
Weekly paper DCA + tax-aware TLH ledger for the ETF factor model.

See PAPER_PORTFOLIO.md for policy. This module is designed to run at the end of
main.py after target weights are known, and to upsert summaries into Supabase.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

import config

WEEKLY_CONTRIBUTION = float(getattr(config, "WEEKLY_CONTRIBUTION_USD", 1000.0))
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


def _category_peers(ticker: str) -> List[str]:
    mapping = getattr(config, "ETF_CATEGORIES", {})
    for peers in mapping.values():
        if ticker in peers:
            return list(peers)
    return []


def _choose_substitute(
    sold: str,
    as_of: pd.Timestamp,
    ledger: Ledger,
    opens: pd.DataFrame,
    weights: Dict[str, float],
) -> Optional[str]:
    banned = _identical_set(sold)
    for peer in _category_peers(sold):
        if peer in banned:
            continue
        if _is_wash_restricted(ledger, peer, as_of):
            continue
        if _price_on_or_before(opens, peer, as_of) is None:
            continue
        if weights.get(peer, 0.0) > 0.11:
            continue
        return peer
    for peer in _category_peers(sold):
        if peer in banned or _is_wash_restricted(ledger, peer, as_of):
            continue
        if _price_on_or_before(opens, peer, as_of) is not None:
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
) -> None:
    open_factor = [l for l in ledger.lots if l.status == "open" and l.strategy == "factor"]
    for lot in open_factor:
        age = (as_of.normalize() - lot.opened_on.normalize()).days
        if age < MIN_HOLD_DAYS:
            continue
        px = _price_on_or_before(opens, lot.ticker, as_of)
        if px is None:
            continue
        pnl = lot.shares * px - lot.shares * lot.cost_per_share
        still = weights.get(lot.ticker, 0.0) > WEIGHT_EPS

        if pnl < 0:
            if not still:
                _record_sale(ledger, lot, as_of, px, "tlh_exit_no_allocation")
                continue
            proceeds = _record_sale(ledger, lot, as_of, px, "tlh_rotate")
            sub = _choose_substitute(lot.ticker, as_of, ledger, opens, weights)
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
        "open_factor_lots": sum(1 for l in ledger.lots if l.status == "open" and l.strategy == "factor"),
    }


def process_week(
    run_date: str,
    target_weights: Dict[str, float],
    ledger: Optional[Ledger] = None,
) -> Tuple[Ledger, dict]:
    """Advance the ledger through one model run / fill cycle."""
    ledger = ledger or Ledger()
    run_ts = pd.Timestamp(run_date).normalize()
    fill_ts = _next_business_day(run_ts)

    # Expire wash restrictions
    for t, sold_on in list(ledger.wash.items()):
        if (fill_ts - pd.Timestamp(sold_on).normalize()).days >= WASH_SALE_DAYS:
            del ledger.wash[t]

    tickers = sorted(set(target_weights) | {l.ticker for l in ledger.lots if l.status == "open"} | {"VOO"})
    for t in list(target_weights):
        tickers.extend(_category_peers(t)[:8])
    tickers = sorted(set(tickers))

    start = (fill_ts - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    end = fill_ts.strftime("%Y-%m-%d")
    # Also need history for MTM of older lots — pull a wider window when summarizing later.
    opens = _fetch_daily_opens(tickers, start=(run_ts - pd.Timedelta(days=420)).strftime("%Y-%m-%d"), end=end)

    weights = {k.upper(): float(v) for k, v in target_weights.items() if float(v) > WEIGHT_EPS}
    total = sum(weights.values())
    if total > 0:
        weights = {k: v / total for k, v in weights.items()}

    _evaluate_exits(ledger, fill_ts, weights, opens)
    _deploy(ledger, run_ts, fill_ts, weights, opens)
    summary = _summary(ledger, fill_ts, opens, run_count=1)  # caller aggregates run_count
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


def run_paper_portfolio_step(portfolio_df: pd.DataFrame, run_date: Optional[str] = None) -> dict:
    """Convenience entrypoint for main.py."""
    run_date = run_date or datetime.now().strftime("%Y-%m-%d")
    if portfolio_df is None or portfolio_df.empty:
        return {}
    weights = {
        str(r["Ticker"]).upper(): float(r["Target_Weight"])
        for _, r in portfolio_df.iterrows()
        if float(r["Target_Weight"]) > WEIGHT_EPS
    }
    ledger, summary = process_week(run_date, weights, Ledger())
    # Note: full multi-week continuity requires loading prior lots from Supabase.
    # The dashboard currently replays full history from factor_predictions.
    summary["open_factor_lots"] = sum(1 for l in ledger.lots if l.status == "open" and l.strategy == "factor")
    export_paper_summary_to_supabase(run_date, summary)
    return summary
