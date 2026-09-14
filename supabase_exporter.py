import os
import pandas as pd
from datetime import datetime
from supabase import create_client, Client

def export_to_supabase(factor_returns_df: pd.DataFrame, portfolio_df: pd.DataFrame):
    """
    Exports 3-Month Factor Excess Returns and 10-ETF Portfolio Weights to Supabase.
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
    # Expects factor_returns_df to have factors as index/column and predicted return as value
    for factor, row in factor_returns_df.iterrows():
        records.append({
            "execution_date": today,
            "data_type": "factor_returns",
            "ticker_or_factor": str(factor),
            "value": float(row['predicted_excess_return'])
        })

    # 2. Format 10-ETF Factor Portfolio Weights
    # Expects portfolio_df to have Ticker as index and Weight as value
    for ticker, row in portfolio_df.head(10).iterrows():
        records.append({
            "execution_date": today,
            "data_type": "portfolio_weights",
            "ticker_or_factor": str(ticker),
            "value": float(row['Weight'])
        })

    # Push payload to Supabase
    try:
        response = supabase.table("factor_predictions").insert(records).execute()
        print("Successfully exported predictions to Supabase!")
    except Exception as e:
        print(f"Failed to export to Supabase: {e}")
