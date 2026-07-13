"""Optional lightweight pytdx adapter used by the standalone radar.

The main dashboard remains usable without pytdx.  When the optional dependency
is installed, this module adds current five-level quotes and historical minute
time bars without importing the much larger ETF research stack.
"""

from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from statistics import median
from typing import Any


TDX_HOSTS = [
    ("60.12.136.250", 7709),
    ("117.184.140.156", 7709),
    ("119.147.212.81", 7709),
    ("60.191.117.167", 7709),
    ("218.75.126.9", 7709),
    ("180.153.18.170", 7709),
    ("115.238.56.198", 7709),
]

_tdx_api_cache: dict[str, Any] = {"api": None, "host": ""}


def _connect_tdx(timeout: float = 2.5):
    """Connect to the first available public TDX quote node."""
    global _tdx_api_cache
    api = _tdx_api_cache.get("api")
    if api is not None:
        try:
            api.get_security_count(1)
            return api, _tdx_api_cache.get("host", "")
        except Exception:
            try:
                api.disconnect()
            except Exception:
                pass
            _tdx_api_cache = {"api": None, "host": ""}

    try:
        from pytdx.hq import TdxHq_API
    except ImportError:
        return None, ""

    for ip, port in TDX_HOSTS:
        candidate = TdxHq_API(auto_retry=True)
        try:
            if candidate.connect(ip, port, time_out=timeout):
                host = f"{ip}:{port}"
                _tdx_api_cache = {"api": candidate, "host": host}
                return candidate, host
        except Exception:
            try:
                candidate.disconnect()
            except Exception:
                pass
    return None, ""


def _market_code(symbol: str) -> tuple[int, str]:
    code = symbol.split(".")[0]
    suffix = symbol.split(".")[-1].upper() if "." in symbol else ""
    return (1 if suffix == "SH" or code.startswith(("5", "6", "9")) else 0), code


def _trading_minute_datetimes(trade_date: date) -> list[datetime]:
    slots: list[datetime] = []
    for start, end in ((dtime(9, 31), dtime(11, 30)), (dtime(13, 1), dtime(15, 0))):
        current = datetime.combine(trade_date, start)
        stop = datetime.combine(trade_date, end)
        while current <= stop:
            slots.append(current)
            current += timedelta(minutes=1)
    return slots


def fetch_history_minute_time_bars(symbol: str, trade_date: date | None = None) -> list[dict[str, Any]]:
    """Fetch one A-share day of TDX minute-time observations.

    The TDX endpoint returns 240 close-like prices without timestamps.  We map
    them to 09:31–11:30 and 13:01–15:00.  OHLC is intentionally flat and the
    dashboard labels any signed-flow reconstruction as a proxy, never as native
    main-force flow.
    """
    api, _host = _connect_tdx()
    if api is None:
        return []
    market, code = _market_code(symbol)
    trade_date = trade_date or date.today()
    try:
        raw_rows = api.get_history_minute_time_data(market, code, int(trade_date.strftime("%Y%m%d"))) or []
    except Exception:
        return []
    positive_prices = [float(row.get("price") or 0) for row in raw_rows if float(row.get("price") or 0) > 0]
    if not positive_prices:
        return []
    # Public nodes occasionally expose a fixed decimal scale.  The conservative
    # thresholds only correct clearly impossible A-share medians.
    middle = median(positive_prices)
    scale = 100.0 if middle > 10000 else 10.0 if middle > 1000 else 1.0
    result: list[dict[str, Any]] = []
    for timestamp, raw in zip(_trading_minute_datetimes(trade_date), raw_rows):
        try:
            close = float(raw.get("price") or 0) / scale
            if close <= 0:
                continue
            volume = float(raw.get("vol", raw.get("volume", 0)) or 0) * 100.0
            result.append({
                "symbol": symbol,
                "time": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "open": round(close, 6),
                "high": round(close, 6),
                "low": round(close, 6),
                "close": round(close, 6),
                "volume": volume,
                "amount": round(close * volume, 3),
            })
        except (TypeError, ValueError):
            continue
    return result
