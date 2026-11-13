#!/usr/bin/env python3
"""
Append recent EOD ATM IV into option_iv_history (Wave E / #8).

Uses ThetaData free-tier EOD via modules.thetadata_iv_bootstrap — no demo IV.
Default window: last --days calendar days through last settled EOD date.

Examples:
  PYTHONPATH=. python3 scripts/refresh_option_iv_history.py --days 7
  PYTHONPATH=. python3 scripts/refresh_option_iv_history.py --tickers XLRE --days 30
  PYTHONPATH=. python3 scripts/refresh_option_iv_history.py --days 5 --no-upsert
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

from modules.options_sleeve import PHASE1_OPTIONABLE_ETFS
from modules.thetadata_iv_bootstrap import (
    default_history_window,
    last_settled_eod_date,
    run_bootstrap,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="Lookback calendar days (default 7)")
    parser.add_argument(
        "--tickers",
        default=",".join(PHASE1_OPTIONABLE_ETFS),
        help="Comma-separated underlyings",
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path("data/option_iv_history/atm_iv_refresh.csv"),
    )
    parser.add_argument("--no-upsert", action="store_true")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    end = last_settled_eod_date()
    start = end - timedelta(days=max(int(args.days), 1) - 1)
    floor_start, _ = default_history_window(end)
    if start < floor_start:
        start = floor_start

    print(f"[iv-refresh] {tickers} {start} → {end} upsert={not args.no_upsert}")
    try:
        df = run_bootstrap(
            tickers,
            start=start,
            end=end,
            artifact_path=args.artifact,
            upsert=not args.no_upsert,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[iv-refresh] FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"[iv-refresh] rows={len(df)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
