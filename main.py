import config
from modules.data_ingestion import fetch_all_data
from modules.dynamic_beta_estimator import run_kalman_filter_regressions
from modules.factor_forecaster import generate_factor_forecasts
from modules.fund_scorer import score_and_rank_funds
from modules.supabase_exporter import export_to_supabase

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

    # Calculate Overall Portfolio Summary Metrics
    port_exp_return = (top_picks['Target_Weight'] * top_picks['Total_Expected_Return_3M']).sum()
    port_vol = (top_picks['Target_Weight'] * top_picks['Volatility']).sum()
    port_sharpe = (port_exp_return / port_vol) if port_vol > 0 else 0.0

    # Print to Console Output
    print(f"\n--- PORTFOLIO SUMMARY METRICS ---")
    print(f"  • Total Expected Return (3M) : {port_exp_return:+.2%}")
    print(f"  • Expected Volatility        : {port_vol:.2%}")
    print(f"  • Expected Sharpe Ratio      : {port_sharpe:.2f}\n")

    # Export to Supabase with new metrics
    export_to_supabase(
        forecast_report=forecast_report,
        portfolio_df=top_picks,
        portfolio_return=port_exp_return,
        portfolio_vol=port_vol,
        portfolio_sharpe=port_sharpe
    )

if __name__ == "__main__":
    main()
