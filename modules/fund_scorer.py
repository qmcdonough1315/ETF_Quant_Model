import pandas as pd
import numpy as np
import config
from modules.portfolio_optimizer import attach_horizon_volatility, construct_portfolio

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
    
    # Apply configured tilts (e.g., overweight HML & CMA)
    tilted_preds = [factor_preds[f] * config.FACTOR_TILTS[f] for f in config.TARGET_FACTORS]
    predicted_vector = np.array(tilted_preds)
    horizon = config.FORECAST_HORIZON_MONTHS
    
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
        
        # Kalman alpha is a monthly intercept; compound to the forecast horizon
        alpha_horizon = ((1 + recent_states['alpha']) ** horizon) - 1
        
        scoring_data.append({
            'Ticker': ticker,
            'Expected_Factor_Return_3M': expected_factor_return,
            'Raw_Alpha_3M': alpha_horizon,
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

    scores_df = attach_horizon_volatility(scores_df, prices)
    if scores_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    top_picks = construct_portfolio(
        scores_df=scores_df,
        prices=prices,
        factor_preds=factor_preds,
        top_n=top_n,
    )
    if top_picks.empty:
        return pd.DataFrame(), pd.DataFrame()
    
    beta_cols = ['Ticker', 'Beta_Mkt', 'Beta_SMB', 'Beta_HML', 'Beta_RMW', 'Beta_CMA', 'Beta_WML']
    top_betas_df = top_picks[beta_cols].copy()
    
    return top_picks, top_betas_df
