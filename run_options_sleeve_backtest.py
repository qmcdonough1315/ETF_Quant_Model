#!/usr/bin/env python3
"""
Point-in-time options sleeve backtest (checklist #10).

Uses stored ATM IV → IVR only (no demo IV). Periods from config.BACKTEST_PERIODS /
BACKTEST_PERIODS.md. When IV history does not cover a named stress window, the
run reports the overlap and refuses to invent data.

Examples:
  PYTHONPATH=. python3 run_options_sleeve_backtest.py --from-supabase
  PYTHONPATH=. python3 run_options_sleeve_backtest.py --iv-csv data/option_iv_history/atm_iv_from_supabase.csv
  PYTHONPATH=. python3 run_options_sleeve_backtest.py --period HOLD_OUT --from-supabase
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

import config
from modules.options_sleeve import PHASE1_OPTIONABLE_ETFS
from modules.options_sleeve_backtest import (
    load_iv_history,
    run_options_sleeve_backtest,
    summarize_sleeve_runs,
)


LIMITATIONS = """
LIMITATIONS (read before trusting numbers)
- No historical option chains: strikes are OTM% proxies; marks are Black–Scholes
  with stored ATM IV (flat smile). Not fantasy fills of live mids, but also not
  exchange prints.
- Entry credit is softened by OPTIONS_FILL_CREDIT_FRACTION (mid→limit conservatism).
- Per-trade size uses the production per-name margin cap (~2% of book), not the
  full $25k sleeve on every ticker. Concurrent multi-name risk is not netted to a
  hard sleeve ceiling — treat aggregate P&L as an upper-bound research view.
- Factor axis uses trailing ~3M return z-scores as a stand-in for weekly
  Total_Expected_Return_3M composites — same ±0.5 gates, different signal source.
