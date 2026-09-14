import os
import pandas as pd
from datetime import datetime
from supabase import create_client, Client

def export_to_supabase(forecast_report, portfolio_df: pd.DataFrame, top_betas: pd.DataFrame = None):
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

    # 1. Format Predicted 3-Month Factor Excess Returns (Extract from dictionary)
    predictions = forecast_report.get('predictions', {}) if isinstance(forecast_report, dict) else {}
    for factor, val in predictions.items():
        records.append({
            "execution_date": today,
            "data_type": "factor_returns",
            "ticker_or_factor": str(factor),
            "value": float(val)
        })

    # 2. Format 10-ETF Factor Portfolio Weights (Uses Target_Weight from main.py)
    for _, row in portfolio_df.head(10).iterrows():
        records.append({
            "execution_date": today,
            "data_type": "portfolio_weights",
            "ticker_or_factor": str(row['Ticker']),
            "value": float(row['Target_Weight'])
        })

    # Push payload to Supabase
    try:
        # Insert this right before: response = supabase.table("factor_predictions").insert(records).execute()
        print(f"DEBUG: Payload contains {len(records)} records.")
        print(f"DEBUG: Sample record: {records[0] if records else 'EMPTY'}")

        response = supabase.table("factor_predictions").insert(records).execute()
        print("Successfully exported predictions to Supabase!")
    except Exception as e:
        print(f"Failed to export to Supabase: {e}")
