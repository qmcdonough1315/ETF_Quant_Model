#!/usr/bin/env python3
"""
Bootstrap ~1y of Phase 1 ETF ATM IV history from ThetaData free EOD.

Requires:
  THETADATA_API_KEY
Optional:
  SUPABASE_URL, SUPABASE_KEY  (upsert into option_iv_history)

Usage:
  python run_iv_bootstrap.py
  python run_iv_bootstrap.py --no-upsert --tickers SPY,QQQ
  python run_iv_bootstrap.py --start 2025-01-01 --end 2025-06-30
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from modules.options_sleeve import PHASE1_OPTIONABLE_ETFS
from modules.thetadata_iv_bootstrap import run_bootstrap


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tickers",
        default=",".join(PHASE1_OPTIONABLE_ETFS),
        help="Comma-separated underlyings (default: Phase 1 list)",
    )
    parser.add_argument("--start", type=_parse_date, default=None)
    parser.add_argument("--end", type=_parse_date, default=None)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path("data/option_iv_history/atm_iv_bootstrap.csv"),
    )
    parser.add_argument(
        "--no-upsert",
        action="store_true",
        help="Skip Supabase upsert (still writes local CSV)",
    )
    args = parser.parse_args()
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    df = run_bootstrap(
        tickers,
        start=args.start,
        end=args.end,
        artifact_path=args.artifact,
        upsert=not args.no_upsert,
    )
    print(f"[iv-bootstrap] done: {len(df)} rows, tickers={sorted(df['ticker'].unique()) if len(df) else []}")


if __name__ == "__main__":
    main()