- IV history quality bounds the sample. Multi-year COVID/BEAR_22 need deeper
  option_iv_history (Wave E / #8). We never synthesize IVR.
- Ignores early exercise, pin, ex-div, borrow, and assignment (see future #11).
"""


def resolve_period(period_id: Optional[str]) -> tuple[str, Optional[str], Optional[str]]:
    if not period_id:
        return "IV_OVERLAP", None, None
    key = period_id.upper()
    if key not in config.BACKTEST_PERIODS:
        known = ", ".join(sorted(config.BACKTEST_PERIODS))
        raise SystemExit(f"Unknown --period {period_id!r}. Choose from: {known}")
    spec = config.BACKTEST_PERIODS[key]
    return key, spec.get("start"), spec.get("end")


def fetch_daily_prices(tickers: list[str], start: str, end: Optional[str]) -> pd.DataFrame:
    end_download = None
    if end:
        # yfinance end is exclusive-ish; pad a few days
        end_download = (pd.Timestamp(end) + pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    raw = yf.download(
        tickers,
        start=start,
        end=end_download,
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if isinstance(raw.columns, pd.MultiIndex):
        px = raw["Close"].copy()
    else:
        px = raw[["Close"]].copy() if "Close" in raw.columns else raw.copy()
        if len(tickers) == 1:
            px.columns = [tickers[0]]
    px.index = pd.to_datetime(px.index).tz_localize(None).normalize()
    px = px.sort_index()
    px.columns = [str(c).upper() for c in px.columns]
    return px


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", default=None, help="BACKTEST_PERIODS id (optional)")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--iv-csv", default=None, help="Path to option_iv_history CSV")
    parser.add_argument(
        "--from-supabase",
        action="store_true",
        help="Pull option_iv_history when local CSV missing",
    )
    parser.add_argument(
        "--artifact",
        default="/opt/cursor/artifacts/options_sleeve_backtest_metrics.md",
        help="Markdown metrics table path",
    )
    parser.add_argument("--capital", type=float, default=None)
    args = parser.parse_args()

    period_id, p_start, p_end = resolve_period(args.period)
    start = args.start or p_start
    end = args.end if args.end is not None else p_end

    print("=" * 72)
    print(f"OPTIONS SLEEVE BACKTEST [{period_id}]")
    print("=" * 72)
    print(LIMITATIONS)

    iv = load_iv_history(args.iv_csv, from_supabase=args.from_supabase)
    iv_start, iv_end = iv["as_of_date"].min(), iv["as_of_date"].max()
    print(f"IV history: {len(iv)} rows | {iv_start.date()} → {iv_end.date()}")
    print(f"Tickers: {sorted(iv['ticker'].unique())}")

    # Clamp requested window to IV availability (never invent).
    req_start = pd.Timestamp(start) if start else iv_start
    req_end = pd.Timestamp(end) if end else iv_end
    use_start = max(req_start, iv_start)
    use_end = min(req_end, iv_end)
    if use_start > use_end:
        raise SystemExit(
            f"No overlap between requested [{req_start.date()} → {req_end.date()}] "
            f"and IV history [{iv_start.date()} → {iv_end.date()}]. "
            "Backfill option_iv_history (#8) before running this stress window."
        )
    if use_start != req_start or use_end != req_end:
        print(
            f"NOTE: clamped period to IV overlap {use_start.date()} → {use_end.date()} "
            f"(requested {req_start.date()} → {req_end.date()})"
        )

    capital = float(
        args.capital
        if args.capital is not None
        else getattr(config, "OPTIONS_PAPER_CAPITAL_USD", 25_000.0)
    )
    tickers = list(PHASE1_OPTIONABLE_ETFS)
    # Pull a bit of prehistory for trailing composites / IVR warm-up.
    dl_start = (use_start - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    prices = fetch_daily_prices(tickers, dl_start, use_end.strftime("%Y-%m-%d"))
    print(f"Daily prices: {prices.shape[0]} sessions × {prices.shape[1]} names")

    runs = {
        "phase1_rules": run_options_sleeve_backtest(
            iv,
            prices,
            start=str(use_start.date()),
            end=str(use_end.date()),
            mode="phase1",
            capital_usd=capital,
        ),
        "always_skip": run_options_sleeve_backtest(
            iv,
            prices,
            start=str(use_start.date()),
            end=str(use_end.date()),
            mode="always_skip",
            capital_usd=capital,
        ),
        "naive_short_put": run_options_sleeve_backtest(
            iv,
            prices,
            start=str(use_start.date()),
            end=str(use_end.date()),
            mode="naive_short_put",
            capital_usd=capital,
        ),
    }

    spy = prices["SPY"] if "SPY" in prices.columns else None
    summary = summarize_sleeve_runs(
        runs,
        capital_usd=capital,
        spy_prices=spy,
        start=use_start,
        end=use_end,
    )

    print("\n" + "=" * 72)
    print("BENCHMARK SUMMARY")
    print("=" * 72)
    show = summary.copy()
    show["total_pnl_usd"] = show["total_pnl_usd"].map(lambda v: f"${v:,.2f}")
    show["return_on_sleeve_capital"] = show["return_on_sleeve_capital"].map(
        lambda v: f"{v*100:+.2f}%"
    )
    show["win_rate"] = show["win_rate"].map(
        lambda v: "n/a" if pd.isna(v) else f"{v*100:.1f}%"
    )
    show["avg_pnl_per_trade"] = show["avg_pnl_per_trade"].map(
        lambda v: "n/a" if pd.isna(v) else f"${v:,.2f}"
    )
    print(show.to_string(index=False))

    phase = runs["phase1_rules"]
    if not phase.empty:
        print("\nExit reason counts (phase1):")
        print(phase["exit_reason"].value_counts().to_string())
        print("\nSample trades:")
        print(
            phase.head(8)[
                [
                    "entry_date",
                    "ticker",
                    "structure",
                    "iv_rank",
                    "pnl_usd",
                    "exit_reason",
                ]
            ].to_string(index=False)
        )

    artifact = Path(args.artifact)
    artifact.parent.mkdir(parents=True, exist_ok=True)

    def _md_table(df: pd.DataFrame) -> str:
        cols = list(df.columns)
        header = "| " + " | ".join(str(c) for c in cols) + " |"
        sep = "| " + " | ".join("---" for _ in cols) + " |"
        body = [
            "| " + " | ".join(str(row[c]) for c in cols) + " |"
            for _, row in df.iterrows()
        ]
        return "\n".join([header, sep, *body])

    lines = [
        f"# Options sleeve backtest — {period_id}",
        "",
        f"- Window used: `{use_start.date()}` → `{use_end.date()}`",
        f"- IV rows: {len(iv)} ({iv_start.date()} → {iv_end.date()})",
        f"- Sleeve capital (benchmark denominator): ${capital:,.0f}",
        f"- Per-trade sizing budget: name margin cap (see `max_name_margin_usd`)",
        "",
        "## Benchmarks",
        "",
        _md_table(summary),
        "",
        "## Limitations",
        LIMITATIONS,
    ]
    if not phase.empty:
        exit_df = phase["exit_reason"].value_counts().rename_axis("exit_reason").reset_index(name="count")
        lines.extend(["", "## Phase 1 exit reasons", "", _md_table(exit_df)])
    artifact.write_text("\n".join(lines))
    print(f"\nWrote artifact: {artifact}")


if __name__ == "__main__":
    main()
