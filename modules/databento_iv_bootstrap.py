"""
Databento OPRA → option_iv_history bootstrap (cost-aware).

Goal: stay under the signup free-credit budget (~$125) while building daily
ATM ~30 DTE IV rows compatible with `option_iv_history`.

Recommended path (default):
  schema=cbbo-1m, stype_in=parent, symbols=SPY.OPT / QQQ.OPT / …,
  **EOD window only** (last ~10 minutes of the regular session) as the NBBO
  snapshot used for IV. Full-session CBBO-1s/1m for entire chains is usually
  far too large for $125.

Published OPRA usage-based rates (pay-as-you-go, approx — confirm on
databento.com/pricing). Actual billed size comes from metadata.get_cost when
DATABENTO_API_KEY is set.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from modules.black_scholes_iv import implied_volatility, mid_price
from modules.options_sleeve import PHASE1_OPTIONABLE_ETFS
from modules.thetadata_iv_bootstrap import (
    AtmIvRow,
    pick_atm_iv_for_day,
    rows_to_frame,
    upsert_supabase,
    write_artifact,
)


DATASET = "OPRA.PILLAR"
SOURCE = "databento_cbbo"
ET = ZoneInfo("America/New_York")
DEFAULT_BUDGET_USD = 125.0
DEFAULT_START = date(2019, 11, 10)
DEFAULT_END = date(2025, 11, 10)
# Last 10 minutes of RTH — EOD NBBO proxy (aligns to Databento 10-minute cost boundaries).
EOD_START_ET = time(15, 50)
EOD_END_ET = time(16, 0)

# Approximate pay-as-you-go $/GB (OPRA). Used only for offline heuristics.
SCHEMA_USD_PER_GB = {
    "cmbp-1": 0.16,
    "cbbo-1m": 2.00,
    "cbbo-1s": 2.00,
    "definition": 5.00,
    "statistics": 11.00,
    "trades": 280.00,
    "ohlcv-1d": 600.00,
}

OCC_RE = re.compile(
    r"^(?P<root>\S+)\s+(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})"
    r"(?P<cp>[CP])(?P<strike>\d{8})$"
)


@dataclass(frozen=True)
class CostLine:
    label: str
    schema: str
    mode: str  # "eod_window" | "full_session" | "definition"
    tickers: tuple[str, ...]
    start: date
    end: date
    cost_usd: Optional[float]
    method: str  # "get_cost" | "heuristic"
    note: str = ""


def parent_symbol(ticker: str) -> str:
    return f"{str(ticker).upper()}.OPT"


def trading_days(start: date, end: date) -> list[date]:
    """Weekday calendar proxy (no holiday calendar — good enough for sizing)."""
    out: list[date] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            out.append(cur)
        cur += timedelta(days=1)
    return out


def eod_window_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, EOD_START_ET, tzinfo=ET)
    end = datetime.combine(day, EOD_END_ET, tzinfo=ET)
    return start, end


def parse_occ_symbol(symbol: str) -> Optional[dict[str, Any]]:
    m = OCC_RE.match(str(symbol).strip())
    if not m:
        return None
    yy, mm, dd = int(m.group("yy")), int(m.group("mm")), int(m.group("dd"))
    year = 2000 + yy
    strike = int(m.group("strike")) / 1000.0
    return {
        "root": m.group("root").upper(),
        "expiration": date(year, mm, dd),
        "right": "call" if m.group("cp") == "C" else "put",
        "strike": strike,
    }


def _client(api_key: Optional[str] = None):
    import databento as db

    key = api_key or os.environ.get("DATABENTO_API_KEY")
    if not key:
        raise RuntimeError(
            "DATABENTO_API_KEY is not set. Export it to call get_cost / download."
        )
    return db.Historical(key)


def get_cost_usd(
    *,
    schema: str,
    symbols: list[str],
    start: datetime | date | str,
    end: datetime | date | str,
    stype_in: str = "parent",
    api_key: Optional[str] = None,
) -> float:
    client = _client(api_key)
    return float(
        client.metadata.get_cost(
            dataset=DATASET,
            schema=schema,
            symbols=symbols,
            stype_in=stype_in,
            start=start,
            end=end,
        )
    )


def heuristic_eod_cbbo_cost(
    tickers: Iterable[str],
    start: date,
    end: date,
    *,
    schema: str = "cbbo-1m",
    gb_per_ticker_day: float = 0.004,
) -> float:
    """
    Rough offline size model for parent-chain EOD windows.

    Default 0.004 GB/ticker/day is a conservative placeholder for cbbo-1m over
    ~10 minutes of a liquid ETF option chain. Replace with get_cost when keyed.
    """
    days = len(trading_days(start, end))
    n = len(list(tickers))
    rate = float(SCHEMA_USD_PER_GB.get(schema, 2.0))
    return days * n * gb_per_ticker_day * rate


def heuristic_full_session_cbbo_cost(
    tickers: Iterable[str],
    start: date,
    end: date,
    *,
    schema: str = "cbbo-1m",
    # ~6.5h session / 10m ≈ 39× an EOD window if density were uniform (it isn't;
    # open is denser). Use 50× as a cautious multiplier for budgeting.
    session_multiple: float = 50.0,
    gb_per_ticker_day_eod: float = 0.004,
) -> float:
    return heuristic_eod_cbbo_cost(
        tickers, start, end, schema=schema, gb_per_ticker_day=gb_per_ticker_day_eod
    ) * session_multiple


def estimate_cost_report(
    tickers: Iterable[str] = PHASE1_OPTIONABLE_ETFS,
    *,
    start: date = DEFAULT_START,
    end: date = DEFAULT_END,
    budget_usd: float = DEFAULT_BUDGET_USD,
    sample_week_start: Optional[date] = None,
    api_key: Optional[str] = None,
) -> dict[str, Any]:
    """
    Build a cost matrix: EOD CBBO-1m vs full-session CBBO-1m vs definition.

    When DATABENTO_API_KEY is available, calibrate heuristics from a 5-trading-day
    get_cost sample on SPY.OPT (or the first ticker).
    """
    tickers_t = tuple(str(t).upper() for t in tickers)
    days = trading_days(start, end)
    n_days = len(days)
    sample_start = sample_week_start or date(2024, 8, 5)
    # Align sample to a Mon–Fri block inside the window when possible.
    if sample_start < start:
        sample_start = start
    sample_days = trading_days(sample_start, sample_start + timedelta(days=10))[:5]
    if not sample_days:
        sample_days = days[:5]

    calibrated_eod_gb_per_ticker_day: Optional[float] = None
    sample_lines: list[dict[str, Any]] = []
    method = "heuristic"

    key = api_key or os.environ.get("DATABENTO_API_KEY")
    if key and sample_days:
        try:
            # Continuous EOD windows aren't one request — cost one full RTH day of
            # cbbo-1m for SPY.OPT, then scale: EOD≈10m/390m of session.
            probe_day = sample_days[0]
            rth_start = datetime.combine(probe_day, time(9, 30), tzinfo=ET)
            rth_end = datetime.combine(probe_day, time(16, 0), tzinfo=ET)
            eod_start, eod_end = eod_window_bounds(probe_day)
            sym = [parent_symbol(tickers_t[0])]
            cost_full = get_cost_usd(
                schema="cbbo-1m", symbols=sym, start=rth_start, end=rth_end, api_key=key
            )
            cost_eod = get_cost_usd(
                schema="cbbo-1m", symbols=sym, start=eod_start, end=eod_end, api_key=key
            )
            rate = SCHEMA_USD_PER_GB["cbbo-1m"]
            gb_eod = cost_eod / rate if rate else None
            calibrated_eod_gb_per_ticker_day = gb_eod
            sample_lines.append(
                {
                    "ticker": tickers_t[0],
                    "day": probe_day.isoformat(),
                    "cbbo_1m_full_rth_usd": cost_full,
                    "cbbo_1m_eod_10m_usd": cost_eod,
                    "implied_eod_gb": gb_eod,
                }
            )
            method = "get_cost_calibrated"
        except Exception as exc:  # noqa: BLE001
            sample_lines.append({"error": str(exc)})

    gb_day = calibrated_eod_gb_per_ticker_day or 0.004
    eod_cost = heuristic_eod_cbbo_cost(
        tickers_t, start, end, gb_per_ticker_day=gb_day
    )
    full_cost = heuristic_full_session_cbbo_cost(
        tickers_t, start, end, gb_per_ticker_day_eod=gb_day
    )
    # definition for parent chains — typically small vs CBBO
    def_cost = n_days * len(tickers_t) * 0.00005 * SCHEMA_USD_PER_GB["definition"]

    lines = [
        CostLine(
            label="EOD NBBO (cbbo-1m, 15:50–16:00 ET)",
            schema="cbbo-1m",
            mode="eod_window",
            tickers=tickers_t,
            start=start,
            end=end,
            cost_usd=eod_cost,
            method=method,
            note="Recommended for option_iv_history ATM IV bootstrap.",
        ),
        CostLine(
            label="Full RTH NBBO (cbbo-1m, 09:30–16:00 ET)",
            schema="cbbo-1m",
            mode="full_session",
            tickers=tickers_t,
            start=start,
            end=end,
            cost_usd=full_cost,
            method=method,
            note="All intraday minute BBO snapshots — usually exceeds $125 for 14 ETF chains × 6y.",
        ),
        CostLine(
            label="Instrument definitions",
            schema="definition",
            mode="definition",
            tickers=tickers_t,
            start=start,
            end=end,
            cost_usd=def_cost,
            method="heuristic",
            note="Needed to map instrument ids; cheap relative to CBBO.",
        ),
    ]

    fits_budget = {
        line.label: (line.cost_usd is not None and line.cost_usd <= budget_usd)
        for line in lines
    }

    # Budget packs: concrete scopes that (heuristically) fit free credits.
    packs: list[dict[str, Any]] = []
    core3 = ("SPY", "QQQ", "IWM")
    core_cost = heuristic_eod_cbbo_cost(core3, start, end, gb_per_ticker_day=gb_day)
    packs.append(
        {
            "name": "core3_full_history",
            "tickers": list(core3),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "cost_usd": core_cost,
            "fits_budget": core_cost <= budget_usd,
            "note": "Liquid index ETFs only — best first pull under free credits.",
        }
    )
    # Greedy prefix of Phase 1 list for the full window.
    prefix_fit = []
    running = 0.0
    per_ticker = eod_cost / max(len(tickers_t), 1)
    for t in tickers_t:
        if running + per_ticker <= budget_usd:
            prefix_fit.append(t)
            running += per_ticker
        else:
            break
    if prefix_fit:
        packs.append(
            {
                "name": "phase1_prefix_full_history",
                "tickers": prefix_fit,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "cost_usd": running,
                "fits_budget": True,
                "note": f"First {len(prefix_fit)} of Phase 1 order for the full window.",
            }
        )
    # Shorten calendar for all requested tickers until under budget.
    if eod_cost > budget_usd and n_days > 0:
        max_days = max(1, int(budget_usd / (eod_cost / n_days)))
        # Walk back from end by weekdays.
        subset_days = days[-max_days:]
        pack_start = subset_days[0]
        pack_cost = heuristic_eod_cbbo_cost(
            tickers_t, pack_start, end, gb_per_ticker_day=gb_day
        )
        packs.append(
            {
                "name": "all_tickers_recent_window",
                "tickers": list(tickers_t),
                "start": pack_start.isoformat(),
                "end": end.isoformat(),
                "cost_usd": pack_cost,
                "fits_budget": pack_cost <= budget_usd,
                "note": (
                    f"~{max_days} weekdays ending {end.isoformat()} "
                    "so full Phase 1 chain set fits the budget."
                ),
            }
        )

    if fits_budget[lines[0].label]:
        recommendation = (
            "Pull EOD cbbo-1m windows only (15:50–16:00 ET); skip full-session CBBO."
        )
    else:
        recommendation = (
            "Full Phase 1 × full history EOD estimate exceeds budget — "
            "use a budget pack (core3 or recent window) and calibrate with get_cost."
        )

    return {
        "dataset": DATASET,
        "budget_usd": budget_usd,
        "window": {"start": start.isoformat(), "end": end.isoformat(), "n_weekdays": n_days},
        "tickers": list(tickers_t),
        "calibration": {
            "method": method,
            "eod_gb_per_ticker_day": gb_day,
            "sample": sample_lines,
        },
        "lines": [
            {
                "label": ln.label,
                "schema": ln.schema,
                "mode": ln.mode,
                "cost_usd": ln.cost_usd,
                "fits_budget": fits_budget[ln.label],
                "method": ln.method,
                "note": ln.note,
            }
            for ln in lines
        ],
        "budget_packs": packs,
        "recommendation": recommendation,
        "schema_rates_usd_per_gb": SCHEMA_USD_PER_GB,
    }


def render_cost_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Databento → option_iv_history cost estimate",
        "",
        f"- Dataset: `{report['dataset']}`",
        f"- Window: `{report['window']['start']}` → `{report['window']['end']}` "
        f"({report['window']['n_weekdays']} weekdays)",
        f"- Tickers ({len(report['tickers'])}): {', '.join(report['tickers'])}",
        f"- Budget: ${report['budget_usd']:.2f} free credits",
        f"- Calibration: `{report['calibration']['method']}` "
        f"(eod_gb/ticker/day≈{report['calibration']['eod_gb_per_ticker_day']:.6f})",
        "",
        "## Scenarios",
        "",
        "| Scenario | Schema | Est. cost | Fits $125? | Note |",
        "|---|---|---:|:---:|---|",
    ]
    for row in report["lines"]:
        cost = row["cost_usd"]
        cost_s = "—" if cost is None else f"${cost:,.2f}"
        fit = "yes" if row["fits_budget"] else "no"
        lines.append(
            f"| {row['label']} | `{row['schema']}` | {cost_s} | {fit} | {row['note']} |"
        )
    packs = report.get("budget_packs") or []
    if packs:
        lines.extend(
            [
                "",
                "## Budget packs (heuristic, under free credits)",
                "",
                "| Pack | Tickers | Window | Est. cost | Fits? | Note |",
                "|---|---|---|---:|:---:|---|",
            ]
        )
        for p in packs:
            cost = p.get("cost_usd")
            cost_s = "—" if cost is None else f"${cost:,.2f}"
            fit = "yes" if p.get("fits_budget") else "no"
            tickers = ", ".join(p.get("tickers") or [])
            lines.append(
                f"| `{p.get('name')}` | {tickers} | `{p.get('start')}` → `{p.get('end')}` "
                f"| {cost_s} | {fit} | {p.get('note', '')} |"
            )

    lines.extend(
        [
            "",
            f"**Recommendation:** {report['recommendation']}",
            "",
            "## Notes",
            "",
            "- There is no `cbbo-1d` on OPRA; EOD NBBO is approximated with `cbbo-1m` in the last 10 minutes of RTH.",
            "- `ohlcv-1d` is ~$600/GB — a poor fit for free credits if you need many chain symbols.",
            "- Parent symbology (`SPY.OPT`) pulls the **full chain**; we reduce to ATM ~30 DTE locally for `option_iv_history`.",
            "- Always run `metadata.get_cost` before a live download; heuristics can be off on quiet/busy names.",
            "- Live pull: `DATABENTO_API_KEY` + `scripts/run_databento_iv_bootstrap.py` (budget gate; day-by-day get_cost).",
            "",
        ]
    )
    return "\n".join(lines)


def cbbo_df_to_option_day(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse a CBBO frame to one bid/ask row per OCC symbol (last snapshot)."""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if "symbol" not in out.columns:
        return pd.DataFrame()
    # Prefer last snapshot per symbol in the EOD window.
    if isinstance(out.index, pd.DatetimeIndex):
        out = out.sort_index()
    out = out.groupby("symbol", as_index=False).tail(1)
    rows = []
    for r in out.itertuples(index=False):
        parsed = parse_occ_symbol(getattr(r, "symbol"))
        if not parsed:
            continue
        bid = getattr(r, "bid_px_00", None)
        ask = getattr(r, "ask_px_00", None)
        rows.append(
            {
                "expiration": parsed["expiration"],
                "right": parsed["right"],
                "strike": parsed["strike"],
                "bid": bid,
                "ask": ask,
                "close": mid_price(
                    float(bid) if bid is not None and pd.notna(bid) else None,
                    float(ask) if ask is not None and pd.notna(ask) else None,
                    None,
                ),
            }
        )
    return pd.DataFrame(rows)


