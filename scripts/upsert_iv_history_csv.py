#!/usr/bin/env python3
"""Upsert a local ATM IV CSV into Supabase option_iv_history."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from modules.thetadata_iv_bootstrap import upsert_supabase


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "csv_path",
        type=Path,
        nargs="?",
        default=Path("data/option_iv_history/atm_iv_bootstrap.csv"),
    )
    args = parser.parse_args()
    df = pd.read_csv(args.csv_path)
    n = upsert_supabase(df)
    print(f"upserted {n} rows from {args.csv_path}")


if __name__ == "__main__":
    main()
