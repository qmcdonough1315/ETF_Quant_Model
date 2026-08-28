import config
import pandas as pd
import numpy as np

from modules.data_ingestion import fetch_all_data
from modules.dynamic_beta_estimator import run_kalman_filter_regressions
from modules.factor_forecaster import generate_factor_forecasts
from modules.fund_scorer import score_and_rank_funds

def calculate_sharpe_ratio(returns_series: pd.Series, risk_free_rate: float = 0.03, periods_per_year: float = 4.0) -> float:
    """
    Calculates the annualized Sharpe Ratio for 3-month period returns.
    periods_per_year = 4 (since each return observation represents 3 months).
    """
    if returns_series.std() == 0:
        return 0.0
    
    # Average return per 3-month period
    mean_period_ret = returns_series.mean()
    # Volatility across 3-month periods
    std_period_ret = returns_series.std()
    
    # Convert annual risk-free rate to 3-month risk-free rate
    rf_period = (1 + risk_free_rate) ** (1 / periods_per_year) - 1
    
    # Annualized Sharpe Ratio = (Period Excess Return * periods_per_year) / (Period Volatility * sqrt(periods_per_year))
    sharpe = ((mean_period_ret - rf_period) * periods_per_year) / (std_period_ret * np.sqrt(periods_per_year))
    return sharpe

