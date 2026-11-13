#!/usr/bin/env python3
"""
Report option_iv_history coverage for Phase 1 tickers and XLRE gaps vs SPY (#8).

Loads Supabase (default) or a local CSV. Writes a markdown artifact; never invents IV.
Optionally backfill XLRE missing dates via ThetaData when --backfill-xlre is set.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

from modules.options_sleeve import PHASE1_OPTIONABLE_ETFS


def _load_from_supabase() -> pd.DataFrame:
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY required")
    client = create_client(url, key)
    rows: list[dict] = []
    start = 0
    while True:
        batch = (
            client.table("option_iv_history")
            .select("as_of_date,ticker,atm_iv,source")
            .range(start, start + 999)
            .execute()
            .data
        )
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 1000:
            break
        start += 1000
    return pd.DataFrame(rows)


def _coverage(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ticker"] = df["ticker"].astype(str).str.upper()
    df["as_of_date"] = pd.to_datetime(df["as_of_date"]).dt.normalize()
    rows = []
    for t in PHASE1_OPTIONABLE_ETFS:
        sub = df[df["ticker"] == t]
        if sub.empty:
            rows.append(
                {
                    "ticker": t,
                    "n_rows": 0,
                    "min_date": None,
                    "max_date": None,
                    "n_unique_dates": 0,
                }
            )
            continue
        rows.append(
            {
                "ticker": t,
                "n_rows": int(len(sub)),
                "min_date": sub["as_of_date"].min().date().isoformat(),
                "max_date": sub["as_of_date"].max().date().isoformat(),
                "n_unique_dates": int(sub["as_of_date"].nunique()),
            }
        )
    return pd.DataFrame(rows)


def _xlre_gaps_vs_spy(df: pd.DataFrame) -> list[date]:
    df = df.copy()
    df["ticker"] = df["ticker"].astype(str).str.upper()
    df["as_of_date"] = pd.to_datetime(df["as_of_date"]).dt.normalize()
    spy = set(df.loc[df["ticker"] == "SPY", "as_of_date"].dt.date)
    xlre = set(df.loc[df["ticker"] == "XLRE", "as_of_date"].dt.date)
    return sorted(spy - xlre)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iv-csv", type=Path, default=None)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path("/opt/cursor/artifacts/iv_coverage_report.md"),
    )
    parser.add_argument(
        "--backfill-xlre",
        action="store_true",
        help="Attempt ThetaData pull for XLRE dates missing vs SPY (can be slow)",
    )
    parser.add_argument("--no-upsert", action="store_true")
    args = parser.parse_args()

    if args.iv_csv is not None:
        df = pd.read_csv(args.iv_csv)
        source = str(args.iv_csv)
    else:
        try:
            df = _load_from_supabase()
            source = "supabase:option_iv_history"
        except Exception as exc:  # noqa: BLE001
            print(f"Supabase load failed: {exc}", file=sys.stderr)
            return 1

    if df.empty:
        print("No IV rows — refuse to invent coverage.", file=sys.stderr)
        return 1

    cov = _coverage(df)
    gaps = _xlre_gaps_vs_spy(df)
    print(cov.to_string(index=False))
    print(f"\nXLRE gaps vs SPY dates: {len(gaps)}")
    if gaps[:10]:
        print("  first gaps:", ", ".join(d.isoformat() for d in gaps[:10]))

    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# option_iv_history coverage (Wave E / #8)",
        "",
        f"- Source: `{source}`",
        f"- Total rows loaded: {len(df)}",
        f"- XLRE missing vs SPY dates: **{len(gaps)}**",
        "",
        "## Per-ticker counts",
        "",
        "| ticker | n_rows | min_date | max_date | n_unique_dates |",
        "| --- | ---: | --- | --- | ---: |",
    ]
    for _, r in cov.iterrows():
        lines.append(
            f"| {r['ticker']} | {r['n_rows']} | {r['min_date']} | {r['max_date']} | {r['n_unique_dates']} |"
        )
    if gaps:
        lines.extend(
            [
                "",
                "## XLRE gap sample (first 25)",
                "",
                ", ".join(d.isoformat() for d in gaps[:25]),
            ]
        )
    else:
        lines.extend(["", "XLRE has no gaps vs SPY dates in this sample."])

    backfill_note = "not requested"
    if args.backfill_xlre and gaps:
        # ThetaData free tier is chunked by date range; pull min→max gap window for XLRE only.
        from modules.thetadata_iv_bootstrap import run_bootstrap

        start, end = gaps[0], gaps[-1]
        print(f"[xlre-backfill] requesting XLRE {start} → {end} ({len(gaps)} missing dates)")
        try:
            out = Path("data/option_iv_history/xlre_gap_backfill.csv")
            bdf = run_bootstrap(
                ["XLRE"],
                start=start,
                end=end,
                artifact_path=out,
                upsert=not args.no_upsert,
            )
            backfill_note = f"pulled {len(bdf)} XLRE rows → {out} upsert={not args.no_upsert}"
            print(f"[xlre-backfill] {backfill_note}")
        except Exception as exc:  # noqa: BLE001
            backfill_note = f"FAILED: {exc}"
            print(f"[xlre-backfill] {backfill_note}", file=sys.stderr)
    elif args.backfill_xlre:
        backfill_note = "no gaps — skipped"

    lines.extend(["", f"## XLRE backfill", "", backfill_note, ""])
    args.artifact.write_text("\n".join(lines))
    print(f"Wrote {args.artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
