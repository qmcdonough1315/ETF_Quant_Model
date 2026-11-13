"""
Load / save paper Ledger state to Supabase (Wave B #2).

Empty DB → empty Ledger (no demo lots). Service role key required for writes.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any, Optional

import pandas as pd

from modules.paper_portfolio import (
    SUBSTANTIALLY_IDENTICAL,
    Lot,
    Ledger,
    WASH_SALE_DAYS,
    _identical_set,
)


LEDGER_STATE_ID = "default"


def _client():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        return None
    from supabase import create_client

    return create_client(url, key)


def lot_to_row(lot: Lot) -> dict[str, Any]:
    return {
        "id": lot.id,
        "strategy": lot.strategy,
        "ticker": lot.ticker.upper(),
        "shares": float(lot.shares),
        "cost_per_share": float(lot.cost_per_share),
        "cost_basis": float(lot.shares * lot.cost_per_share),
        "opened_on": pd.Timestamp(lot.opened_on).date().isoformat(),
        "run_date": pd.Timestamp(lot.run_date).date().isoformat(),
        "status": lot.status,
        "closed_on": pd.Timestamp(lot.closed_on).date().isoformat() if lot.closed_on is not None else None,
        "close_price": float(lot.close_price) if lot.close_price is not None else None,
        "realized_pnl": float(lot.realized_pnl) if lot.realized_pnl is not None else None,
        "close_reason": lot.close_reason,
        "replacement_for": lot.replacement_for,
    }


def row_to_lot(row: dict[str, Any]) -> Lot:
    return Lot(
        id=str(row["id"]),
        strategy=str(row["strategy"]),
        ticker=str(row["ticker"]).upper(),
        shares=float(row["shares"]),
        cost_per_share=float(row["cost_per_share"]),
        opened_on=pd.Timestamp(row["opened_on"]).normalize(),
        run_date=pd.Timestamp(row["run_date"]).normalize(),
        status=str(row.get("status") or "open"),
        closed_on=pd.Timestamp(row["closed_on"]).normalize() if row.get("closed_on") else None,
        close_price=float(row["close_price"]) if row.get("close_price") is not None else None,
        realized_pnl=float(row["realized_pnl"]) if row.get("realized_pnl") is not None else None,
        close_reason=row.get("close_reason"),
        replacement_for=row.get("replacement_for"),
    )


def active_wash_restricted_tickers(
    wash: dict[str, pd.Timestamp],
    as_of: Optional[str | date | pd.Timestamp] = None,
    *,
    include_identicals: bool = True,
) -> list[str]:
    """Tickers blocked by wash-sale window (optionally expanding substantially identical peers)."""
    as_ts = pd.Timestamp(as_of or pd.Timestamp.utcnow().normalize()).normalize()
    banned: set[str] = set()
    for ticker, sold_on in wash.items():
        if sold_on is None:
            continue
        age = (as_ts - pd.Timestamp(sold_on).normalize()).days
        if age < WASH_SALE_DAYS:
            if include_identicals:
                banned |= _identical_set(str(ticker))
            else:
                banned.add(str(ticker).upper())
    return sorted(banned)


def ledger_from_parts(
    lot_rows: list[dict[str, Any]],
    wash_rows: list[dict[str, Any]],
    state: Optional[dict[str, Any]] = None,
) -> tuple[Ledger, int]:
    """Pure reconstruct for tests (no network)."""
    lots = [row_to_lot(r) for r in lot_rows]
    wash = {
        str(r["ticker"]).upper(): pd.Timestamp(r["sold_on"]).normalize()
        for r in wash_rows
        if r.get("ticker") and r.get("sold_on")
    }
    state = state or {}
    ledger = Ledger(
        lots=lots,
        wash=wash,
        cum_realized_gains=float(state.get("cum_realized_gains") or 0.0),
        cum_realized_losses=float(state.get("cum_realized_losses") or 0.0),
        cash_factor=float(state.get("cash_factor") or 0.0),
        cash_voo=float(state.get("cash_voo") or 0.0),
    )
    run_count = int(state.get("run_count") or 0)
    return ledger, run_count


def load_ledger_from_supabase() -> tuple[Ledger, int]:
    """
    Load prior ledger. Missing tables / empty DB → empty Ledger and run_count=0.
    Never invents demo lots.
    """
    client = _client()
    if client is None:
        print("[paper-ledger] SUPABASE_URL/KEY missing — starting empty ledger")
        return Ledger(), 0

    lot_rows: list[dict[str, Any]] = []
    wash_rows: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    try:
        lots_res = client.table("paper_lots").select("*").execute()
        lot_rows = list(lots_res.data or [])
    except Exception as exc:  # noqa: BLE001
        print(f"[paper-ledger] load paper_lots failed (apply supabase_paper_ledger_continuity.sql?): {exc}")
        return Ledger(), 0

    try:
        wash_res = client.table("paper_wash_sales").select("*").execute()
        wash_rows = list(wash_res.data or [])
    except Exception as exc:  # noqa: BLE001
        print(f"[paper-ledger] load paper_wash_sales failed: {exc}")

    try:
        st_res = (
            client.table("paper_ledger_state")
            .select("*")
            .eq("id", LEDGER_STATE_ID)
            .limit(1)
            .execute()
        )
        if st_res.data:
            state = dict(st_res.data[0])
    except Exception as exc:  # noqa: BLE001
        print(f"[paper-ledger] load paper_ledger_state failed: {exc}")

    ledger, run_count = ledger_from_parts(lot_rows, wash_rows, state)
    print(
        f"[paper-ledger] loaded lots={len(ledger.lots)} "
        f"open={sum(1 for l in ledger.lots if l.status == 'open')} "
        f"wash={len(ledger.wash)} run_count={run_count}"
    )
    return ledger, run_count


def save_ledger_to_supabase(ledger: Ledger, *, run_count: int) -> None:
    client = _client()
    if client is None:
        print("[paper-ledger] SUPABASE_URL/KEY missing — skip ledger save")
        return

    lot_payload = [lot_to_row(lot) for lot in ledger.lots]
    try:
        # Upsert all known lots (open + closed) so TLH closes persist.
        for i in range(0, len(lot_payload), 200):
            chunk = lot_payload[i : i + 200]
            if chunk:
                client.table("paper_lots").upsert(chunk, on_conflict="id").execute()
    except Exception as exc:  # noqa: BLE001
        print(f"[paper-ledger] save paper_lots failed: {exc}")
        return

    wash_payload = [
        {"ticker": t.upper(), "sold_on": pd.Timestamp(d).date().isoformat()}
        for t, d in ledger.wash.items()
    ]
    try:
        # Replace wash set: delete rows not in payload, upsert active.
        existing = client.table("paper_wash_sales").select("ticker").execute()
        existing_tickers = {str(r["ticker"]).upper() for r in (existing.data or [])}
        keep = {r["ticker"] for r in wash_payload}
        drop = sorted(existing_tickers - keep)
        for t in drop:
            client.table("paper_wash_sales").delete().eq("ticker", t).execute()
        if wash_payload:
            client.table("paper_wash_sales").upsert(wash_payload, on_conflict="ticker").execute()
    except Exception as exc:  # noqa: BLE001
        print(f"[paper-ledger] save paper_wash_sales failed: {exc}")

    state_row = {
        "id": LEDGER_STATE_ID,
        "cash_factor": float(ledger.cash_factor),
        "cash_voo": float(ledger.cash_voo),
        "cum_realized_gains": float(ledger.cum_realized_gains),
        "cum_realized_losses": float(ledger.cum_realized_losses),
        "run_count": int(run_count),
    }
    try:
        client.table("paper_ledger_state").upsert(state_row, on_conflict="id").execute()
    except Exception as exc:  # noqa: BLE001
        print(f"[paper-ledger] save paper_ledger_state failed: {exc}")
        return

    print(
        f"[paper-ledger] saved lots={len(lot_payload)} wash={len(wash_payload)} run_count={run_count}"
    )


# Re-export for type checkers / callers that need the peer map.
__all__ = [
    "SUBSTANTIALLY_IDENTICAL",
    "active_wash_restricted_tickers",
    "ledger_from_parts",
    "load_ledger_from_supabase",
    "lot_to_row",
    "row_to_lot",
    "save_ledger_to_supabase",
]
