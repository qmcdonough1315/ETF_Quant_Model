import os
import pandas as pd
from datetime import datetime
from supabase import create_client, Client

def export_to_supabase(
    forecast_report, 
    portfolio_df: pd.DataFrame, 
    portfolio_return: float = None, 
    portfolio_vol: float = None, 
    portfolio_sharpe: float = None,
    top_betas: pd.DataFrame = None
):
    """
    Exports Factor Returns, Portfolio Weights, Fund Returns, and Summary Metrics to Supabase.
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    
    if not url or not key:
        print("Supabase credentials not found. Skipping export.")
        return

    supabase: Client = create_client(url, key)
    today = datetime.now().strftime('%Y-%m-%d')
    records = []

    # 1. Format Predicted 3-Month Factor Excess Returns
    predictions = forecast_report.get('predictions', {}) if isinstance(forecast_report, dict) else {}
    for factor, val in predictions.items():
        records.append({
            "execution_date": today,
            "data_type": "factor_returns",
            "ticker_or_factor": str(factor),
            "value": float(val)
        })

    # 2. Format 10-ETF Portfolio Weights & Individual Fund Expected Returns
    for _, row in portfolio_df.head(10).iterrows():
        ticker = str(row['Ticker'])
        
        # Target Weight
        records.append({
            "execution_date": today,
            "data_type": "portfolio_weights",
            "ticker_or_factor": ticker,
            "value": float(row['Target_Weight'])
        })
        
        # Fund Expected Return
        if 'Total_Expected_Return_3M' in row:
            records.append({
                "execution_date": today,
                "data_type": "fund_expected_return",
                "ticker_or_factor": ticker,
                "value": float(row['Total_Expected_Return_3M'])
            })

    # 3. Format Portfolio Level Summary Metrics
    if portfolio_return is not None:
        records.append({
            "execution_date": today,
            "data_type": "portfolio_metric",
            "ticker_or_factor": "expected_return_3m",
            "value": float(portfolio_return)
        })
        
    if portfolio_vol is not None:
        records.append({
            "execution_date": today,
            "data_type": "portfolio_metric",
            "ticker_or_factor": "expected_volatility",
            "value": float(portfolio_vol)
        })

    if portfolio_sharpe is not None:
        records.append({
            "execution_date": today,
            "data_type": "portfolio_metric",
            "ticker_or_factor": "expected_sharpe_ratio",
            "value": float(portfolio_sharpe)
        })

    # Push payload to Supabase
    try:
        response = supabase.table("factor_predictions").insert(records).execute()
        print(f"DEBUG Response Data: {response.data}")
        if response.data:
            print("Successfully exported extended predictions & metrics to Supabase!")
        else:
            print("WARNING: Insert call completed, but Supabase returned 0 inserted rows.")
    except Exception as e:
        print(f"Failed to export to Supabase: {e}")
