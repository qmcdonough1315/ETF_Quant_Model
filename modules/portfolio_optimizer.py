import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf
import config


def _horizon_vol(monthly_returns: pd.Series, horizon: int) -> float:
    vol_monthly = monthly_returns.tail(12).std()
    if pd.isna(vol_monthly) or vol_monthly <= 0:
        return np.nan
    return float(vol_monthly * np.sqrt(horizon))


def attach_horizon_volatility(scores_df: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    horizon = config.FORECAST_HORIZON_MONTHS
    vols = []
    for ticker in scores_df["Ticker"]:
        if ticker not in prices.columns:
            vols.append(np.nan)
            continue
        vols.append(_horizon_vol(prices[ticker], horizon))
    out = scores_df.copy()
    out["Volatility"] = vols
    out["Inv_Vol"] = 1.0 / out["Volatility"]
    return out.dropna(subset=["Volatility"])


def filter_negative_rmw_drag(scores_df: pd.DataFrame, factor_preds: dict) -> pd.DataFrame:
    """Drop names where Beta_RMW * RMW premium is negative (factor drag)."""
    rmw_premium = float(factor_preds.get("RMW", 0.0))
    rmw_contribution = scores_df["Beta_RMW"] * rmw_premium
    return scores_df.loc[rmw_contribution >= 0].copy()


def filter_high_volatility(scores_df: pd.DataFrame) -> pd.DataFrame:
    """
    Exclude 3M vol above the cap unless expected return / vol clears the exception.
    """
    vol_cap = config.HIGH_VOL_THRESHOLD_3M
    sharpe_floor = config.HIGH_VOL_SHARPE_EXCEPTION
    ret = scores_df["Total_Expected_Return_3M"]
    vol = scores_df["Volatility"]
    keep = (vol <= vol_cap) | ((ret / vol) > sharpe_floor)
    return scores_df.loc[keep].copy()


def tilted_expected_returns(scores_df: pd.DataFrame, factor_preds: dict) -> np.ndarray:
    """Boost objective toward positive HML and CMA betas when those premiums are positive."""
    mu = scores_df["Total_Expected_Return_3M"].to_numpy(dtype=float)
    intensity = config.HML_CMA_TILT_INTENSITY
    hml_pred = max(float(factor_preds.get("HML", 0.0)), 0.0)
    cma_pred = max(float(factor_preds.get("CMA", 0.0)), 0.0)
    hml_pos = np.clip(scores_df["Beta_HML"].to_numpy(dtype=float), 0.0, None)
    cma_pos = np.clip(scores_df["Beta_CMA"].to_numpy(dtype=float), 0.0, None)
    return mu + intensity * (hml_pos * hml_pred + cma_pos * cma_pred)


def _covariance_3m(prices: pd.DataFrame, tickers: list[str]) -> np.ndarray:
    horizon = config.FORECAST_HORIZON_MONTHS
    lookback = config.MVO_COV_LOOKBACK_MONTHS
    rets = prices[tickers].tail(lookback).dropna(how="any")
    if len(rets) < 12:
        rets = prices[tickers].dropna(how="any").tail(max(lookback, 12))

    if len(rets) < 3:
        vols = prices[tickers].tail(12).std().fillna(prices[tickers].std()).to_numpy(dtype=float)
        vols = np.nan_to_num(vols, nan=0.05)
        cov_m = np.diag(np.square(vols))
        return cov_m * horizon

    try:
        cov_m = LedoitWolf().fit(rets.to_numpy(dtype=float)).covariance_
    except Exception:
        cov_m = np.cov(rets.to_numpy(dtype=float), rowvar=False)

    cov = np.atleast_2d(np.asarray(cov_m, dtype=float)) * horizon
    cov = 0.5 * (cov + cov.T)
    cov.flat[:: cov.shape[0] + 1] += 1e-8
    return cov


def _inverse_vol_weights(vols: np.ndarray, max_weight: float) -> np.ndarray:
    inv = 1.0 / np.clip(vols, 1e-8, None)
    w = inv / inv.sum()
    return _cap_and_renormalize(w, max_weight)


def _cap_and_renormalize(w: np.ndarray, max_weight: float) -> np.ndarray:
    w = np.clip(w, 0.0, None)
    if w.sum() <= 0:
        w = np.ones_like(w) / len(w)
    else:
        w = w / w.sum()

    n = len(w)
    cap = max_weight if n * max_weight >= 1.0 else 1.0 / n
    for _ in range(n):
        over = w > cap + 1e-12
        if not over.any():
            break
        excess = (w[over] - cap).sum()
        w[over] = cap
        under = ~over
        if under.any() and w[under].sum() > 0:
            w[under] += excess * (w[under] / w[under].sum())
        else:
            break
    w = np.clip(w, 0.0, cap)
    return w / w.sum()


def maximize_sharpe(
    mu: np.ndarray,
    cov: np.ndarray,
    vols: np.ndarray,
    max_weight: float = None,
) -> np.ndarray:
    n = len(mu)
    if n == 0:
        return np.array([])

    cap = config.MAX_ASSET_WEIGHT if max_weight is None else max_weight
    if n * cap < 1.0:
        cap = 1.0 / n

    def neg_sharpe(w):
        port_ret = float(w @ mu)
        port_vol = float(np.sqrt(max(w @ cov @ w, 0.0)))
        if port_vol < 1e-12:
            return 1e6
        return -port_ret / port_vol

    w0 = _inverse_vol_weights(vols, cap)
    bounds = [(0.0, cap)] * n
    constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}

    result = minimize(
        neg_sharpe,
        w0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 1000, "ftol": 1e-9, "disp": False},
    )

    if result.success and np.isfinite(result.x).all():
        w = np.clip(result.x, 0.0, cap)
        if w.sum() <= 0:
            return w0
        return w / w.sum()
    return w0


