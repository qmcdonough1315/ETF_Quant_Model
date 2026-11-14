"""Unit tests for Databento IV bootstrap helpers (no network)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from modules.databento_iv_bootstrap import (
    cbbo_df_to_option_day,
    estimate_cost_report,
    heuristic_eod_cbbo_cost,
    heuristic_full_session_cbbo_cost,
    parse_occ_symbol,
    render_cost_markdown,
)


def test_parse_occ_symbol():
    p = parse_occ_symbol("SPY   241115P00525000")
    assert p is not None
    assert p["root"] == "SPY"
    assert p["expiration"] == date(2024, 11, 15)
    assert p["right"] == "put"
    assert abs(p["strike"] - 525.0) < 1e-9


def test_cbbo_df_to_option_day_last_snapshot():
    df = pd.DataFrame(
        {
            "symbol": [
                "SPY   241115C00525000",
                "SPY   241115C00525000",
                "SPY   241115P00525000",
            ],
            "bid_px_00": [1.0, 1.2, 2.0],
            "ask_px_00": [1.1, 1.3, 2.2],
        }
    )
    out = cbbo_df_to_option_day(df)
    assert len(out) == 2
    call = out[out["right"] == "call"].iloc[0]
    assert abs(float(call["bid"]) - 1.2) < 1e-12  # last snapshot kept


def test_cost_heuristics_eod_cheaper_than_full_session():
    tickers = ["SPY", "QQQ"]
    start, end = date(2024, 1, 1), date(2024, 1, 31)
    eod = heuristic_eod_cbbo_cost(tickers, start, end)
    full = heuristic_full_session_cbbo_cost(tickers, start, end)
    assert eod > 0
    assert full > eod * 10


def test_estimate_report_markdown_without_api_key():
    report = estimate_cost_report(
        ["SPY", "QQQ"],
        start=date(2019, 11, 10),
        end=date(2025, 11, 10),
        budget_usd=125.0,
    )
    md = render_cost_markdown(report)
    assert "cbbo-1m" in md
    assert "$125" in md or "125" in md
    eod = next(x for x in report["lines"] if x["mode"] == "eod_window")
    full = next(x for x in report["lines"] if x["mode"] == "full_session")
    assert eod["cost_usd"] < full["cost_usd"]
    assert report["budget_packs"]
    assert any(p["name"] == "core3_full_history" for p in report["budget_packs"])
    assert "Budget packs" in md


def test_phase1_full_history_needs_budget_pack():
    from modules.options_sleeve import PHASE1_OPTIONABLE_ETFS

    report = estimate_cost_report(
        PHASE1_OPTIONABLE_ETFS,
        start=date(2019, 11, 10),
        end=date(2025, 11, 10),
        budget_usd=125.0,
    )
    eod = next(x for x in report["lines"] if x["mode"] == "eod_window")
    assert eod["fits_budget"] is False
    packs = {p["name"]: p for p in report["budget_packs"]}
    assert packs["core3_full_history"]["fits_budget"] is True
    assert packs["phase1_prefix_full_history"]["fits_budget"] is True
    assert len(packs["phase1_prefix_full_history"]["tickers"]) < len(PHASE1_OPTIONABLE_ETFS)
    assert "all_tickers_recent_window" in packs
    assert packs["all_tickers_recent_window"]["fits_budget"] is True
