"""
Alpaca paper Trading API helpers.

Credentials (env only — never commit):
  ALPACA_API_KEY_ID / APCA_API_KEY_ID
  ALPACA_API_SECRET_KEY / APCA_API_SECRET_KEY
Optional:
  ALPACA_API_BASE_URL / APCA_API_BASE_URL  (default https://paper-api.alpaca.markets)
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

DEFAULT_PAPER_BASE = "https://paper-api.alpaca.markets"


def _credentials() -> tuple[Optional[str], Optional[str], str]:
    key_id = (os.environ.get("ALPACA_API_KEY_ID") or os.environ.get("APCA_API_KEY_ID") or "").strip()
    secret = (
        os.environ.get("ALPACA_API_SECRET_KEY") or os.environ.get("APCA_API_SECRET_KEY") or ""
    ).strip()
    base = (
        os.environ.get("ALPACA_API_BASE_URL")
        or os.environ.get("APCA_API_BASE_URL")
        or DEFAULT_PAPER_BASE
    ).strip()
    base = base.rstrip("/")
    if base.endswith("/v2"):
        base = base[:-3]
    return key_id or None, secret or None, base


def configured() -> bool:
    key_id, secret, _ = _credentials()
    return bool(key_id and secret)


def alpaca_get(path: str) -> dict[str, Any] | list[Any]:
    key_id, secret, base = _credentials()
    if not key_id or not secret:
        raise RuntimeError(
            "Alpaca credentials missing. Set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY."
        )
    url = f"{base}/v2{path if path.startswith('/') else '/' + path}"
    req = urllib.request.Request(
        url,
        headers={
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Alpaca HTTP {exc.code}: {body}") from exc


def get_account() -> dict[str, Any]:
    data = alpaca_get("/account")
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected Alpaca account payload")
    return data


def get_positions() -> list[dict[str, Any]]:
    data = alpaca_get("/positions")
    if not isinstance(data, list):
        raise RuntimeError("Unexpected Alpaca positions payload")
    return data


def get_option_contracts(underlying_symbols: list[str], limit: int = 100) -> list[dict[str, Any]]:
    q = urllib.parse.urlencode(
        {
            "underlying_symbols": ",".join(underlying_symbols),
            "status": "active",
            "limit": str(limit),
        }
    )
    data = alpaca_get(f"/options/contracts?{q}")
    if isinstance(data, dict) and "option_contracts" in data:
        contracts = data["option_contracts"]
        return contracts if isinstance(contracts, list) else []
    if isinstance(data, list):
        return data
    return []


def alpaca_post(path: str, body: dict[str, Any]) -> dict[str, Any] | list[Any]:
    key_id, secret, base = _credentials()
    if not key_id or not secret:
        raise RuntimeError(
            "Alpaca credentials missing. Set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY."
        )
    if "paper-api.alpaca.markets" not in base.lower():
        raise RuntimeError("Refusing order: ALPACA_API_BASE_URL is not paper-api.alpaca.markets.")
    url = f"{base}/v2{path if path.startswith('/') else '/' + path}"
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_txt = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Alpaca HTTP {exc.code}: {body_txt}") from exc


def place_mleg_order(payload: dict[str, Any], *, confirm: bool = False) -> dict[str, Any]:
    """
    Submit a multi-leg options order to Alpaca paper.
    Credit spreads must use a negative limit_price.
    """
    if not confirm:
        raise RuntimeError("Set confirm=True to submit a paper mleg order.")
    if payload.get("order_class") != "mleg":
        raise RuntimeError("order_class must be mleg.")
    try:
        limit = float(payload.get("limit_price"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("limit_price required") from exc
    if limit >= 0:
        raise RuntimeError("Credit spreads require a negative limit_price (Alpaca convention).")
    data = alpaca_post("/orders", payload)
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected Alpaca order payload")
    return data


def place_equity_order(payload: dict[str, Any], *, confirm: bool = False) -> dict[str, Any]:
    """
    Submit a single-leg equity order to Alpaca paper.

    Buys: prefer notional market orders for fractional DCA (qty also OK).
    Sells (Wave B #6): qty market orders only (TLH/HIFO propose path).
    """
    if not confirm:
        raise RuntimeError("Set confirm=True to submit a paper equity order.")
    if payload.get("order_class") in ("mleg", "bracket", "oco", "oto"):
        raise RuntimeError("Use place_mleg_order for multi-leg / complex order classes.")
    side = str(payload.get("side") or "").lower()
    if side not in {"buy", "sell"}:
        raise RuntimeError("side must be buy or sell")
    symbol = str(payload.get("symbol") or "").strip().upper()
    if not symbol:
        raise RuntimeError("symbol required")
    has_notional = payload.get("notional") is not None and str(payload.get("notional")).strip() != ""
    has_qty = payload.get("qty") is not None and str(payload.get("qty")).strip() != ""
    if side == "sell":
        if not has_qty or has_notional:
            raise RuntimeError("Equity sells require qty (not notional).")
    elif has_notional == has_qty:
        raise RuntimeError("Provide exactly one of notional or qty.")
    body = {
        "symbol": symbol,
        "side": side,
        "type": str(payload.get("type") or "market"),
        "time_in_force": str(payload.get("time_in_force") or "day"),
    }
    if has_notional:
        try:
            notional = float(payload.get("notional"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("notional must be a number") from exc
        if notional < 1.0:
            raise RuntimeError("notional must be >= 1.00")
        body["notional"] = f"{notional:.2f}"
    else:
        body["qty"] = str(payload.get("qty"))
    data = alpaca_post("/orders", body)
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected Alpaca order payload")
    return data


def paper_ledger_summary() -> dict[str, Any]:
    """Compact snapshot for logging / export."""
    if not configured():
        return {"live": False, "error": "credentials_missing"}
    account = get_account()
    positions = get_positions()
    return {
        "live": True,
        "status": account.get("status"),
        "equity": account.get("equity"),
        "cash": account.get("cash"),
        "buying_power": account.get("buying_power"),
        "options_buying_power": account.get("options_buying_power"),
        "options_trading_level": account.get("options_trading_level"),
        "position_count": len(positions),
        "symbols": [p.get("symbol") for p in positions],
    }
