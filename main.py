import config
from modules.data_ingestion import fetch_all_data
from modules.dynamic_beta_estimator import run_kalman_filter_regressions
from modules.factor_forecaster import generate_factor_forecasts
from modules.fund_scorer import score_and_rank_funds

def main():
    print(f"Initializing Quantitative Pipeline ({config.FORECAST_HORIZON_MONTHS}-Month Horizon)...")
    
    # 1. Ingest Data
    prices, factors, macro = fetch_all_data(config.ETF_POPULATION)
    
    # 2. Kalman Filter Betas
    beta_profiles = run_kalman_filter_regressions(prices, factors)
    
    # 3. Forecast Factor Returns
    forecast_report = generate_factor_forecasts(
        factors, 
        macro, 
        threshold=config.MIN_FACTOR_THRESHOLD
    )
    
    print(f"--- PREDICTED {config.FORECAST_HORIZON_MONTHS}-MONTH FACTOR EXCESS RETURNS ---")
    for factor, ret in forecast_report['predictions'].items():
        print(f"  • {factor:8s}: {ret * 100:+.2f}%")
        
    # --- TAX-LOSS HARVESTING FRAMEWORK ---
    # In a full backtest, this list will dynamically update with tickers sold at a loss 
    # within the last 30 days to strictly enforce wash-sale compliance.
    recent_wash_sales = [] 
    
    # 4. Score Funds with 3-Month Horizon, Volatility Sizing, and Wash-Sale filtering
    top_picks, top_betas = score_and_rank_funds(
        beta_profiles=beta_profiles, 
        forecast_report=forecast_report, 
        prices=prices, 
        top_n=10,
        restricted_tickers=recent_wash_sales
    )
    
    # Display Expected Returns Table
    print(f"\n--- TOP 10 ETF PICKS ({config.FORECAST_HORIZON_MONTHS}-MONTH EXPECTED RETURNS & WEIGHTS) ---")
    returns_table = top_picks[[
        'Ticker', 'Total_Expected_Return_3M', 'Volatility', 'Target_Weight'
    ]]
    print(returns_table.to_string(index=False))
    
    # Display Separate Factor Betas Table
    print("\n--- FACTOR BETAS PROJECTION TABLE (TOP 10 ETFs) ---")
    print(top_betas.to_string(index=False))

if __name__ == "__main__":
    main()
