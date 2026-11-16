#!/usr/bin/env python3
"""
Estimate Databento OPRA cost for Phase 1 ETF option EOD NBBO → option_iv_history.

Does not download data. With DATABENTO_API_KEY, calibrates size via metadata.get_cost
on a sample day; otherwise uses published $/GB heuristics.

Example:
  PYTHONPATH=. python3 scripts/databento_iv_cost_estimate.py
  PYTHONPATH=. python3 scripts/databento_iv_cost_estimate.py --tickers SPY,QQQ --budget 125
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.databento_iv_bootstrap import (
    DEFAULT_BUDGET_USD,
    DEFAULT_END,
    DEFAULT_START,
    run_cost_estimate,
)
from modules.options_sleeve import PHASE1_OPTIONABLE_ETFS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tickers",
        default=",".join(PHASE1_OPTIONABLE_ETFS),
        help="Comma-separated underlyings",
    )
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET_USD)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path("/opt/cursor/artifacts/databento_iv_cost_estimate.md"),
    )
    args = parser.parse_args()
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    run_cost_estimate(
        tickers=tickers,
        start=args.start,
        end=args.end,
        budget_usd=float(args.budget),
        artifact=args.artifact,
    )


if __name__ == "__main__":
    main()
