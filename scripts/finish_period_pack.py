#!/usr/bin/env python3
"""
Finish / rebuild a research-card pack from partial ETF artifacts.

- Rebuilds options legs for periods that already have steps.csv + summary.json
- Runs missing periods fresh
- Writes period_matrix.json + WALKFORWARD_REPORT.md
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
from modules.walkforward_metrics import blend_period_returns, periods_per_year_from_step
from run_walkforward_backtest import resolve_period, run_walkforward_backtest

# Import pack helpers without requiring scripts/ to be a package.
import importlib.util

_pack_path = Path(__file__).with_name("run_walkforward_period_pack.py")
_spec = importlib.util.spec_from_file_location("run_walkforward_period_pack", _pack_path)
_pack = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_pack)
_period_row_from_etf = _pack._period_row_from_etf
_try_options_trades = _pack._try_options_trades


def _hydrate_results_from_artifacts(period_dir: Path) -> Optional[pd.DataFrame]:
    steps = period_dir / "steps.csv"
    summary_path = period_dir / "summary.json"
    if not steps.is_file() or not summary_path.is_file():
        return None
    import json

    summary = json.loads(summary_path.read_text())
    df = pd.read_csv(steps)
    df.attrs["period_id"] = summary.get("period_id")
    df.attrs["coverage"] = summary.get("coverage")
    df.attrs["strategy_summary"] = summary.get("etf")
    df.attrs["benchmark_summaries"] = summary.get("benchmarks")
    df.attrs["horizon_label"] = summary.get("horizon_label") or "3M"
    step_m = int(config.BACKTEST_PERIODS[summary["period_id"]].get("rebalance_step_months", 3))
    df.attrs["periods_per_year"] = periods_per_year_from_step(step_m)
    df.attrs["initial_capital"] = float(config.RESEARCH_ETF_CAPITAL_USD)
    df.attrs["risk_free_rate"] = float(config.RESEARCH_RISK_FREE_RATE)
    df.attrs["cost_bps_one_way"] = summary.get("cost_bps_one_way")
    df.attrs["start_date"] = summary.get("start")
    df.attrs["end_date"] = summary.get("end")
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-etf-dir",
        type=Path,
        default=Path("/opt/cursor/artifacts/walkforward_research_card/live/etf"),
        help="Existing etf/<PERIOD> artifact directory",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path("artifacts/walkforward_research_card_live"),
    )
    parser.add_argument("--cost-bps", type=float, default=5.0)
    parser.add_argument("--from-supabase", action="store_true")
    parser.add_argument("--iv-csv", default=None)
    parser.add_argument("--skip-options", action="store_true")
    parser.add_argument(
        "--periods",
        default=",".join(config.RESEARCH_CARD_PERIODS),
    )
    args = parser.parse_args()

    assumptions = research_assumptions(cost_bps_one_way=args.cost_bps)
    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    etf_out = artifact_dir / "etf"
    etf_out.mkdir(parents=True, exist_ok=True)

    period_rows: list[dict[str, Any]] = []
    for period_id in [p.strip().upper() for p in args.periods.split(",") if p.strip()]:
        print(f"\n>>> Finish period {period_id}")
        src = Path(args.source_etf_dir) / period_id
        results = _hydrate_results_from_artifacts(src)

        if results is None or results.empty:
            pid, start, end, step, tune = resolve_period(period_id, None, None, None)
            if not tune:
                print(f"NOTE: {pid} is HOLD_OUT / tune=False")
            results = run_walkforward_backtest(
                start_date=start,
                end_date=end,
                initial_capital=float(assumptions["etf_capital_usd"]),
                rebalance_step_months=step,
                cost_bps_one_way=args.cost_bps,
                period_id=pid,
                artifact_dir=etf_out,
            )
            if results.empty:
                period_rows.append(
                    {
                        "period_id": period_id,
                        "label": config.BACKTEST_PERIODS[period_id].get("label"),
                        "error": "empty_walkforward",
                    }
                )
                continue
        else:
            # Mirror hydrated artifacts into the output tree.
            dest = etf_out / period_id
            dest.mkdir(parents=True, exist_ok=True)
            results.to_csv(dest / "steps.csv", index=False)
            write_json(
                dest / "summary.json",
                {
                    "period_id": period_id,
                    "start": results.attrs.get("start_date"),
                    "end": results.attrs.get("end_date"),
                    "coverage": results.attrs.get("coverage"),
                    "etf": results.attrs.get("strategy_summary"),
                    "benchmarks": results.attrs.get("benchmark_summaries"),
                    "horizon_label": results.attrs.get("horizon_label"),
                    "cost_bps_one_way": results.attrs.get("cost_bps_one_way"),
                },
            )

        if args.skip_options:
            opt_status, trades, opt_meta = "skipped", None, {"reason": "skip_options"}
        else:
            start = results.attrs.get("start_date")
            end = results.attrs.get("end_date")
            opt_status, trades, opt_meta = _try_options_trades(
                str(start),
                str(end) if end else None,
                iv_csv=args.iv_csv,
                from_supabase=bool(args.from_supabase),
                options_book_usd=float(assumptions["options_book_usd"]),
            )
            print(f"  options status={opt_status} meta={opt_meta}")

        row = _period_row_from_etf(
            period_id,
            results,
            options_status=opt_status,
            options_trades=trades,
            options_meta=opt_meta,
            assumptions=assumptions,
        )
        period_rows.append(row)
        write_json(etf_out / period_id / "period_row.json", row)

    card = build_card_envelope(period_rows, assumptions=assumptions)
    # Clear sample flag if present from prior templates
    card["assumptions"].pop("sample", None)
    write_json(artifact_dir / "period_matrix.json", card)
    (artifact_dir / "WALKFORWARD_REPORT.md").write_text(render_report_markdown(card))
    print(f"\nWrote {artifact_dir / 'period_matrix.json'}")
    print(f"Wrote {artifact_dir / 'WALKFORWARD_REPORT.md'}")


if __name__ == "__main__":
    main()
