import io
import os
import zipfile
from datetime import datetime
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd
import pandas_datareader.data as web
import yfinance as yf

import config

CACHE_DIR = "data"
os.makedirs(CACHE_DIR, exist_ok=True)

FACTORS_CACHE_PATH = os.path.join(CACHE_DIR, "fama_french_factors.csv")
MACRO_CACHE_PATH = os.path.join(CACHE_DIR, "macro_indicators.csv")

KEN_FRENCH_FF5_ZIP = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
    "F-F_Research_Data_5_Factors_2x3_CSV.zip"
)
KEN_FRENCH_MOM_ZIP = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
    "F-F_Momentum_Factor_CSV.zip"
)
WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"
_USER_AGENT = "QuirkMacroETFQuant/1.0 (+https://github.com/qmcdonough1315/ETF_Quant_Model)"


def fetch_etf_returns(tickers: list, start_date: str = "1996-01-01") -> pd.DataFrame:
    print(f"📥 Fetching ETF returns starting from {start_date}...")
    raw_data = yf.download(tickers, start=start_date, interval="1mo", auto_adjust=True, progress=False)
    prices = raw_data['Close'] if isinstance(raw_data.columns, pd.MultiIndex) else (raw_data['Close'] if 'Close' in raw_data else raw_data)
    monthly_returns = prices.dropna(how='all', axis=1).pct_change().dropna(how='all')
    monthly_returns.index = pd.to_datetime(monthly_returns.index).to_period('M')
    return monthly_returns


def _http_get(url: str, timeout: int = 60) -> bytes:
    req = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _wayback_closest_url(original_url: str) -> Optional[str]:
    """Return a Wayback replay URL for the latest successful snapshot of original_url."""
    from urllib.parse import quote

    query = (
        f"{WAYBACK_CDX}?url={quote(original_url, safe='')}&output=json"
        f"&filter=statuscode:200&limit=1&sort=reverse"
    )
    try:
        raw = _http_get(query, timeout=30)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        print(f"  • Wayback CDX lookup failed: {exc}")
        return None

    try:
        import json

        rows = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"  • Wayback CDX parse failed: {exc}")
        return None

    if not isinstance(rows, list) or len(rows) < 2:
        return None
    # CDX rows: [urlkey, timestamp, original, mimetype, statuscode, digest, length]
    timestamp = rows[1][1]
    original = rows[1][2]
    return f"https://web.archive.org/web/{timestamp}id_/{original}"


def _download_ken_french_zip(url: str) -> bytes:
    """Download a Ken French zip, falling back to Wayback when Dartmouth is down."""
    errors: list[str] = []
    try:
        return _http_get(url)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"direct: {exc}")

    wayback = _wayback_closest_url(url)
    if wayback:
        try:
            print(f"  • Ken French direct fetch failed; using Wayback: {wayback}")
            return _http_get(wayback)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"wayback: {exc}")

    # Last-chance alias that often resolves to a recent capture.
    alias = f"https://web.archive.org/web/2026/{url}"
    try:
        print("  • Trying Wayback year alias for Ken French zip...")
        return _http_get(alias)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"wayback-alias: {exc}")

    raise RuntimeError("; ".join(errors))


def _parse_ken_french_monthly_csv(csv_bytes: bytes) -> pd.DataFrame:
    """
    Parse the monthly block from a Ken French factor CSV (zip member contents).

    Ken French files include a prose header, a monthly table, a blank line, then
    an annual table. We keep only the first (monthly) table.
    """
    text = csv_bytes.decode("utf-8", errors="replace")
    lines = text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith(","):
            continue
        cols = [c.strip() for c in stripped.split(",")[1:]]
        joined = "|".join(cols).lower()
        if "mkt-rf" in joined or joined.startswith("mom"):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("Could not locate Ken French monthly header row")

    header = [c.strip() for c in lines[header_idx].split(",")]
    rows: list[list[str]] = []
    for line in lines[header_idx + 1 :]:
        if not line.strip():
            break
        rows.append([c.strip() for c in line.split(",")])

    df = pd.DataFrame(rows, columns=header)
    # First column is YYYYMM with an empty header name.
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col], format="%Y%m")
    df = df.set_index(date_col)
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(how="all")
    return df


