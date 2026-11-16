"""Ken French CSV parse + cache normalize (no live Dartmouth dependency)."""

from __future__ import annotations

import io
import zipfile

import pandas as pd
import pytest

from modules.data_ingestion import (
    _factors_from_zip_bytes,
    _normalize_cached_factors,
    _parse_ken_french_monthly_csv,
)


def _zip_csv(name: str, body: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, body)
    return buf.getvalue()


FF5_SAMPLE = """This file was created using the 202609 CRSP database.

,Mkt-RF,SMB,HML,RMW,CMA,RF
202607,   -0.61,   -0.09,    2.11,   11.07,    2.27,    0.33
202608,    2.56,   -0.52,   -3.54,   -4.09,   -2.01,    0.29
202609,   -1.07,   -4.60,   -1.55,   -3.22,    1.08,    0.31

,Mkt-RF,SMB,HML,RMW,CMA,RF
2024,   10.00,    1.00,    2.00,    3.00,    4.00,    5.00
"""

MOM_SAMPLE = """Momentum factor header prose.

,Mom
202607,   1.10
202608,   2.20
202609,   6.70

,Mom
2024,   9.00
"""


def test_parse_ken_french_monthly_stops_before_annual():
    df = _parse_ken_french_monthly_csv(FF5_SAMPLE.encode())
    assert list(df.columns) == ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"]
    assert len(df) == 3
    assert df.index.min() == pd.Timestamp("2026-07-01")
    assert df.index.max() == pd.Timestamp("2026-09-01")
    assert float(df.loc[pd.Timestamp("2026-09-01"), "Mkt-RF"]) == -1.07


def test_factors_from_zip_bytes_joins_momentum_and_scales():
    factors = _factors_from_zip_bytes(
        _zip_csv("ff5.csv", FF5_SAMPLE),
        _zip_csv("mom.csv", MOM_SAMPLE),
    )
    assert "WML" in factors.columns
    assert "Mkt_RF" in factors.columns
    assert factors.index.max() == pd.Period("2026-09", freq="M")
    # Ken French files are percent; we store decimals.
    assert float(factors.loc[pd.Period("2026-09", freq="M"), "Mkt_RF"]) == pytest.approx(-0.0107)
    assert float(factors.loc[pd.Period("2026-09", freq="M"), "WML"]) == pytest.approx(0.0670)


def test_normalize_cached_factors_accepts_legacy_beta_names():
    raw = pd.DataFrame(
        {
            "Date": ["2026-05-01", "2026-06-01"],
            "Beta_Mkt": [0.01, -0.02],
            "Beta_SMB": [0.0, 0.01],
            "Beta_HML": [0.0, 0.0],
            "Beta_RMW": [0.0, 0.0],
            "Beta_CMA": [0.0, 0.0],
            "RF": [0.003, 0.003],
            "Beta_WML": [0.02, 0.01],
        }
    )
    out = _normalize_cached_factors(raw)
    assert "Mkt_RF" in out.columns
    assert "WML" in out.columns
    assert out.index.max() == pd.Period("2026-06", freq="M")
