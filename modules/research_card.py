"""
Research-card helpers: assumptions, benchmark blends, artifact I/O, report rows.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

import config
from modules.backtest_returns import portfolio_period_return
from modules.walkforward_metrics import summarize_period_returns


SCHEMA_VERSION = 1


def research_assumptions(
    *,
    cost_bps_one_way: Optional[float] = None,
    rebalance_step_months: int = 3,
) -> dict[str, Any]:
    bps = (
        float(cost_bps_one_way)
        if cost_bps_one_way is not None
        else float(config.RESEARCH_EQUITY_COST_BPS_ONE_WAY)
    )
    return {
        "total_capital_usd": float(config.RESEARCH_TOTAL_CAPITAL_USD),
        "etf_weight": float(config.RESEARCH_ETF_WEIGHT),
        "options_weight": float(config.RESEARCH_OPTIONS_WEIGHT),
        "etf_capital_usd": float(config.RESEARCH_ETF_CAPITAL_USD),
        "options_book_usd": float(config.RESEARCH_OPTIONS_BOOK_USD),
        "options_book_includes_cash_reserve": True,
        "etf_cost_bps_one_way": bps,
        "rebalance_step_months": int(rebalance_step_months),
        "risk_free_rate": float(config.RESEARCH_RISK_FREE_RATE),
        "weighting": "Target_Weight",
        "headline_peer": str(config.RESEARCH_HEADLINE_PEER),
        "note": (
            "Allocator view is $100k at 50/50 ETF model / options book. "
            "Paper ops may still show $25k options sleeve + $25k margin reserve; "
            "research collapses that reserve into the options book (collateral for bets). "
            "Idle options cash earns 0 in this card unless noted."
        ),
    }


def benchmark_specs() -> dict[str, Any]:
    return {k: dict(v) for k, v in config.RESEARCH_BENCHMARKS.items()}


def required_benchmark_tickers() -> list[str]:
    tickers: set[str] = set()
    for spec in config.RESEARCH_BENCHMARKS.values():
        tickers.update(str(t).upper() for t in spec["weights"])
    return sorted(tickers)


def holding_window_return(
    returns_df: pd.DataFrame,
    holding_dates: pd.DatetimeIndex,
    weights: dict[str, float],
) -> float:
    """Compound a static weight blend over a holding window."""
    cols = [c for c in weights if c in returns_df.columns]
    if not cols:
        return 0.0
    period = returns_df.loc[holding_dates, cols]
    return float(portfolio_period_return(period, weights, equal_weight=False))


def metrics_payload(
    period_returns: pd.Series,
    *,
    initial_capital: float,
    risk_free_rate: float,
    periods_per_year: float,
    benchmark_returns: Optional[pd.Series] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    base = summarize_period_returns(
        period_returns,
        initial_capital=initial_capital,
        risk_free_rate=risk_free_rate,
        periods_per_year=periods_per_year,
        benchmark_returns=benchmark_returns,
    )
    if extra:
        base.update(extra)
    return base


def options_pnl_to_period_returns(
    trades: pd.DataFrame,
    rebalance_dates: list[str],
    holding_windows: list[tuple[str, str]],
    *,
    options_book_usd: float,
) -> pd.Series:
    """
    Map options trade PnL into ETF-aligned holding windows by exit date.

    Windows with no exits contribute 0 (cash / no realized sleeve PnL).
    """
    if options_book_usd <= 0:
        return pd.Series(0.0, index=rebalance_dates, dtype=float)
    if trades is None or trades.empty:
        return pd.Series(0.0, index=rebalance_dates, dtype=float)

    df = trades.copy()
    df["exit_date"] = pd.to_datetime(df["exit_date"])
    out = []
    for reb, (start_s, end_s) in zip(rebalance_dates, holding_windows):
        start = pd.Timestamp(start_s)
        end = pd.Timestamp(end_s)
        # Month-label windows from walk-forward are YYYY-MM; expand to month bounds.
        if len(start_s) == 7:
            start = pd.Timestamp(start_s + "-01")
            end = pd.Timestamp(end_s + "-01") + pd.offsets.MonthEnd(0)
        mask = (df["exit_date"] >= start) & (df["exit_date"] <= end)
        pnl = float(df.loc[mask, "pnl_usd"].sum()) if mask.any() else 0.0
        out.append(pnl / float(options_book_usd))
    return pd.Series(out, index=rebalance_dates, dtype=float)


def build_card_envelope(
    periods: list[dict[str, Any]],
    *,
    assumptions: Optional[dict[str, Any]] = None,
    run_id: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "assumptions": assumptions or research_assumptions(),
        "benchmarks": benchmark_specs(),
        "periods": periods,
    }


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = _sanitize_for_json(payload)
    # allow_nan=False so Vite/JSON.parse never see bare NaN/Infinity tokens.
    path.write_text(
        json.dumps(clean, indent=2, default=_json_default, allow_nan=False) + "\n"
    )
    return path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively replace NaN/±Inf with None for strict JSON."""
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            return None
        return obj
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if hasattr(obj, "item"):
        try:
            return _sanitize_for_json(obj.item())
        except Exception:  # noqa: BLE001
            pass
    return obj


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if isinstance(obj, float) and (obj != obj or obj in (float("inf"), float("-inf"))):
        return None
    if hasattr(obj, "item"):
        try:
            return _sanitize_for_json(obj.item())
        except Exception:  # noqa: BLE001
            pass
    return str(obj)


