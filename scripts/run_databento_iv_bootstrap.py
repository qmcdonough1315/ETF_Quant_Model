#!/usr/bin/env python3
"""
Download Databento OPRA EOD NBBO (cbbo-1m, 15:50–16:00 ET) for Phase 1 ETFs,
reduce to ATM ~30 DTE IV, write option_iv_history-compatible CSV.

Safety: estimates cost first and refuses to run if estimate > --budget unless --force.
Requires DATABENTO_API_KEY for live pulls.

Example:
  PYTHONPATH=. python3 scripts/run_databento_iv_bootstrap.py --cost-only
  PYTHONPATH=. python3 scripts/run_databento_iv_bootstrap.py --tickers SPY --start 2024-01-01 --end 2024-01-31
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
    run_bootstrap,
    run_cost_estimate,
)
from modules.options_sleeve import PHASE1_OPTIONABLE_ETFS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tickers",
        default=",".join(PHASE1_OPTIONABLE_ETFS),
    )
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET_USD)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path("data/option_iv_history/atm_iv_databento.csv"),
    )
    parser.add_argument(
        "--cost-only",
        action="store_true",
        help="Only write the cost estimate (no download)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow download even if estimate exceeds budget (still stops when live costs exhaust budget)",
    )
    parser.add_argument(
        "--upsert",
        action="store_true",
        help="Upsert into Supabase option_iv_history when credentials exist",
    )
    args = parser.parse_args()
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    if args.cost_only:
        run_cost_estimate(
            tickers=tickers,
            start=args.start,
            end=args.end,
            budget_usd=float(args.budget),
        )
        return

    run_bootstrap(
        tickers,
        start=args.start,
        end=args.end,
        budget_usd=float(args.budget),
        artifact_path=args.artifact,
        upsert=bool(args.upsert),
        force=bool(args.force),
    )


if __name__ == "__main__":
    main()
