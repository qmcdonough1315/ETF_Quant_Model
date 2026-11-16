"""
Live-run realism diagnostics for the ETF factor book.

Does not change weights. Compares the current forecast / scorecard / portfolio
against historical horizon distributions and simple structural gates so the
desk can see *where* headline expected return and Sharpe look stretched.

Severity:
  ok   — no gate tripped
  warn — at least one soft gate
  fail — at least one hard gate (portfolio μ, Sharpe, or extreme name μ)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

import config


SEVERITY_RANK = {"ok": 0, "warn": 1, "fail": 2}


@dataclass
class RealismFlag:
    code: str
    severity: str  # ok | warn | fail
    message: str
    value: Optional[float] = None
    threshold: Optional[float] = None
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def compounded_horizon_returns(monthly: pd.Series, horizon: int) -> pd.Series:
    """Trailing compounded returns over `horizon` months (label at window end)."""
    s = monthly.astype(float).dropna()
    if len(s) < horizon:
        return pd.Series(dtype=float)
    out = []
    idx = []
    for i in range(horizon - 1, len(s)):
        window = s.iloc[i - horizon + 1 : i + 1]
        out.append(float(np.prod(1.0 + window.to_numpy()) - 1.0))
        idx.append(s.index[i])
    return pd.Series(out, index=idx, dtype=float)


def empirical_percentile(history: pd.Series, value: float) -> Optional[float]:
    hist = history.dropna().astype(float)
    if hist.empty or not np.isfinite(value):
        return None
    return float((hist.to_numpy() <= float(value)).mean())


def annualized_sharpe_equivalent(
    horizon_return: float,
    horizon_vol: float,
    *,
    horizon_months: int | None = None,
    risk_free_annual: float | None = None,
) -> float:
    """
    Convert a horizon E[r]/σ ratio into an annualized Sharpe-like figure.

    Matches the walk-forward convention of scaling mean by periods/year and
    vol by sqrt(periods/year), with an annual rf converted to the horizon.
    """
    h = int(horizon_months or config.FORECAST_HORIZON_MONTHS)
    rf_ann = float(
        config.REALISM_RISK_FREE_RATE if risk_free_annual is None else risk_free_annual
    )
    if horizon_vol <= 0 or not np.isfinite(horizon_return) or not np.isfinite(horizon_vol):
        return 0.0
    periods = 12.0 / float(h)
    rf_h = (1.0 + rf_ann) ** (1.0 / periods) - 1.0
    return float(((horizon_return - rf_h) * periods) / (horizon_vol * np.sqrt(periods)))


def _beta_row(states: pd.DataFrame) -> dict[str, float]:
    recent = states.tail(3).ewm(span=2).mean().iloc[-1]
    return {
        "Mkt_RF": float(recent["beta_mkt"]),
        "SMB": float(recent["beta_smb"]),
        "HML": float(recent["beta_hml"]),
        "RMW": float(recent["beta_rmw"]),
        "CMA": float(recent["beta_cma"]),
        "WML": float(recent["beta_wml"]),
        "alpha_m": float(recent["alpha"]),
    }


def factor_contribution_table(
    holdings: pd.DataFrame,
    beta_profiles: dict,
    predictions: dict[str, float],
    *,
    apply_tilts: bool = True,
) -> pd.DataFrame:
    """Per-holding, per-factor β×forecast contributions (horizon expected factor piece)."""
    preds = {
        f: float(predictions[f]) * (config.FACTOR_TILTS[f] if apply_tilts else 1.0)
        for f in config.TARGET_FACTORS
    }
    rows = []
    for _, row in holdings.iterrows():
        ticker = str(row["Ticker"])
        weight = float(row.get("Target_Weight", 0.0))
        if ticker not in beta_profiles:
            continue
        betas = _beta_row(beta_profiles[ticker])
        for factor in config.TARGET_FACTORS:
            beta = betas[factor]
            pred = preds[factor]
            contrib = beta * pred
            # Fade tailwind: negative factor forecast × negative beta still
            # *adds* to expected return (shorting a factor expected to lose).
            fade_tailwind = bool(beta < 0.0 and pred < 0.0 and abs(pred) > 0.005)
            rows.append(
                {
                    "Ticker": ticker,
                    "Weight": weight,
                    "Factor": factor,
                    "Beta": beta,
                    "Forecast": pred,
                    "Contribution": contrib,
                    "Weighted_Contribution": weight * contrib,
                    "Fade_Tailwind": fade_tailwind,
                }
            )
    return pd.DataFrame(rows)


def _max_severity(flags: Iterable[RealismFlag]) -> str:
    rank = 0
    for flag in flags:
        rank = max(rank, SEVERITY_RANK.get(flag.severity, 0))
    for name, value in SEVERITY_RANK.items():
        if value == rank:
            return name
    return "ok"


def evaluate_factor_forecasts(
    predictions: dict[str, float],
    factors: pd.DataFrame,
    *,
    horizon: int | None = None,
) -> list[RealismFlag]:
    h = int(horizon or config.FORECAST_HORIZON_MONTHS)
    lo = float(config.REALISM_FACTOR_PCTILE_LO)
    hi = float(config.REALISM_FACTOR_PCTILE_HI)
    flags: list[RealismFlag] = []

    for factor, pred in predictions.items():
        if factor not in factors.columns:
            continue
        hist = compounded_horizon_returns(factors[factor], h)
        pct = empirical_percentile(hist, float(pred))
        if pct is None:
            continue
        detail = {
            "factor": factor,
            "forecast": float(pred),
            "hist_p05": float(hist.quantile(0.05)),
            "hist_p50": float(hist.quantile(0.50)),
            "hist_p95": float(hist.quantile(0.95)),
            "percentile": pct,
        }
        if pct < lo or pct > hi:
            flags.append(
                RealismFlag(
                    code=f"factor_forecast_tail:{factor}",
                    severity="warn",
                    message=(
                        f"{factor} {h}M forecast {pred:+.2%} is at historical "
                        f"percentile {pct:.0%} (gate {lo:.0%}–{hi:.0%})."
                    ),
                    value=float(pred),
                    threshold=float(hist.quantile(hi if pct > hi else lo)),
                    detail=detail,
                )
            )
        else:
            flags.append(
                RealismFlag(
                    code=f"factor_forecast_ok:{factor}",
                    severity="ok",
                    message=f"{factor} {h}M forecast {pred:+.2%} ~ p{pct:.0%} historically.",
                    value=float(pred),
                    detail=detail,
                )
            )
    return flags


def evaluate_scorecard(
    holdings: pd.DataFrame,
    scores_df: pd.DataFrame,
    beta_profiles: dict,
    predictions: dict[str, float],
) -> tuple[list[RealismFlag], dict[str, Any]]:
    flags: list[RealismFlag] = []
    meta: dict[str, Any] = {}
    if holdings is None or holdings.empty:
        return flags, meta

    h = holdings.copy()
    scored = scores_df.set_index("Ticker") if "Ticker" in scores_df.columns else scores_df
    name_cap = float(config.REALISM_NAME_EXPECTED_ABS)

    extreme = []
    for _, row in h.iterrows():
        ticker = str(row["Ticker"])
        mu = float(row.get("Total_Expected_Return_3M", np.nan))
        if abs(mu) >= name_cap:
            extreme.append((ticker, mu))
            flags.append(
                RealismFlag(
                    code=f"name_expected_extreme:{ticker}",
                    severity="fail" if abs(mu) >= name_cap * 1.25 else "warn",
                    message=(
                        f"{ticker} expected {config.FORECAST_HORIZON_MONTHS}M return "
                        f"{mu:+.1%} exceeds ±{name_cap:.0%} gate."
                    ),
                    value=mu,
                    threshold=name_cap,
                )
            )
    meta["extreme_names"] = extreme

    # Tilt lift on the book factor piece.
    untilted = factor_contribution_table(h, beta_profiles, predictions, apply_tilts=False)
    tilted = factor_contribution_table(h, beta_profiles, predictions, apply_tilts=True)
    untilted_mu = float(untilted["Weighted_Contribution"].sum()) if not untilted.empty else 0.0
    tilted_mu = float(tilted["Weighted_Contribution"].sum()) if not tilted.empty else 0.0
    tilt_lift = tilted_mu - untilted_mu
    meta["untilted_factor_mu"] = untilted_mu
    meta["tilted_factor_mu"] = tilted_mu
    meta["tilt_lift"] = tilt_lift
    if abs(tilt_lift) >= float(config.REALISM_TILT_LIFT_MAX):
        flags.append(
            RealismFlag(
                code="factor_tilt_lift",
                severity="warn",
                message=(
                    f"FACTOR_TILTS lift book factor μ by {tilt_lift:+.2%} "
                    f"(untilted {untilted_mu:+.2%} → tilted {tilted_mu:+.2%})."
                ),
                value=tilt_lift,
                threshold=float(config.REALISM_TILT_LIFT_MAX),
            )
        )

    # Fade-tailwind: negative forecast × negative beta still adds to μ.
    if not tilted.empty:
        gross = float(tilted["Weighted_Contribution"].abs().sum())
        fade = tilted.loc[tilted["Fade_Tailwind"], "Weighted_Contribution"]
        fade_sum = float(fade.sum()) if len(fade) else 0.0
        share = (abs(fade_sum) / gross) if gross > 1e-12 else 0.0
        meta["fade_tailwind_share"] = share
        meta["fade_tailwind_mu"] = fade_sum
        top_fade = (
            tilted.loc[tilted["Fade_Tailwind"]]
            .assign(abs_w=lambda d: d["Weighted_Contribution"].abs())
            .sort_values("abs_w", ascending=False)
            .head(5)[["Ticker", "Factor", "Beta", "Forecast", "Weighted_Contribution"]]
        )
        meta["top_fade_channels"] = top_fade.to_dict(orient="records")
        if share >= float(config.REALISM_FADE_TAILWIND_SHARE_MAX):
            flags.append(
                RealismFlag(
                    code="fade_tailwind_dependence",
                    severity="warn",
                    message=(
                        f"{share:.0%} of gross |β×f| book contribution is fade-tailwind "
                        f"(neg. forecast × neg. β; μ from those channels {fade_sum:+.2%})."
                    ),
                    value=share,
                    threshold=float(config.REALISM_FADE_TAILWIND_SHARE_MAX),
                    detail={"top": meta["top_fade_channels"]},
                )
            )

    # SPY multiple on the same scorecard.
    spy_mu = None
    if "SPY" in scored.index and "Total_Expected_Return_3M" in scored.columns:
        spy_mu = float(scored.loc["SPY", "Total_Expected_Return_3M"])
    meta["spy_expected"] = spy_mu

    return flags, meta


def evaluate_portfolio(
    holdings: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    port_return: float,
    port_vol: float,
    port_sharpe: float,
    scores_df: Optional[pd.DataFrame] = None,
) -> tuple[list[RealismFlag], dict[str, Any]]:
    flags: list[RealismFlag] = []
    meta: dict[str, Any] = {
        "horizon_return": float(port_return),
        "horizon_vol": float(port_vol),
        "horizon_sharpe": float(port_sharpe),
    }
    h = int(config.FORECAST_HORIZON_MONTHS)
    ann_sharpe = annualized_sharpe_equivalent(port_return, port_vol)
    meta["annualized_sharpe_equivalent"] = ann_sharpe
    meta["annualized_return_simple"] = float(port_return) * (12.0 / h)
    meta["annualized_vol"] = float(port_vol) * np.sqrt(12.0 / h)

    if abs(port_return) >= float(config.REALISM_PORTFOLIO_EXPECTED_ABS):
        flags.append(
            RealismFlag(
                code="portfolio_expected_extreme",
                severity="fail",
                message=(
                    f"Book expected {h}M return {port_return:+.1%} exceeds "
                    f"±{config.REALISM_PORTFOLIO_EXPECTED_ABS:.0%} gate "
                    f"(~{meta['annualized_return_simple']:.0%} simple annualized)."
                ),
                value=float(port_return),
                threshold=float(config.REALISM_PORTFOLIO_EXPECTED_ABS),
            )
        )

    if port_sharpe >= float(config.REALISM_HORIZON_SHARPE_MAX):
        flags.append(
            RealismFlag(
                code="horizon_sharpe_high",
                severity="fail",
                message=(
                    f"Reported {h}M Sharpe {port_sharpe:.2f} is a horizon ratio "
                    f"(E[r]/σ), not annualized — annualized equivalent ≈ {ann_sharpe:.2f}."
                ),
                value=float(port_sharpe),
                threshold=float(config.REALISM_HORIZON_SHARPE_MAX),
            )
        )

    if ann_sharpe >= float(config.REALISM_ANN_SHARPE_MAX):
        flags.append(
            RealismFlag(
                code="annualized_sharpe_high",
                severity="fail",
                message=(
                    f"Annualized Sharpe equivalent {ann_sharpe:.2f} exceeds "
                    f"{config.REALISM_ANN_SHARPE_MAX:.1f} gate."
                ),
                value=float(ann_sharpe),
                threshold=float(config.REALISM_ANN_SHARPE_MAX),
            )
        )

    # Diversification / vol compression.
    if holdings is not None and not holdings.empty and "Volatility" in holdings.columns:
        w = holdings["Target_Weight"].to_numpy(dtype=float)
        vols = holdings["Volatility"].to_numpy(dtype=float)
        standalone = float(np.nansum(w * vols))
        div = (standalone / port_vol) if port_vol > 1e-12 else 0.0
        meta["weighted_standalone_vol"] = standalone
        meta["diversification_ratio"] = div
        if div >= float(config.REALISM_DIVERSIFICATION_RATIO_MAX):
            flags.append(
                RealismFlag(
                    code="vol_compression",
                    severity="warn",
                    message=(
                        f"Diversification ratio {div:.2f} "
                        f"(standalone {standalone:.1%} / book {port_vol:.1%}) "
                        f"exceeds {config.REALISM_DIVERSIFICATION_RATIO_MAX:.2f} — "
                        "cov estimate may be over-compressing risk."
                    ),
                    value=div,
                    threshold=float(config.REALISM_DIVERSIFICATION_RATIO_MAX),
                )
            )

    if scores_df is not None and "SPY" in set(scores_df.get("Ticker", [])):
        spy_mu = float(
            scores_df.loc[scores_df["Ticker"] == "SPY", "Total_Expected_Return_3M"].iloc[0]
        )
        meta["spy_expected"] = spy_mu
        if spy_mu > 1e-6:
            multiple = float(port_return) / spy_mu
            meta["vs_spy_multiple"] = multiple
            if multiple >= float(config.REALISM_VS_SPY_MULTIPLE_MAX):
                flags.append(
                    RealismFlag(
                        code="vs_spy_multiple",
                        severity="warn",
                        message=(
                            f"Book expected return is {multiple:.1f}× SPY's scored "
                            f"{h}M expectation ({spy_mu:+.1%})."
                        ),
                        value=multiple,
                        threshold=float(config.REALISM_VS_SPY_MULTIPLE_MAX),
                    )
                )

    # Historical SPY horizon return context if prices available.
    if prices is not None and "SPY" in prices.columns:
        spy_hist = compounded_horizon_returns(prices["SPY"], h)
        if not spy_hist.empty:
            meta["spy_hist_p50"] = float(spy_hist.quantile(0.50))
            meta["spy_hist_p90"] = float(spy_hist.quantile(0.90))
            meta["spy_hist_p95"] = float(spy_hist.quantile(0.95))
            pct = empirical_percentile(spy_hist, float(port_return))
            meta["book_mu_vs_spy_hist_percentile"] = pct
            if pct is not None and pct >= 0.95:
                flags.append(
                    RealismFlag(
                        code="book_mu_vs_spy_history",
                        severity="warn",
                        message=(
                            f"Book {h}M μ {port_return:+.1%} sits at the "
                            f"{pct:.0%} percentile of realized SPY {h}M returns."
                        ),
                        value=float(port_return),
                        threshold=float(spy_hist.quantile(0.95)),
                    )
                )

    return flags, meta


def run_realism_diagnostics(
    *,
    predictions: dict[str, float],
    factors: pd.DataFrame,
    holdings: pd.DataFrame,
    scores_df: pd.DataFrame,
    beta_profiles: dict,
    prices: pd.DataFrame,
    port_return: float,
    port_vol: float,
    port_sharpe: float,
) -> dict[str, Any]:
    flags: list[RealismFlag] = []
    flags.extend(evaluate_factor_forecasts(predictions, factors))
    score_flags, score_meta = evaluate_scorecard(
        holdings, scores_df, beta_profiles, predictions
    )
    flags.extend(score_flags)
    port_flags, port_meta = evaluate_portfolio(
        holdings,
        prices,
        port_return=port_return,
        port_vol=port_vol,
        port_sharpe=port_sharpe,
        scores_df=scores_df,
    )
    flags.extend(port_flags)

    # Drop pure-ok factor chatter from the primary flag list used for severity,
    # but keep them in the full report under factor_notes.
    factor_notes = [f for f in flags if f.code.startswith("factor_forecast_")]
    actionable = [f for f in flags if f.severity != "ok"]
    severity = _max_severity(actionable) if actionable else "ok"

    report = {
        "severity": severity,
        "horizon_months": int(config.FORECAST_HORIZON_MONTHS),
        "flags": [f.as_dict() for f in actionable],
        "factor_notes": [f.as_dict() for f in factor_notes],
        "meta": {**score_meta, **port_meta},
        "n_warn": sum(1 for f in actionable if f.severity == "warn"),
        "n_fail": sum(1 for f in actionable if f.severity == "fail"),
    }
    return report


def format_realism_report(report: dict[str, Any]) -> str:
    h = int(report.get("horizon_months") or config.FORECAST_HORIZON_MONTHS)
    sev = str(report.get("severity", "ok")).upper()
    meta = report.get("meta") or {}
    lines = [
        f"--- MODEL REALISM DIAGNOSTICS ({sev}) ---",
        (
            f"  • Headline {h}M μ {meta.get('horizon_return', float('nan')):+.2%} | "
            f"σ {meta.get('horizon_vol', float('nan')):.2%} | "
            f"Sharpe_{h}M {meta.get('horizon_sharpe', float('nan')):.2f} "
            f"(ann. equiv ≈ {meta.get('annualized_sharpe_equivalent', float('nan')):.2f})"
        ),
    ]
    if "tilted_factor_mu" in meta:
        lines.append(
            f"  • Factor μ untilted {meta.get('untilted_factor_mu', 0):+.2%} → "
            f"tilted {meta.get('tilted_factor_mu', 0):+.2%} "
            f"(tilt lift {meta.get('tilt_lift', 0):+.2%})"
        )
    if meta.get("fade_tailwind_share") is not None:
        lines.append(
            f"  • Fade-tailwind share of gross |β×f| "
            f"{meta['fade_tailwind_share']:.0%} "
            f"(μ from those channels {meta.get('fade_tailwind_mu', 0):+.2%})"
        )
    if meta.get("diversification_ratio") is not None:
        lines.append(
            f"  • Diversification ratio {meta['diversification_ratio']:.2f} "
            f"(standalone {meta.get('weighted_standalone_vol', float('nan')):.1%} / "
            f"book {meta.get('horizon_vol', float('nan')):.1%})"
        )
    if meta.get("spy_expected") is not None:
        lines.append(
            f"  • SPY scored {h}M μ {meta['spy_expected']:+.2%}"
            + (
                f" → book is {meta['vs_spy_multiple']:.1f}× SPY"
                if meta.get("vs_spy_multiple") is not None
                else ""
            )
        )

    actionable = report.get("flags") or []
    if not actionable:
        lines.append("  • No realism gates tripped.")
    else:
        lines.append(f"  • Gates: {report.get('n_fail', 0)} fail / {report.get('n_warn', 0)} warn")
        for flag in actionable:
            mark = "FAIL" if flag["severity"] == "fail" else "WARN"
            lines.append(f"  • [{mark}] {flag['message']}")

    # Compact factor percentile strip (warns only, else one-liner).
    factor_warns = [
        f for f in (report.get("factor_notes") or []) if f.get("severity") == "warn"
    ]
    if factor_warns:
        lines.append("  • Factor forecast tails:")
        for flag in factor_warns:
            lines.append(f"      - {flag['message']}")
    return "\n".join(lines)


def realism_metric_records(report: dict[str, Any], execution_date: str) -> list[dict[str, Any]]:
    """Optional Supabase portfolio_metric rows for the realism summary."""
    meta = report.get("meta") or {}
    severity = str(report.get("severity", "ok"))
    records = [
        {
            "execution_date": execution_date,
            "data_type": "portfolio_metric",
            "ticker_or_factor": "realism_severity",
            "value": float(SEVERITY_RANK.get(severity, 0)),
        },
        {
            "execution_date": execution_date,
            "data_type": "portfolio_metric",
            "ticker_or_factor": "expected_sharpe_annualized",
            "value": float(meta.get("annualized_sharpe_equivalent") or 0.0),
        },
        {
            "execution_date": execution_date,
            "data_type": "portfolio_metric",
            "ticker_or_factor": "realism_fail_count",
            "value": float(report.get("n_fail") or 0),
        },
        {
            "execution_date": execution_date,
            "data_type": "portfolio_metric",
            "ticker_or_factor": "realism_warn_count",
            "value": float(report.get("n_warn") or 0),
        },
    ]
    if meta.get("tilt_lift") is not None:
        records.append(
            {
                "execution_date": execution_date,
                "data_type": "portfolio_metric",
                "ticker_or_factor": "realism_tilt_lift",
                "value": float(meta["tilt_lift"]),
            }
        )
    if meta.get("fade_tailwind_share") is not None:
        records.append(
            {
                "execution_date": execution_date,
                "data_type": "portfolio_metric",
                "ticker_or_factor": "realism_fade_tailwind_share",
                "value": float(meta["fade_tailwind_share"]),
            }
        )
    if meta.get("diversification_ratio") is not None:
        records.append(
            {
                "execution_date": execution_date,
                "data_type": "portfolio_metric",
                "ticker_or_factor": "realism_diversification_ratio",
                "value": float(meta["diversification_ratio"]),
            }
        )
    return records
