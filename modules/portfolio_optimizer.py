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


def _category_index_groups(tickers: list[str]) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = {}
    for i, ticker in enumerate(tickers):
        category = config.ETF_CATEGORY_BY_TICKER.get(ticker, "Other")
        groups.setdefault(category, []).append(i)
    return groups


def _feasible_category_cap(
    tickers: list[str],
    asset_cap: float,
    desired_cat_cap: float,
) -> float:
    """
    Raise the category cap just enough that sum-to-one remains feasible under
    the single-name caps. A concentrated candidate pool can otherwise make a
    hard 30% sleeve limit impossible.
    """
    groups = _category_index_groups(tickers)
    if not groups:
        return 1.0

    cat_cap = max(desired_cat_cap, asset_cap)

    def capacity(limit: float) -> float:
        return float(sum(min(limit, len(idxs) * asset_cap) for idxs in groups.values()))

    while capacity(cat_cap) < 1.0 - 1e-9 and cat_cap < 1.0:
        cat_cap = min(1.0, cat_cap + 0.05)
    return cat_cap


def _enforce_category_caps(
    w: np.ndarray,
    tickers: list[str],
    cat_cap: float,
    asset_cap: float,
) -> np.ndarray:
    """Project weights onto single-name and category caps, then renormalize."""
    w = np.clip(np.asarray(w, dtype=float), 0.0, asset_cap)
    if w.sum() <= 0:
        w = np.ones(len(w), dtype=float) / len(w)

    groups = _category_index_groups(tickers)
    for _ in range(len(groups) + 2):
        w = w / w.sum()
        violated = False
        for idxs in groups.values():
            sleeve = float(w[idxs].sum())
            limit = min(cat_cap, len(idxs) * asset_cap)
            if sleeve > limit + 1e-12:
                violated = True
                scale = limit / sleeve
                w[idxs] *= scale
        w = np.clip(w, 0.0, asset_cap)
        if not violated:
            break

    if w.sum() <= 0:
        return np.ones(len(w), dtype=float) / len(w)
    return w / w.sum()


def maximize_sharpe(
    mu: np.ndarray,
    cov: np.ndarray,
    vols: np.ndarray,
    tickers: list[str] | None = None,
    max_weight: float = None,
    max_category_weight: float = None,
) -> np.ndarray:
    n = len(mu)
    if n == 0:
        return np.array([])

    cap = config.MAX_ASSET_WEIGHT if max_weight is None else max_weight
    if n * cap < 1.0:
        cap = 1.0 / n

    desired_cat_cap = (
        config.MAX_CATEGORY_WEIGHT if max_category_weight is None else max_category_weight
    )
    labels = tickers if tickers is not None else [f"A{i}" for i in range(n)]
    cat_cap = _feasible_category_cap(labels, cap, desired_cat_cap)

    def neg_sharpe(w):
        port_ret = float(w @ mu)
        port_vol = float(np.sqrt(max(w @ cov @ w, 0.0)))
        if port_vol < 1e-12:
            return 1e6
        return -port_ret / port_vol

    w0 = _enforce_category_caps(_inverse_vol_weights(vols, cap), labels, cat_cap, cap)
    bounds = [(0.0, cap)] * n
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

    if cat_cap < 1.0:
        for idxs in _category_index_groups(labels).values():
            if len(idxs) == 0:
                continue
            sleeve_cap = min(cat_cap, len(idxs) * cap)
            constraints.append(
                {
                    "type": "ineq",
                    "fun": lambda w, idx=idxs, limit=sleeve_cap: limit - float(np.sum(w[idx])),
                }
            )

    result = minimize(
        neg_sharpe,
        w0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 1000, "ftol": 1e-9, "disp": False},
    )

    if result.success and np.isfinite(result.x).all():
        return _enforce_category_caps(result.x, labels, cat_cap, cap)
    return w0


def construct_portfolio(
    scores_df: pd.DataFrame,
    prices: pd.DataFrame,
    factor_preds: dict,
    max_holdings: int | None = None,
) -> pd.DataFrame:
    """
    Apply RMW / vol screens, CMA+HML tilts, then long-only max-Sharpe MVO
    with single-name and category concentration caps.

    Holdings count is endogenous: keep names above MIN_ASSET_WEIGHT, up to
    MAX_HOLDINGS. There is no forced minimum count.
    """
    eligible = scores_df.copy()
    eligible = filter_negative_rmw_drag(eligible, factor_preds)
    eligible = filter_high_volatility(eligible)

    if eligible.empty:
        return pd.DataFrame()

    eligible = eligible.copy()
    eligible["Opt_Mu"] = tilted_expected_returns(eligible, factor_preds)
    eligible["Ret_Risk"] = eligible["Total_Expected_Return_3M"] / eligible["Volatility"]
    eligible["Category"] = eligible["Ticker"].map(
        lambda t: config.ETF_CATEGORY_BY_TICKER.get(t, "Other")
    )

    holdings_cap = config.MAX_HOLDINGS if max_holdings is None else max_holdings
    pool_n = max(holdings_cap, min(config.MVO_CANDIDATE_POOL, len(eligible)))
    candidates = eligible.sort_values(
        by=["Opt_Mu", "Ret_Risk"],
        ascending=False,
    ).head(pool_n).copy()

    tickers = candidates["Ticker"].tolist()
    mu = candidates["Opt_Mu"].to_numpy(dtype=float)
    vols = candidates["Volatility"].to_numpy(dtype=float)
    cov = _covariance_3m(prices, tickers)

    weights = maximize_sharpe(mu, cov, vols, tickers=tickers)

    candidates = candidates.copy()
    candidates["Target_Weight"] = weights

    min_w = config.MIN_ASSET_WEIGHT
    holdings = (
        candidates.loc[candidates["Target_Weight"] >= min_w]
        .sort_values("Target_Weight", ascending=False)
        .head(holdings_cap)
        .copy()
    )

    # If the min-weight screen wiped everyone out, fall back to the largest weights.
    if holdings.empty:
        holdings = (
            candidates.sort_values("Target_Weight", ascending=False)
            .head(max(1, min(holdings_cap, len(candidates))))
            .copy()
        )

    if len(holdings) < len(candidates):
        mu_h = holdings["Opt_Mu"].to_numpy(dtype=float)
        vols_h = holdings["Volatility"].to_numpy(dtype=float)
        tickers_h = holdings["Ticker"].tolist()
        cov_h = _covariance_3m(prices, tickers_h)
        holdings["Target_Weight"] = maximize_sharpe(mu_h, cov_h, vols_h, tickers=tickers_h)

    # Dust filter. Re-project after each drop so scaling the survivors cannot
    # punch through the single-name or category caps.
    for _ in range(4):
        kept = holdings.loc[holdings["Target_Weight"] >= min_w - 1e-12].copy()
        if kept.empty:
            return pd.DataFrame()
        tickers_kept = kept["Ticker"].tolist()
        raw = kept["Target_Weight"].to_numpy(dtype=float)
        asset_cap = config.MAX_ASSET_WEIGHT
        if len(raw) * asset_cap < 1.0:
            asset_cap = 1.0 / len(raw)
        cat_cap = _feasible_category_cap(tickers_kept, asset_cap, config.MAX_CATEGORY_WEIGHT)
        kept["Target_Weight"] = _enforce_category_caps(raw, tickers_kept, cat_cap, asset_cap)
        holdings = kept
        if np.all(holdings["Target_Weight"].to_numpy(dtype=float) >= min_w - 1e-12):
            break

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
