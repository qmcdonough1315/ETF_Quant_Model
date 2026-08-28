import os
import pandas as pd
import yfinance as yf
import pandas_datareader.data as web
from datetime import datetime
import config

CACHE_DIR = "data"
os.makedirs(CACHE_DIR, exist_ok=True)

def fetch_etf_returns(tickers: list, start_date: str = "1996-01-01") -> pd.DataFrame:
    print(f"📥 Fetching ETF returns starting from {start_date}...")
    raw_data = yf.download(tickers, start=start_date, interval="1mo", auto_adjust=True, progress=False)
    prices = raw_data['Close'] if isinstance(raw_data.columns, pd.MultiIndex) else (raw_data['Close'] if 'Close' in raw_data else raw_data)
    monthly_returns = prices.dropna(how='all', axis=1).pct_change().dropna(how='all')
    monthly_returns.index = pd.to_datetime(monthly_returns.index).to_period('M')
    return monthly_returns

def fetch_ken_french_factors(start_date: str = "1996-01-01") -> pd.DataFrame:
    print("📥 Fetching Ken French Factors...")
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    
    # Pull 5-Factor dataset (Mkt-RF, SMB, HML, RMW, CMA)
    ff5 = web.DataReader("F-F_Research_Data_5_Factors_2x3", "famafrench", start=start_dt)[0]
    ff_mom = web.DataReader("F-F_Momentum_Factor", "famafrench", start=start_dt)[0]
    
    factors = ff5.join(ff_mom, how="inner").rename(columns={"Mkt-RF": "Mkt_RF", "Mom   ": "WML", "Mom": "WML"})
    factors = factors / 100.0
    factors.index = factors.index.to_timestamp().to_period('M')
    return factors

def fetch_macro_indicators(start_date: str = "1996-01-01") -> pd.DataFrame:
    print("📥 Fetching Macroeconomic Indicators from FRED...")
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    
    # Get the FRED tickers from config
    fred_series = config.MACRO_FRED_SERIES
    tickers = list(fred_series.keys())
    
    # Download data from FRED
    macro_raw = web.DataReader(tickers, "fred", start_dt)
    
    # Rename columns to human-readable names based on config dictionary
    macro_raw = macro_raw.rename(columns=fred_series)
    
    # Convert daily/weekly data to end-of-month frequency to match ETF/Factor data
    macro_monthly = macro_raw.resample('ME').last() 
    macro_monthly.index = macro_monthly.index.to_period('M')
    
    # Apply percentage changes to specific columns (e.g., inflation, money supply)
    for col in config.MACRO_PCT_CHANGE_COLS:
        if col in macro_monthly.columns:
            macro_monthly[col] = macro_monthly[col].pct_change()
            
    return macro_monthly.dropna()

def fetch_all_data(tickers, start_date="1996-01-01", use_cache=True):
    """
    Main orchestration function to fetch and return all required datasets.
    """
    prices = fetch_etf_returns(tickers, start_date)
    factors = fetch_ken_french_factors(start_date)
    macro = fetch_macro_indicators(start_date)
    
    # Return exactly the three variables expected by main.py
    return prices, factors, macro
