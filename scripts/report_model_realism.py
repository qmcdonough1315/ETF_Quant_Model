#!/usr/bin/env python3
"""
Run the live ETF pipeline and print model realism diagnostics only.

Does not export to Supabase or touch the paper ledger. Useful for desk review
when headline expected return / Sharpe look stretched.

  PYTHONPATH=. python3 scripts/report_model_realism.py
  PYTHONPATH=. python3 scripts/report_model_realism.py --json /tmp/realism.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import config
from modules.data_ingestion import fetch_all_data
from modules.dynamic_beta_estimator import run_kalman_filter_regressions
from modules.factor_forecaster import generate_factor_forecasts
from modules.fund_scorer import score_and_rank_funds
from modules.point_in_time import ken_french_asof
from modules.portfolio_optimizer import portfolio_expected_metrics
from modules.realism_diagnostics import format_realism_report, run_realism_diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Optional path to write the full realism JSON report",
    )
    args = parser.parse_args()

    prices, factors, macro = fetch_all_data(config.ETF_POPULATION)
    factors_pit = ken_french_asof(factors, factors.index.max())
    beta_profiles = run_kalman_filter_regressions(prices, factors_pit)
    forecast_report = generate_factor_forecasts(
        factors_pit, macro, threshold=config.MIN_FACTOR_THRESHOLD
    )
    top_picks, _betas, scores_df = score_and_rank_funds(
        beta_profiles=beta_profiles,
        forecast_report=forecast_report,
        prices=prices,
    )
    if top_picks.empty:
        print("No holdings produced — cannot score realism.", file=sys.stderr)
        return 1

    port_ret, port_vol, port_sharpe = portfolio_expected_metrics(top_picks, prices)
    report = run_realism_diagnostics(
        predictions=forecast_report["predictions"],
        factors=factors_pit,
        holdings=top_picks,
        scores_df=scores_df,
        beta_profiles=beta_profiles,
        prices=prices,
        port_return=port_ret,
        port_vol=port_vol,
        port_sharpe=port_sharpe,
    )
    print(format_realism_report(report))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, default=str))
        print(f"  • Wrote {args.json}")

    return 0 if report.get("severity") != "fail" else 2


if __name__ == "__main__":
    raise SystemExit(main())
