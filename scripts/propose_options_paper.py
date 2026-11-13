#!/usr/bin/env python3
"""
Human-in-the-loop helper: print the Phase 1 options *signal board* (never places).

Wave E / #9 — gated by kill-switch + IVR fail-closed. Desk confirms chain packaging
and paper place in the web Options Trade Desk (confirm=true). See DESK_RUNBOOK.md.

Usage:
  PYTHONPATH=. python3 scripts/propose_options_paper.py
  PYTHONPATH=. python3 scripts/propose_options_paper.py --tickers SPY,QQQ --out /tmp/board.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Optional

from modules.options_sleeve import PHASE1_OPTIONABLE_ETFS, build_signal
from modules.risk_policy import kill_switch_from_env_snapshot


def _supabase():
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY required")
    return create_client(url, key)


def _latest_iv_ranks(client, tickers: list[str]) -> dict[str, Optional[float]]:
    """Best-effort: read option_iv_rank_latest view; missing → None (fail closed)."""
    out: dict[str, Optional[float]] = {t: None for t in tickers}
    try:
        rows = client.table("option_iv_rank_latest").select("ticker,iv_rank").execute().data
        for r in rows or []:
            t = str(r.get("ticker", "")).upper()
            if t in out and r.get("iv_rank") is not None:
                out[t] = float(r["iv_rank"])
    except Exception as exc:  # noqa: BLE001
        print(f"[propose] IVR view unavailable ({exc}); all IVR treated missing.", file=sys.stderr)
    return out


def _latest_composites(client, tickers: list[str]) -> dict[str, float]:
    """Read options_composite rows (ticker_or_factor / execution_date schema)."""
    out: dict[str, float] = {}
    try:
        rows = (
            client.table("factor_predictions")
            .select("ticker_or_factor,value,data_type,execution_date")
            .eq("data_type", "options_composite")
            .order("execution_date", desc=True)
            .limit(500)
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[propose] composites unavailable: {exc}", file=sys.stderr)
        return out
    if not rows:
        return out
    latest = rows[0].get("execution_date")
    for r in rows:
        if r.get("execution_date") != latest:
            continue
        t = str(r.get("ticker_or_factor", "")).upper()
        if t in tickers and r.get("value") is not None:
            out[t] = float(r["value"])
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tickers",
        default=",".join(PHASE1_OPTIONABLE_ETFS),
        help="Comma-separated Phase 1 underlyings",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Alias kept for docs; this CLI never places orders",
    )
    parser.add_argument("--out", default=None, help="Optional JSON path for the board")
    args = parser.parse_args()
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    ks = kill_switch_from_env_snapshot()
    print(
        f"[propose] kill_switch active={ks.active} level={ks.level} "
        f"halt_new_short_premium={ks.halt_new_short_premium}"
    )
    if ks.halt_new_short_premium:
        print("[propose] Kill-switch ON — all names will skip (fail closed).")

    try:
        client = _supabase()
    except Exception as exc:  # noqa: BLE001
        print(f"[propose] {exc}", file=sys.stderr)
        return 1

    ivrs = _latest_iv_ranks(client, tickers)
    comps = _latest_composites(client, tickers)
    results: list[dict[str, Any]] = []

    for t in tickers:
        ivr = ivrs.get(t)
        has_comp = t in comps
        comp = comps.get(t, 0.0)
        signal = build_signal(
            t, comp, ivr, kill_switch_active=ks.halt_new_short_premium
        )
        row: dict[str, Any] = {
            "ticker": t,
            "composite": comp if has_comp else None,
            "iv_rank": ivr,
            "structure": signal.structure,
            "regime": signal.regime,
            "rationale": signal.rationale,
            "skip_reason": signal.rationale if signal.structure.startswith("skip_") else None,
        }
        if not has_comp and not signal.structure.startswith("skip_"):
            # Still allow structure from z=0 neutral if IVR present; note missing composite.
            row["rationale"] = signal.rationale + " (composite missing → treated as 0)."
        tag = "SKIP" if signal.structure.startswith("skip_") else "READY"
        print(
            f"  {t:5s} {tag:5s} {signal.structure:16s} "
            f"ivr={ivr if ivr is not None else 'None'} z={comp if has_comp else 'None'}"
        )
        results.append(row)

    payload = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "kill_switch": asdict(ks),
        "note": (
            "Signal board only — no orders placed. Package/place on Options Trade Desk "
            "with confirm=true paper guards (DESK_RUNBOOK.md)."
        ),
        "results": results,
    }
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        print(f"[propose] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
