import pandas as pd
from sklearn.multioutput import MultiOutputRegressor
import lightgbm as lgb
import config


def _as_month_period_index(df: pd.DataFrame) -> pd.DataFrame:
    """Align factor/macro frames on monthly PeriodIndex without mutating callers."""
    out = df.copy()
    if isinstance(out.index, pd.PeriodIndex):
        return out
    out.index = pd.to_datetime(out.index).to_period("M")
    return out


def build_factor_features(
    factor_df: pd.DataFrame,
    macro_df: pd.DataFrame,
    lookback_lags: int = 3,
) -> pd.DataFrame:
    """Causal feature matrix (may contain leading NaNs from lags)."""
    factor_df = _as_month_period_index(factor_df)
    macro_df = _as_month_period_index(macro_df)
    df_factors = factor_df[config.TARGET_FACTORS].copy()

    X_dict = {}
    for col in config.TARGET_FACTORS:
        for lag in range(1, lookback_lags + 1):
            X_dict[f"{col}_lag{lag}"] = df_factors[col].shift(lag)
        X_dict[f"{col}_roll3_mean"] = df_factors[col].shift(1).rolling(3).mean()

    X_factors = pd.DataFrame(X_dict, index=df_factors.index)

    macro_features = macro_df.copy()
    if all(
        k in macro_features.columns
        for k in ["cpi_inflation", "yield_curve_slope", "wti_oil", "usd_index"]
    ):
        macro_features["stagflation_risk"] = (
            macro_features["cpi_inflation"] * macro_features["yield_curve_slope"]
        )
        macro_features["vix_x_credit_spread"] = (
            macro_features["vix"] * macro_features["credit_spread"]
        )

    macro_lagged = macro_features.shift(1)
    return X_factors.join(macro_lagged, how="inner")


def build_factor_targets(
    factor_df: pd.DataFrame,
    horizon: int | None = None,
) -> pd.DataFrame:
    """
    Forward compounded factor returns over `horizon` months.

    Uses shift(-h) for labels only. Trailing rows where the forward window is
    incomplete are NaN and must not be used as training targets.
    """
    if horizon is None:
        horizon = config.FORECAST_HORIZON_MONTHS

    factor_df = _as_month_period_index(factor_df)
    df_factors = factor_df[config.TARGET_FACTORS].copy()

    Y_dict = {}
    for col in config.TARGET_FACTORS:
        comp_return = pd.Series(1.0, index=df_factors.index)
        for h in range(1, horizon + 1):
            comp_return *= 1 + df_factors[col].shift(-h)
        Y_dict[f"fwd{horizon}m_{col}"] = comp_return - 1

    return pd.DataFrame(Y_dict, index=df_factors.index)


def create_factor_features_and_targets(
    factor_df: pd.DataFrame,
    macro_df: pd.DataFrame,
    lookback_lags: int = 3,
    horizon: int | None = None,
):
    """
    Build aligned feature/target frames without jointly dropna'ing.

    Training must use only rows where both X and Y are complete. Prediction must
    use the latest feature-complete row that was excluded from that fit
    (normally the decision month, where forward Y is incomplete).
    """
    if horizon is None:
        horizon = config.FORECAST_HORIZON_MONTHS

    X_full = build_factor_features(factor_df, macro_df, lookback_lags=lookback_lags)
    Y_full = build_factor_targets(factor_df, horizon=horizon)
    common = X_full.index.intersection(Y_full.index)
    return X_full.loc[common], Y_full.loc[common]


def select_train_predict_indices(
    X: pd.DataFrame,
    Y: pd.DataFrame,
) -> tuple[pd.Index, object]:
    """
    Choose training rows and a single OOS predict index.

    Prefer the latest row with complete features and incomplete targets (true
    decision-date row). If every feature-complete row also has complete Y
    (e.g. history already truncated), hold out the last complete row from fit
    and predict it — never fit and predict the same row.
    """
    if X.empty or Y.empty:
        raise ValueError("Empty feature/target frames for factor forecast.")

    feature_ok = X.notna().all(axis=1)
    target_ok = Y.notna().all(axis=1)
    train_mask = feature_ok & target_ok
    pred_mask = feature_ok & ~target_ok

    if pred_mask.any():
        pred_idx = X.index[pred_mask][-1]
        train_index = X.index[train_mask]
    elif train_mask.any():
        complete_idx = X.index[train_mask]
        if len(complete_idx) < 2:
            raise ValueError(
                "Need at least two complete feature/target rows to hold out an OOS predict row."
            )
        pred_idx = complete_idx[-1]
        train_index = complete_idx[:-1]
    else:
        raise ValueError("No complete feature rows available for factor forecast.")

    if len(train_index) == 0:
        raise ValueError("No training rows remain after excluding the predict row.")
    if pred_idx in train_index:
        raise RuntimeError("Predict row must not appear in the training index.")

    return train_index, pred_idx


def generate_factor_forecasts(
    factor_df: pd.DataFrame,
    macro_df: pd.DataFrame,
    threshold: float = 0.01,
):
    """
    Fit on rows with complete forward targets; predict the latest decision-date
    feature row that was excluded from that fit.

    `threshold` is retained for caller compatibility; it is not applied here.
    """
    del threshold  # reserved / unused (callers still pass MIN_FACTOR_THRESHOLD)

    X, Y = create_factor_features_and_targets(
        factor_df, macro_df, horizon=config.FORECAST_HORIZON_MONTHS
    )
    train_index, pred_idx = select_train_predict_indices(X, Y)

    base_gbm = lgb.LGBMRegressor(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.02,
        random_state=42,
        verbosity=-1,
    )
    model = MultiOutputRegressor(base_gbm).fit(X.loc[train_index], Y.loc[train_index])

    pred_vector = model.predict(X.loc[[pred_idx]])[0]
    predictions = {
        factor: float(pred) for factor, pred in zip(config.TARGET_FACTORS, pred_vector)
    }
    return {
        "predictions": predictions,
        "asof": str(pred_idx),
        "train_end": str(train_index[-1]),
        "n_train": int(len(train_index)),
    }
