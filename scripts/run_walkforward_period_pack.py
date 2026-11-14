#!/usr/bin/env python3
"""
Run the frozen research-card period pack and write period_matrix.json (+ markdown).

Equity sleeve: production Target_Weight walk-forward at RESEARCH_* assumptions.
Options book: phase1 sleeve when IV history is available; else status=uncovered
with cash-drag (0%) assumed inside the combined 50/50 book.

Example:
  PYTHONPATH=. python3 scripts/run_walkforward_period_pack.py \\
      --artifact-dir /opt/cursor/artifacts/walkforward_research_card \\
      --cost-bps 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from modules.research_card import (
    build_card_envelope,
    metrics_payload,
    options_pnl_to_period_returns,
    render_report_markdown,
    research_assumptions,
    write_json,
)
from modules.walkforward_metrics import blend_period_returns
from run_walkforward_backtest import resolve_period, run_walkforward_backtest


def _try_options_trades(
    start: str,
    end: Optional[str],
    *,
    iv_csv: Optional[str],
    from_supabase: bool,
    options_book_usd: float,
) -> tuple[str, Optional[pd.DataFrame], dict[str, Any]]:
    """Return (status, trades_df|None, meta)."""
    try:
        from modules.options_sleeve import PHASE1_OPTIONABLE_ETFS
        from modules.options_sleeve_backtest import (
            load_iv_history,
            run_options_sleeve_backtest,
        )
        # Shared daily price helper lives on the options CLI module.
        from run_options_sleeve_backtest import fetch_daily_prices
    except Exception as e:  # noqa: BLE001
        return "error", None, {"error": str(e)}

    try:
        iv = load_iv_history(iv_csv, from_supabase=from_supabase)
    except FileNotFoundError as e:
        return "uncovered", None, {"reason": str(e)}
    except Exception as e:  # noqa: BLE001
        return "uncovered", None, {"reason": str(e)}

    iv_start, iv_end = iv["as_of_date"].min(), iv["as_of_date"].max()
    req_start = pd.Timestamp(start)
    req_end = pd.Timestamp(end) if end else iv_end
    use_start = max(req_start, iv_start)
    use_end = min(req_end, iv_end)
    if use_start > use_end:
        return (
            "uncovered",
            None,
            {
                "reason": "no_iv_overlap",
                "iv_start": str(iv_start.date()),
                "iv_end": str(iv_end.date()),
                "requested_start": str(req_start.date()),
                "requested_end": str(req_end.date()),
            },
        )

    tickers = list(PHASE1_OPTIONABLE_ETFS)
    dl_start = (use_start - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    try:
        prices = fetch_daily_prices(tickers, dl_start, use_end.strftime("%Y-%m-%d"))
        trades = run_options_sleeve_backtest(
            iv,
            prices,
            start=str(use_start.date()),
            end=str(use_end.date()),
            mode="phase1",
            capital_usd=float(options_book_usd),
        )
    except Exception as e:  # noqa: BLE001
        return "error", None, {"error": str(e)}

    meta = {
        "window_start": str(use_start.date()),
        "window_end": str(use_end.date()),
        "iv_rows": int(len(iv)),
        "n_trades": int(len(trades)),
        "clamped": bool(use_start != req_start or use_end != req_end),
    }
    return "ok", trades, meta


def _period_row_from_etf(
    period_id: str,
    results_df: pd.DataFrame,
    *,
    options_status: str,
    options_trades: Optional[pd.DataFrame],
    options_meta: dict[str, Any],
    assumptions: dict[str, Any],
) -> dict[str, Any]:
    spec = config.BACKTEST_PERIODS[period_id]
    horizon = results_df.attrs["horizon_label"]
    ppy = float(results_df.attrs["periods_per_year"])
    rf = float(results_df.attrs["risk_free_rate"])
    opt_cap = float(assumptions["options_book_usd"])
    etf_w = float(assumptions["etf_weight"])
    opt_w = float(assumptions["options_weight"])
    peer = str(assumptions["headline_peer"])

    ret_col = f"Strategy_Return_{horizon}"
    etf_rets = results_df[ret_col]
    reb = results_df["Rebalance_Date"].tolist()
    windows = list(zip(results_df["Holding_Start"], results_df["Holding_End"]))

    if options_status == "ok" and options_trades is not None:
        opt_rets = options_pnl_to_period_returns(
            options_trades,
            reb,
            windows,
            options_book_usd=opt_cap,
        )
        # Align to ETF positional index so 50/50 blend does not mis-join on labels.
        opt_rets = pd.Series(opt_rets.to_numpy(), index=etf_rets.index, dtype=float)
        opt_extra = {
            "status": "ok",
            "n_trades": int(len(options_trades)),
            **{k: v for k, v in options_meta.items() if k != "n_trades"},
        }
        opt_summary = metrics_payload(
            opt_rets,
            initial_capital=opt_cap,
            risk_free_rate=rf,
            periods_per_year=ppy,
            extra=opt_extra,
        )
    else:
        # Cash drag inside the options book when IV uncovered / failed.
        opt_rets = pd.Series(0.0, index=etf_rets.index, dtype=float)
        opt_summary = metrics_payload(
            opt_rets,
            initial_capital=opt_cap,
            risk_free_rate=rf,
            periods_per_year=ppy,
            extra={
                "status": options_status,
                "n_trades": 0,
                **options_meta,
                "note": (
                    "Options PnL not simulated for this window; "
                    "combined assumes idle cash (0%)."
                ),
            },
        )

    combined_rets = blend_period_returns(
        etf_rets, opt_rets, left_weight=etf_w, right_weight=opt_w
    )
    peer_col = f"{peer}_Return_{horizon}"
    peer_rets = (
        pd.Series(results_df[peer_col].to_numpy(), index=etf_rets.index, dtype=float)
        if peer_col in results_df.columns
        else None
    )
    combined_summary = metrics_payload(
        combined_rets,
        initial_capital=float(assumptions["total_capital_usd"]),
        risk_free_rate=rf,
        periods_per_year=ppy,
        benchmark_returns=peer_rets,
        extra={
            "status": "ok" if options_status == "ok" else "options_cash_drag",
            "etf_weight": etf_w,
            "options_weight": opt_w,
        },
    )

    etf_summary = dict(results_df.attrs["strategy_summary"])
    benches = dict(results_df.attrs["benchmark_summaries"])

    return {
        "period_id": period_id,
        "label": spec.get("label"),
        "start": results_df.attrs.get("start_date"),
        "end": results_df.attrs.get("end_date"),
        "tune": bool(spec.get("tune", True)),
        "coverage": results_df.attrs.get("coverage"),
        "etf": etf_summary,
        "options": opt_summary,
        "combined": combined_summary,
        "benchmarks": benches,
    }


def run_period_pack(
    periods: list[str],
    *,
    artifact_dir: Path,
    cost_bps: float,
    smoke: bool,
    iv_csv: Optional[str],
    from_supabase: bool,
    skip_options: bool,
) -> dict[str, Any]:
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    assumptions = research_assumptions(cost_bps_one_way=cost_bps)
    period_rows: list[dict[str, Any]] = []

    universe = None
    if smoke:
        universe = [
            "SPY",
            "QQQ",
            "IWM",
            "XLK",
            "XLF",
            "XLE",
            "XLV",
            "VTI",
            "VGT",
            "VOO",
            "JEPI",
        ]

    for period_id in periods:
        key = period_id.upper()
        pid, start, end, step, tune = resolve_period(key, None, None, None)
        if not tune:
            print(f"NOTE: {pid} is HOLD_OUT / tune=False — reporting only.")
        print(f"\n>>> Pack period {pid} ({start} → {end or 'latest'}) step={step}M")

        results = run_walkforward_backtest(
            start_date=start,
            end_date=end,
            initial_capital=float(assumptions["etf_capital_usd"]),
            rebalance_step_months=step,
            cost_bps_one_way=cost_bps,
            period_id=pid,
            universe=universe,
            artifact_dir=artifact_dir / "etf",
        )
        if results.empty:
            period_rows.append(
                {
                    "period_id": pid,
                    "label": config.BACKTEST_PERIODS[pid].get("label"),
                    "start": start,
                    "end": end,
                    "error": "empty_walkforward",
                }
            )
            continue

        if skip_options:
            opt_status, trades, opt_meta = "skipped", None, {"reason": "skip_options"}
        else:
            opt_status, trades, opt_meta = _try_options_trades(
                start,
                end,
                iv_csv=iv_csv,
                from_supabase=from_supabase,
                options_book_usd=float(assumptions["options_book_usd"]),
            )

        row = _period_row_from_etf(
            pid,
            results,
            options_status=opt_status,
            options_trades=trades,
            options_meta=opt_meta,
            assumptions=assumptions,
        )
        period_rows.append(row)
        write_json(artifact_dir / "etf" / pid / "period_row.json", row)

    card = build_card_envelope(period_rows, assumptions=assumptions)
    write_json(artifact_dir / "period_matrix.json", card)
    md = render_report_markdown(card)
    (artifact_dir / "WALKFORWARD_REPORT.md").write_text(md)
    print(f"\nWrote {artifact_dir / 'period_matrix.json'}")
    print(f"Wrote {artifact_dir / 'WALKFORWARD_REPORT.md'}")
    return card


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--periods",
        default=",".join(config.RESEARCH_CARD_PERIODS),
        help="Comma-separated BACKTEST_PERIODS ids",
    )
    parser.add_argument(
        "--artifact-dir",
        default="/opt/cursor/artifacts/walkforward_research_card",
    )
    parser.add_argument(
        "--cost-bps",
        type=float,
        default=float(config.RESEARCH_EQUITY_COST_BPS_ONE_WAY),
    )
    parser.add_argument("--smoke", action="store_true", help="Tiny liquid universe")
    parser.add_argument("--iv-csv", default=None)
    parser.add_argument("--from-supabase", action="store_true")
    parser.add_argument(
        "--skip-options",
        action="store_true",
        help="ETF-only pack; options leg treated as idle cash in combined book",
    )
    args = parser.parse_args()
    periods = [p.strip().upper() for p in args.periods.split(",") if p.strip()]
    run_period_pack(
        periods,
        artifact_dir=Path(args.artifact_dir),
        cost_bps=float(args.cost_bps),
        smoke=bool(args.smoke),
        iv_csv=args.iv_csv,
        from_supabase=bool(args.from_supabase),
        skip_options=bool(args.skip_options),
    )


if __name__ == "__main__":
    main()