def markdown_period_table(card: dict[str, Any]) -> str:
    """Concise front-page markdown table for the research card."""
    peer = card.get("assumptions", {}).get("headline_peer", config.RESEARCH_HEADLINE_PEER)
    lines = [
        "| Period | Story | Combined | vs peer | Sharpe | MDD | Hit vs peer | Options |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for p in card.get("periods", []):
        pid = p.get("period_id", "")
        story = p.get("label", "")
        comb = p.get("combined") or {}
        peer_m = (p.get("benchmarks") or {}).get(peer) or {}
        opt = p.get("options") or {}
        status = opt.get("status", "n/a")
        if status == "uncovered":
            opt_cell = "uncovered"
        elif status == "ok":
            opt_cell = _pct(opt.get("total_return"))
        else:
            opt_cell = status
        vs_peer = comb.get("excess_total_vs_benchmark")
        if vs_peer is None and peer_m.get("total_return") is not None and comb.get("total_return") is not None:
            vs_peer = float(comb["total_return"]) - float(peer_m["total_return"])
        lines.append(
            "| {pid} | {story} | {comb_ret} | {vs} | {sharpe} | {mdd} | {hit} | {opt} |".format(
                pid=pid,
                story=story,
                comb_ret=_pct(comb.get("total_return")),
                vs=_pct(vs_peer),
                sharpe=_num(comb.get("sharpe")),
                mdd=_mdd(comb.get("max_drawdown")),
                hit=_pct(comb.get("hit_rate_vs_benchmark"), digits=0),
                opt=opt_cell,
            )
        )
    return "\n".join(lines)


def render_report_markdown(card: dict[str, Any]) -> str:
    a = card.get("assumptions", {})
    lines = [
        "# Walk-forward research card",
        "",
        f"- Generated: `{card.get('generated_at')}`",
        f"- Run id: `{card.get('run_id')}`",
        (
            f"- Book: ${a.get('total_capital_usd', 0):,.0f} at "
            f"{100 * float(a.get('etf_weight', 0.5)):.0f}/"
            f"{100 * float(a.get('options_weight', 0.5)):.0f} "
            "ETF model / options book (reserve included in options book)"
        ),
        (
            f"- ETF costs: {a.get('etf_cost_bps_one_way')} bps one-way · "
            f"step {a.get('rebalance_step_months')}M · "
            f"weights `{a.get('weighting')}` · rf={a.get('risk_free_rate')}"
        ),
        f"- Headline peer: `{a.get('headline_peer')}`",
        "",
        a.get("note", ""),
        "",
        "## Period matrix",
        "",
        markdown_period_table(card),
        "",
        "## Benchmarks",
        "",
    ]
    for bid, spec in (card.get("benchmarks") or {}).items():
        lines.append(f"- `{bid}` — {spec.get('label')} ({spec.get('role')})")
    lines.extend(["", "## Period detail", ""])
    for p in card.get("periods", []):
        lines.append(f"### {p.get('period_id')} — {p.get('label')}")
        lines.append("")
        lines.append(
            f"- Window: `{p.get('start')}` → `{p.get('end') or 'latest'}` · "
            f"coverage={_pct(p.get('coverage'))}"
        )
        etf = p.get("etf") or {}
        lines.append(
            f"- ETF sleeve: {_pct(etf.get('total_return'))} · Sharpe {_num(etf.get('sharpe'))} · "
            f"avg turnover {_num(etf.get('avg_turnover'), 3)}"
        )
        opt = p.get("options") or {}
        lines.append(
            f"- Options book: status `{opt.get('status')}` · "
            f"{_pct(opt.get('total_return'))} · n_trades={opt.get('n_trades', 'n/a')}"
        )
        for bid, bm in (p.get("benchmarks") or {}).items():
            lines.append(f"- {bid}: {_pct(bm.get('total_return'))} · Sharpe {_num(bm.get('sharpe'))}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _pct(x: Any, digits: int = 2) -> str:
    if x is None:
        return "—"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if v != v:
        return "—"
    return f"{v * 100:+.{digits}f}%"


def _mdd(x: Any, digits: int = 2) -> str:
    """Max drawdown is ≤ 0; render without a misleading plus on zeros."""
    if x is None:
        return "—"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if v != v:
        return "—"
    return f"{v * 100:.{digits}f}%"


def _num(x: Any, digits: int = 2) -> str:
    if x is None:
        return "—"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if v != v:
        return "—"
    return f"{v:.{digits}f}"