def _factors_from_zip_bytes(ff5_zip: bytes, mom_zip: bytes) -> pd.DataFrame:
    def _first_csv(zbytes: bytes) -> bytes:
        with zipfile.ZipFile(io.BytesIO(zbytes)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not names:
                raise ValueError("Ken French zip contained no CSV")
            return zf.read(names[0])

    ff5 = _parse_ken_french_monthly_csv(_first_csv(ff5_zip))
    mom = _parse_ken_french_monthly_csv(_first_csv(mom_zip))
    factors = ff5.join(mom, how="inner").rename(
        columns={"Mkt-RF": "Mkt_RF", "Mom   ": "WML", "Mom": "WML"}
    )
    # Collapse any residual Mom* column name variants.
    rename_mom = {c: "WML" for c in factors.columns if c.strip().lower().startswith("mom")}
    if rename_mom:
        factors = factors.rename(columns=rename_mom)
    factors = factors / 100.0
    factors.index = pd.to_datetime(factors.index).to_period("M")
    return factors


def _normalize_cached_factors(df: pd.DataFrame) -> pd.DataFrame:
    """Accept either canonical or legacy Beta_* cache column names."""
    out = df.copy()
    if "Date" in out.columns:
        out["Date"] = pd.to_datetime(out["Date"])
        out = out.set_index("Date")
    out.index = pd.to_datetime(out.index).to_period("M")
    legacy = {
        "Beta_Mkt": "Mkt_RF",
        "Beta_SMB": "SMB",
        "Beta_HML": "HML",
        "Beta_RMW": "RMW",
        "Beta_CMA": "CMA",
        "Beta_WML": "WML",
        "Mkt-RF": "Mkt_RF",
        "Mom": "WML",
        "Mom   ": "WML",
    }
    out = out.rename(columns={k: v for k, v in legacy.items() if k in out.columns})
    return out.sort_index()


def _save_factors_cache(factors: pd.DataFrame) -> None:
    cache = factors.copy()
    cache = cache.reset_index()
    cache.rename(columns={cache.columns[0]: "Date"}, inplace=True)
    cache["Date"] = cache["Date"].astype(str)
    cache.to_csv(FACTORS_CACHE_PATH, index=False)
    print(f"  • Wrote Ken French cache → {FACTORS_CACHE_PATH} (through {factors.index.max()})")


def _load_factors_cache(start_date: str) -> pd.DataFrame:
    if not os.path.exists(FACTORS_CACHE_PATH):
        raise FileNotFoundError(FACTORS_CACHE_PATH)
    raw = pd.read_csv(FACTORS_CACHE_PATH)
    factors = _normalize_cached_factors(raw)
    start = pd.Period(pd.Timestamp(start_date), freq="M")
    return factors.loc[factors.index >= start]


def fetch_ken_french_factors(start_date: str = "1996-01-01") -> pd.DataFrame:
    """
    Fetch Fama–French 5 + momentum.

    Order: pandas_datareader (Dartmouth) → direct/Wayback zip → local CSV cache.
    Successful remote pulls refresh data/fama_french_factors.csv.
    """
    print("📥 Fetching Ken French Factors...")
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    errors: list[str] = []

    # 1) Canonical pandas_datareader path (works when Dartmouth is healthy).
    try:
        ff5 = web.DataReader("F-F_Research_Data_5_Factors_2x3", "famafrench", start=start_dt)[0]
        ff_mom = web.DataReader("F-F_Momentum_Factor", "famafrench", start=start_dt)[0]
        factors = ff5.join(ff_mom, how="inner").rename(
            columns={"Mkt-RF": "Mkt_RF", "Mom   ": "WML", "Mom": "WML"}
        )
        factors = factors / 100.0
        factors.index = factors.index.to_timestamp().to_period("M")
        _save_factors_cache(factors)
        return factors
    except Exception as exc:  # noqa: BLE001
        errors.append(f"pandas_datareader: {exc}")
        print(f"  • pandas_datareader Ken French failed: {exc}")

    # 2) Direct zip / Wayback Machine (Dartmouth SSL/502 outages).
    try:
        ff5_zip = _download_ken_french_zip(KEN_FRENCH_FF5_ZIP)
        mom_zip = _download_ken_french_zip(KEN_FRENCH_MOM_ZIP)
        factors = _factors_from_zip_bytes(ff5_zip, mom_zip)
        start_period = pd.Period(pd.Timestamp(start_date), freq="M")
        factors = factors.loc[factors.index >= start_period]
        _save_factors_cache(factors)
        print(f"  • Ken French zip/Wayback OK through {factors.index.max()}")
        return factors
    except Exception as exc:  # noqa: BLE001
        errors.append(f"zip/wayback: {exc}")
        print(f"  • Ken French zip/Wayback failed: {exc}")

    # 3) Local cache last resort (keeps Sunday runs from hard-failing on host outages).
    try:
        factors = _load_factors_cache(start_date)
        print(
            f"  • Using local Ken French cache through {factors.index.max()} "
            f"({FACTORS_CACHE_PATH})"
        )
        return factors
    except Exception as exc:  # noqa: BLE001
        errors.append(f"cache: {exc}")

    raise RuntimeError("Ken French factor fetch failed: " + " | ".join(errors))


def fetch_macro_indicators(start_date: str = "1996-01-01") -> pd.DataFrame:
    print("📥 Fetching Macroeconomic Indicators from FRED...")
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")

    # Get the FRED tickers from config
    fred_series = config.MACRO_FRED_SERIES
    tickers = list(fred_series.keys())

    try:
        # Download data from FRED
        macro_raw = web.DataReader(tickers, "fred", start_dt)

        # Rename columns to human-readable names based on config dictionary
        macro_raw = macro_raw.rename(columns=fred_series)

        # Convert daily/weekly data to end-of-month frequency to match ETF/Factor data
        macro_monthly = macro_raw.resample('ME').last()
        macro_monthly.index = macro_monthly.index.to_period('M')

        # Apply percentage changes to specific columns (e.g., inflation, money supply)
        for col in config.MACRO_PCT_CHANGE_COLS:
            if col in macro_monthly.columns:
                macro_monthly[col] = macro_monthly[col].pct_change()

        out = macro_monthly.dropna()
        cache = out.reset_index()
        cache.rename(columns={cache.columns[0]: "DATE"}, inplace=True)
        cache.to_csv(MACRO_CACHE_PATH, index=False)
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"  • FRED fetch failed: {exc}")
        if not os.path.exists(MACRO_CACHE_PATH):
            raise
        raw = pd.read_csv(MACRO_CACHE_PATH)
        date_col = "DATE" if "DATE" in raw.columns else raw.columns[0]
        raw[date_col] = pd.to_datetime(raw[date_col])
        raw = raw.set_index(date_col).sort_index()
        # Legacy cache is daily FRED levels; newer cache is already monthly.
        if len(raw) > 40 * (raw.index.max().year - raw.index.min().year + 1):
            raw = raw.resample("ME").last()
            for col in config.MACRO_PCT_CHANGE_COLS:
                if col in raw.columns:
                    raw[col] = raw[col].pct_change()
        raw.index = raw.index.to_period("M")
        print(f"  • Using local macro cache through {raw.index.max()} ({MACRO_CACHE_PATH})")
        return raw.dropna()


def fetch_all_data(tickers, start_date="1996-01-01", use_cache=True):
    """
    Main orchestration function to fetch and return all required datasets.

    use_cache is retained for callers; remote pulls refresh on-disk caches, and
    caches are used automatically when remote providers are unavailable.
    """
    _ = use_cache  # caches are always written/read as fallback; flag kept for API compat
    prices = fetch_etf_returns(tickers, start_date)
    factors = fetch_ken_french_factors(start_date)
    macro = fetch_macro_indicators(start_date)

    # Return exactly the three variables expected by main.py
    return prices, factors, macro
