#!/usr/bin/env python3
"""
Build a schema-valid sample period_matrix.json for UI wiring (no market download).

Numbers are illustrative placeholders — replace by running
scripts/run_walkforward_period_pack.py against live data.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from modules.research_card import (
    build_card_envelope,
    render_report_markdown,
    research_assumptions,
    write_json,
)


def _sleeve(total_return: float, sharpe: float, mdd: float, hit: float, excess: float):
    return {
        "n_periods": 4,
        "final_value": 50_000 * (1 + total_return),
        "total_return": total_return,
        "ann_vol": 0.15,
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "hit_rate_vs_benchmark": hit,
        "excess_total_vs_benchmark": excess,
        "avg_turnover": 0.25,
        "total_costs": 0.002,
        "cost_bps_one_way": 5.0,
    }


def _bench(total_return: float, sharpe: float):
    return {
        "n_periods": 4,
        "final_value": 50_000 * (1 + total_return),
        "total_return": total_return,
        "ann_vol": 0.14,
        "sharpe": sharpe,
        "max_drawdown": -0.12,
        "hit_rate_vs_benchmark": None,
        "excess_total_vs_benchmark": None,
    }


def sample_periods():
    # Illustrative shape only — not live results.
    specs = [
        ("FULL", 0.42, 0.38, 0.55, -0.18, 0.55, 0.04),
        ("COVID", 0.12, 0.08, 0.35, -0.22, 0.50, 0.03),
        ("BEAR_22", -0.08, -0.12, 0.10, -0.20, 0.40, 0.02),
        ("BULL_23_24", 0.28, 0.22, 0.70, -0.08, 0.60, 0.04),
        ("HOLD_OUT", 0.09, 0.07, 0.45, -0.06, 0.50, 0.01),
    ]
    rows = []
    for pid, comb, peer, sharpe, mdd, hit, excess in specs:
        period = config.BACKTEST_PERIODS[pid]
        etf_ret = comb * 1.1
        opt_ret = comb * 0.9
        rows.append(
            {
                "period_id": pid,
                "label": period.get("label"),
                "start": period.get("start"),
                "end": period.get("end"),
                "tune": bool(period.get("tune", True)),
                "coverage": 0.92,
                "sample": True,
                "etf": {
                    **_sleeve(etf_ret, sharpe + 0.05, mdd, hit, excess),
                    "coverage": 0.92,
                },
                "options": {
                    "status": "sample",
                    "n_trades": 12,
                    "total_return": opt_ret,
                    "sharpe": sharpe - 0.05,
                    "max_drawdown": mdd * 0.5,
                    "final_value": 50_000 * (1 + opt_ret),
                    "ann_vol": 0.10,
                    "hit_rate_vs_benchmark": None,
                    "excess_total_vs_benchmark": None,
                    "note": "Placeholder — replace with period pack output",
                },
                "combined": {
                    **_sleeve(comb, sharpe, mdd, hit, excess),
                    "final_value": 100_000 * (1 + comb),
                    "status": "sample",
                    "etf_weight": 0.5,
                    "options_weight": 0.5,
                },
                "benchmarks": {
                    "VOO": _bench(peer * 0.95, sharpe - 0.05),
                    "JEPI": _bench(peer * 0.9, sharpe),
                    "VOO_JEPI_50_50": _bench(peer, sharpe),
                    "VGT": _bench(peer * 1.2, sharpe + 0.1),
                },
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "research_card" / "period_matrix.sample.json",
    )
    args = parser.parse_args()
    assumptions = research_assumptions(cost_bps_one_way=5.0)
    assumptions["sample"] = True
    assumptions["note"] = (
        assumptions["note"]
        + " THIS FILE IS A SCHEMA SAMPLE with illustrative numbers — not live backtest output."
    )
    card = build_card_envelope(sample_periods(), assumptions=assumptions, run_id="sample")
    write_json(args.out, card)
    md_path = args.out.with_suffix(".md")
    md_path.write_text(render_report_markdown(card))
    print(f"Wrote {args.out}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
