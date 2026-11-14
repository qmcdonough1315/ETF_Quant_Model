#!/usr/bin/env python3
"""
Walk-forward ETF selector backtest.

Default: compound each holding window with production Target_Weight (Σ w_i r_i).
Ablation: --equal-weight uses the mean of ticker compounded returns.
Costs: --cost-bps one-way equity bps on dollars traded at rebalance.
Periods: --period FULL|COVID|... from config.BACKTEST_PERIODS / BACKTEST_PERIODS.md.

Research-card benchmarks: VOO, JEPI, VOO_JEPI_50_50, VGT (see config.RESEARCH_BENCHMARKS).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Optional

import pandas as pd

import config
from modules.backtest_returns import (
    apply_cost_ladder,
    net_period_return,
    normalize_weights,
    portfolio_period_return,
)
from modules.data_ingestion import fetch_all_data
from modules.dynamic_beta_estimator import run_kalman_filter_regressions
from modules.factor_forecaster import generate_factor_forecasts
from modules.fund_scorer import score_and_rank_funds
from modules.point_in_time import ken_french_asof
from modules.research_card import (
    holding_window_return,
    metrics_payload,
    required_benchmark_tickers,
    write_json,
)
from modules.walkforward_metrics import periods_per_year_from_step


def resolve_period(
    period_id: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
    rebalance_step_months: Optional[int],
) -> tuple[str, str, Optional[str], int, bool]:
    """Return (period_id, start, end|None, step_months, tune_allowed)."""
    if period_id:
        key = period_id.upper()
        if key not in config.BACKTEST_PERIODS:
            known = ", ".join(sorted(config.BACKTEST_PERIODS))
            raise SystemExit(f"Unknown --period {period_id!r}. Choose from: {known}")
        spec = config.BACKTEST_PERIODS[key]
        return (
            key,
            start_date or spec["start"],
            end_date if end_date is not None else spec.get("end"),
            int(rebalance_step_months or spec.get("rebalance_step_months") or config.FORECAST_HORIZON_MONTHS),
            bool(spec.get("tune", True)),
        )
    return (
        "CUSTOM",
        start_date or config.BACKTEST_PERIODS[config.BACKTEST_DEFAULT_PERIOD]["start"],
        end_date if end_date is not None else config.BACKTEST_PERIODS[config.BACKTEST_DEFAULT_PERIOD].get("end"),
        int(rebalance_step_months or config.FORECAST_HORIZON_MONTHS),
        True,
    )


def run_walkforward_backtest(
    start_date: str = "2019-01-31",
    end_date: Optional[str] = "2025-12-31",
    initial_capital: float = None,
    max_holdings: int = None,
    rebalance_step_months: int = 3,
    risk_free_rate: float = None,
    *,
    equal_weight: bool = False,
    cost_bps_one_way: float = None,
    period_id: str = "CUSTOM",
    universe: Optional[list[str]] = None,
    cost_sensitivity: bool = False,
    artifact_dir: Optional[str | Path] = None,
) -> pd.DataFrame:
    if initial_capital is None:
        initial_capital = float(config.RESEARCH_ETF_CAPITAL_USD)
    if max_holdings is None:
        max_holdings = config.MAX_HOLDINGS
    if cost_bps_one_way is None:
        cost_bps_one_way = float(
            getattr(config, "RESEARCH_EQUITY_COST_BPS_ONE_WAY", config.BACKTEST_EQUITY_COST_BPS_ONE_WAY)
        )
    if risk_free_rate is None:
        risk_free_rate = float(getattr(config, "RESEARCH_RISK_FREE_RATE", 0.03))

    periods_per_year = periods_per_year_from_step(rebalance_step_months)
    horizon_label = f"{rebalance_step_months}M"
    mode = "equal-weight ablation" if equal_weight else "production Target_Weight"
    traded_universe = [t.upper() for t in (universe or list(config.ETF_POPULATION))]
    sens_bps = tuple(
        float(x)
        for x in getattr(
            config, "BACKTEST_EQUITY_COST_SENSITIVITY_BPS", (0.0, 5.0, 10.0)
        )
    )
    bench_tickers = required_benchmark_tickers()
    bench_specs = config.RESEARCH_BENCHMARKS

    print("=" * 70)
    print(f"WALK-FORWARD BACKTEST [{period_id}] ({start_date} → {end_date or 'latest'})")
    print(f"Holding / rebalance step: {rebalance_step_months} months | mode: {mode}")
    print(f"Equity cost: {cost_bps_one_way:.1f} bps one-way on traded notional")
    print(f"ETF sleeve capital: ${initial_capital:,.2f}")
    if abs(float(cost_bps_one_way)) < 1e-12:
        print(
            "NOTE: 0 bps is the research-optimistic baseline — not a silent free-fill claim. "
            f"Run --cost-sensitivity for {sens_bps} bps ladder."
        )
    print(f"Universe size: {len(traded_universe)}")
    print(f"Benchmarks: {', '.join(bench_specs)}")
    print("=" * 70)

    all_etfs = list(set(traded_universe + bench_tickers + ["VTI", "SPY", "VOO"]))
    prices, factors, macro = fetch_all_data(all_etfs)

    print("Benchmark coverage:")
    for ticker in bench_tickers:
        if ticker in prices.columns:
            print(f"  • {ticker}: missing={int(prices[ticker].isna().sum())}")
        else:
            print(f"  • {ticker}: NOT IN DATA")

    def _to_timestamp_index(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        if isinstance(out.index, pd.PeriodIndex):
            out.index = out.index.to_timestamp()
        else:
            out.index = pd.to_datetime(out.index)
        return out

    prices = _to_timestamp_index(prices)
    factors = _to_timestamp_index(factors)
    macro = _to_timestamp_index(macro)

    looks_like_prices = bool((prices.iloc[0].abs() > 1.0).any())
    returns_df = prices.pct_change().dropna(how="all") if looks_like_prices else prices.copy()

    all_dates = returns_df.index
    end_ts = pd.Timestamp(end_date) if end_date else all_dates.max()
    rebalance_dates = all_dates[(all_dates >= start_date) & (all_dates <= end_ts)]

    if len(rebalance_dates) < rebalance_step_months + 1:
        print("Not enough date points to execute walk-forward steps.")
        return pd.DataFrame()

    first = rebalance_dates[0]
    cover = float(returns_df.loc[:first].notna().iloc[-1].mean()) if len(returns_df) else 0.0
    print(f"Universe column coverage at {first.strftime('%Y-%m')}: {cover:.1%}")

    strategy_value = float(initial_capital)
    bench_values = {bid: float(initial_capital) for bid in bench_specs}
    prev_weights: Optional[pd.Series] = None
    history: list[dict[str, Any]] = []

    for i in range(0, len(rebalance_dates) - rebalance_step_months, rebalance_step_months):
        current_date = rebalance_dates[i]
        holding_dates = rebalance_dates[i + 1 : i + 1 + rebalance_step_months]

        hist_returns = returns_df.loc[:current_date]
        # Ken French month T is not available at month-end T (publication lag).
        hist_factors = ken_french_asof(factors, current_date)
        hist_macro = macro.loc[:current_date]

        top_picks_df = pd.DataFrame()
        try:
            beta_profiles = run_kalman_filter_regressions(hist_returns, hist_factors)
            forecast_report = generate_factor_forecasts(
                hist_factors, hist_macro, threshold=config.MIN_FACTOR_THRESHOLD
            )
            top_picks_df, _top_betas_df, _scores_df = score_and_rank_funds(
                beta_profiles,
                forecast_report,
                prices=hist_returns,
                max_holdings=max_holdings,
            )
            selected_tickers = top_picks_df["Ticker"].tolist() if not top_picks_df.empty else []
        except Exception as e:  # noqa: BLE001 — keep walk-forward alive on single-date failures
            print(f"Warning on {current_date.strftime('%Y-%m-%d')}: {e}")
            selected_tickers = []

        cost = 0.0
        turnover = 0.0
        gross = 0.0
        if selected_tickers and not top_picks_df.empty:
            period_returns = returns_df.loc[holding_dates, selected_tickers]
            weights = top_picks_df.set_index("Ticker")["Target_Weight"]
            gross = portfolio_period_return(
                period_returns, weights, equal_weight=equal_weight
            )
            w_new = normalize_weights(weights)
            if equal_weight:
                w_new = pd.Series(1.0 / len(selected_tickers), index=selected_tickers, dtype=float)
            strat_ret, cost, turnover = net_period_return(
                gross, w_new, prev_weights, one_way_bps=cost_bps_one_way
            )
            prev_weights = w_new
        else:
            strat_ret = 0.0

        row: dict[str, Any] = {
            "Rebalance_Date": current_date.strftime("%Y-%m"),
            "Holding_Window": (
                f"{holding_dates[0].strftime('%Y-%m')} to {holding_dates[-1].strftime('%Y-%m')}"
            ),
            "Holding_Start": holding_dates[0].strftime("%Y-%m"),
            "Holding_End": holding_dates[-1].strftime("%Y-%m"),
            "Top_Picks": ", ".join(selected_tickers),
            f"Strategy_Return_{horizon_label}": strat_ret,
            "Gross_Return": gross,
            "Turnover": turnover,
            "Cost": cost,
        }

        strategy_value *= 1 + strat_ret
        row["Strategy_Value"] = strategy_value

        for bid, spec in bench_specs.items():
            br = holding_window_return(returns_df, holding_dates, spec["weights"])
            bench_values[bid] *= 1 + br
            row[f"{bid}_Return_{horizon_label}"] = float(br)
            row[f"{bid}_Value"] = bench_values[bid]

        history.append(row)

    results_df = pd.DataFrame(history)
    if results_df.empty:
        return results_df

    ret_col = f"Strategy_Return_{horizon_label}"
    peer = config.RESEARCH_HEADLINE_PEER
    peer_col = f"{peer}_Return_{horizon_label}"

    strat_summary = metrics_payload(
        results_df[ret_col],
        initial_capital=initial_capital,
        risk_free_rate=risk_free_rate,
        periods_per_year=periods_per_year,
        benchmark_returns=results_df[peer_col] if peer_col in results_df.columns else None,
        extra={
            "avg_turnover": float(results_df["Turnover"].mean()) if "Turnover" in results_df else 0.0,
            "total_costs": float(results_df["Cost"].sum()) if "Cost" in results_df else 0.0,
            "cost_bps_one_way": float(cost_bps_one_way),
            "coverage": cover,
            "equal_weight": bool(equal_weight),
        },
    )

    bench_summaries: dict[str, dict[str, Any]] = {}
    for bid in bench_specs:
        col = f"{bid}_Return_{horizon_label}"
        bench_summaries[bid] = metrics_payload(
            results_df[col],
            initial_capital=initial_capital,
            risk_free_rate=risk_free_rate,
            periods_per_year=periods_per_year,
        )

    print("\n" + "=" * 80)
    print("RISK-ADJUSTED PERFORMANCE COMPARISON (ETF sleeve)")
    print("=" * 80)

    rows_print = [
        (
            "Model Strategy (ETF)",
            strat_summary["final_value"],
            strat_summary["total_return"],
            strat_summary["ann_vol"],
            strat_summary["sharpe"],
            strat_summary["max_drawdown"],
        )
    ]
    for bid, spec in bench_specs.items():
        s = bench_summaries[bid]
        rows_print.append(
            (
                f"{bid} — {spec['label']}",
                s["final_value"],
                s["total_return"],
                s["ann_vol"],
                s["sharpe"],
                s["max_drawdown"],
            )
        )

    metrics_summary = pd.DataFrame(
        rows_print,
        columns=[
            "Asset / Strategy",
            "Final Value ($)",
            "Total Return (%)",
            "Ann. Volatility (%)",
            "Sharpe Ratio",
            "Max Drawdown (%)",
        ],
    )
    show = metrics_summary.copy()
    show["Final Value ($)"] = show["Final Value ($)"].map(lambda v: f"${v:,.2f}")
    show["Total Return (%)"] = show["Total Return (%)"].map(lambda v: f"{100 * v:+.2f}%")
    show["Ann. Volatility (%)"] = show["Ann. Volatility (%)"].map(lambda v: f"{100 * v:.2f}%")
    show["Sharpe Ratio"] = show["Sharpe Ratio"].map(lambda v: f"{v:.2f}")
    show["Max Drawdown (%)"] = show["Max Drawdown (%)"].map(lambda v: f"{100 * v:.2f}%")
    print(show.to_string(index=False))

    print(
        f"\nHit rate vs {peer}: {_fmt_pct(strat_summary.get('hit_rate_vs_benchmark'))} | "
        f"excess total vs {peer}: {_fmt_pct(strat_summary.get('excess_total_vs_benchmark'))}"
    )
    print(
        f"Avg turnover={strat_summary['avg_turnover']:.3f} | "
        f"total costs deducted={strat_summary['total_costs']:.4%} "
        f"@ {cost_bps_one_way:.1f} bps one-way"
    )

    if cost_sensitivity and "Gross_Return" in results_df.columns:
        ladder = apply_cost_ladder(
            results_df["Gross_Return"],
            results_df["Turnover"],
            sens_bps,
            initial_capital=initial_capital,
            risk_free_rate=risk_free_rate,
            periods_per_year=periods_per_year,
        )
        print("\n" + "=" * 80)
        print("EQUITY COST SENSITIVITY (same gross path / turnover; 0 / 5 / 10 bps)")
        print("=" * 80)
        show_l = ladder.copy()
        show_l["final_value"] = show_l["final_value"].map(lambda v: f"${v:,.2f}")
        show_l["total_return"] = show_l["total_return"].map(lambda v: f"{v*100:+.2f}%")
        show_l["total_costs"] = show_l["total_costs"].map(lambda v: f"{v:.4%}")
        show_l["avg_turnover"] = show_l["avg_turnover"].map(lambda v: f"{v:.3f}")
        show_l["sharpe"] = show_l["sharpe"].map(lambda v: f"{v:.2f}")
        print(show_l.to_string(index=False))
        results_df.attrs["cost_sensitivity"] = ladder

    print("=" * 80 + "\n")

    results_df.attrs["period_id"] = period_id
    results_df.attrs["coverage"] = cover
    results_df.attrs["strategy_summary"] = strat_summary
    results_df.attrs["benchmark_summaries"] = bench_summaries
    results_df.attrs["horizon_label"] = horizon_label
    results_df.attrs["periods_per_year"] = periods_per_year
    results_df.attrs["initial_capital"] = initial_capital
    results_df.attrs["risk_free_rate"] = risk_free_rate
    results_df.attrs["cost_bps_one_way"] = cost_bps_one_way
    results_df.attrs["start_date"] = start_date
    results_df.attrs["end_date"] = end_date

    if artifact_dir:
        _write_period_artifacts(Path(artifact_dir), period_id, results_df)

    return results_df


def _write_period_artifacts(artifact_dir: Path, period_id: str, results_df: pd.DataFrame) -> None:
    out = Path(artifact_dir) / period_id
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "period_id": period_id,
        "start": results_df.attrs.get("start_date"),
        "end": results_df.attrs.get("end_date"),
        "coverage": results_df.attrs.get("coverage"),
        "etf": results_df.attrs.get("strategy_summary"),
        "benchmarks": results_df.attrs.get("benchmark_summaries"),
        "horizon_label": results_df.attrs.get("horizon_label"),
        "cost_bps_one_way": results_df.attrs.get("cost_bps_one_way"),
    }
    # JSON first (smaller / less brittle on some artifact mounts); CSV best-effort.
    write_json(out / "summary.json", summary)
    try:
        results_df.to_csv(out / "steps.csv", index=False)
    except OSError as e:  # noqa: BLE001 — keep run alive if artifact FS flakes
        fallback = Path("artifacts") / "walkforward" / period_id
        fallback.mkdir(parents=True, exist_ok=True)
        results_df.to_csv(fallback / "steps.csv", index=False)
        write_json(fallback / "summary.json", summary)
        print(f"WARNING: steps.csv write failed ({e}); wrote fallback under {fallback}")
    print(f"Wrote ETF artifacts under {out}")


def _fmt_pct(x: Any) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "n/a"
    if v != v:
        return "n/a"
    return f"{100 * v:+.2f}%"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--period",
        default=config.BACKTEST_DEFAULT_PERIOD,
        help=f"Period id from config.BACKTEST_PERIODS (default {config.BACKTEST_DEFAULT_PERIOD})",
    )
    parser.add_argument("--start", default=None, help="Override period start YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="Override period end YYYY-MM-DD")
    parser.add_argument(
        "--capital",
        type=float,
        default=None,
        help=f"ETF sleeve capital (default research {config.RESEARCH_ETF_CAPITAL_USD})",
    )
    parser.add_argument("--max-holdings", type=int, default=None)
    parser.add_argument("--step-months", type=int, default=None, help="Override rebalance step")
    parser.add_argument(
        "--equal-weight",
        action="store_true",
        help="Ablation: mean of ticker returns instead of Target_Weight",
    )
    parser.add_argument(
        "--cost-bps",
        type=float,
        default=None,
        help="One-way equity cost bps (default RESEARCH_EQUITY_COST_BPS_ONE_WAY)",
    )
    parser.add_argument(
        "--cost-sensitivity",
        action="store_true",
        help="After one walk-forward, report 0/5/10 bps ladder on the same gross/turnover path",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Fast end-to-end check on a tiny liquid universe (still real data; not demo)",
    )
    parser.add_argument(
        "--artifact-dir",
        default=None,
        help="If set, write steps.csv + summary.json under <dir>/<PERIOD>/",
    )
    args = parser.parse_args()

    period_id, start, end, step, tune = resolve_period(
        args.period, args.start, args.end, args.step_months
    )
    universe = None
    if args.smoke:
        universe = ["SPY", "QQQ", "IWM", "XLK", "XLF", "XLE", "XLV", "VTI", "VGT", "VOO", "JEPI"]
        if args.period == config.BACKTEST_DEFAULT_PERIOD and args.start is None:
            period_id, start, end, step, tune = resolve_period(
                "COVID", args.start, args.end, args.step_months
            )
        print(f"SMOKE mode: universe={universe} period={period_id}")

    if not tune:
        print(
            f"NOTE: period {period_id} is marked tune=False (HOLD_OUT). "
            "Use for reporting only — do not fit hyperparameters on this slice."
        )

    run_walkforward_backtest(
        start_date=start,
        end_date=end,
        initial_capital=args.capital,
        max_holdings=args.max_holdings,
        rebalance_step_months=step,
        equal_weight=args.equal_weight,
        cost_bps_one_way=args.cost_bps,
        period_id=period_id,
        universe=universe,
        cost_sensitivity=bool(args.cost_sensitivity),
        artifact_dir=args.artifact_dir,
    )


if __name__ == "__main__":
    main()
