import pandas as pd
import numpy as np
from sklearn.linear_model import RidgeCV
from pykalman import KalmanFilter
import config
import warnings

warnings.filterwarnings("ignore")

def run_kalman_filter_regressions(etf_returns_df: pd.DataFrame, factor_df: pd.DataFrame) -> dict:
    """
    Executes a Regularized Kalman Filter seeded by Ridge Regression 
    to dynamically track ETF betas and alpha over time without collinearity collapse.
    """
    print("📈 Executing Regularized Kalman Filter (Ridge Seeded) for Dynamic Betas...")
    
    # Ensure exact index alignment safely, regardless of whether it's already a PeriodIndex
    if not isinstance(etf_returns_df.index, pd.PeriodIndex):
        etf_returns_df.index = pd.to_datetime(etf_returns_df.index).to_period('M')
        
    if not isinstance(factor_df.index, pd.PeriodIndex):
        factor_df.index = pd.to_datetime(factor_df.index).to_period('M')
    
    df_merged = etf_returns_df.join(factor_df, how='inner')
    results = {}
    
    factors = config.TARGET_FACTORS
    
    for ticker in etf_returns_df.columns:
        cols_to_keep = [ticker, 'RF'] + factors
        
        # Verify ALL required columns survived the merge
        missing_cols = [c for c in cols_to_keep if c not in df_merged.columns]
        if missing_cols:
            continue
            
        df = df_merged[cols_to_keep].dropna().copy()
        
        # Require at least 12 months of data to seed the Ridge baseline
        if len(df) < 12: 
            continue
            
        df['excess_ret'] = df[ticker] - df['RF']
        
        # Extract matrices
        X = df[factors].values
        y = df['excess_ret'].values
        
        # --- 1. RIDGE REGRESSION BASELINE (Collinearity Fix) ---
        # Seed the model using the first 12 months to establish a structural anchor
        X_seed = X[:12]
        y_seed = y[:12]
        
        # RidgeCV automatically finds the best L2 penalty (alpha) to stabilize the betas
        ridge_model = RidgeCV(alphas=np.logspace(-4, 4, 100), fit_intercept=True).fit(X_seed, y_seed)
        
        # Combine the intercept (alpha) and the factor coefficients into our initial state vector
        baseline_betas = np.insert(ridge_model.coef_, 0, ridge_model.intercept_)
        
        # --- 2. KALMAN FILTER ESTIMATION ---
        n_dim_state = len(factors) + 1  # 1 Alpha + 6 Factors
        n_timesteps = len(y)
        
        # Create observation matrices with a constant for alpha: shape (n_timesteps, 1, n_dim_state)
        X_with_const = np.hstack([np.ones((n_timesteps, 1)), X])
        observation_matrices = X_with_const.reshape(n_timesteps, 1, n_dim_state)
        
        # Strict collinearity adjustments
        transition_variance = 0.00001
        observation_cov = 5.0
        
        kf = KalmanFilter(
            n_dim_obs=1,
            n_dim_state=n_dim_state,
            initial_state_mean=baseline_betas, 
            initial_state_covariance=np.eye(n_dim_state) * 0.1,
            transition_matrices=np.eye(n_dim_state),
            observation_matrices=observation_matrices,
            observation_covariance=observation_cov,
            transition_covariance=np.eye(n_dim_state) * transition_variance 
        )
        
        try:
            # Filter the hidden state sequences (Dynamic Betas)
            state_means, _ = kf.filter(y)
            
            kalman_states = pd.DataFrame(
                state_means, 
                index=df.index,
                columns=['alpha', 'beta_mkt', 'beta_smb', 'beta_hml', 'beta_rmw', 'beta_cma', 'beta_wml']
            )
            
            results[ticker] = kalman_states
        except Exception as e:
            print(f"⚠️ Warning: Could not converge Kalman Filter for {ticker} ({e}).")
            
    return results