def spot_from_yfinance(ticker: str, start: date, end: date) -> dict[date, float]:
    import yfinance as yf

    raw = yf.download(
        ticker,
        start=start.isoformat(),
        end=(end + timedelta(days=3)).isoformat(),
        interval="1d",
        auto_adjust=True,
        progress=False,
    )
    if raw is None or len(raw) == 0:
        return {}
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"][ticker] if ticker in raw["Close"].columns else raw["Close"].iloc[:, 0]
    else:
        close = raw["Close"]
    out: dict[date, float] = {}
    for ts, px in close.dropna().items():
        out[pd.Timestamp(ts).date()] = float(px)
    return out


def download_eod_cbbo_day(
    ticker: str,
    day: date,
    *,
    api_key: Optional[str] = None,
) -> pd.DataFrame:
    client = _client(api_key)
    start, end = eod_window_bounds(day)
    data = client.timeseries.get_range(
        dataset=DATASET,
        schema="cbbo-1m",
        stype_in="parent",
        symbols=[parent_symbol(ticker)],
        start=start,
        end=end,
    )
    return data.to_df()


def bootstrap_symbol_eod(
    ticker: str,
    start: date,
    end: date,
    *,
    api_key: Optional[str] = None,
    budget_remaining: Optional[list[float]] = None,
    pause_every: int = 20,
) -> list[AtmIvRow]:
    """
    Download EOD CBBO windows day-by-day and reduce to ATM IV rows.

    budget_remaining: optional single-element list mutated as costs accrue
    (stop when exhausted).
    """
    ticker = ticker.upper()
    spots = spot_from_yfinance(ticker, start, end)
    rows: list[AtmIvRow] = []
    days = trading_days(start, end)
    for i, day in enumerate(days, 1):
        if budget_remaining is not None and budget_remaining[0] <= 0:
            print(f"[databento-iv] budget exhausted before {ticker} {day}")
            break
        if day not in spots:
            continue
        try:
            if budget_remaining is not None:
                s, e = eod_window_bounds(day)
                day_cost = get_cost_usd(
                    schema="cbbo-1m",
                    symbols=[parent_symbol(ticker)],
                    start=s,
                    end=e,
                    api_key=api_key,
                )
                if day_cost > budget_remaining[0]:
                    print(
                        f"[databento-iv] skip {ticker} {day}: "
                        f"day_cost=${day_cost:.4f} > remaining=${budget_remaining[0]:.4f}"
                    )
                    break
                budget_remaining[0] -= day_cost
            cbbo = download_eod_cbbo_day(ticker, day, api_key=api_key)
            opt_day = cbbo_df_to_option_day(cbbo)
            picked = pick_atm_iv_for_day(opt_day, spots[day], day)
            if picked is None:
                continue
            rows.append(
                AtmIvRow(
                    as_of_date=picked.as_of_date,
                    ticker=ticker,
                    atm_iv=picked.atm_iv,
                    dte=picked.dte,
                    call_iv=picked.call_iv,
                    put_iv=picked.put_iv,
                    spot=picked.spot,
                    call_strike=picked.call_strike,
                    put_strike=picked.put_strike,
                    call_mid=picked.call_mid,
                    put_mid=picked.put_mid,
                    source=SOURCE,
                )
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[databento-iv] {ticker} {day} failed: {exc}")
        if pause_every and i % pause_every == 0:
            print(f"[databento-iv] {ticker}: {i}/{len(days)} days, {len(rows)} IV rows")
    return rows


def run_cost_estimate(
    *,
    tickers: Iterable[str] = PHASE1_OPTIONABLE_ETFS,
    start: date = DEFAULT_START,
    end: date = DEFAULT_END,
    budget_usd: float = DEFAULT_BUDGET_USD,
    artifact: Optional[Path] = None,
) -> dict[str, Any]:
    report = estimate_cost_report(
        tickers, start=start, end=end, budget_usd=budget_usd
    )
    md = render_cost_markdown(report)
    out = artifact or Path("/opt/cursor/artifacts/databento_iv_cost_estimate.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    json_path = out.with_suffix(".json")
    import json

    json_path.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(md)
    print(f"\n[databento-iv] wrote {out}")
    print(f"[databento-iv] wrote {json_path}")
    return report


def run_bootstrap(
    tickers: Iterable[str] = PHASE1_OPTIONABLE_ETFS,
    *,
    start: date = DEFAULT_START,
    end: date = DEFAULT_END,
    budget_usd: float = DEFAULT_BUDGET_USD,
    artifact_path: Optional[Path] = None,
    upsert: bool = False,
    force: bool = False,
) -> pd.DataFrame:
    report = estimate_cost_report(tickers, start=start, end=end, budget_usd=budget_usd)
    eod_line = next(x for x in report["lines"] if x["mode"] == "eod_window")
    est = float(eod_line["cost_usd"] or 0.0)
    print(render_cost_markdown(report))
    if est > budget_usd and not force:
        raise SystemExit(
            f"EOD estimate ${est:.2f} exceeds budget ${budget_usd:.2f}. "
            "Narrow --tickers/--start/--end or pass --force after reviewing get_cost."
        )

    budget = [float(budget_usd)]
    all_rows: list[AtmIvRow] = []
    out = artifact_path or Path("data/option_iv_history/atm_iv_databento.csv")
    for ticker in tickers:
        print(f"[databento-iv] {ticker} {start} → {end} (budget left ${budget[0]:.2f})")
        rows = bootstrap_symbol_eod(
            ticker, start, end, budget_remaining=budget
        )
        all_rows.extend(rows)
        write_artifact(rows_to_frame(all_rows), out)
        print(f"[databento-iv] {ticker}: {len(rows)} days")
        if budget[0] <= 0:
            break

    df = rows_to_frame(all_rows)
    # Ensure source column is databento.
    if not df.empty:
        df["source"] = SOURCE
    write_artifact(df, out)
    print(f"[databento-iv] wrote {len(df)} rows → {out} (budget left ${budget[0]:.2f})")
    if upsert and not df.empty:
        try:
            n = upsert_supabase(df)
            print(f"[databento-iv] upserted {n} rows to Supabase option_iv_history")
        except Exception as exc:  # noqa: BLE001
            print(f"[databento-iv] Supabase upsert skipped/failed: {exc}")
    return df
