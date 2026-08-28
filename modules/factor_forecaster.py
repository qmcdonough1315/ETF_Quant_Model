import os
import pandas as pd
from sklearn.multioutput import MultiOutputRegressor
import lightgbm as lgb
import config

def create_factor_features_and_targets(
    factor_df: pd.DataFrame,
    macro_df: pd.DataFrame,
    lookback_lags: int = 3,
    # Set default horizon to 6
    horizon: int = 6 
):
    
    df_factors = factor_df[config.TARGET_FACTORS].copy()
    
    # 1. Factor Lag Features
    X_dict = {}
    for col in config.TARGET_FACTORS:
        for lag in range(1, lookback_lags + 1):
            X_dict[f"{col}_lag{lag}"] = df_factors[col].shift(lag)
        X_dict[f"{col}_roll3_mean"] = df_factors[col].shift(1).rolling(3).mean()
        
    X_factors = pd.DataFrame(X_dict, index=df_factors.index)
    
    # 2. Macro Features
    macro_features = macro_df.copy()
    if all(k in macro_features.columns for k in ['cpi_inflation', 'yield_curve_slope', 'wti_oil', 'usd_index']):
        macro_features['stagflation_risk'] = macro_features['cpi_inflation'] * macro_features['yield_curve_slope']
        macro_features['vix_x_credit_spread'] = macro_features['vix'] * macro_features['credit_spread']
    
    macro_lagged = macro_features.shift(1)
    X_full = X_factors.join(macro_lagged, how='inner')
    
    # 3. Target Vectors: 6-Month Forward Cumulative Returns
    Y_dict = {}
    for col in config.TARGET_FACTORS:
        # Compound monthly factor returns over 6 months: (1 + r_t+1) * ... * (1 + r_t+6) - 1
        comp_return = pd.Series(1.0, index=df_factors.index)
        for h in range(1, horizon + 1):
            comp_return *= (1 + df_factors[col].shift(-h))
        Y_dict[f"fwd6m_{col}"] = comp_return - 1  # Fixed: y_dict -> Y_dict

    Y = pd.DataFrame(Y_dict, index=df_factors.index)  # Fixed: DataFram -> DataFrame
    
    dataset = X_full.join(Y).dropna()
    return dataset[X_full.columns], dataset[Y.columns]

def generate_factor_forecasts(factor_df: pd.DataFrame, macro_df: pd.DataFrame, threshold: float = 0.01):
    X, Y = create_factor_features_and_targets(factor_df, macro_df)
    
    base_gbm = lgb.LGBMRegressor(n_estimators=200, max_depth=5, learning_rate=0.02, random_state=42, verbosity=-1)
    model = MultiOutputRegressor(base_gbm).fit(X, Y)
    
    latest_features = X.iloc[[-1]]
    pred_vector = model.predict(latest_features)[0]
    
    predictions = {factor: float(pred) for factor, pred in zip(config.TARGET_FACTORS, pred_vector)}
    return {"predictions": predictions}
