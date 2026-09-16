import pandas as pd
import numpy as np
import config

from modules.fund_scorer import score_and_rank_funds
from modules.dynamic_beta_estimator import run_kalman_filter_regressions
from modules.factor_forecaster import generate_factor_forecasts


def _period_label(ts) -> str:
    if hasattr(ts, "strftime"):
        return ts.strftime("%Y-%m")
    return str(ts)


def run_historical_backtest(
    start_date: str,
    end_date: str,
    df_etfs: pd.DataFrame,
    df_factors: pd.DataFrame,
    df_macro: pd.DataFrame,
    initial_capital: float = 10000.0,
    top_n: int = 10,
    rebalance_step_months: int = None,
):
    """
    Walk-forward portfolio rotation matched to the forecast / holding horizon.
    """
    if rebalance_step_months is None:
        rebalance_step_months = config.FORECAST_HORIZON_MONTHS

    horizon_label = f"{rebalance_step_months}M"

    print(f"🚀 Starting Backtest from {start_date} to {end_date}")
    print(f"📅 Holding / rebalance horizon: {rebalance_step_months} months")
    print(f"💰 Initial Capital: ${initial_capital:,.2f}\n")

    all_dates = df_etfs.index
    test_dates = all_dates[(all_dates >= start_date) & (all_dates <= end_date)]

    portfolio_value = initial_capital
    history = []

    for i in range(0, len(test_dates) - rebalance_step_months, rebalance_step_months):
        current_date = test_dates[i]
        holding_dates = test_dates[i + 1 : i + 1 + rebalance_step_months]

        print(
            f"\n--- Rebalance Date: {_period_label(current_date)} | "
            f"Holding: {_period_label(holding_dates[0])} to {_period_label(holding_dates[-1])} ---"
        )

        hist_etfs = df_etfs.loc[:current_date]
        hist_factors = df_factors.loc[:current_date]
        hist_macro = df_macro.loc[:current_date]

        beta_profiles = run_kalman_filter_regressions(hist_etfs, hist_factors)
        forecast_report = generate_factor_forecasts(hist_factors, hist_macro)

        top_picks_df, _top_betas_df = score_and_rank_funds(
            beta_profiles,
            forecast_report,
            prices=hist_etfs,
            top_n=top_n,
        )

        if top_picks_df.empty:
            print("⚠️ No valid picks returned. Holding cash.")
            period_return = 0.0
            selected_tickers = []
        else:
            selected_tickers = top_picks_df["Ticker"].tolist()
            period_returns = df_etfs.loc[holding_dates, selected_tickers]
            compounded_ticker_returns = (1 + period_returns).prod(axis=0) - 1

            weights = top_picks_df.set_index("Ticker")["Target_Weight"]
            weights = weights.reindex(compounded_ticker_returns.index).fillna(0.0)
            if weights.sum() > 0:
                weights = weights / weights.sum()
                period_return = float((compounded_ticker_returns * weights).sum())
            else:
                period_return = float(compounded_ticker_returns.mean())

        portfolio_value *= 1 + period_return

        voo_ret = (
            ((1 + df_etfs.loc[holding_dates, "VOO"]).prod() - 1)
            if "VOO" in df_etfs.columns
            else 0.0
        )
        ftec_ret = (
            ((1 + df_etfs.loc[holding_dates, "FTEC"]).prod() - 1)
            if "FTEC" in df_etfs.columns
            else 0.0
        )

        history.append(
            {
                "Rebalance_Date": _period_label(current_date),
                "Holding_Period": (
                    f"{_period_label(holding_dates[0])} to {_period_label(holding_dates[-1])}"
                ),
                "Top_Picks": ", ".join(selected_tickers),
                f"Strategy_Return_{horizon_label}": period_return,
                f"VOO_Return_{horizon_label}": voo_ret,
                f"FTEC_Return_{horizon_label}": ftec_ret,
                "Strategy_Value": portfolio_value,
            }
        )

    return pd.DataFrame(history)
