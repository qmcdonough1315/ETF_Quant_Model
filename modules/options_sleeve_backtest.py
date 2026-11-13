"""
Point-in-time options sleeve research backtest (Wave D / checklist #10).

Honest / crude by design:
- IVR from stored ATM IV history only (CSV or Supabase) — never invents IV.
- Factor axis uses a documented stand-in: cross-sectional z-score of trailing
  ~3M underlying returns over Phase 1 names (same ±0.5 gates as production).
- No historical option chain: strikes via OTM% proxies; marks via Black–Scholes
  with contemporaneous ATM IV when available.
- Exits: 50% of credit take-profit, 2× credit stop, else expiry intrinsic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Optional

import numpy as np
import pandas as pd

import config
from modules.black_scholes_iv import black_scholes_price
from modules.iv_rank import iv_rank_from_series
from modules.options_composite import normalize_phase1_composites
from modules.options_orders import preferred_width
from modules.options_sleeve import (
    PHASE1_OPTIONABLE_ETFS,
    Structure,
    build_signal,
    max_name_margin_usd,
)


ExitReason = Literal["take_profit", "stop", "expiry", "skip", "no_data"]


@dataclass(frozen=True)
class SleeveTradeResult:
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    ticker: str
    structure: Structure
    iv_rank: float
    composite: float
    credit: float
    width: float
    qty: int
    pnl_usd: float
    exit_reason: ExitReason
    max_loss_usd: float


def load_iv_history(
    path: Optional[str | Path] = None,
    *,
    from_supabase: bool = False,
) -> pd.DataFrame:
    """
    Load ATM IV history. Prefer explicit path, else local CSV, else Supabase.
    Raises if empty — callers must not invent rows.
    """
    candidates: list[Path] = []
    if path is not None:
        candidates.append(Path(path))
    candidates.extend(
        [
            Path("data/option_iv_history/atm_iv_from_supabase.csv"),
            Path("data/option_iv_history/atm_iv_bootstrap.csv"),
        ]
    )

    df: Optional[pd.DataFrame] = None
    for p in candidates:
        if p.is_file():
            df = pd.read_csv(p)
            break

    if df is None and from_supabase:
        df = _fetch_iv_from_supabase()

    if df is None or df.empty:
        raise FileNotFoundError(
            "No option_iv_history available. Provide --iv-csv, place a CSV under "
            "data/option_iv_history/, or pass --from-supabase with credentials. "
            "Refusing to synthesize IV."
        )

    out = df.copy()
    out["ticker"] = out["ticker"].astype(str).str.upper()
    out["as_of_date"] = pd.to_datetime(out["as_of_date"]).dt.normalize()
    out["atm_iv"] = pd.to_numeric(out["atm_iv"], errors="coerce")
    if "spot" in out.columns:
        out["spot"] = pd.to_numeric(out["spot"], errors="coerce")
    out = out.dropna(subset=["ticker", "as_of_date", "atm_iv"])
    out = out.sort_values(["ticker", "as_of_date"]).drop_duplicates(
        ["ticker", "as_of_date"], keep="last"
    )
    if out.empty:
        raise ValueError("IV history loaded but all rows were invalid after cleaning.")
    return out.reset_index(drop=True)


def _fetch_iv_from_supabase() -> pd.DataFrame:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY required for --from-supabase")
    from supabase import create_client

    client = create_client(url, key)
    rows: list[dict] = []
    start = 0
    while True:
        batch = (
            client.table("option_iv_history")
            .select("as_of_date,ticker,atm_iv,spot,dte,source")
            .range(start, start + 999)
            .execute()
            .data
        )
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 1000:
            break
        start += 1000
    return pd.DataFrame(rows)


def point_in_time_ivr(
    history: pd.DataFrame,
    ticker: str,
    as_of: pd.Timestamp,
    *,
    lookback_days: Optional[int] = None,
) -> Optional[float]:
    lookback = int(
        lookback_days
        if lookback_days is not None
        else getattr(config, "OPTIONS_BACKTEST_IV_LOOKBACK_DAYS", 365)
    )
    as_of = pd.Timestamp(as_of).normalize()
    start = as_of - pd.Timedelta(days=lookback)
    mask = (
        (history["ticker"] == ticker.upper())
        & (history["as_of_date"] >= start)
        & (history["as_of_date"] <= as_of)
    )
    window = history.loc[mask, "atm_iv"]
    if window.empty:
        return None
    return iv_rank_from_series(window)


def atm_iv_on_or_before(
    history: pd.DataFrame, ticker: str, as_of: pd.Timestamp
) -> Optional[float]:
    as_of = pd.Timestamp(as_of).normalize()
    sub = history.loc[
        (history["ticker"] == ticker.upper()) & (history["as_of_date"] <= as_of)
    ]
    if sub.empty:
        return None
    return float(sub.iloc[-1]["atm_iv"])


def trailing_return_composites(
    prices: pd.DataFrame,
    as_of: pd.Timestamp,
    *,
    lookback_trading_days: int = 63,
    universe: Iterable[str] = PHASE1_OPTIONABLE_ETFS,
) -> dict[str, float]:
    """
    Documented stand-in for weekly factor composites: z-score of trailing
    ~3M total return across Phase 1 names using only prices ≤ as_of.
    """
    as_of = pd.Timestamp(as_of).normalize()
    hist = prices.loc[:as_of]
    if hist.empty or len(hist) < lookback_trading_days + 1:
        return {}
    window = hist.iloc[-(lookback_trading_days + 1) :]
    rets: dict[str, float] = {}
    for t in universe:
        t = str(t).upper()
        if t not in window.columns:
            continue
        s = window[t].dropna()
        if len(s) < lookback_trading_days // 2:
            continue
        r = float(s.iloc[-1] / s.iloc[0] - 1.0)
        if np.isfinite(r):
            rets[t] = r
    return normalize_phase1_composites(rets, universe=universe)


def _otm_pct_for_delta(abs_delta: float) -> float:
    if abs_delta >= 0.22:
        return float(getattr(config, "OPTIONS_BACKTEST_OTM_PCT_25D", 0.045))
    return float(getattr(config, "OPTIONS_BACKTEST_OTM_PCT_18D", 0.065))


def _bs_put(spot: float, strike: float, t_years: float, iv: float) -> float:
    return float(black_scholes_price(spot, strike, t_years, 0.0, iv, "put"))


def _bs_call(spot: float, strike: float, t_years: float, iv: float) -> float:
    return float(black_scholes_price(spot, strike, t_years, 0.0, iv, "call"))


def approximate_structure_value(
    structure: Structure,
    spot: float,
    iv: float,
    *,
    width: float,
    short_delta: float,
    dte: float,
) -> Optional[float]:
    """
    Mark of the short credit package as a *debit to close* (positive = costs money).
    At entry, credit received ≈ this value under the same model.
    """
    if structure in {"skip_low_iv", "skip_kill_switch"}:
        return None
    if spot <= 0 or iv <= 0 or width <= 0 or dte <= 0:
        return None
    t = max(float(dte), 1.0) / 365.0
    otm = _otm_pct_for_delta(short_delta)
    value = 0.0
    if structure in {"bull_put_spread", "iron_condor"}:
        short_k = spot * (1.0 - otm)
        long_k = short_k - width
        if long_k <= 0:
            return None
        value += _bs_put(spot, short_k, t, iv) - _bs_put(spot, long_k, t, iv)
    if structure in {"bear_call_spread", "iron_condor"}:
        short_k = spot * (1.0 + otm)
        long_k = short_k + width
        value += _bs_call(spot, short_k, t, iv) - _bs_call(spot, long_k, t, iv)
    if value <= 0 or not np.isfinite(value):
        return None
    return float(value)


def _intrinsic_close_cost(
    structure: Structure,
    spot: float,
    *,
    width: float,
    short_delta: float,
    entry_spot: float,
) -> float:
    """Expiry intrinsic cost to close (max(0, intrinsic package))."""
    otm = _otm_pct_for_delta(short_delta)
    cost = 0.0
    if structure in {"bull_put_spread", "iron_condor"}:
        short_k = entry_spot * (1.0 - otm)
        long_k = short_k - width
        # Short put payoff to us is -max(K-S,0); long put +max(K-S,0)
        short_pay = max(short_k - spot, 0.0)
        long_pay = max(long_k - spot, 0.0)
        cost += max(short_pay - long_pay, 0.0)
    if structure in {"bear_call_spread", "iron_condor"}:
        short_k = entry_spot * (1.0 + otm)
        long_k = short_k + width
        short_pay = max(spot - short_k, 0.0)
        long_pay = max(spot - long_k, 0.0)
        cost += max(short_pay - long_pay, 0.0)
    return float(min(cost, width * (2 if structure == "iron_condor" else 1)))


def simulate_credit_trade(
    structure: Structure,
    entry_date: pd.Timestamp,
    entry_spot: float,
    entry_iv: float,
    price_path: pd.Series,
    iv_history: pd.DataFrame,
    ticker: str,
    *,
    short_delta: float,
    hold_dte: Optional[int] = None,
    fill_fraction: Optional[float] = None,
    capital_budget: Optional[float] = None,
    profit_take_pct: Optional[float] = None,
    stop_multiple: Optional[float] = None,
) -> Optional[SleeveTradeResult]:
    if structure in {"skip_low_iv", "skip_kill_switch"}:
        return None
    hold_dte = int(
        hold_dte
        if hold_dte is not None
        else getattr(config, "OPTIONS_BACKTEST_HOLD_DTE", 37)
    )
    fill_fraction = float(
        fill_fraction
        if fill_fraction is not None
        else getattr(config, "OPTIONS_FILL_CREDIT_FRACTION", 0.92)
    )
    profit_take = float(
        profit_take_pct
        if profit_take_pct is not None
        else getattr(config, "OPTIONS_PROFIT_TAKE_PCT", 0.50)
    )
    stop_mult = float(
        stop_multiple
        if stop_multiple is not None
        else getattr(config, "OPTIONS_STOP_MULTIPLE", 2.0)
    )
    # Match production propose path: size off per-name margin, not the whole sleeve.
    if capital_budget is None:
        options_cap = float(getattr(config, "OPTIONS_PAPER_CAPITAL_USD", 25_000.0))
        budget = min(max_name_margin_usd(), options_cap)
    else:
        budget = float(capital_budget)

    width = preferred_width(ticker, entry_spot)
    mid_credit = approximate_structure_value(
        structure,
        entry_spot,
        entry_iv,
        width=width,
        short_delta=short_delta,
        dte=hold_dte,
    )
    if mid_credit is None:
        return None
    # Conservative entry: only keep fill_fraction of model mid credit.
    credit = mid_credit * fill_fraction
    if credit <= 0:
        return None

    max_loss_per = max(width - credit, 0.01) * 100.0
    if structure == "iron_condor":
        # Two wings; budget against wider of the two (same width each side here).
        max_loss_per = max(width - credit / 2.0, 0.01) * 100.0
    qty = int(budget // max_loss_per)
    qty = max(min(qty, 5), 0)
    if qty < 1:
        return None

    entry_date = pd.Timestamp(entry_date).normalize()
    expiry = entry_date + pd.Timedelta(days=hold_dte)
    path = price_path.loc[(price_path.index > entry_date) & (price_path.index <= expiry)]
    if path.empty:
        return None

    tp_level = credit * (1.0 - profit_take)  # debit to close at 50% profit
    stop_level = credit * stop_mult

    exit_date = path.index[-1]
    exit_reason: ExitReason = "expiry"
    close_cost = credit  # fallback

    for dt, spot in path.items():
        remaining = max((expiry - pd.Timestamp(dt)).days, 0)
        if remaining <= 0:
            close_cost = _intrinsic_close_cost(
                structure,
                float(spot),
                width=width,
                short_delta=short_delta,
                entry_spot=entry_spot,
            )
            exit_date = pd.Timestamp(dt)
            exit_reason = "expiry"
            break
        iv = atm_iv_on_or_before(iv_history, ticker, pd.Timestamp(dt)) or entry_iv
        mark = approximate_structure_value(
            structure,
            float(spot),
            float(iv),
            width=width,
            short_delta=short_delta,
            dte=remaining,
        )
        if mark is None:
            continue
        if mark <= tp_level:
            close_cost = mark
            exit_date = pd.Timestamp(dt)
            exit_reason = "take_profit"
            break
        if mark >= stop_level:
            close_cost = mark
            exit_date = pd.Timestamp(dt)
            exit_reason = "stop"
            break
    else:
        # Finished path without break — settle last day
        last_dt = path.index[-1]
        last_spot = float(path.iloc[-1])
        remaining = max((expiry - pd.Timestamp(last_dt)).days, 0)
        if remaining <= 1:
            close_cost = _intrinsic_close_cost(
                structure,
                last_spot,
                width=width,
                short_delta=short_delta,
                entry_spot=entry_spot,
            )
            exit_reason = "expiry"
        else:
            iv = atm_iv_on_or_before(iv_history, ticker, pd.Timestamp(last_dt)) or entry_iv
            mark = approximate_structure_value(
                structure,
                last_spot,
                float(iv),
                width=width,
                short_delta=short_delta,
                dte=max(remaining, 1),
            )
            close_cost = mark if mark is not None else credit
            exit_reason = "expiry"
        exit_date = pd.Timestamp(last_dt)

    pnl_per = (credit - float(close_cost)) * 100.0
    pnl = pnl_per * qty
    return SleeveTradeResult(
        entry_date=entry_date,
        exit_date=pd.Timestamp(exit_date).normalize(),
        ticker=ticker.upper(),
        structure=structure,
        iv_rank=float("nan"),
        composite=float("nan"),
        credit=float(credit),
        width=float(width),
        qty=qty,
        pnl_usd=float(pnl),
        exit_reason=exit_reason,
        max_loss_usd=float(max_loss_per * qty),
    )


def _month_ends(dates: pd.DatetimeIndex) -> list[pd.Timestamp]:
    s = pd.Series(1, index=pd.DatetimeIndex(dates).normalize()).sort_index()
    # last available session per calendar month
    grouped = s.groupby([s.index.year, s.index.month]).apply(lambda x: x.index.max())
    return [pd.Timestamp(x).normalize() for x in grouped.tolist()]


def run_options_sleeve_backtest(
    iv_history: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    universe: Iterable[str] = PHASE1_OPTIONABLE_ETFS,
    mode: Literal["phase1", "always_skip", "naive_short_put"] = "phase1",
    kill_switch_active: bool = False,
    capital_usd: Optional[float] = None,
) -> pd.DataFrame:
    """
    Monthly entry loop over Phase 1 names.

    mode:
      - phase1: production Q1–Q4 map with IVR gate
      - always_skip: no trades (benchmark)
      - naive_short_put: always bull-put when IV+price exist (ignore IVR/composite)
    """
    # Per-trade budget mirrors options_orders (name margin cap), not full $25k each.
    if capital_usd is None:
        options_cap = float(getattr(config, "OPTIONS_PAPER_CAPITAL_USD", 25_000.0))
        per_trade_budget = min(max_name_margin_usd(), options_cap)
    else:
        per_trade_budget = float(capital_usd)
    prices = prices.copy()
    prices.index = pd.to_datetime(prices.index).normalize()
    prices = prices.sort_index()

    iv_min = pd.Timestamp(iv_history["as_of_date"].min())
    iv_max = pd.Timestamp(iv_history["as_of_date"].max())
    start_ts = pd.Timestamp(start) if start else iv_min
    end_ts = pd.Timestamp(end) if end else iv_max
    # Need lookback for IVR — skip first ~60 calendar days of the IV sample.
    trade_start = max(start_ts, iv_min + pd.Timedelta(days=60))

    sessions = prices.index[(prices.index >= trade_start) & (prices.index <= end_ts)]
    entries = [d for d in _month_ends(sessions) if trade_start <= d <= end_ts]

    trades: list[SleeveTradeResult] = []
    for entry in entries:
        composites = trailing_return_composites(prices, entry, universe=universe)
        for ticker in universe:
            ticker = str(ticker).upper()
            if ticker not in prices.columns:
                continue
            spot_series = prices[ticker].dropna()
            if entry not in spot_series.index:
                # nearest prior close
                prior = spot_series.loc[:entry]
                if prior.empty:
                    continue
                spot = float(prior.iloc[-1])
                entry_eff = pd.Timestamp(prior.index[-1])
            else:
                spot = float(spot_series.loc[entry])
                entry_eff = entry

            iv = atm_iv_on_or_before(iv_history, ticker, entry_eff)
            if iv is None:
                continue
            ivr = point_in_time_ivr(iv_history, ticker, entry_eff)
            if ivr is None and mode == "phase1":
                continue

            if mode == "always_skip":
                continue
            if mode == "naive_short_put":
                structure: Structure = "bull_put_spread"
                short_delta = 0.25
                composite = 0.0
                ivr_val = float(ivr) if ivr is not None else float("nan")
            else:
                composite = float(composites.get(ticker, 0.0))
                ivr_val = float(ivr)  # type: ignore[arg-type]
                signal = build_signal(
                    ticker,
                    composite,
                    ivr_val,
                    kill_switch_active=kill_switch_active,
                )
                if signal.structure in {"skip_low_iv", "skip_kill_switch"}:
                    continue
                structure = signal.structure
                short_delta = signal.short_delta

            result = simulate_credit_trade(
                structure,
                entry_eff,
                spot,
                float(iv),
                spot_series,
                iv_history,
                ticker,
                short_delta=short_delta,
                capital_budget=per_trade_budget,
            )
            if result is None:
                continue
            trades.append(
                SleeveTradeResult(
                    entry_date=result.entry_date,
                    exit_date=result.exit_date,
                    ticker=result.ticker,
                    structure=result.structure,
                    iv_rank=ivr_val,
                    composite=composite if mode != "naive_short_put" else float("nan"),
                    credit=result.credit,
                    width=result.width,
                    qty=result.qty,
                    pnl_usd=result.pnl_usd,
                    exit_reason=result.exit_reason,
                    max_loss_usd=result.max_loss_usd,
                )
            )

    if not trades:
        return pd.DataFrame(
            columns=[
                "entry_date",
                "exit_date",
                "ticker",
                "structure",
                "iv_rank",
                "composite",
                "credit",
                "width",
                "qty",
                "pnl_usd",
                "exit_reason",
                "max_loss_usd",
            ]
        )
    return pd.DataFrame([t.__dict__ for t in trades])


def summarize_sleeve_runs(
    runs: dict[str, pd.DataFrame],
    *,
    capital_usd: float,
    spy_prices: Optional[pd.Series] = None,
    start: Optional[pd.Timestamp] = None,
    end: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """Compare strategy modes + risk-matched SPY hold on options capital."""
    rows = []
    for name, df in runs.items():
        pnl = float(df["pnl_usd"].sum()) if not df.empty else 0.0
        n = int(len(df))
        wins = int((df["pnl_usd"] > 0).sum()) if n else 0
        rows.append(
            {
                "strategy": name,
                "n_trades": n,
                "total_pnl_usd": pnl,
                "return_on_sleeve_capital": pnl / capital_usd if capital_usd else 0.0,
                "win_rate": (wins / n) if n else float("nan"),
                "avg_pnl_per_trade": (pnl / n) if n else 0.0,
            }
        )

    if spy_prices is not None and start is not None and end is not None:
        s = spy_prices.dropna().sort_index()
        s = s.loc[(s.index >= start) & (s.index <= end)]
        if len(s) >= 2:
            spy_ret = float(s.iloc[-1] / s.iloc[0] - 1.0)
            rows.append(
                {
                    "strategy": "risk_matched_spy_hold",
                    "n_trades": 0,
                    "total_pnl_usd": spy_ret * capital_usd,
                    "return_on_sleeve_capital": spy_ret,
                    "win_rate": float("nan"),
                    "avg_pnl_per_trade": float("nan"),
                }
            )
    return pd.DataFrame(rows)
