import pandas as pd
import numpy as np

from modules.fund_scorer import score_and_rank_funds
from modules.dynamic_beta_estimator import run_kalman_filter_regressions
from modules.factor_forecaster import generate_factor_forecasts 

def run_historical_backtest(
    start_date: str, 
    end_date: str, 
    df_etfs: pd.DataFrame, 
    df_factors: pd.DataFrame,
    df_macro: pd.DataFrame,
    initial_capital: float = 10000.0,
    top_n: int = 10,
    rebalance_step_months: int = 6  # Updated to match 6-month horizon
):
    """
    Simulates a walk-forward portfolio rotation strategy matched to a 6-month holding period.
    """
    print(f"🚀 Starting Backtest from {start_date} to {end_date}")
    print(f"💰 Initial Capital: ${initial_capital:,.2f}\n")

    all_dates = df_etfs.index
    test_dates = all_dates[(all_dates >= start_date) & (all_dates <= end_date)]
    
    portfolio_value = initial_capital
    history = []

    # Step forward by 6 months instead of 1 month
    for i in range(0, len(test_dates) - rebalance_step_months, rebalance_step_months):
        current_date = test_dates[i]
        holding_dates = test_dates[i + 1 : i + 1 + rebalance_step_months]

        print(f"\n--- Rebalance Date: {current_date.strftime('%Y-%m')} | Holding: {holding_dates[0].strftime('%Y-%m')} to {holding_dates[-1].strftime('%Y-%m')} ---")
        
        # 1. STRICT DATA SLICING
        hist_etfs = df_etfs.loc[:current_date]
        hist_factors = df_factors.loc[:current_date]
        hist_macro = df_macro.loc[:current_date]

        # 2. RUN PIPELINE
        beta_profiles = run_kalman_filter_regressions(hist_etfs, hist_factors)
        forecast_report = generate_factor_forecasts(hist_factors, hist_macro)

        # 3. UNPACK TUPLE (top_picks, top_betas)
        top_picks_df, top_betas_df = score_and_rank_funds(beta_profiles, forecast_report, top_n=top_n)
        
        if top_picks_df.empty:
            print("⚠️ No valid picks returned. Holding cash.")
            period_return = 0.0
            selected_tickers = []
        else:
            selected_tickers = top_picks_df['Ticker'].tolist()
            
            # 4. CUMULATIVE 6-MONTH REALIZED PERFORMANCE
            period_returns = df_etfs.loc[holding_dates, selected_tickers]
            # Compound returns across the 6-month holding window per ticker
            compounded_ticker_returns = (1 + period_returns).prod(axis=0) - 1
            period_return = compounded_ticker_returns.mean()

        portfolio_value *= (1 + period_return)

        # Benchmark 6-month compounded performance
        voo_ret = ((1 + df_etfs.loc[holding_dates, 'VOO']).prod() - 1) if 'VOO' in df_etfs.columns else 0.0
        ftec_ret = ((1 + df_etfs.loc[holding_dates, 'FTEC']).prod() - 1) if 'FTEC' in df_etfs.columns else 0.0

        history.append({
            'Rebalance_Date': current_date.strftime('%Y-%m'),
            'Holding_Period': f"{holding_dates[0].strftime('%Y-%m')} to {holding_dates[-1].strftime('%Y-%m')}",
            'Top_Picks': ", ".join(selected_tickers),
            'Strategy_Return_6M': period_return,
            'VOO_Return_6M': voo_ret,
            'FTEC_Return_6M': ftec_ret,
            'Strategy_Value': portfolio_value
        })

    return pd.DataFrame(history)
