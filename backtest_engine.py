import pandas as pd
import config

from modules.backtest_returns import net_period_return, normalize_weights, portfolio_period_return
from modules.fund_scorer import score_and_rank_funds
from modules.dynamic_beta_estimator import run_kalman_filter_regressions
from modules.factor_forecaster import generate_factor_forecasts
from modules.point_in_time import ken_french_asof


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
    max_holdings: int = None,
    rebalance_step_months: int = None,
    *,
    equal_weight: bool = False,
    cost_bps_one_way: float = None,
):
    """
    Walk-forward portfolio rotation matched to the forecast / holding horizon.

    Uses production Target_Weight by default (Σ w_i r_i). Set equal_weight=True for ablation.
    """
    if rebalance_step_months is None:
        rebalance_step_months = config.FORECAST_HORIZON_MONTHS
    if max_holdings is None:
        max_holdings = config.MAX_HOLDINGS
    if cost_bps_one_way is None:
        cost_bps_one_way = float(getattr(config, "BACKTEST_EQUITY_COST_BPS_ONE_WAY", 0.0))

    horizon_label = f"{rebalance_step_months}M"
    mode = "equal-weight ablation" if equal_weight else "production Target_Weight"

    print(f"Starting Backtest from {start_date} to {end_date}")
    print(f"Holding / rebalance horizon: {rebalance_step_months} months | {mode}")
    print(f"Equity cost: {cost_bps_one_way:.1f} bps one-way")
    print(f"Initial Capital: ${initial_capital:,.2f}\n")

    all_dates = df_etfs.index
    test_dates = all_dates[(all_dates >= start_date) & (all_dates <= end_date)]

    portfolio_value = initial_capital
    prev_weights = None
    history = []

    for i in range(0, len(test_dates) - rebalance_step_months, rebalance_step_months):
        current_date = test_dates[i]
        holding_dates = test_dates[i + 1 : i + 1 + rebalance_step_months]

        print(
            f"\n--- Rebalance Date: {_period_label(current_date)} | "
            f"Holding: {_period_label(holding_dates[0])} to {_period_label(holding_dates[-1])} ---"
        )

        hist_etfs = df_etfs.loc[:current_date]
        hist_factors = ken_french_asof(df_factors, current_date)
        hist_macro = df_macro.loc[:current_date]

        beta_profiles = run_kalman_filter_regressions(hist_etfs, hist_factors)
        forecast_report = generate_factor_forecasts(hist_factors, hist_macro)

        top_picks_df, _top_betas_df, _scores_df = score_and_rank_funds(
            beta_profiles,
            forecast_report,
            prices=hist_etfs,
            max_holdings=max_holdings,
        )

        cost = 0.0
        turnover = 0.0
        if top_picks_df.empty:
            print("No valid picks returned. Holding cash.")
            period_return = 0.0
            selected_tickers = []
        else:
            selected_tickers = top_picks_df["Ticker"].tolist()
            period_returns = df_etfs.loc[holding_dates, selected_tickers]
            weights = top_picks_df.set_index("Ticker")["Target_Weight"]
            gross = portfolio_period_return(
                period_returns, weights, equal_weight=equal_weight
            )
            w_new = normalize_weights(weights)
            if equal_weight:
                w_new = pd.Series(
                    1.0 / len(selected_tickers), index=selected_tickers, dtype=float
                )
            period_return, cost, turnover = net_period_return(
                gross, w_new, prev_weights, one_way_bps=cost_bps_one_way
            )
            prev_weights = w_new

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
                "Turnover": turnover,
                "Cost": cost,
                "Strategy_Value": portfolio_value,
            }
        )

    return pd.DataFrame(history)
