"""Wave B #2 / #6: ledger continuity + TLH sell proposals (no network)."""

from __future__ import annotations

import uuid

import pandas as pd

from modules.etf_orders import build_equity_sell_payload, propose_tlh_sells
from modules.paper_ledger_store import (
    active_wash_restricted_tickers,
    ledger_from_parts,
    lot_to_row,
    row_to_lot,
)
from modules.paper_portfolio import Ledger, Lot, process_week


def _lot(ticker: str, shares: float, cps: float, opened: str, strategy: str = "factor") -> Lot:
    return Lot(
        id=str(uuid.uuid4()),
        strategy=strategy,
        ticker=ticker,
        shares=shares,
        cost_per_share=cps,
        opened_on=pd.Timestamp(opened),
        run_date=pd.Timestamp(opened),
    )


def test_lot_roundtrip_preserves_cost_basis():
    lot = _lot("QQQ", 10.0, 100.0, "2026-09-21")
    restored = row_to_lot(lot_to_row(lot))
    assert restored.ticker == "QQQ"
    assert restored.shares == 10.0
    assert restored.cost_per_share == 100.0
    assert restored.status == "open"


def test_two_week_continuity_does_not_reset_cost_basis(monkeypatch):
    """Week-2 must keep week-1 lot cost basis when no network prices force skip."""
    # Stub opens so process_week can mark and buy without yfinance.
    opens = pd.DataFrame(
        {
            "QQQ": [100.0, 110.0, 120.0],
            "VOO": [400.0, 410.0, 420.0],
            "XLK": [150.0, 140.0, 130.0],
        },
        index=pd.to_datetime(["2026-09-20", "2026-09-21", "2026-09-22"]),
    )

    def fake_fetch(tickers, start, end):
        cols = [t for t in tickers if t in opens.columns]
        return opens[cols].copy() if cols else opens.copy()

    monkeypatch.setattr("modules.paper_portfolio._fetch_daily_opens", fake_fetch)

    ledger = Ledger()
    ledger, summary1 = process_week(
        "2026-09-20",
        {"QQQ": 1.0},
        ledger,
        run_count=1,
    )
    open_lots_w1 = [l for l in ledger.lots if l.status == "open" and l.strategy == "factor"]
    assert open_lots_w1, "week 1 should open a factor lot"
    basis_w1 = {l.id: (l.shares, l.cost_per_share) for l in open_lots_w1}

    # Serialize like Supabase would, then restore for week 2.
    lot_rows = [lot_to_row(l) for l in ledger.lots]
    wash_rows = [{"ticker": t, "sold_on": d.strftime("%Y-%m-%d")} for t, d in ledger.wash.items()]
    state = {
        "cash_factor": ledger.cash_factor,
        "cash_voo": ledger.cash_voo,
        "cum_realized_gains": ledger.cum_realized_gains,
        "cum_realized_losses": ledger.cum_realized_losses,
        "run_count": 1,
    }
    ledger2, run_count = ledger_from_parts(lot_rows, wash_rows, state)
    assert run_count == 1
    for lot_id, (shares, cps) in basis_w1.items():
        match = next(l for l in ledger2.lots if l.id == lot_id)
        assert match.shares == shares
        assert match.cost_per_share == cps

    ledger2, summary2 = process_week(
        "2026-09-27",
        {"QQQ": 0.5, "XLK": 0.5},
        ledger2,
        run_count=run_count + 1,
    )
    # Prior lot still present with same cost basis id.
    for lot_id, (shares, cps) in basis_w1.items():
        match = next(l for l in ledger2.lots if l.id == lot_id)
        assert match.cost_per_share == cps
    assert summary2["run_count"] == 2
    assert summary1["run_count"] == 1


def test_active_wash_includes_identical_peers():
    wash = {"SPY": pd.Timestamp("2026-10-01")}
    banned = active_wash_restricted_tickers(wash, as_of="2026-10-10")
    assert "SPY" in banned
    assert "VOO" in banned  # substantially identical


def test_propose_tlh_sells_builds_qty_orders():
    trades = [
        {
            "side": "sell",
            "ticker": "XLK",
            "shares": 3.5,
            "price": 100.0,
            "reason": "tlh_rotate",
            "strategy": "factor",
            "lot_id": "abc",
            "date": "2026-10-01",
        },
        {"side": "buy", "ticker": "XLF", "shares": 1.0, "strategy": "factor"},
    ]
    proposal = propose_tlh_sells(trades)
    assert proposal["count"] == 1
    order = proposal["sells"][0]["order"]
    assert order["side"] == "sell"
    assert order["symbol"] == "XLK"
    assert float(order["qty"]) == 3.5
    payload = build_equity_sell_payload("XLK", 3.5)
    assert payload.to_dict()["side"] == "sell"