def construct_portfolio(
    scores_df: pd.DataFrame,
    prices: pd.DataFrame,
    factor_preds: dict,
    top_n: int = 10,
) -> pd.DataFrame:
    """
    Apply RMW / vol screens, CMA+HML tilts, then long-only max-Sharpe MVO
    with a per-name weight cap.
    """
    eligible = scores_df.copy()
    eligible = filter_negative_rmw_drag(eligible, factor_preds)
    eligible = filter_high_volatility(eligible)

    if eligible.empty:
        return pd.DataFrame()

    eligible = eligible.copy()
    eligible["Opt_Mu"] = tilted_expected_returns(eligible, factor_preds)
    eligible["Ret_Risk"] = eligible["Total_Expected_Return_3M"] / eligible["Volatility"]

    pool_n = max(top_n, min(config.MVO_CANDIDATE_POOL, len(eligible)))
    candidates = eligible.sort_values(
        by=["Opt_Mu", "Ret_Risk"],
        ascending=False,
    ).head(pool_n).copy()

    tickers = candidates["Ticker"].tolist()
    mu = candidates["Opt_Mu"].to_numpy(dtype=float)
    vols = candidates["Volatility"].to_numpy(dtype=float)
    cov = _covariance_3m(prices, tickers)

    weights = maximize_sharpe(mu, cov, vols)

    candidates = candidates.copy()
    candidates["Target_Weight"] = weights
    holdings = (
        candidates.loc[candidates["Target_Weight"] > 1e-4]
        .sort_values("Target_Weight", ascending=False)
        .head(top_n)
        .copy()
    )

    if holdings.empty:
        return pd.DataFrame()

    if len(holdings) < len(candidates):
        mu_h = holdings["Opt_Mu"].to_numpy(dtype=float)
        vols_h = holdings["Volatility"].to_numpy(dtype=float)
        cov_h = _covariance_3m(prices, holdings["Ticker"].tolist())
        holdings["Target_Weight"] = maximize_sharpe(mu_h, cov_h, vols_h)

    holdings["Target_Weight"] = holdings["Target_Weight"] / holdings["Target_Weight"].sum()
    return holdings.sort_values("Target_Weight", ascending=False)


def portfolio_expected_metrics(holdings: pd.DataFrame, prices: pd.DataFrame) -> tuple[float, float, float]:
    """Expected 3M return, covariance-based 3M vol, and Sharpe."""
    if holdings.empty:
        return 0.0, 0.0, 0.0

    tickers = holdings["Ticker"].tolist()
    w = holdings.set_index("Ticker").loc[tickers, "Target_Weight"].to_numpy(dtype=float)
    mu = holdings.set_index("Ticker").loc[tickers, "Total_Expected_Return_3M"].to_numpy(dtype=float)
    cov = _covariance_3m(prices, tickers)

    port_ret = float(w @ mu)
    port_vol = float(np.sqrt(max(w @ cov @ w, 0.0)))
    port_sharpe = (port_ret / port_vol) if port_vol > 0 else 0.0
    return port_ret, port_vol, port_sharpe