def run_walkforward_backtest(
    start_date: str = '2018-12-31', 
    end_date: str = '2026-06-30', 
    initial_capital: float = 10000.0,
    top_n: int = 10,
    rebalance_step_months: int = 3,
    risk_free_rate: float = 0.03
):
    print("=" * 70)
    print(f"🚀 INITIALIZING 3-MONTH WALK-FORWARD BACKTEST ({start_date} to {end_date})")
    print(f"💰 Starting Portfolio Capital: ${initial_capital:,.2f}")
    print("=" * 70)

    # 1. Fetch datasets
    all_etfs = list(set(config.ETF_POPULATION + ['VTI', 'SPY', 'VGT']))
    prices, factors, macro = fetch_all_data(all_etfs)

    # ADD THESE DIAGNOSTIC PRINTS:
    print("Checking benchmark availability in returns DataFrame:")
    for ticker in ['VTI', 'SPY', 'VGT']:
         print(f"  • {ticker} in columns? {ticker in prices.columns} | Missing values: {prices[ticker].isna().sum() if ticker in prices.columns else 'N/A'}")
    
    prices.index = pd.to_datetime(prices.index)
    factors.index = pd.to_datetime(factors.index)
    macro.index = pd.to_datetime(macro.index)

    returns_df = prices.pct_change().dropna() if (prices.iloc[0] > 1.0).any() else prices.copy()

    all_dates = returns_df.index
    rebalance_dates = all_dates[(all_dates >= start_date) & (all_dates <= end_date)]

    if len(rebalance_dates) < rebalance_step_months + 1:
        print("⚠️ Not enough date points to execute 6-month backtest steps.")
        return

    strategy_value = initial_capital
    vti_value = initial_capital
    spy_value = initial_capital
    vgt_value = initial_capital

    history = []

    # 2. Walk-Forward Loop
    for i in range(0, len(rebalance_dates) - rebalance_step_months, rebalance_step_months):
        current_date = rebalance_dates[i]
        holding_dates = rebalance_dates[i + 1 : i + 1 + rebalance_step_months]

        hist_returns = returns_df.loc[:current_date]
        hist_factors = factors.loc[:current_date]
        hist_macro = macro.loc[:current_date]

        try:
            beta_profiles = run_kalman_filter_regressions(hist_returns, hist_factors)
            forecast_report = generate_factor_forecasts(hist_factors, hist_macro, threshold=config.MIN_FACTOR_THRESHOLD)
            top_picks_df, top_betas_df = score_and_rank_funds(beta_profiles, forecast_report, top_n=top_n)
            selected_tickers = top_picks_df['Ticker'].head(top_n).tolist()
        except Exception as e:
            print(f"⚠️ Error on {current_date.strftime('%Y-%m-%d')}: {e}")
            selected_tickers = []

        if selected_tickers:
            period_returns = returns_df.loc[holding_dates, selected_tickers]
            strat_ret = ((1 + period_returns).prod(axis=0) - 1).mean()
        else:
            strat_ret = 0.0

        vti_ret = ((1 + returns_df.loc[holding_dates, 'VTI']).prod() - 1) if 'VTI' in returns_df.columns else 0.0
        spy_ret = ((1 + returns_df.loc[holding_dates, 'SPY']).prod() - 1) if 'SPY' in returns_df.columns else 0.0
        vgt_ret = ((1 + returns_df.loc[holding_dates, 'VGT']).prod() - 1) if 'VGT' in returns_df.columns else 0.0

        strategy_value *= (1 + strat_ret)
        vti_value *= (1 + vti_ret)
        spy_value *= (1 + spy_ret)
        vgt_value *= (1 + vgt_ret)

        history.append({
            'Rebalance_Date': current_date.strftime('%Y-%m'),
            'Holding_Window': f"{holding_dates[0].strftime('%Y-%m')} to {holding_dates[-1].strftime('%Y-%m')}",
            'Top_Picks': ", ".join(selected_tickers),
            'Strategy_Return_6M': strat_ret,
            'VTI_Return_6M': vti_ret,
            'SPY_Return_6M': spy_ret,
            'VGT_Return_6M': vgt_ret,
            'Strategy_Value': strategy_value,
            'VTI_Value': vti_value,
            'SPY_Value': spy_value,
            'VGT_Value': vgt_value
        })

    results_df = pd.DataFrame(history)

    # 3. Compute Risk & Sharpe Ratio Metrics
    strat_sharpe = calculate_sharpe_ratio(results_df['Strategy_Return_6M'], risk_free_rate)
    vti_sharpe = calculate_sharpe_ratio(results_df['VTI_Return_6M'], risk_free_rate)
    spy_sharpe = calculate_sharpe_ratio(results_df['SPY_Return_6M'], risk_free_rate)
    vgt_sharpe = calculate_sharpe_ratio(results_df['VGT_Return_6M'], risk_free_rate)

    strat_vol = results_df['Strategy_Return_6M'].std() * np.sqrt(2) * 100
    vti_vol = results_df['VTI_Return_6M'].std() * np.sqrt(2) * 100
    spy_vol = results_df['SPY_Return_6M'].std() * np.sqrt(2) * 100
    vgt_vol = results_df['VGT_Return_6M'].std() * np.sqrt(2) * 100

    strat_tot_ret = ((strategy_value / initial_capital) - 1) * 100
    vti_tot_ret = ((vti_value / initial_capital) - 1) * 100
    spy_tot_ret = ((spy_value / initial_capital) - 1) * 100
    vgt_tot_ret = ((vgt_value / initial_capital) - 1) * 100

    # Print Summary Performance Table
    print("\n" + "=" * 80)
    print("📊 RISK-ADJUSTED PERFORMANCE COMPARISON")
    print("=" * 80)
    
    metrics_summary = pd.DataFrame({
        'Asset / Strategy': ['Model Strategy', 'VTI (Total Market)', 'SPY (S&P 500)', 'VGT (Tech Focus)'],
        'Final Value ($)': [f"${strategy_value:,.2f}", f"${vti_value:,.2f}", f"${spy_value:,.2f}", f"${vgt_value:,.2f}"],
        'Total Return (%)': [f"{strat_tot_ret:+.2f}%", f"{vti_tot_ret:+.2f}%", f"{spy_tot_ret:+.2f}%", f"{vgt_tot_ret:+.2f}%"],
        'Ann. Volatility (%)': [f"{strat_vol:.2f}%", f"{vti_vol:.2f}%", f"{spy_vol:.2f}%", f"{vgt_vol:.2f}%"],
        'Sharpe Ratio': [f"{strat_sharpe:.2f}", f"{vti_sharpe:.2f}", f"{spy_sharpe:.2f}", f"{vgt_sharpe:.2f}"]
    })
    
    print(metrics_summary.to_string(index=False))
    print("=" * 80 + "\n")

    return results_df

if __name__ == "__main__":
    run_walkforward_backtest(start_date='2018-12-31', end_date='2026-06-30', initial_capital=10000.0)
