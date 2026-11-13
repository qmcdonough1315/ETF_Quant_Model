#!/usr/bin/env python3
"""
Weekly reconciliation: model target weights ↔ Supabase ↔ Alpaca paper ↔ paper_lots.

Wave B #5. Presence-check secrets only (never print values).
Exit code 1 on material drift.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from typing import Any, Optional

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import config


def _presence(name: str) -> bool:
    return bool((os.environ.get(name) or "").strip())


def _supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        return None
    from supabase import create_client

    return create_client(url, key)


def _latest_model_weights(client) -> dict[str, float]:
    """Read latest portfolio_weights rows from factor_predictions."""
    res = (
        client.table("factor_predictions")
        .select("execution_date,data_type,ticker_or_factor,value")
        .eq("data_type", "portfolio_weights")
        .order("execution_date", desc=True)
        .limit(500)
        .execute()
    )
    rows = list(res.data or [])
    if not rows:
        return {}
    latest = rows[0]["execution_date"]
    weights = {
        str(r["ticker_or_factor"]).upper(): float(r["value"])
        for r in rows
        if r.get("execution_date") == latest and r.get("ticker_or_factor")
    }
    total = sum(weights.values())
    if total > 1.5:  # percent form
        weights = {k: v / 100.0 for k, v in weights.items()}
        total = sum(weights.values())
    if total > 0:
        weights = {k: v / total for k, v in weights.items()}
    return weights


def _paper_lot_shares(client) -> dict[str, float]:
    res = (
        client.table("paper_lots")
        .select("ticker,shares,status,strategy")
        .eq("status", "open")
        .eq("strategy", "factor")
        .execute()
    )
    out: dict[str, float] = defaultdict(float)
    for row in res.data or []:
        out[str(row["ticker"]).upper()] += float(row["shares"])
    return dict(out)


def _alpaca_equity_shares() -> dict[str, float]:
    from modules.alpaca_client import configured, get_positions

    if not configured():
        return {}
    out: dict[str, float] = {}
    for pos in get_positions():
        symbol = str(pos.get("symbol") or "").upper()
        # Skip option OCC symbols (usually length > 5 / contain digits densely).
        if not symbol or len(symbol) > 5:
            continue
        try:
            qty = float(pos.get("qty") or 0.0)
        except (TypeError, ValueError):
            continue
        if abs(qty) > 0:
            out[symbol] = qty
    return out


def reconcile(
    *,
    weight_drift: float,
    share_drift_pct: float,
) -> int:
    print("=== Paper book reconcile ===")
    print(
        "secrets:",
        f"SUPABASE_URL={'SET' if _presence('SUPABASE_URL') else 'MISSING'}",
        f"SUPABASE_KEY={'SET' if _presence('SUPABASE_KEY') else 'MISSING'}",
        f"ALPACA={'SET' if (_presence('ALPACA_API_KEY_ID') or _presence('APCA_API_KEY_ID')) else 'MISSING'}",
    )

    client = _supabase()
    if client is None:
        print("FAIL: Supabase credentials missing")
        return 1

    failures: list[str] = []
    try:
        model_w = _latest_model_weights(client)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: model weights: {exc}")
        return 1
    try:
        lot_shares = _paper_lot_shares(client)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: paper_lots unavailable ({exc}) — apply supabase_paper_ledger_continuity.sql?")
        lot_shares = {}

    try:
        alpaca_shares = _alpaca_equity_shares()
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: Alpaca positions unavailable: {exc}")
        alpaca_shares = {}

    print(f"model names={len(model_w)} paper_lot names={len(lot_shares)} alpaca equity names={len(alpaca_shares)}")

    # Weight vs lot presence: every model name should have an open lot after DCA weeks,
    # but during ramp empty lots are OK — only flag large weight with zero lots AND alpaca.
    for ticker, w in sorted(model_w.items(), key=lambda kv: -kv[1]):
        if w < weight_drift:
            continue
        if ticker not in lot_shares and ticker not in alpaca_shares:
            failures.append(
                f"weight_orphan {ticker}: model_w={w:.2%} but no paper_lot/Alpaca position"
            )

    # Share drift: paper lots vs Alpaca when both present.
    for ticker in sorted(set(lot_shares) | set(alpaca_shares)):
        lot_q = lot_shares.get(ticker, 0.0)
        alp_q = alpaca_shares.get(ticker, 0.0)
        if lot_q == 0 and alp_q == 0:
            continue
        denom = max(abs(lot_q), abs(alp_q), 1e-9)
        drift = abs(lot_q - alp_q) / denom
        if drift > share_drift_pct and abs(lot_q - alp_q) > 1e-4:
            failures.append(
                f"share_drift {ticker}: paper_lots={lot_q:.6f} alpaca={alp_q:.6f} drift={drift:.1%}"
            )

    # Alpaca-only equity (not in open factor lots) — possible manual trades / VOO.
    for ticker, qty in sorted(alpaca_shares.items()):
        if ticker == "VOO":
            continue
        if ticker not in lot_shares and ticker not in model_w:
            failures.append(f"alpaca_extra {ticker}: qty={qty:.6f} not in model/lots")

    if failures:
        print("FAIL drifts:")
        for line in failures:
            print(f"  • {line}")
        return 1

    print("OK: no material drifts vs thresholds "
          f"(weight>={weight_drift:.0%}, share>={share_drift_pct:.0%})")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--weight-drift",
        type=float,
        default=float(getattr(config, "RECONCILE_WEIGHT_DRIFT_ABS", 0.02)),
    )
    parser.add_argument(
        "--share-drift-pct",
        type=float,
        default=float(getattr(config, "RECONCILE_SHARE_DRIFT_PCT", 0.05)),
    )
    args = parser.parse_args()
    raise SystemExit(reconcile(weight_drift=args.weight_drift, share_drift_pct=args.share_drift_pct))


if __name__ == "__main__":
    main()
