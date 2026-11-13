#!/usr/bin/env python3
"""
Walk-forward ETF selector backtest.

Default: compound each holding window with production Target_Weight (Σ w_i r_i).
Ablation: --equal-weight uses the mean of ticker compounded returns.
Costs: --cost-bps one-way equity bps on dollars traded at rebalance (see modules/backtest_returns.py).
Periods: --period FULL|COVID|... from config.BACKTEST_PERIODS / BACKTEST_PERIODS.md.
"""

from __future__ import annotations

import argparse
from typing import Optional

import numpy as np
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


def calculate_sharpe_ratio(
    returns_series: pd.Series,
    risk_free_rate: float = 0.03,
    periods_per_year: float = 4.0,
) -> float:
    """Annualized Sharpe for fixed-horizon period returns."""
    if returns_series is None or len(returns_series) == 0 or returns_series.std() == 0:
        return 0.0

    mean_period_ret = float(returns_series.mean())
    std_period_ret = float(returns_series.std())
    rf_period = (1 + risk_free_rate) ** (1 / periods_per_year) - 1
    return ((mean_period_ret - rf_period) * periods_per_year) / (
        std_period_ret * np.sqrt(periods_per_year)
    )


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
    initial_capital: float = 10000.0,
    max_holdings: int = None,
    rebalance_step_months: int = 3,
    risk_free_rate: float = 0.03,
    *,
    equal_weight: bool = False,
    cost_bps_one_way: float = None,
    period_id: str = "CUSTOM",
    universe: Optional[list[str]] = None,
    cost_sensitivity: bool = False,
):
    if max_holdings is None:
        max_holdings = config.MAX_HOLDINGS
    if cost_bps_one_way is None:
        cost_bps_one_way = float(getattr(config, "BACKTEST_EQUITY_COST_BPS_ONE_WAY", 0.0))

    periods_per_year = 12.0 / float(rebalance_step_months)
    horizon_label = f"{rebalance_step_months}M"
    mode = "equal-weight ablation" if equal_weight else "production Target_Weight"
    traded_universe = [t.upper() for t in (universe or list(config.ETF_POPULATION))]
    sens_bps = tuple(
        float(x)
        for x in getattr(
            config, "BACKTEST_EQUITY_COST_SENSITIVITY_BPS", (0.0, 5.0, 10.0)
        )
    )

    print("=" * 70)
    print(f"WALK-FORWARD BACKTEST [{period_id}] ({start_date} → {end_date or 'latest'})")
    print(f"Holding / rebalance step: {rebalance_step_months} months | mode: {mode}")
    print(f"Equity cost: {cost_bps_one_way:.1f} bps one-way on traded notional")
    if abs(float(cost_bps_one_way)) < 1e-12:
        print(
            "NOTE: 0 bps is the research-optimistic baseline — not a silent free-fill claim. "
            f"Run --cost-sensitivity for {sens_bps} bps ladder."
        )
    print(f"Universe size: {len(traded_universe)} | Starting capital: ${initial_capital:,.2f}")
    print("=" * 70)

    all_etfs = list(set(traded_universe + ["VTI", "SPY", "VGT", "VOO"]))
    prices, factors, macro = fetch_all_data(all_etfs)

    print("Benchmark coverage:")
    for ticker in ["VTI", "SPY", "VGT", "VOO"]:
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

    # data_ingestion already returns monthly returns for ETFs; don't pct_change twice.
    looks_like_prices = bool((prices.iloc[0].abs() > 1.0).any())
    returns_df = prices.pct_change().dropna(how="all") if looks_like_prices else prices.copy()

    all_dates = returns_df.index
    end_ts = pd.Timestamp(end_date) if end_date else all_dates.max()
    rebalance_dates = all_dates[(all_dates >= start_date) & (all_dates <= end_ts)]

    if len(rebalance_dates) < rebalance_step_months + 1:
        print("Not enough date points to execute walk-forward steps.")
        return pd.DataFrame()

    # Coverage diagnostic at first rebalance (universe readiness).
    first = rebalance_dates[0]
    cover = float(returns_df.loc[:first].notna().iloc[-1].mean()) if len(returns_df) else 0.0
    print(f"Universe column coverage at {first.strftime('%Y-%m')}: {cover:.1%}")

    strategy_value = initial_capital
    vti_value = initial_capital
    spy_value = initial_capital
    vgt_value = initial_capital

    prev_weights: Optional[pd.Series] = None
    history = []

    for i in range(0, len(rebalance_dates) - rebalance_step_months, rebalance_step_months):
        current_date = rebalance_dates[i]
        holding_dates = rebalance_dates[i + 1 : i + 1 + rebalance_step_months]

        hist_returns = returns_df.loc[:current_date]
        hist_factors = factors.loc[:current_date]
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
            # Staying in cash: no weight update.

        vti_ret = (
            ((1 + returns_df.loc[holding_dates, "VTI"]).prod() - 1)
            if "VTI" in returns_df.columns
            else 0.0
        )
        spy_ret = (
            ((1 + returns_df.loc[holding_dates, "SPY"]).prod() - 1)
            if "SPY" in returns_df.columns
            else 0.0
        )
        vgt_ret = (
            ((1 + returns_df.loc[holding_dates, "VGT"]).prod() - 1)
            if "VGT" in returns_df.columns
            else 0.0
        )

        strategy_value *= 1 + strat_ret
        vti_value *= 1 + vti_ret
        spy_value *= 1 + spy_ret
        vgt_value *= 1 + vgt_ret

        history.append(
            {
                "Rebalance_Date": current_date.strftime("%Y-%m"),
                "Holding_Window": (
                    f"{holding_dates[0].strftime('%Y-%m')} to {holding_dates[-1].strftime('%Y-%m')}"
                ),
                "Top_Picks": ", ".join(selected_tickers),
                f"Strategy_Return_{horizon_label}": strat_ret,
                "Gross_Return": gross,
                f"VTI_Return_{horizon_label}": float(vti_ret),
                f"SPY_Return_{horizon_label}": float(spy_ret),
                f"VGT_Return_{horizon_label}": float(vgt_ret),
                "Turnover": turnover,
                "Cost": cost,
                "Strategy_Value": strategy_value,
                "VTI_Value": vti_value,
                "SPY_Value": spy_value,
                "VGT_Value": vgt_value,
            }
        )

    results_df = pd.DataFrame(history)
    if results_df.empty:
        return results_df

    ret_col = f"Strategy_Return_{horizon_label}"
    vti_col = f"VTI_Return_{horizon_label}"
    spy_col = f"SPY_Return_{horizon_label}"
    vgt_col = f"VGT_Return_{horizon_label}"

    strat_sharpe = calculate_sharpe_ratio(results_df[ret_col], risk_free_rate, periods_per_year)
    vti_sharpe = calculate_sharpe_ratio(results_df[vti_col], risk_free_rate, periods_per_year)
    spy_sharpe = calculate_sharpe_ratio(results_df[spy_col], risk_free_rate, periods_per_year)
    vgt_sharpe = calculate_sharpe_ratio(results_df[vgt_col], risk_free_rate, periods_per_year)

    ann_vol = lambda s: float(s.std() * np.sqrt(periods_per_year) * 100)

    strat_tot_ret = ((strategy_value / initial_capital) - 1) * 100
    vti_tot_ret = ((vti_value / initial_capital) - 1) * 100
    spy_tot_ret = ((spy_value / initial_capital) - 1) * 100
    vgt_tot_ret = ((vgt_value / initial_capital) - 1) * 100

    print("\n" + "=" * 80)
    print("RISK-ADJUSTED PERFORMANCE COMPARISON")
    print("=" * 80)

    metrics_summary = pd.DataFrame(
        {
            "Asset / Strategy": [
                "Model Strategy",
                "VTI (Total Market)",
                "SPY (S&P 500)",
                "VGT (Tech Focus)",
            ],
            "Final Value ($)": [
                f"${strategy_value:,.2f}",
                f"${vti_value:,.2f}",
                f"${spy_value:,.2f}",
                f"${vgt_value:,.2f}",
            ],
            "Total Return (%)": [
                f"{strat_tot_ret:+.2f}%",
                f"{vti_tot_ret:+.2f}%",
                f"{spy_tot_ret:+.2f}%",
                f"{vgt_tot_ret:+.2f}%",
            ],
            "Ann. Volatility (%)": [
                f"{ann_vol(results_df[ret_col]):.2f}%",
                f"{ann_vol(results_df[vti_col]):.2f}%",
                f"{ann_vol(results_df[spy_col]):.2f}%",
                f"{ann_vol(results_df[vgt_col]):.2f}%",
            ],
            "Sharpe Ratio": [
                f"{strat_sharpe:.2f}",
                f"{vti_sharpe:.2f}",
                f"{spy_sharpe:.2f}",
                f"{vgt_sharpe:.2f}",
            ],
        }
    )

    print(metrics_summary.to_string(index=False))
    if "Cost" in results_df.columns:
        print(
            f"\nAvg turnover={results_df['Turnover'].mean():.3f} | "
            f"total costs deducted={results_df['Cost'].sum():.4%} "
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
        show = ladder.copy()
        show["final_value"] = show["final_value"].map(lambda v: f"${v:,.2f}")
        show["total_return"] = show["total_return"].map(lambda v: f"{v*100:+.2f}%")
        show["total_costs"] = show["total_costs"].map(lambda v: f"{v:.4%}")
        show["avg_turnover"] = show["avg_turnover"].map(lambda v: f"{v:.3f}")
        show["sharpe"] = show["sharpe"].map(lambda v: f"{v:.2f}")
        show = show.rename(
            columns={
                "cost_bps_one_way": "bps",
                "final_value": "Final Value",
                "total_return": "Total Return",
                "total_costs": "Total Costs",
                "avg_turnover": "Avg Turnover",
                "sharpe": "Sharpe",
            }
        )
        print(show.to_string(index=False))
        print(
            "\nHow costs affect headline Sharpe: higher one-way bps shrinks net period "
            "returns one-for-one with turnover×bps; Sharpe usually falls unless turnover "
            "is near zero. Prefer the 5–10 bps columns for implementation realism."
        )
        print("=" * 80 + "\n")
        results_df.attrs["cost_sensitivity"] = ladder

    print("=" * 80 + "\n")

    return results_df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--period",
        default=config.BACKTEST_DEFAULT_PERIOD,
        help=f"Period id from config.BACKTEST_PERIODS (default {config.BACKTEST_DEFAULT_PERIOD})",
    )
    parser.add_argument("--start", default=None, help="Override period start YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="Override period end YYYY-MM-DD")
    parser.add_argument("--capital", type=float, default=10000.0)
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
        help="One-way equity cost bps (default config.BACKTEST_EQUITY_COST_BPS_ONE_WAY)",
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
    args = parser.parse_args()

    period_id, start, end, step, tune = resolve_period(
        args.period, args.start, args.end, args.step_months
    )
    universe = None
    if args.smoke:
        # Real prices only — small sleeve so CI/agents can finish quickly.
        universe = ["SPY", "QQQ", "IWM", "XLK", "XLF", "XLE", "XLV", "VTI", "VGT", "VOO"]
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
    )


if __name__ == "__main__":
    main()
