import pandas as pd
import numpy as np
import config

def score_and_rank_funds(
    beta_profiles: dict, 
    forecast_report: dict, 
    prices: pd.DataFrame, 
    top_n: int = 10,
    restricted_tickers: list = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    
    if restricted_tickers is None:
        restricted_tickers = []
        
    factor_preds = forecast_report['predictions']
    
    # Apply configured tilts (e.g., Overweight Momentum & Profitability)
    tilted_preds = [factor_preds[f] * config.FACTOR_TILTS[f] for f in config.TARGET_FACTORS]
    predicted_vector = np.array(tilted_preds)
    
    scoring_data = []
    
    for ticker, df in beta_profiles.items():
        # STRICT WASH-SALE ENFORCEMENT: Skip if recently harvested for a loss
        if ticker in restricted_tickers:
            continue 
            
        if len(df) < 3: 
            continue
            
        recent_states = df.tail(3).ewm(span=2).mean().iloc[-1]
        
        beta_vector = np.array([
            recent_states['beta_mkt'], recent_states['beta_smb'], 
            recent_states['beta_hml'], recent_states['beta_rmw'], 
            recent_states['beta_cma'], recent_states['beta_wml']
        ])
        
        expected_factor_return = np.dot(beta_vector, predicted_vector)
        
        # Scale monthly alpha to a 3-month horizon
        alpha_3m = ((1 + recent_states['alpha']) ** 3) - 1
        
        scoring_data.append({
            'Ticker': ticker,
            'Expected_Factor_Return_3M': expected_factor_return,
            'Raw_Alpha_3M': alpha_3m,
            'Beta_Mkt': recent_states['beta_mkt'],
            'Beta_SMB': recent_states['beta_smb'],
            'Beta_HML': recent_states['beta_hml'],
            'Beta_RMW': recent_states['beta_rmw'],
            'Beta_CMA': recent_states['beta_cma'],
            'Beta_WML': recent_states['beta_wml']
        })
        
    scores_df = pd.DataFrame(scoring_data)
    if scores_df.empty:
        return pd.DataFrame(), pd.DataFrame()
    
    # Shrinkage & Total Expected Return
    mean_alpha = scores_df['Raw_Alpha_3M'].mean()
    w = config.ALPHA_SHRINKAGE_WEIGHT
    scores_df['Shrunk_Alpha_3M'] = (w * scores_df['Raw_Alpha_3M']) + ((1 - w) * mean_alpha)
    scores_df['Total_Expected_Return_3M'] = scores_df['Expected_Factor_Return_3M'] + scores_df['Shrunk_Alpha_3M']
    
    # Rank and slice top picks
    top_picks = scores_df.sort_values(by='Total_Expected_Return_3M', ascending=False).head(top_n).copy()
    
    # --- VOLATILITY-ADJUSTED SIZING ---
    vols = []
    for ticker in top_picks['Ticker']:
        # Trailing 12-month standard deviation for volatility calculation
        vol = prices[ticker].tail(12).std()
        vols.append(vol)
        
    top_picks['Volatility'] = vols
    top_picks['Inv_Vol'] = 1.0 / top_picks['Volatility']
    
    # Normalize weights to sum to 100%
    top_picks['Target_Weight'] = top_picks['Inv_Vol'] / top_picks['Inv_Vol'].sum()
    
    # Separate Beta Output
    beta_cols = ['Ticker', 'Beta_Mkt', 'Beta_SMB', 'Beta_HML', 'Beta_RMW', 'Beta_CMA', 'Beta_WML']
    top_betas_df = top_picks[beta_cols].copy()
    
    return top_picks, top_betas_df
