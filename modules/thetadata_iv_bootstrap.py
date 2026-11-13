"""
Bootstrap daily ~30 DTE ATM IV from ThetaData free-tier EOD option reports.

IV definition (v1): average of call and put Black–Scholes IVs from mid prices
for strikes nearest spot, targeting ~30 calendar DTE.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from modules.black_scholes_iv import implied_volatility, mid_price
from modules.options_sleeve import PHASE1_OPTIONABLE_ETFS


TARGET_DTE = 30
MAX_DTE = 45
MIN_DTE = 20
STRIKE_RANGE = 3  # strikes above/below spot + ATM
REQUEST_PAUSE_SEC = 3.2  # stay under free-tier ~20 req/min
DEFAULT_RATE = 0.0


@dataclass(frozen=True)
class AtmIvRow:
    as_of_date: date
    ticker: str
    atm_iv: float
    dte: int
    call_iv: Optional[float]
    put_iv: Optional[float]
    spot: float
    call_strike: Optional[float]
    put_strike: Optional[float]
    call_mid: Optional[float]
    put_mid: Optional[float]
    source: str = "thetadata_eod"


def _as_date(value) -> Optional[date]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date()


def _right_norm(value) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip().upper()
    if s in {"C", "CALL"}:
        return "call"
    if s in {"P", "PUT"}:
        return "put"
    return None


def pick_atm_iv_for_day(
    opt_day: pd.DataFrame,
    spot: float,
    as_of: date,
    *,
    rate: float = DEFAULT_RATE,
    target_dte: int = TARGET_DTE,
) -> Optional[AtmIvRow]:
    """Select ~30 DTE ATM call/put and average their IVs."""
    if opt_day is None or opt_day.empty or not (spot > 0):
        return None

    df = opt_day.copy()
    df["expiration_d"] = df["expiration"].map(_as_date)
    df["right_n"] = df["right"].map(_right_norm)
    df["strike_f"] = pd.to_numeric(df["strike"], errors="coerce")
    df = df.dropna(subset=["expiration_d", "right_n", "strike_f"])
    if df.empty:
        return None

    df["dte"] = df["expiration_d"].map(lambda d: (d - as_of).days)
    df = df[(df["dte"] >= MIN_DTE) & (df["dte"] <= MAX_DTE)]
    if df.empty:
        return None

    # Prefer expiry closest to target DTE.
    expiries = (
        df.groupby("expiration_d", as_index=False)["dte"]
        .first()
        .assign(abs_diff=lambda x: (x["dte"] - target_dte).abs())
        .sort_values(["abs_diff", "dte"])
    )
    best_exp = expiries.iloc[0]["expiration_d"]
    best_dte = int(expiries.iloc[0]["dte"])
    dated = df[df["expiration_d"] == best_exp].copy()
    dated["abs_spot"] = (dated["strike_f"] - spot).abs()

    call_iv = put_iv = None
    call_strike = put_strike = None
    call_mid = put_mid = None

    for side in ("call", "put"):
        side_df = dated[dated["right_n"] == side].sort_values(["abs_spot", "strike_f"])
        if side_df.empty:
            continue
        row = side_df.iloc[0]
        bid = float(row["bid"]) if pd.notna(row.get("bid")) else None
        ask = float(row["ask"]) if pd.notna(row.get("ask")) else None
        close = float(row["close"]) if pd.notna(row.get("close")) else None
        px = mid_price(bid, ask, close)
        if px is None:
            continue
        iv = implied_volatility(
            price=px,
            spot=spot,
            strike=float(row["strike_f"]),
            time_years=max(best_dte, 1) / 365.0,
            right=side,
            rate=rate,
        )
        if iv is None:
            continue
        if side == "call":
            call_iv, call_strike, call_mid = iv, float(row["strike_f"]), px
        else:
            put_iv, put_strike, put_mid = iv, float(row["strike_f"]), px

    ivs = [v for v in (call_iv, put_iv) if v is not None]
    if not ivs:
        return None
    return AtmIvRow(
        as_of_date=as_of,
        ticker="",  # filled by caller
        atm_iv=float(sum(ivs) / len(ivs)),
        dte=best_dte,
        call_iv=call_iv,
        put_iv=put_iv,
        spot=float(spot),
        call_strike=call_strike,
        put_strike=put_strike,
        call_mid=call_mid,
        put_mid=put_mid,
    )


class ThetaIvBootstrapper:
    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        pause_sec: float = REQUEST_PAUSE_SEC,
        rate: float = DEFAULT_RATE,
    ):
        try:
            from thetadata import ThetaClient
        except ImportError as exc:
            raise RuntimeError(
                "thetadata import failed. Install deps with: "
                "pip install thetadata python-dotenv pandas numpy"
            ) from exc

        kwargs = {"dataframe_type": "pandas"}
        if api_key:
            kwargs["api_key"] = api_key
        self.client = ThetaClient(**kwargs)
        self.pause_sec = pause_sec
        self.rate = rate
        self._last_request = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.pause_sec:
            time.sleep(self.pause_sec - elapsed)
        self._last_request = time.monotonic()

    def stock_eod(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        self._throttle()
        df = self.client.stock_history_eod(symbol=symbol, start_date=start, end_date=end)
        if df is None or len(df) == 0:
            return pd.DataFrame()
        out = df.copy()
        # Column names vary slightly; normalize.
        cols = {c.lower(): c for c in out.columns}
        date_col = cols.get("created") or cols.get("date") or cols.get("timestamp")
        close_col = cols.get("close")
        if date_col is None or close_col is None:
            return pd.DataFrame()
        out["as_of_date"] = out[date_col].map(_as_date)
        out["close"] = pd.to_numeric(out[close_col], errors="coerce")
        return out.dropna(subset=["as_of_date", "close"])[["as_of_date", "close"]]

    def option_eod_chunk(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        self._throttle()
        df = self.client.option_history_eod(
            symbol=symbol,
            expiration="*",
            start_date=start,
            end_date=end,
            max_dte=MAX_DTE,
            strike_range=STRIKE_RANGE,
        )
        if df is None or len(df) == 0:
            return pd.DataFrame()
        return df

    def bootstrap_symbol(
        self,
        symbol: str,
        start: date,
        end: date,
        *,
        chunk_days: int = 14,
    ) -> list[AtmIvRow]:
        symbol = symbol.upper()
        spots = self.stock_eod(symbol, start, end)
        if spots.empty:
            return []
        spot_map = {r.as_of_date: float(r.close) for r in spots.itertuples(index=False)}

        rows: list[AtmIvRow] = []
        cursor = start
        while cursor <= end:
            chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
            opt = self.option_eod_chunk(symbol, cursor, chunk_end)
            if not opt.empty:
                # Attach trade date from `created` (EOD report date).
                opt = opt.copy()
                opt["as_of_date"] = opt["created"].map(_as_date)
                for as_of, day in opt.groupby("as_of_date"):
                    if as_of is None or as_of not in spot_map:
                        continue
                    picked = pick_atm_iv_for_day(day, spot_map[as_of], as_of, rate=self.rate)
                    if picked is None:
                        continue
                    rows.append(
                        AtmIvRow(
                            as_of_date=picked.as_of_date,
                            ticker=symbol,
                            atm_iv=picked.atm_iv,
                            dte=picked.dte,
                            call_iv=picked.call_iv,
                            put_iv=picked.put_iv,
                            spot=picked.spot,
                            call_strike=picked.call_strike,
                            put_strike=picked.put_strike,
                            call_mid=picked.call_mid,
                            put_mid=picked.put_mid,
                        )
                    )
            cursor = chunk_end + timedelta(days=1)
        # Deduplicate by date (last wins).
        by_date = {r.as_of_date: r for r in rows}
        return [by_date[d] for d in sorted(by_date)]


def rows_to_frame(rows: Iterable[AtmIvRow]) -> pd.DataFrame:
    records = [
        {
            "as_of_date": r.as_of_date.isoformat(),
            "ticker": r.ticker,
            "atm_iv": r.atm_iv,
            "dte": r.dte,
            "call_iv": r.call_iv,
            "put_iv": r.put_iv,
            "spot": r.spot,
            "call_strike": r.call_strike,
            "put_strike": r.put_strike,
            "call_mid": r.call_mid,
            "put_mid": r.put_mid,
            "source": r.source,
        }
        for r in rows
    ]
    return pd.DataFrame.from_records(records)


def default_history_window(as_of: Optional[date] = None) -> tuple[date, date]:
    """Free tier: ~1y history, EOD delayed 1 day."""
    end = as_of or (datetime.now(timezone.utc).date() - timedelta(days=1))
    start = end - timedelta(days=365)
    # Free access table cites 2023-06-01 as first date; clamp defensively.
    floor = date(2023, 6, 1)
    if start < floor:
        start = floor
    return start, end


def write_artifact(df: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".parquet":
        df.to_parquet(path, index=False)
    else:
        df.to_csv(path, index=False)
    return path


def upsert_supabase(df: pd.DataFrame) -> int:
    """Upsert into option_iv_history. Returns rows attempted."""
    import os

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY missing — wrote local artifact only.")
    if df.empty:
        return 0
    from supabase import create_client

    client = create_client(url, key)
    payload = df.where(pd.notnull(df), None).to_dict(orient="records")
    # Chunk to keep payloads modest.
    n = 0
    for i in range(0, len(payload), 200):
        chunk = payload[i : i + 200]
        client.table("option_iv_history").upsert(
            chunk, on_conflict="as_of_date,ticker,source"
        ).execute()
        n += len(chunk)
    return n


def run_bootstrap(
    tickers: Iterable[str] = PHASE1_OPTIONABLE_ETFS,
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
    artifact_path: Optional[Path] = None,
    upsert: bool = True,
) -> pd.DataFrame:
    import os

    api_key = os.environ.get("THETADATA_API_KEY")
    if not api_key:
        raise RuntimeError("THETADATA_API_KEY is not set in this environment.")

    s, e = default_history_window(end)
    if start is not None:
        s = start
    if end is not None:
        e = end

    boot = ThetaIvBootstrapper(api_key=api_key)
    all_rows: list[AtmIvRow] = []
    for ticker in tickers:
        print(f"[iv-bootstrap] {ticker} {s} → {e}")
        all_rows.extend(boot.bootstrap_symbol(ticker, s, e))
        print(f"[iv-bootstrap] {ticker}: {sum(1 for r in all_rows if r.ticker == ticker)} days")

    df = rows_to_frame(all_rows)
    out = artifact_path or Path("data/option_iv_history/atm_iv_bootstrap.csv")
    write_artifact(df, out)
    print(f"[iv-bootstrap] wrote {len(df)} rows → {out}")

    if upsert:
        try:
            n = upsert_supabase(df)
            print(f"[iv-bootstrap] upserted {n} rows to Supabase option_iv_history")
        except Exception as exc:
            print(f"[iv-bootstrap] Supabase upsert skipped/failed: {exc}")
    return df
