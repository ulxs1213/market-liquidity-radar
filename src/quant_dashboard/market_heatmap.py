from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

import requests

from quant_dashboard.market_heatmap_history import MarketHeatmapHistoryStore
from quant_dashboard.trading_calendar import (
    a_share_session_status,
    current_or_previous_trading_day,
    is_trading_day,
    previous_trading_day,
)


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("MLR_DATA_DIR", str(ROOT / "data"))).expanduser().resolve()
CACHE_DIR = DATA_DIR / "market_heatmap"
EM_HOSTS = (
    ("https://push2.eastmoney.com", False),
    ("https://push2delay.eastmoney.com", True),
)
EM_UT = "bd1d9ddb04089700cf9c27f6f7426281"
SECTOR_FIELDS = (
    "f12,f14,f2,f3,f4,f5,f6,f8,f10,f62,f66,f69,f72,f75,f78,f81,"
    "f84,f87,f104,f105,f124,f128,f136,f140,f141,f184"
)
STOCK_FIELDS = (
    "f12,f13,f14,f2,f3,f4,f5,f6,f8,f10,f15,f16,f17,f18,f20,f21,"
    "f62,f66,f69,f72,f75,f78,f81,f84,f87,f100,f102,f103,f124"
)

# These are market-wide eligibility/index-universe buckets, not a coherent
# industry or investable theme.  Keeping the list exact and conservative avoids
# silently hiding ordinary concepts that merely contain similar words.
CONCEPT_AGGREGATE_BOARD_NAMES = frozenset(
    {
        "融资融券",
        "沪股通",
        "深股通",
        "MSCI中国",
        "富时罗素",
        "标普道琼斯A股",
    }
)


def _minute_labels(start: str, end: str) -> list[str]:
    start_hour, start_minute = (int(part) for part in start.split(":"))
    end_hour, end_minute = (int(part) for part in end.split(":"))
    first = start_hour * 60 + start_minute
    last = end_hour * 60 + end_minute
    return [f"{minute // 60:02d}:{minute % 60:02d}" for minute in range(first, last + 1)]


REGULAR_SESSION_LABELS = tuple(_minute_labels("09:30", "11:30") + _minute_labels("13:00", "15:00"))
AUCTION_SESSION_LABELS = tuple(_minute_labels("09:15", "09:29"))


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "-", "--"):
            return default
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _epoch_text(value: Any) -> str:
    try:
        return datetime.fromtimestamp(int(float(value))).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        return ""


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp.replace(path)


def _zscore_map(rows: list[dict[str, Any]], key: str) -> dict[str, float]:
    values = [_number(row.get(key)) for row in rows]
    if not values:
        return {}
    ordered = sorted(values)
    lower = ordered[max(0, int((len(ordered) - 1) * 0.025))]
    upper = ordered[min(len(ordered) - 1, math.ceil((len(ordered) - 1) * 0.975))]
    winsorized = [max(lower, min(upper, value)) for value in values]
    mean = sum(winsorized) / len(winsorized)
    variance = sum((value - mean) ** 2 for value in winsorized) / max(1, len(winsorized))
    std = variance**0.5
    if std < 1e-12:
        return {str(row.get("code")): 0.0 for row in rows}
    return {
        str(row.get("code")): max(-3.0, min(3.0, (value - mean) / std))
        for row, value in zip(rows, winsorized)
    }


class EastmoneyHeatmapProvider:
    """Small, rate-limited adapter for public quote pages.

    Eastmoney does not publish a stability SLA for these endpoints.  The adapter
    therefore exposes provenance and delay flags and never labels a snapshot as
    exchange-authoritative data.
    """

    def __init__(self, timeout: float = 5.0) -> None:
        self.timeout = timeout

    def _get(self, path: str, params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        errors: list[str] = []
        for host, delayed in EM_HOSTS:
            session = requests.Session()
            session.trust_env = False
            started = time.perf_counter()
            try:
                response = session.get(
                    f"{host}{path}",
                    params=params,
                    timeout=self.timeout,
                    headers={
                        "User-Agent": "Mozilla/5.0 (market-liquidity-radar/1.0)",
                        "Referer": "https://quote.eastmoney.com/",
                    },
                )
                response.raise_for_status()
                payload = response.json()
                if int(payload.get("rc", -1)) != 0 or not payload.get("data"):
                    raise ValueError(f"unexpected payload rc={payload.get('rc')}")
                return payload, {
                    "provider": "东方财富公开行情页接口",
                    "host": host,
                    "possibly_delayed": delayed,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                    "contract": "非官方稳定契约；仅作行情观察，需时间戳和多源校验",
                }
            except Exception as exc:  # noqa: BLE001 - provider errors must degrade cleanly
                errors.append(f"{host}: {type(exc).__name__}: {exc}")
            finally:
                session.close()
        raise RuntimeError(" | ".join(errors[-4:]))

    def sectors(self, board_type: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        fs = "m:90+t:3" if board_type == "concept" else "m:90+t:2"
        rows: list[dict[str, Any]] = []
        page = 1
        pages_fetched = 0
        reported_total = 0
        source: dict[str, Any] = {}
        elapsed_ms = 0.0
        # Follow the upstream-reported total instead of assuming that a board
        # universe will always fit in eight pages.  The high safety ceiling
        # prevents an upstream pagination bug from creating an infinite loop.
        while page <= 100:
            payload, page_source = self._get(
                "/api/qt/clist/get",
                {
                    "pn": page,
                    "pz": 100,
                    "po": 1,
                    "np": 1,
                    "ut": EM_UT,
                    "fltt": 2,
                    "invt": 2,
                    "fid": "f62",
                    "fs": fs,
                    "fields": SECTOR_FIELDS,
                },
            )
            data = payload.get("data") or {}
            chunk = [row for row in (data.get("diff") or []) if isinstance(row, dict)]
            rows.extend(chunk)
            pages_fetched += 1
            elapsed_ms += _number(page_source.get("elapsed_ms"))
            source = page_source
            total = int(_number(data.get("total")))
            reported_total = max(reported_total, total)
            if not chunk or (total > 0 and page * 100 >= total) or len(chunk) < 100:
                break
            page += 1

        # A live list can reorder while pages are being fetched.  Never expose
        # duplicate board codes as if they were distinct coverage.
        unique_rows: list[dict[str, Any]] = []
        seen_codes: set[str] = set()
        for row in rows:
            code = str(row.get("f12") or "")
            if code and code in seen_codes:
                continue
            if code:
                seen_codes.add(code)
            unique_rows.append(row)
        source = dict(source)
        source["elapsed_ms"] = round(elapsed_ms, 2)
        source["pages"] = pages_fetched
        source["reported_total"] = reported_total
        source["row_count"] = len(unique_rows)
        source["complete"] = reported_total == 0 or len(unique_rows) >= reported_total
        return unique_rows, source

    def stocks(self, fs: str, limit: int = 120) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        requested = max(10, min(500, limit))
        rows: list[dict[str, Any]] = []
        seen_codes: set[str] = set()
        source: dict[str, Any] = {}
        elapsed_ms = 0.0
        reported_total = 0
        page = 1
        pages_fetched = 0
        while page <= 10 and len(rows) < requested:
            payload, page_source = self._get(
                "/api/qt/clist/get",
                {
                    "pn": page,
                    # The live endpoint currently caps a response at 100 rows
                    # even when a larger pz is requested.
                    "pz": 100,
                    "po": 1,
                    "np": 1,
                    "ut": EM_UT,
                    "fltt": 2,
                    "invt": 2,
                    "fid": "f6",
                    "fs": fs,
                    "fields": STOCK_FIELDS,
                },
            )
            data = payload.get("data") or {}
            chunk = [row for row in (data.get("diff") or []) if isinstance(row, dict)]
            pages_fetched += 1
            elapsed_ms += _number(page_source.get("elapsed_ms"))
            source = page_source
            reported_total = max(reported_total, int(_number(data.get("total"))))
            for row in chunk:
                code = str(row.get("f12") or "")
                if code and code in seen_codes:
                    continue
                if code:
                    seen_codes.add(code)
                rows.append(row)
                if len(rows) >= requested:
                    break
            if not chunk or len(chunk) < 100 or (reported_total > 0 and page * 100 >= reported_total):
                break
            page += 1
        target_count = min(requested, reported_total) if reported_total > 0 else requested
        source = dict(source)
        source["elapsed_ms"] = round(elapsed_ms, 2)
        source["pages"] = pages_fetched
        source["reported_total"] = reported_total
        source["requested_limit"] = requested
        source["row_count"] = len(rows)
        source["complete"] = len(rows) >= target_count
        return rows, source

    def fund_flow_timeline(self, secid: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        payload, source = self._get(
            "/api/qt/stock/fflow/kline/get",
            {
                "lmt": 0,
                "klt": 1,
                "fields1": "f1,f2,f3,f7",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63",
                "secid": secid,
            },
        )
        data = payload.get("data") or {}
        points: list[dict[str, Any]] = []
        for line in data.get("klines") or []:
            parts = str(line).split(",")
            if len(parts) < 6:
                continue
            points.append(
                {
                    "time": parts[0],
                    "flow": _number(parts[1]),
                    "small_flow": _number(parts[2]),
                    "medium_flow": _number(parts[3]),
                    "large_flow": _number(parts[4]),
                    "super_large_flow": _number(parts[5]),
                    "resolution": "1m",
                }
            )
        source = dict(source)
        source.update(
            {
                "provider": "东方财富公开分钟资金流接口",
                "endpoint": "/api/qt/stock/fflow/kline/get",
                "secid": secid,
                "field_mapping": {
                    "f51": "分钟时间",
                    "f52": "主力净流入累计值",
                    "f53": "小单净流入累计值",
                    "f54": "中单净流入累计值",
                    "f55": "大单净流入累计值",
                    "f56": "超大单净流入累计值",
                },
                "row_count": len(points),
            }
        )
        return points, source

    def stock_intraday(self, secid: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        payload, source = self._get(
            "/api/qt/stock/trends2/get",
            {
                "secid": secid,
                "fields1": "f1,f2,f3,f4,f5,f6,f7,f8",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
                # iscr=1 asks the same public trends endpoint to include the
                # provider's real 09:15-09:29 call-auction observations.  The
                # service separates those rows from continuous trading below;
                # it never synthesizes auction prices.
                "iscr": 1,
                "ndays": 1,
                "ut": EM_UT,
            },
        )
        data = payload.get("data") or {}
        points: list[dict[str, Any]] = []
        for line in data.get("trends") or []:
            parts = str(line).split(",")
            if len(parts) < 8:
                continue
            points.append(
                {
                    "time": parts[0],
                    "close": _number(parts[1]),
                    "open": _number(parts[2]),
                    "high": _number(parts[3]),
                    "low": _number(parts[4]),
                    "volume": _number(parts[5]),
                    "amount": _number(parts[6]),
                    "average": _number(parts[7]),
                    "resolution": "1m",
                }
            )
        source = dict(source)
        source.update(
            {
                "provider": "东方财富公开分时价格接口",
                "endpoint": "/api/qt/stock/trends2/get",
                "secid": secid,
                "field_mapping": {
                    "f51": "分钟时间",
                    "f52": "最新价",
                    "f53": "分钟开盘价",
                    "f54": "分钟最高价",
                    "f55": "分钟最低价",
                    "f56": "分钟成交量（手；普通A股通常1手=100股）",
                    "f57": "分钟成交额",
                    "f58": "当日均价",
                },
                "pre_close": _number(data.get("preClose")),
                "row_count": len(points),
                "auction_query": "iscr=1",
                "auction_contract": "仅透传上游实际返回的09:15-09:29价格观察；成交量为0也不改写或推断",
            }
        )
        return points, source


class MarketHeatmapService:
    def __init__(
        self,
        ttl_seconds: float = 3.0,
        provider: EastmoneyHeatmapProvider | None = None,
        history_store: MarketHeatmapHistoryStore | None = None,
        historical_bar_fetcher: Callable[[str, date], list[dict[str, Any]]] | None = None,
        cache_dir: Path | str | None = None,
    ) -> None:
        self.ttl_seconds = max(1.0, ttl_seconds)
        self.provider = provider or EastmoneyHeatmapProvider()
        self.history_store = history_store
        self.historical_bar_fetcher = historical_bar_fetcher
        self.cache_dir = Path(cache_dir or CACHE_DIR).expanduser().resolve()
        self._lock = threading.Lock()
        self._flow_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
        self._history_lock = threading.Lock()
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._previous: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self._timeline: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=1200))
        self._liquidity_ranks: dict[str, int] = {}
        self._collector_state: dict[str, Any] = {
            "status": "initializing",
            "status_label": "正在初始化",
            "last_cycle_at": "",
            "last_error": "",
            "cycle_count": 0,
            "industry_interval_sec": int(self.ttl_seconds),
            "concept_interval_sec": 15,
            "liquidity_interval_sec": int(self.ttl_seconds),
        }

    def session_axis(
        self,
        trade_date: str = "",
        include_auction: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Return a complete A-share minute skeleton and the current fill boundary.

        The labels are presentation slots, not quote observations.  Consumers
        should map real points onto them and keep every index at or after
        ``blank_from_index`` empty.  Lunch is deliberately absent, so 11:30 and
        13:00 are adjacent.  The regular axis always ends at the exchange close
        of 15:00; no 15:01-15:30 values are invented.
        """
        now = now or datetime.now()
        selected_text = str(trade_date or now.date().isoformat())[:10]
        try:
            selected_date = datetime.strptime(selected_text, "%Y-%m-%d").date()
        except ValueError:
            return {
                "ok": False,
                "error": "trade_date 必须为 YYYY-MM-DD",
                "session_axis": {},
                "session_progress": {},
            }

        auction_labels = list(AUCTION_SESSION_LABELS)
        regular_labels = list(REGULAR_SESSION_LABELS)
        labels = (auction_labels if include_auction else []) + regular_labels
        trading_day = is_trading_day(selected_date)
        status = "future"
        elapsed_slots = 0
        if not trading_day:
            status = "non_trading_day"
        elif selected_date < now.date():
            status = "historical_complete"
            elapsed_slots = len(labels)
        elif selected_date > now.date():
            status = "future"
        else:
            minute = now.hour * 60 + now.minute
            if minute < 9 * 60 + 15:
                status = "pre_open"
            elif minute <= 9 * 60 + 25:
                status = "auction"
            elif minute < 9 * 60 + 30:
                status = "pre_open_wait"
            elif minute <= 11 * 60 + 30:
                status = "morning"
            elif minute < 13 * 60:
                status = "lunch_break"
            elif minute <= 15 * 60:
                status = "afternoon"
            else:
                status = "closed_complete"
            current_label = now.strftime("%H:%M")
            elapsed_slots = sum(label <= current_label for label in labels)

        total_slots = len(labels)
        elapsed_slots = max(0, min(total_slots, elapsed_slots))
        progress = {
            "status": status,
            "as_of": now.isoformat(timespec="seconds"),
            "elapsed_slots": elapsed_slots,
            "remaining_slots": total_slots - elapsed_slots,
            "total_slots": total_slots,
            "last_elapsed_index": elapsed_slots - 1,
            "last_elapsed_label": labels[elapsed_slots - 1] if elapsed_slots else "",
            "blank_from_index": elapsed_slots,
            "completion_ratio": round(elapsed_slots / total_slots, 6) if total_slots else 0.0,
            "is_complete": elapsed_slots == total_slots and trading_day,
        }
        axis = {
            "timezone": "Asia/Shanghai",
            "trade_date": selected_text,
            "is_trading_day": trading_day,
            "include_auction": bool(include_auction),
            "labels": labels,
            "minute_keys": [f"{selected_text} {label}" for label in labels],
            "regular_labels": regular_labels,
            "auction_labels": auction_labels,
            "sessions": [
                {"name": "call_auction", "start": "09:15", "end": "09:29", "slots": 15, "optional": True},
                {"name": "morning", "start": "09:30", "end": "11:30", "slots": 121},
                {"name": "afternoon", "start": "13:00", "end": "15:00", "slots": 121},
            ],
            "lunch_compressed": True,
            "adjacent_boundary": ["11:30", "13:00"],
            "market_close": "15:00",
            "display_end": "15:00",
            "contract": "完整分钟骨架仅用于定位真实数据与保留未来空白；不补午休、不延长到15:30、不补缺失行情",
        }
        return {
            "ok": True,
            "generated_at": _iso_now(),
            "session_axis": axis,
            "session_progress": progress,
        }

    def _session_fields(
        self,
        trade_date: str,
        *,
        include_auction: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        contract = self.session_axis(trade_date, include_auction=include_auction, now=now)
        return {
            "session_axis": contract.get("session_axis") or {},
            "session_progress": contract.get("session_progress") or {},
        }

    @staticmethod
    def _session(data_time: str) -> str:
        if not data_time:
            return "unknown"
        try:
            stamp = datetime.fromisoformat(data_time)
        except ValueError:
            return "unknown"
        today = datetime.now().date()
        if stamp.date() != today:
            return "historical_replay"
        hm = stamp.hour * 60 + stamp.minute
        if 555 <= hm <= 690:
            return "morning"
        if 780 <= hm <= 930:
            return "afternoon"
        return "closed"

    def _cache_path(self, board_type: str) -> Path:
        return self.cache_dir / f"latest_{board_type}.json"

    def _load_disk_cache(self, board_type: str) -> dict[str, Any] | None:
        try:
            payload = json.loads(self._cache_path(board_type).read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("sectors"):
                payload["stale"] = True
                payload["mode"] = "cached_replay"
                payload["status_message"] = "上游接口暂不可用，保留最近一次成功快照。"
                return payload
        except Exception:
            return None
        return None

    def _stale_memory_cache(self, cache_key: str, error: Exception) -> dict[str, Any] | None:
        cached = self._cache.get(cache_key)
        if not cached or not cached[1].get("ok"):
            return None
        payload = dict(cached[1])
        payload["stale"] = True
        payload["response_cached"] = True
        payload["served_at"] = _iso_now()
        payload["upstream_error"] = str(error)
        payload["status_message"] = "上游接口暂不可用，保留最近一次成功快照。"
        self._cache[cache_key] = (time.monotonic() + self.ttl_seconds, payload)
        return payload

    def _sector_rows(self, raw_rows: list[dict[str, Any]], board_type: str) -> list[dict[str, Any]]:
        previous = self._previous[board_type]
        rows: list[dict[str, Any]] = []
        for raw in raw_rows:
            code = str(raw.get("f12") or "")
            if not code:
                continue
            data_time = _epoch_text(raw.get("f124"))
            flow = _number(raw.get("f62"))
            amount = _number(raw.get("f6"))
            old = previous.get(code) or {}
            old_data_time = str(old.get("data_time") or "")
            same_day = bool(data_time and old_data_time) and old_data_time[:10] == data_time[:10]
            is_new_event = same_day and data_time != old_data_time
            delta_flow = flow - _number(old.get("main_net_inflow")) if is_new_event else 0.0
            delta_amount = amount - _number(old.get("amount")) if is_new_event else 0.0
            rise = int(_number(raw.get("f104")))
            fall = int(_number(raw.get("f105")))
            breadth = (rise - fall) / max(1, rise + fall)
            flow_ratio = flow / amount * 100 if amount else 0.0
            rows.append(
                {
                    "code": code,
                    "name": str(raw.get("f14") or code),
                    "price": _number(raw.get("f2")),
                    "change_pct": _number(raw.get("f3")),
                    "amount": amount,
                    "main_net_inflow": flow,
                    "main_net_ratio": _number(raw.get("f184"), flow_ratio),
                    "delta_flow": delta_flow,
                    "delta_amount": max(0.0, delta_amount),
                    "rise_count": rise,
                    "fall_count": fall,
                    "breadth": breadth,
                    "leader_name": str(raw.get("f128") or ""),
                    "leader_code": str(raw.get("f140") or ""),
                    "leader_change_pct": _number(raw.get("f136")),
                    "data_time": data_time,
                    "is_new_event": is_new_event,
                }
            )
        scores = {
            "change_pct": _zscore_map(rows, "change_pct"),
            "main_net_ratio": _zscore_map(rows, "main_net_ratio"),
            "breadth": _zscore_map(rows, "breadth"),
            "delta_flow": _zscore_map(rows, "delta_flow"),
        }
        for row in rows:
            code = row["code"]
            contributions = {
                "change_pct": round(0.35 * scores["change_pct"].get(code, 0.0), 4),
                "main_net_ratio": round(0.35 * scores["main_net_ratio"].get(code, 0.0), 4),
                "breadth": round(0.20 * scores["breadth"].get(code, 0.0), 4),
                "delta_flow": round(0.10 * scores["delta_flow"].get(code, 0.0), 4),
            }
            row["strength_score"] = round(sum(contributions.values()), 4)
            row["score_contributions"] = contributions
            old = previous.get(code) or {}
            if row["data_time"] and (not old.get("data_time") or row["is_new_event"]):
                previous[code] = {
                    "main_net_inflow": row["main_net_inflow"],
                    "amount": row["amount"],
                    "data_time": row["data_time"],
                }
                self._timeline[code].append(
                    {
                        "time": row["data_time"],
                        "flow": row["main_net_inflow"],
                        "delta_flow": row["delta_flow"],
                        "change_pct": row["change_pct"],
                    }
                )
        return rows

    def _clamp_snapshot_to_session_close(
        self,
        payload: dict[str, Any],
        board_type: str,
        session_status: str,
    ) -> dict[str, Any]:
        """Expose the last locally observed exchange timestamp while the market is paused.

        Eastmoney keeps advancing f124 during lunch although the quote values are
        frozen.  The UI must not imply that 12:xx is a real market observation,
        so use the latest persisted in-session timestamp (normally 11:30).
        """
        result = dict(payload)
        observed_time = ""
        if self.history_store is not None:
            latest = self.history_store.latest_sector_rows(board_type, datetime.now().date().isoformat())
            observed_time = max((str(row.get("data_time") or "") for row in latest), default="")
        if observed_time:
            result["data_time"] = observed_time
            result["sectors"] = [dict(row, data_time=observed_time) for row in result.get("sectors") or []]
        result.update(
            {
                "mode": session_status,
                "served_at": _iso_now(),
                "status_message": "午间休市，沿用11:30最后有效快照。" if session_status == "lunch_break" else "非交易时段，沿用最近有效快照。",
            }
        )
        return result

    def snapshot(self, board_type: str = "industry", force: bool = False) -> dict[str, Any]:
        board_type = str(board_type or "").strip().lower()
        if board_type not in {"industry", "concept"}:
            return {
                "ok": False,
                "generated_at": _iso_now(),
                "board_type": board_type,
                "error_code": "invalid_board_type",
                "error": "board_type 仅支持 industry 或 concept",
                "sectors": [],
            }
        now = time.monotonic()
        cached = self._cache.get(board_type)
        session_status = a_share_session_status(datetime.now())
        if isinstance(self.provider, EastmoneyHeatmapProvider) and cached and session_status in {"lunch_break", "closed"}:
            result = self._clamp_snapshot_to_session_close(cached[1], board_type, session_status)
            result["response_cached"] = True
            return result
        if not force and cached and now < cached[0]:
            result = dict(cached[1])
            result["response_cached"] = True
            return result
        with self._lock:
            now = time.monotonic()
            cached = self._cache.get(board_type)
            if not force and cached and now < cached[0]:
                result = dict(cached[1])
                result["response_cached"] = True
                return result
            try:
                raw_rows, source = self.provider.sectors(board_type)
                rows = self._sector_rows(raw_rows, board_type)
                data_times = [row["data_time"] for row in rows if row.get("data_time")]
                data_time = max(data_times) if data_times else ""
                session = self._session(data_time)
                delayed = bool(source.get("possibly_delayed"))
                payload = {
                    "ok": True,
                    "generated_at": _iso_now(),
                    "data_time": data_time,
                    "board_type": board_type,
                    "refresh_interval_ms": int(self.ttl_seconds * 1000),
                    "mode": session,
                    "stale": session == "historical_replay",
                    "source": source,
                    "status_message": (
                        "当前为最近交易日回放。" if session == "historical_replay" else
                        "当前接口可能延迟，页面不用于自动交易。" if delayed else
                        "盘中观察模式；资金流为供应商估算口径。"
                    ),
                    "method": {
                        "flow": "f62 供应商估算主力净流入；不是账户级现金流",
                        "score": "各指标先按2.5%/97.5%缩尾，再计算：0.35×涨幅Z + 0.35×净流入占比Z + 0.20×涨跌家数广度Z + 0.10×净流入增量Z",
                        "delta": "同一交易日相邻成功快照的累计值差；日切归零",
                        "aggregation": "行业层级和概念成分可能重叠；跨板块求和不代表全市场现金净流入",
                    },
                    "field_units": {
                        "price": "指数点",
                        "change_pct": "百分比",
                        "amount": "人民币元",
                        "main_net_inflow": "人民币元",
                        "main_net_ratio": "百分比",
                        "delta_flow": "人民币元/相邻成功快照",
                        "delta_amount": "人民币元/相邻成功快照",
                        "breadth": "无量纲，范围[-1,1]",
                        "strength_score": "横截面Z分数组合，无量纲",
                    },
                    "sectors": rows,
                    "response_cached": False,
                }
                if isinstance(self.provider, EastmoneyHeatmapProvider) and session_status in {"lunch_break", "closed"}:
                    payload = self._clamp_snapshot_to_session_close(payload, board_type, session_status)
                self._cache[board_type] = (time.monotonic() + self.ttl_seconds, payload)
                _atomic_json(self._cache_path(board_type), payload)
                if self.history_store is not None:
                    payload["history_rows_inserted"] = self.history_store.record_sectors(payload)
                return payload
            except Exception as exc:  # noqa: BLE001
                memory_fallback = self._stale_memory_cache(board_type, exc)
                if memory_fallback:
                    memory_fallback["mode"] = "cached_replay"
                    return memory_fallback
                fallback = self._load_disk_cache(board_type)
                if fallback:
                    fallback["ok"] = True
                    fallback["upstream_error"] = str(exc)
                    self._cache[board_type] = (time.monotonic() + self.ttl_seconds, fallback)
                    return fallback
                return {
                    "ok": False,
                    "generated_at": _iso_now(),
                    "board_type": board_type,
                    "mode": "unavailable",
                    "stale": True,
                    "error": str(exc),
                    "sectors": [],
                    "source": {"provider": "东方财富公开行情页接口", "possibly_delayed": True},
                }

    @staticmethod
    def _stock_rows(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for raw in raw_rows:
            code = str(raw.get("f12") or "")
            if not code:
                continue
            amount = _number(raw.get("f6"))
            flow = _number(raw.get("f62"))
            change = _number(raw.get("f3"))
            volume_ratio = _number(raw.get("f10"))
            turnover = _number(raw.get("f8"))
            activity_score = (
                math.log10(max(1.0, amount)) * 0.35
                + min(20.0, abs(change)) * 0.25
                + min(10.0, volume_ratio) * 0.20
                + min(30.0, turnover) * 0.05
                + math.log10(max(1.0, abs(flow))) * 0.15
            )
            name = str(raw.get("f14") or code)
            new_listing_reason = ""
            if re.match(r"^[NC](?:[A-Z]|[\u4e00-\u9fff])", name, re.IGNORECASE):
                new_listing_reason = "证券简称带 N/C 上市初期标识"
            elif abs(change) >= 40:
                new_listing_reason = "涨跌幅绝对值达到 40%，从核心流动性榜剔除"
            rows.append(
                {
                    "code": code,
                    "market": "SH" if str(raw.get("f13")) == "1" else "SZ",
                    "name": name,
                    "price": _number(raw.get("f2")),
                    "change_pct": change,
                    "amount": amount,
                    "volume": _number(raw.get("f5")),
                    "volume_ratio": volume_ratio,
                    "turnover_pct": turnover,
                    "main_net_inflow": flow,
                    "main_net_ratio": flow / amount * 100 if amount else 0.0,
                    "industry": str(raw.get("f100") or "未分类"),
                    "industry_code": str(raw.get("f102") or ""),
                    "concepts": str(raw.get("f103") or ""),
                    "primary_concept": next(
                        (item.strip() for item in re.split(r"[,;，；]", str(raw.get("f103") or "")) if item.strip()),
                        "未分类",
                    ),
                    "activity_score": round(activity_score, 4),
                    "data_time": _epoch_text(raw.get("f124")),
                    "is_new_listing": bool(new_listing_reason),
                    "new_listing_reason": new_listing_reason,
                }
            )
        return rows

    def sector(self, code: str, limit: int = 120, force: bool = False) -> dict[str, Any]:
        code = "".join(ch for ch in str(code).upper() if ch.isalnum())
        if not code.startswith("BK"):
            return {"ok": False, "error": "板块代码必须以 BK 开头", "stocks": []}
        cache_key = f"sector:{code}:{limit}"
        now = time.monotonic()
        cached = self._cache.get(cache_key)
        if not force and cached and now < cached[0]:
            return dict(cached[1], response_cached=True)
        with self._lock:
            cached = self._cache.get(cache_key)
            if not force and cached and time.monotonic() < cached[0]:
                return dict(cached[1], response_cached=True)
            try:
                raw_rows, source = self.provider.stocks(f"b:{code}", limit=limit)
                stocks = self._stock_rows(raw_rows)
                payload = {
                    "ok": True,
                    "generated_at": _iso_now(),
                    "code": code,
                    "source": source,
                    "field_units": {
                        "price": "人民币元/股",
                        "change_pct": "百分比",
                        "amount": "人民币元",
                        "volume": "手",
                        "volume_ratio": "倍",
                        "turnover_pct": "百分比",
                        "main_net_inflow": "人民币元",
                        "main_net_ratio": "百分比",
                        "activity_score": "启发式综合分，无量纲",
                    },
                    "stocks": stocks,
                    "queues": self._queues(stocks),
                    "response_cached": False,
                }
                self._cache[cache_key] = (time.monotonic() + self.ttl_seconds, payload)
                return payload
            except Exception as exc:  # noqa: BLE001
                fallback = self._stale_memory_cache(cache_key, exc)
                if fallback:
                    return fallback
                return {"ok": False, "generated_at": _iso_now(), "code": code, "error": str(exc), "stocks": []}

    @staticmethod
    def _queues(stocks: list[dict[str, Any]], limit: int = 12) -> dict[str, list[dict[str, Any]]]:
        liquid = [
            row for row in stocks
            if row["amount"] >= 50_000_000 and (abs(row["change_pct"]) >= 2.0 or row["volume_ratio"] >= 1.5)
        ]
        active = sorted(liquid, key=lambda row: row["activity_score"], reverse=True)[:limit]
        up = sorted(
            [row for row in stocks if row["amount"] >= 50_000_000 and row["volume_ratio"] >= 1.0 and row["change_pct"] >= 2.0],
            key=lambda row: (row["amount"] * max(0.2, row["volume_ratio"]) * row["change_pct"]),
            reverse=True,
        )[:limit]
        down = sorted(
            [row for row in stocks if row["amount"] >= 50_000_000 and row["volume_ratio"] >= 1.0 and row["change_pct"] <= -2.0],
            key=lambda row: (row["amount"] * max(0.2, row["volume_ratio"]) * abs(row["change_pct"])),
            reverse=True,
        )[:limit]
        return {"active": active, "surging": up, "falling": down}

    def liquidity_watch(self, limit: int = 120, force: bool = False) -> dict[str, Any]:
        cache_key = f"liquidity:{limit}"
        now = time.monotonic()
        cached = self._cache.get(cache_key)
        session_status = a_share_session_status(datetime.now())
        if isinstance(self.provider, EastmoneyHeatmapProvider) and cached and session_status in {"lunch_break", "closed"}:
            return dict(cached[1], response_cached=True, served_at=_iso_now(), session_status=session_status)
        if not force and cached and now < cached[0]:
            return dict(cached[1], response_cached=True)
        with self._lock:
            cached = self._cache.get(cache_key)
            if not force and cached and time.monotonic() < cached[0]:
                return dict(cached[1], response_cached=True)
            try:
                raw_rows, source = self.provider.stocks("m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23", limit=limit)
                parsed_stocks = self._stock_rows(raw_rows)
                excluded = [row for row in parsed_stocks if row.get("is_new_listing")]
                stocks = sorted(
                    [row for row in parsed_stocks if not row.get("is_new_listing")],
                    key=lambda row: row["activity_score"], reverse=True,
                )
                next_ranks: dict[str, int] = {}
                for rank, row in enumerate(stocks, start=1):
                    previous_rank = self._liquidity_ranks.get(row["code"])
                    row["rank"] = rank
                    row["previous_rank"] = previous_rank
                    row["rank_change"] = None if previous_rank is None else previous_rank - rank
                    row["entered_watch"] = previous_rank is None
                    next_ranks[row["code"]] = rank
                self._liquidity_ranks = next_ranks
                payload = {
                    "ok": True,
                    "generated_at": _iso_now(),
                    "source": source,
                    "field_units": {
                        "price": "人民币元/股",
                        "change_pct": "百分比",
                        "amount": "人民币元",
                        "volume": "手",
                        "volume_ratio": "倍",
                        "turnover_pct": "百分比",
                        "main_net_inflow": "人民币元",
                        "main_net_ratio": "百分比",
                        "activity_score": "启发式综合分，无量纲",
                    },
                    "stocks": stocks,
                    "queues": self._queues(stocks, limit=20),
                    "exclusion_policy": {
                        "rule": "证券简称带 N/C 上市初期标识，或涨跌幅绝对值达到40%，不进入核心流动性图、队列与排名",
                        "excluded_count": len(excluded),
                        "excluded": [
                            {
                                "code": row["code"],
                                "name": row["name"],
                                "change_pct": row["change_pct"],
                                "reason": row["new_listing_reason"],
                            }
                            for row in excluded[:30]
                        ],
                    },
                    "response_cached": False,
                }
                if self.history_store is not None:
                    payload["history_rows_inserted"] = self.history_store.record_stocks(payload)
                self._cache[cache_key] = (time.monotonic() + self.ttl_seconds, payload)
                return payload
            except Exception as exc:  # noqa: BLE001
                fallback = self._stale_memory_cache(cache_key, exc)
                if fallback:
                    return fallback
                return {"ok": False, "generated_at": _iso_now(), "error": str(exc), "stocks": [], "queues": {}}

    def _fund_flow_series(self, secid: str, force: bool = False) -> dict[str, Any]:
        cache_key = f"fflow:{secid}"
        now = time.monotonic()
        cached = self._cache.get(cache_key)
        if not force and cached and now < cached[0]:
            return dict(cached[1], response_cached=True)
        if not hasattr(self.provider, "fund_flow_timeline"):
            return {"ok": True, "secid": secid, "points": [], "source": {}, "response_cached": False}
        with self._flow_locks[cache_key]:
            cached = self._cache.get(cache_key)
            if not force and cached and time.monotonic() < cached[0]:
                return dict(cached[1], response_cached=True)
            try:
                points, source = self.provider.fund_flow_timeline(secid)
                payload = {
                    "ok": True,
                    "secid": secid,
                    "points": points,
                    "source": source,
                    "generated_at": _iso_now(),
                    "response_cached": False,
                }
                # The race chart requests the same small TOP set every three
                # seconds.  A per-symbol lock keeps requests single-flight;
                # six seconds limits upstream pressure while the UI still
                # receives a fresh frame every three seconds.
                self._cache[cache_key] = (time.monotonic() + max(3.0, self.ttl_seconds * 2.0), payload)
                return payload
            except Exception as exc:  # noqa: BLE001
                fallback = self._stale_memory_cache(cache_key, exc)
                if fallback:
                    return fallback
                return {"ok": False, "secid": secid, "points": [], "source": {}, "error": str(exc)}

    def _stock_intraday_series(self, secid: str, force: bool = False) -> dict[str, Any]:
        cache_key = f"stock-intraday:{secid}"
        now = time.monotonic()
        cached = self._cache.get(cache_key)
        if not force and cached and now < cached[0]:
            return dict(cached[1], response_cached=True)
        if not hasattr(self.provider, "stock_intraday"):
            return {"ok": True, "secid": secid, "points": [], "source": {}, "response_cached": False}
        with self._flow_locks[cache_key]:
            cached = self._cache.get(cache_key)
            if not force and cached and time.monotonic() < cached[0]:
                return dict(cached[1], response_cached=True)
            try:
                points, source = self.provider.stock_intraday(secid)
                payload = {
                    "ok": True,
                    "secid": secid,
                    "points": points,
                    "source": source,
                    "generated_at": _iso_now(),
                    "response_cached": False,
                }
                self._cache[cache_key] = (time.monotonic() + self.ttl_seconds, payload)
                return payload
            except Exception as exc:  # noqa: BLE001
                fallback = self._stale_memory_cache(cache_key, exc)
                if fallback:
                    return fallback
                return {"ok": False, "secid": secid, "points": [], "source": {}, "error": str(exc)}

    def _depth_quote(self, code: str, market: str, reference_price: float, force: bool = False) -> dict[str, Any]:
        cache_key = f"depth:{market}:{code}"
        cached = self._cache.get(cache_key)
        if not force and cached and time.monotonic() < cached[0]:
            return dict(cached[1], response_cached=True)
        with self._flow_locks[cache_key]:
            cached = self._cache.get(cache_key)
            if not force and cached and time.monotonic() < cached[0]:
                return dict(cached[1], response_cached=True)
            try:
                from quant_dashboard.history import _connect_tdx  # noqa: PLC2701

                with self._history_lock:
                    api, host = _connect_tdx(timeout=1.5)
                    if api is None:
                        raise RuntimeError("没有可连接的通达信行情主机")
                    raw_rows = api.get_security_quotes([(1 if market == "SH" else 0, code)])
                raw = (raw_rows or [{}])[0]
                raw_last = _number(raw.get("price") or raw.get("last_price"))
                ref = _number(reference_price)
                candidates = (0.01, 0.1, 1.0, 10.0, 100.0, 1000.0)
                scale = min(candidates, key=lambda item: abs(raw_last / item - ref)) if raw_last > 0 and ref > 0 else 1.0

                def price_value(key: str) -> float:
                    value = _number(raw.get(key))
                    return round(value / scale, 6) if value > 0 else 0.0

                asks = [
                    {"level": level, "price": price_value(f"ask{level}"), "volume_lots": _number(raw.get(f"ask_vol{level}"))}
                    for level in range(5, 0, -1)
                ]
                bids = [
                    {"level": level, "price": price_value(f"bid{level}"), "volume_lots": _number(raw.get(f"bid_vol{level}"))}
                    for level in range(1, 6)
                ]
                payload = {
                    "ok": bool(raw),
                    "code": code,
                    "market": market,
                    "last": price_value("price"),
                    "pre_close": price_value("last_close"),
                    "open": price_value("open"),
                    "high": price_value("high"),
                    "low": price_value("low"),
                    "asks": asks,
                    "bids": bids,
                    "server_time": str(raw.get("servertime") or ""),
                    "generated_at": _iso_now(),
                    "source": {
                        "provider": "通达信实时快照 / pytdx",
                        "endpoint": "get_security_quotes(市场,代码)",
                        "host": host,
                        "fields": "买一至买五、卖一至卖五价格与委托量；价格用东方财富最新价做数量级校准",
                        "limitation": "盘口只代表当前可获得快照，历史盘口不能由分钟行情回补",
                    },
                    "response_cached": False,
                }
                self._cache[cache_key] = (time.monotonic() + self.ttl_seconds, payload)
                return payload
            except Exception as exc:  # noqa: BLE001
                fallback = self._stale_memory_cache(cache_key, exc)
                if fallback:
                    return fallback
                return {"ok": False, "code": code, "market": market, "asks": [], "bids": [], "error": str(exc)}

    @staticmethod
    def _timeline_date(points: list[dict[str, Any]]) -> str:
        dates = [str(point.get("time") or "")[:10] for point in points if len(str(point.get("time") or "")) >= 10]
        return max(dates) if dates else ""

    @staticmethod
    def _parse_trade_date(value: str) -> date | None:
        try:
            return datetime.strptime(str(value or "")[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _recent_trade_dates(count: int = 30) -> list[str]:
        result: list[str] = []
        current = current_or_previous_trading_day()
        for _ in range(max(1, min(120, int(count)))):
            result.append(current.isoformat())
            current = previous_trading_day(current)
        return result

    def replay_manifest(self, board_type: str = "industry", trade_date: str = "") -> dict[str, Any]:
        """Expose locally archived replay frames and their factual gaps."""
        if self.history_store is None:
            return {
                "ok": False,
                "board_type": board_type,
                "trade_date": str(trade_date or "")[:10],
                "frames": [],
                "available_dates": [],
                "error": "8772本地连续历史库未启用，无法回放",
            }
        payload = self.history_store.replay_manifest(board_type, trade_date)
        payload["generated_at"] = _iso_now()
        payload["playback"] = {
            "speeds": [1, 2, 5],
            "unit": "每步推进一个本地已观察分钟帧",
            "default_speed": 1,
            "live_refresh_paused_during_replay": True,
        }
        return payload

    def replay_frame(
        self,
        board_type: str = "industry",
        trade_date: str = "",
        frame_time: str = "",
        selected_code: str = "",
        top_each: int = 5,
    ) -> dict[str, Any]:
        """Build all replay surfaces from one exact locally observed minute.

        Cross-sections are never carried forward.  The race trajectories are
        clipped at the frame time, and core-stock membership is returned only
        when it was actually retained in the historical stock row.
        """
        board_type = str(board_type or "industry").lower()
        manifest = self.replay_manifest(board_type, trade_date)
        if not manifest.get("ok"):
            return manifest
        selected_date = str(manifest.get("trade_date") or "")[:10]
        requested_label = str(frame_time or "")[-5:]
        frame_index = next(
            (
                index for index, item in enumerate(manifest.get("frames") or [])
                if str(item.get("label") or "") == requested_label
            ),
            -1,
        )
        if frame_index < 0:
            return {
                "ok": False,
                "board_type": board_type,
                "trade_date": selected_date,
                "frame_time": requested_label,
                "error": "所选分钟不是本地已保存回放帧；缺口不会插值",
            }
        frame_meta = manifest["frames"][frame_index]
        sectors, stocks = self.history_store.replay_frame_rows(
            board_type, selected_date, requested_label
        ) if self.history_store is not None else ([], [])
        if not sectors:
            return {
                "ok": False,
                "board_type": board_type,
                "trade_date": selected_date,
                "frame_time": requested_label,
                "frame": frame_meta,
                "coverage": manifest.get("coverage") or {},
                "error": "该分钟只有个股留档，没有板块横截面；未沿用上一帧",
            }

        if board_type == "concept":
            sectors = [
                row for row in sectors
                if str(row.get("name") or "").strip() not in CONCEPT_AGGREGATE_BOARD_NAMES
            ]
        inflow_all = sorted(
            [row for row in sectors if _number(row.get("main_net_inflow")) > 0],
            key=lambda row: _number(row.get("main_net_inflow")),
            reverse=True,
        )
        outflow_all = sorted(
            [row for row in sectors if _number(row.get("main_net_inflow")) < 0],
            key=lambda row: _number(row.get("main_net_inflow")),
        )
        safe_top = max(1, min(500, int(top_each or 5)))
        selected_race = [
            *[dict(row, race_direction="inflow") for row in inflow_all[:safe_top]],
            *[dict(row, race_direction="outflow") for row in outflow_all[:safe_top]],
        ]
        history_date, grouped = self.history_store.sector_points_bulk(
            board_type,
            [row["code"] for row in selected_race],
            selected_date,
            limit_per_code=360,
        ) if self.history_store is not None else (selected_date, {})
        race_series = []
        for row in selected_race:
            points = [
                {
                    "time": point.get("data_time"),
                    "flow": _number(point.get("flow")),
                    "change_pct": _number(point.get("change_pct")),
                    "amount": _number(point.get("amount")),
                    "resolution": "1m-local-observed-replay",
                }
                for point in (grouped.get(row["code"]) or [])
                if str(point.get("data_time") or "")[11:16] <= requested_label
            ]
            race_series.append(
                {
                    "code": row["code"],
                    "name": row["name"],
                    "direction": row["race_direction"],
                    "snapshot_flow": row["main_net_inflow"],
                    "snapshot_change_pct": row["change_pct"],
                    "points": points,
                    "latest_flow": _number(points[-1].get("flow")) if points else 0.0,
                    "component_count": 0,
                    "components": [],
                    "error": "" if points else "该板块在当前回放时间前没有本地分钟轨迹",
                }
            )

        chosen_sector = next((row for row in sectors if row.get("code") == selected_code), None)
        if chosen_sector is None:
            chosen_sector = inflow_all[0] if inflow_all else (sectors[0] if sectors else None)
        chosen_code = str((chosen_sector or {}).get("code") or "")
        chosen_name = str((chosen_sector or {}).get("name") or "")

        def belongs_to_selected(row: dict[str, Any]) -> bool:
            if not chosen_name:
                return False
            if board_type == "industry":
                return str(row.get("industry") or "").strip() == chosen_name
            concepts = {
                item.strip()
                for item in re.split(r"[,;，；]", str(row.get("concepts") or ""))
                if item.strip()
            }
            return chosen_name in concepts or str(row.get("primary_concept") or "").strip() == chosen_name

        core_stocks = sorted(
            [row for row in stocks if belongs_to_selected(row)],
            key=lambda row: _number(row.get("amount")),
            reverse=True,
        )
        stocks = sorted(stocks, key=lambda row: _number(row.get("activity_score")), reverse=True)
        for rank, row in enumerate(stocks, start=1):
            row["rank"] = rank
            row["previous_rank"] = None
            row["rank_change"] = None
            row["entered_watch"] = False

        axis_payload = self.session_axis(selected_date)
        labels = (axis_payload.get("session_axis") or {}).get("labels") or []
        elapsed_slots = labels.index(requested_label) + 1 if requested_label in labels else 0
        replay_progress = {
            "status": "historical_replay",
            "as_of": f"{selected_date}T{requested_label}:00",
            "elapsed_slots": elapsed_slots,
            "remaining_slots": max(0, len(labels) - elapsed_slots),
            "total_slots": len(labels),
            "last_elapsed_index": elapsed_slots - 1,
            "last_elapsed_label": requested_label,
            "blank_from_index": elapsed_slots,
            "completion_ratio": round(elapsed_slots / len(labels), 6) if labels else 0.0,
            "is_complete": elapsed_slots == len(labels),
        }
        local_source = {
            "provider": "8772本地SQLite真实分钟留档",
            "host": str(self.history_store.path) if self.history_store is not None else "",
            "possibly_delayed": False,
            "contract": "精确读取所选分钟，不前向填充、不插值；缺口直接报告。",
        }
        coverage = dict(manifest.get("coverage") or {})
        coverage.update(
            {
                "frame": frame_meta,
                "core_stock_membership_available": bool(core_stocks),
                "core_stock_limitation": (
                    "按本分钟留档的行业/概念字段筛选全市场流动性样本；只覆盖当时进入本地TOP采集池的股票。"
                    if core_stocks else
                    "该帧没有可核验的板块成员分类留档，核心个股留空；不会用当前成分冒充历史成分。"
                ),
            }
        )
        snapshot = {
            "ok": True,
            "generated_at": _iso_now(),
            "data_time": f"{selected_date}T{requested_label}:00",
            "board_type": board_type,
            "refresh_interval_ms": int(self.ttl_seconds * 1000),
            "mode": "historical_replay",
            "stale": False,
            "source": local_source,
            "status_message": f"历史回放 {selected_date} {requested_label}；仅展示本地真实留档帧。",
            "sectors": sectors,
            "response_cached": False,
        }
        race = {
            "ok": bool(race_series),
            "generated_at": _iso_now(),
            "board_type": board_type,
            "trade_date": selected_date,
            "top_each": safe_top,
            "data_mode": "local_observed_replay",
            "series": race_series,
            "populated_series": sum(bool(item["points"]) for item in race_series),
            "available_dates": [str(row.get("trade_date") or "") for row in manifest.get("available_dates") or []],
            "selection_basis": f"{selected_date} {requested_label} 本地精确横截面",
            "source_disclosure": {
                "title": "8772本地f62历史帧回放",
                "provider": local_source["provider"],
                "endpoint": "market_heatmap_intraday.sqlite3 / sector_intraday",
                "fields": "data_time、f62主力净流入、涨跌幅、成交额",
                "method": f"按{requested_label}精确横截面选择每侧TOP{safe_top}，曲线仅截取到当前回放帧",
                "limitation": coverage.get("contract") or "本地未采集分钟不可恢复",
            },
            "selection": {
                "inflow": [{"code": row["code"], "name": row["name"], "flow": row["main_net_inflow"]} for row in inflow_all[:safe_top]],
                "outflow": [{"code": row["code"], "name": row["name"], "flow": row["main_net_inflow"]} for row in outflow_all[:safe_top]],
            },
            "session_axis": axis_payload.get("session_axis") or {},
            "session_progress": replay_progress,
        }
        liquidity = {
            "ok": bool(stocks),
            "generated_at": _iso_now(),
            "source": local_source,
            "stocks": stocks,
            "queues": self._queues(stocks, limit=20),
            "exclusion_policy": {
                "rule": "历史回放只使用当时已进入本地流动性采集池且已通过新股/极端涨幅过滤的样本",
                "excluded_count": 0,
                "excluded": [],
            },
        }
        core_payload = {
            "ok": bool(core_stocks),
            "generated_at": _iso_now(),
            "code": chosen_code,
            "source": local_source,
            "stocks": core_stocks,
            "queues": self._queues(core_stocks),
            "historical_membership": True,
            "coverage_message": coverage["core_stock_limitation"],
        }
        sparklines = [
            {
                "code": item["code"],
                "name": item["name"],
                "points": item["points"],
                "last": item["latest_flow"],
            }
            for item in race_series
        ]
        return {
            "ok": True,
            "generated_at": _iso_now(),
            "board_type": board_type,
            "trade_date": selected_date,
            "frame_time": requested_label,
            "frame_index": frame_index,
            "frame_count": len(manifest.get("frames") or []),
            "frame": frame_meta,
            "coverage": coverage,
            "snapshot": snapshot,
            "race": race,
            "liquidity": liquidity,
            "core_stocks": core_payload,
            "selected_code": chosen_code,
            "sparklines": sparklines,
            "session_axis": axis_payload.get("session_axis") or {},
            "session_progress": replay_progress,
        }

    def _history_bars(self, code: str, market: str, trade_date: str) -> dict[str, Any]:
        parsed_date = self._parse_trade_date(trade_date)
        if parsed_date is None:
            return {"ok": False, "bars": [], "error": "历史交易日格式无效"}
        market = str(market or "SH").upper()
        symbol = f"{code}.{market}"
        cache_key = f"tdx-history:{symbol}:{parsed_date.isoformat()}"
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() < cached[0]:
            return dict(cached[1], response_cached=True)
        with self._history_lock:
            cached = self._cache.get(cache_key)
            if cached and time.monotonic() < cached[0]:
                return dict(cached[1], response_cached=True)
            try:
                fetcher = self.historical_bar_fetcher
                if fetcher is None:
                    from quant_dashboard.history import fetch_history_minute_time_bars

                    fetcher = fetch_history_minute_time_bars
                bars = [dict(row) for row in (fetcher(symbol, parsed_date) or [])]
                payload = {
                    "ok": bool(bars),
                    "symbol": symbol,
                    "trade_date": parsed_date.isoformat(),
                    "bars": bars,
                    "source": {
                        "provider": "通达信行情协议 / pytdx",
                        "endpoint": f"get_history_minute_time_data({market},{code},{parsed_date.strftime('%Y%m%d')})",
                        "fields": "每分钟价格 price、成交量 vol；成交额=price×vol×100（A股每手100股）",
                        "resolution": "1分钟，正常完整交易日240行",
                        "contract": "历史分时接口；不是逐笔主动买卖，也不直接提供主力净流入",
                    },
                    "error": "" if bars else "TDX 历史分时返回空；可能为休市日、代码当时未上市或行情服务器暂不可用",
                    "response_cached": False,
                }
            except Exception as exc:  # noqa: BLE001
                payload = {
                    "ok": False,
                    "symbol": symbol,
                    "trade_date": parsed_date.isoformat(),
                    "bars": [],
                    "source": {"provider": "通达信行情协议 / pytdx", "endpoint": "get_history_minute_time_data"},
                    "error": str(exc),
                    "response_cached": False,
                }
            ttl = 86400.0 if parsed_date < datetime.now().date() else 20.0
            self._cache[cache_key] = (time.monotonic() + ttl, payload)
            return payload

    @staticmethod
    def _direction_proxy_points(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Allocate minute amount by price direction; never label this as native main flow."""
        points: list[dict[str, Any]] = []
        cumulative_flow = 0.0
        cumulative_amount = 0.0
        previous_price = 0.0
        for row in bars:
            price = _number(row.get("close") or row.get("price"))
            amount = max(0.0, _number(row.get("amount")))
            direction = 0
            if previous_price > 0 and price > previous_price:
                direction = 1
            elif previous_price > 0 and price < previous_price:
                direction = -1
            signed_amount = amount * direction
            cumulative_flow += signed_amount
            cumulative_amount += amount
            points.append(
                {
                    "time": str(row.get("time") or ""),
                    "flow": cumulative_flow,
                    "signed_amount": signed_amount,
                    "amount": amount,
                    "cumulative_amount": cumulative_amount,
                    "price": price,
                    "volume": _number(row.get("volume")),
                    "direction": direction,
                    "resolution": "1m",
                }
            )
            if price > 0:
                previous_price = price
        return points

    @staticmethod
    def _merge_flow_and_bars(
        flow_points: list[dict[str, Any]], bars: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        by_minute = {str(row.get("time") or "")[:16]: row for row in bars}
        cumulative_amount = 0.0
        merged: list[dict[str, Any]] = []
        for point in flow_points:
            row = by_minute.get(str(point.get("time") or "")[:16]) or {}
            amount = max(0.0, _number(row.get("amount")))
            cumulative_amount += amount
            merged.append(
                {
                    **point,
                    "price": _number(row.get("close") or row.get("price")),
                    "volume": _number(row.get("volume")),
                    "amount": amount,
                    "cumulative_amount": cumulative_amount,
                }
            )
        return merged

    def _sector_history_proxy(self, code: str, trade_date: str) -> dict[str, Any]:
        cache_key = f"sector-history-proxy:{code}:{trade_date}"
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() < cached[0]:
            return dict(cached[1], response_cached=True)
        detail = self.sector(code, limit=20, force=False)
        constituents = [
            row for row in (detail.get("stocks") or [])
            if not row.get("is_new_listing") and row.get("code") and row.get("market")
        ][:3]
        fetched: list[tuple[dict[str, Any], dict[str, Any]]] = []
        with ThreadPoolExecutor(max_workers=min(4, max(1, len(constituents)))) as pool:
            futures = {
                pool.submit(self._history_bars, row["code"], row["market"], trade_date): row
                for row in constituents
            }
            for future in as_completed(futures):
                result = future.result()
                if result.get("bars"):
                    fetched.append((futures[future], result))
        aggregate: dict[str, dict[str, Any]] = {}
        for _row, result in fetched:
            for point in self._direction_proxy_points(result.get("bars") or []):
                key = str(point.get("time") or "")[:16]
                bucket = aggregate.setdefault(
                    key,
                    {"time": str(point.get("time") or ""), "signed_amount": 0.0, "amount": 0.0},
                )
                bucket["signed_amount"] += _number(point.get("signed_amount"))
                bucket["amount"] += _number(point.get("amount"))
        cumulative_flow = 0.0
        cumulative_amount = 0.0
        points: list[dict[str, Any]] = []
        for key in sorted(aggregate):
            bucket = aggregate[key]
            cumulative_flow += bucket["signed_amount"]
            cumulative_amount += bucket["amount"]
            points.append(
                {
                    "time": bucket["time"],
                    "flow": cumulative_flow,
                    "signed_amount": bucket["signed_amount"],
                    "amount": bucket["amount"],
                    "cumulative_amount": cumulative_amount,
                    "resolution": "1m",
                }
            )
        payload = {
            "ok": bool(points),
            "points": points,
            "component_count": len(fetched),
            "components": [f"{row['name']} {row['code']}.{row['market']}" for row, _ in fetched],
            "source": {
                "provider": "通达信历史分时 + 当前板块核心成分聚合",
                "endpoint": "pytdx get_history_minute_time_data",
                "fields": "成分股每分钟价格、成交量；分钟成交额=价格×成交量；方向=本分钟价格相对上分钟上涨/下跌",
                "method": "选取当前板块成交额靠前且成功返回历史数据的最多3只成分股；各股分钟成交额按价格方向赋正负后求和并累计",
                "contract": "板块历史资金方向代理，不是东方财富原生f62主力净流；存在当前成分回看偏差和样本覆盖偏差",
            },
            "error": "" if points else "没有成分股返回该交易日的TDX历史分时",
            "response_cached": False,
        }
        self._cache[cache_key] = (time.monotonic() + 86400.0, payload)
        return payload

    def sector_race(
        self,
        board_type: str = "industry",
        top_each: int = 5,
        trade_date: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        board_type = str(board_type or "industry").lower()
        if board_type not in {"industry", "concept"}:
            return {"ok": False, "error": "board_type 仅支持 industry 或 concept", "series": []}
        requested_top = int(top_each)
        all_requested = requested_top <= 0
        top_each = 500 if all_requested else max(1, min(500, requested_top))
        requested_date = str(trade_date or "")[:10]
        cache_key = f"sector-race:{board_type}:{requested_date or 'latest'}:{'all' if all_requested else top_each}"
        cached = self._cache.get(cache_key)
        if not force and cached and time.monotonic() < cached[0]:
            cached_payload = dict(cached[1], response_cached=True)
            cached_payload.update(self._session_fields(str(cached_payload.get("trade_date") or requested_date)))
            return cached_payload

        snapshot = self.snapshot(board_type=board_type, force=force)
        if not snapshot.get("ok"):
            return {"ok": False, "error": snapshot.get("error") or "板块快照不可用", "series": []}
        snapshot_date = str(snapshot.get("data_time") or "")[:10]
        selected_date = requested_date or snapshot_date
        rows = list(snapshot.get("sectors") or [])
        selection_basis = "当前板块快照"
        if requested_date and requested_date != snapshot_date and self.history_store is not None:
            historical_rows = self.history_store.latest_sector_rows(board_type, selected_date)
            if historical_rows:
                rows = historical_rows
                selection_basis = f"8772本地连续库 {selected_date} 每个板块最后有效快照"
        excluded_aggregate_names: list[str] = []
        if board_type == "concept":
            excluded_aggregate_names = sorted(
                {
                    str(row.get("name") or "").strip()
                    for row in rows
                    if str(row.get("name") or "").strip() in CONCEPT_AGGREGATE_BOARD_NAMES
                }
            )
            rows = [
                row
                for row in rows
                if str(row.get("name") or "").strip() not in CONCEPT_AGGREGATE_BOARD_NAMES
            ]
        all_inflow = sorted(
            [row for row in rows if _number(row.get("main_net_inflow")) > 0],
            key=lambda row: _number(row.get("main_net_inflow")),
            reverse=True,
        )
        all_outflow = sorted(
            [row for row in rows if _number(row.get("main_net_inflow")) < 0],
            key=lambda row: _number(row.get("main_net_inflow")),
        )
        inflow = all_inflow if all_requested else all_inflow[:top_each]
        outflow = all_outflow if all_requested else all_outflow[:top_each]
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for direction, group in (("inflow", inflow), ("outflow", outflow)):
            for row in group:
                if row["code"] in seen:
                    continue
                seen.add(row["code"])
                selected.append({**row, "race_direction": direction})

        def build_native(row: dict[str, Any]) -> dict[str, Any]:
            native = self._fund_flow_series(f"90.{row['code']}", force=force)
            points = [
                dict(point)
                for point in (native.get("points") or [])
                if str(point.get("time") or "")[:10] == selected_date
            ]
            return {"row": row, "points": points, "source": native.get("source") or {}, "component_count": 0}

        def build_historical(row: dict[str, Any]) -> dict[str, Any]:
            proxy = self._sector_history_proxy(row["code"], selected_date)
            return {
                "row": row,
                "points": list(proxy.get("points") or []),
                "source": proxy.get("source") or {},
                "component_count": int(proxy.get("component_count") or 0),
                "components": proxy.get("components") or [],
                "error": proxy.get("error") or "",
            }

        local_date = ""
        local_points: dict[str, list[dict[str, Any]]] = {}
        if self.history_store is not None and selected:
            local_date, local_points = self.history_store.sector_points_bulk(
                board_type,
                [row["code"] for row in selected],
                selected_date,
                limit_per_code=360,
            )
        local_coverage = sum(bool(local_points.get(row["code"])) for row in selected)
        # Keep the smallest/default race on the supplier's dedicated minute
        # endpoint.  Larger modes use one local SQLite query instead of N
        # upstream requests every three seconds.
        use_native = bool(selected_date and selected_date == snapshot_date and not all_requested and top_each <= 5)
        use_local_archive = bool(local_coverage and not use_native)
        proxy_truncated = False
        if not use_native and not use_local_archive and (len(inflow) > 20 or len(outflow) > 20):
            proxy_truncated = True
            inflow = inflow[:20]
            outflow = outflow[:20]
            selected = []
            seen.clear()
            for direction, group in (("inflow", inflow), ("outflow", outflow)):
                for row in group:
                    if row["code"] not in seen:
                        seen.add(row["code"])
                        selected.append({**row, "race_direction": direction})
        builders: list[dict[str, Any]] = []
        if use_native:
            with ThreadPoolExecutor(max_workers=min(6, max(1, len(selected)))) as pool:
                futures = {pool.submit(build_native, row): row for row in selected}
                for future in as_completed(futures):
                    builders.append(future.result())
        elif use_local_archive:
            for row in selected:
                points = [
                    {
                        "time": point.get("data_time"),
                        "flow": _number(point.get("flow")),
                        "change_pct": _number(point.get("change_pct")),
                        "amount": _number(point.get("amount")),
                        "resolution": "1m-local-observed",
                    }
                    for point in (local_points.get(row["code"]) or [])
                    if MarketHeatmapHistoryStore._in_trading_session(str(point.get("data_time") or ""))
                ]
                if len(selected) > 100 and len(points) > 60:
                    step = (len(points) - 1) / 59
                    points = [points[round(index * step)] for index in range(60)]
                builders.append({"row": row, "points": points, "source": {}, "component_count": 0})
        else:
            # Historical requests are cached for a day.  Keep sector builds
            # sequential so TDX hosts are not flooded by nested component calls.
            builders = [build_historical(row) for row in selected]

        by_code = {item["row"]["code"]: item for item in builders}
        series: list[dict[str, Any]] = []
        for row in selected:
            item = by_code.get(row["code"]) or {"points": [], "source": {}}
            points = item.get("points") or []
            series.append(
                {
                    "code": row["code"],
                    "name": row["name"],
                    "direction": row["race_direction"],
                    "snapshot_flow": row["main_net_inflow"],
                    "snapshot_change_pct": row["change_pct"],
                    "points": points,
                    "latest_flow": _number(points[-1].get("flow")) if points else 0.0,
                    "component_count": item.get("component_count") or 0,
                    "components": item.get("components") or [],
                    "error": item.get("error") or "",
                }
            )
        populated = [item for item in series if item["points"]]
        top_label = "全部" if all_requested else str(top_each)
        aggregate_limitation = (
            "；概念赛马已排除全市场资格/指数聚合板块：" + "、".join(excluded_aggregate_names)
            if excluded_aggregate_names
            else ""
        )
        if use_native:
            disclosure = {
                "title": "东方财富板块原生分钟主力资金（多板块同图）",
                "provider": "东方财富公开分钟资金流接口",
                "endpoint": "/api/qt/stock/fflow/kline/get，secid=90.BKxxxx，klt=1",
                "fields": "f51分钟；f52主力净流入累计值；f53-f56小/中/大/超大单累计净流入",
                "method": f"按{selection_basis}的f62选净流入TOP{top_label}与净流出TOP{top_label}，每个板块直接绘制供应商分钟累计主力净流",
                "limitation": "供应商估算口径，不是交易所逐账户现金流；公开接口无稳定SLA" + aggregate_limitation,
            }
            data_mode = "native_main_flow"
        elif use_local_archive:
            disclosure = {
                "title": "东方财富f62本地分钟观察轨迹（多板块同图）",
                "provider": "东方财富板块快照 + 8772本地SQLite分钟留档",
                "endpoint": "/api/qt/clist/get 的 f62/f124 → sector_intraday",
                "fields": "f124行情时间；f62供应商估算主力净流入；每代码每分钟保留一个交易时段有效帧",
                "method": f"按{selection_basis}选净流入TOP{top_label}与净流出TOP{top_label}，一次批量查询{local_date or selected_date}的本地f62分钟观察值；11:30与13:00之间不补造数据，图上压缩午休",
                "limitation": "这是本机实际观察到的f62分钟快照，不是专用fflow接口的f52序列；服务未运行或上游失败的分钟无法事后补齐" + ("；全部模式为控制传输和渲染量，每条线等距保留最多60点" if len(selected) > 100 else "") + aggregate_limitation,
            }
            data_mode = "local_observed_f62"
        else:
            disclosure = {
                "title": "历史板块成交资金方向代理（多板块同图）",
                "provider": "通达信历史分时 / pytdx",
                "endpoint": "get_history_minute_time_data(市场,代码,YYYYMMDD)",
                "fields": "当前板块最多3只核心成分股的每分钟价格、成交量；成交额=价格×成交量",
                "method": f"按{selection_basis}选净流入TOP{top_label}与净流出TOP{top_label}；成分股分钟价格上涨记正、下跌记负、平盘记0，再对带符号成交额求和累计",
                "limitation": "这是历史成交方向代理，不是原生主力净流；若本地库没有该日板块快照会退回当前强弱榜，且成分仍存在当前成分回看偏差与最多3只覆盖偏差" + ("；代理模式为保护上游最多返回每侧20条" if proxy_truncated else "") + aggregate_limitation,
            }
            data_mode = "historical_direction_proxy"
        payload = {
            "ok": bool(populated),
            "generated_at": _iso_now(),
            "board_type": board_type,
            "trade_date": selected_date,
            "top_each": 0 if all_requested else top_each,
            "requested_limit": "all" if all_requested else top_each,
            "total_inflow_available": len(all_inflow),
            "total_outflow_available": len(all_outflow),
            "effective_inflow_count": len(inflow),
            "effective_outflow_count": len(outflow),
            "truncated": proxy_truncated,
            "data_mode": data_mode,
            "series": series,
            "populated_series": len(populated),
            "available_dates": self._recent_trade_dates(30),
            "selection_basis": selection_basis,
            "excluded_aggregate_names": excluded_aggregate_names,
            "source_disclosure": disclosure,
            "selection": {
                "inflow": [{"code": row["code"], "name": row["name"], "flow": row["main_net_inflow"]} for row in inflow],
                "outflow": [{"code": row["code"], "name": row["name"], "flow": row["main_net_inflow"]} for row in outflow],
            },
            "error": "" if populated else "所选交易日没有可绘制的板块分钟数据",
            "response_cached": False,
            **self._session_fields(selected_date),
        }
        ttl = self.ttl_seconds if use_native else (12.0 if selected_date == snapshot_date else 86400.0)
        self._cache[cache_key] = (time.monotonic() + ttl, payload)
        return payload

    def sector_sparklines(
        self,
        board_type: str = "industry",
        codes: list[str] | None = None,
        trade_date: str = "",
        max_points: int = 48,
    ) -> dict[str, Any]:
        board_type = str(board_type or "industry").lower()
        if board_type not in {"industry", "concept"}:
            return {"ok": False, "error": "board_type 仅支持 industry 或 concept", "series": []}
        clean_codes = list(dict.fromkeys(str(code or "").upper() for code in (codes or []) if str(code or "").upper().startswith("BK")))[:1000]
        if not clean_codes:
            return {"ok": True, "board_type": board_type, "trade_date": trade_date[:10], "series": []}
        selected_date = str(trade_date or "")[:10]
        grouped: dict[str, list[dict[str, Any]]] = {}
        if self.history_store is not None:
            selected_date, grouped = self.history_store.sector_points_bulk(
                board_type,
                clean_codes,
                selected_date,
                limit_per_code=360,
            )
        names = {
            row.get("code"): row.get("name")
            for row in ((self._cache.get(board_type) or (0, {}))[1].get("sectors") or [])
        }

        def compact(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
            valid = [point for point in points if MarketHeatmapHistoryStore._in_trading_session(str(point.get("data_time") or point.get("time") or ""))]
            limit = max(12, min(120, int(max_points)))
            if len(valid) <= limit:
                sampled = valid
            else:
                step = (len(valid) - 1) / (limit - 1)
                sampled = [valid[round(index * step)] for index in range(limit)]
            return [
                {
                    "time": point.get("data_time") or point.get("time"),
                    "flow": _number(point.get("flow")),
                }
                for point in sampled
            ]

        series = []
        for code in clean_codes:
            points = compact(grouped.get(code) or list(self._timeline.get(code) or []))
            series.append(
                {
                    "code": code,
                    "name": names.get(code) or (points[-1].get("name") if points else code),
                    "points": points,
                    "last": _number(points[-1].get("flow")) if points else 0.0,
                }
            )
        return {
            "ok": True,
            "generated_at": _iso_now(),
            "board_type": board_type,
            "trade_date": selected_date,
            "source_mode": "local_observed_f62",
            "resolution": "每分钟最多一个有效帧；返回端等距抽样",
            "series": series,
            "source": {
                "provider": "东方财富板块快照 + 8772本地SQLite分钟留档",
                "endpoint": "sector_intraday 批量查询",
                "fields": "data_time、main_net_inflow(f62)",
                "limitation": "只包含本机实际运行期间观测到的交易时段分钟，不补造午休与缺失分钟",
            },
            **self._session_fields(selected_date),
        }

    def timeline(self, code: str, limit: int = 600, trade_date: str = "", force: bool = False) -> dict[str, Any]:
        code = str(code).upper().strip()
        try:
            safe_limit = max(1, min(20000, int(limit)))
        except (TypeError, ValueError):
            safe_limit = 600
        selected_date = trade_date[:10]
        realtime_points: list[dict[str, Any]] = []
        if self.history_store is not None:
            selected_date, realtime_points = self.history_store.sector_points(code, selected_date, safe_limit)
        else:
            with self._lock:
                realtime_points = list(self._timeline.get(code) or [])[-safe_limit:]
            if not selected_date:
                selected_date = self._timeline_date(realtime_points)
        minute_payload = self._fund_flow_series(f"90.{code}", force=force)
        minute_points = list(minute_payload.get("points") or [])
        if not selected_date:
            selected_date = self._timeline_date(minute_points)
        minute_points = [point for point in minute_points if str(point.get("time") or "")[:10] == selected_date]
        realtime_points = [point for point in realtime_points if str(point.get("data_time") or point.get("time") or "")[:10] == selected_date]
        legacy_points = [
            {
                "time": point.get("data_time") or point.get("time"),
                "flow": point.get("flow", 0),
                "delta_flow": point.get("delta_flow", 0),
                "change_pct": point.get("change_pct", 0),
            }
            for point in realtime_points
        ]
        if not legacy_points:
            legacy_points = minute_points
        return {
            "ok": True,
            "code": code,
            "trade_date": selected_date,
            "minute_points": minute_points,
            "realtime_points": realtime_points,
            "points": legacy_points[-safe_limit:],
            "minute_source": minute_payload.get("source") or {},
            "realtime_source": {
                "provider": "本地8772连续采集SQLite",
                "path": str(self.history_store.path) if self.history_store is not None else "内存",
                "resolution": "盘中3秒取数；每个代码每分钟仅保留一个有效帧",
                "row_count": len(realtime_points),
            },
            "generated_at": _iso_now(),
            **self._session_fields(selected_date),
        }

    def stock_timeline(
        self,
        code: str,
        market: str = "SH",
        limit: int = 10000,
        trade_date: str = "",
        force: bool = False,
        include_auction: bool = False,
    ) -> dict[str, Any]:
        code = "".join(ch for ch in str(code) if ch.isdigit())[:6]
        market = str(market or "SH").upper()
        if len(code) != 6 or market not in {"SH", "SZ"}:
            return {"ok": False, "error": "个股代码或市场无效", "code": code, "market": market}
        safe_limit = max(1, min(20000, int(limit)))
        requested_date = trade_date[:10]
        selected_date = requested_date
        realtime_points: list[dict[str, Any]] = []
        if self.history_store is not None:
            selected_date, realtime_points = self.history_store.stock_points(code, selected_date, safe_limit)
        secid = f"{1 if market == 'SH' else 0}.{code}"
        minute_payload = self._fund_flow_series(secid, force=force)
        minute_points = list(minute_payload.get("points") or [])
        price_payload: dict[str, Any] = {"points": [], "source": {}}
        raw_price_points: list[dict[str, Any]] = []
        price_points: list[dict[str, Any]] = []
        history_payload: dict[str, Any] = {"bars": [], "source": {}}
        if requested_date:
            history_payload = self._history_bars(code, market, requested_date)
            raw_price_points = [
                {
                    "time": bar.get("time"),
                    "open": _number(bar.get("open"), _number(bar.get("close"))),
                    "high": _number(bar.get("high"), _number(bar.get("close"))),
                    "low": _number(bar.get("low"), _number(bar.get("close"))),
                    "close": _number(bar.get("close")),
                    "average": _number(bar.get("average")),
                    "volume": _number(bar.get("volume")),
                    "amount": _number(bar.get("amount")),
                    "resolution": "1m-history",
                }
                for bar in (history_payload.get("bars") or [])
            ]
        else:
            price_payload = self._stock_intraday_series(secid, force=force)
            raw_price_points = list(price_payload.get("points") or [])
        if not selected_date:
            selected_date = self._timeline_date(raw_price_points) or self._timeline_date(minute_points)
        minute_points = [point for point in minute_points if str(point.get("time") or "")[:10] == selected_date]
        auction_candidates = [
            point
            for point in raw_price_points
            if str(point.get("time") or "")[:10] == selected_date
            and "09:15" <= str(point.get("time") or "")[11:16] < "09:30"
        ]
        price_points = [
            point for point in raw_price_points
            if str(point.get("time") or "")[:10] == selected_date
            and MarketHeatmapHistoryStore._in_trading_session(str(point.get("time") or ""))
        ]
        realtime_points = [point for point in realtime_points if str(point.get("data_time") or "")[:10] == selected_date]
        data_mode = "native_main_flow" if minute_points else "local_only"
        source_disclosure = {
            "title": "东方财富原生分钟主力资金",
            "provider": (minute_payload.get("source") or {}).get("provider") or "东方财富公开分钟资金流接口",
            "endpoint": (minute_payload.get("source") or {}).get("endpoint") or "/api/qt/stock/fflow/kline/get",
            "method": "直接展示供应商分钟累计主力净流；不是交易所逐账户现金流",
            "limitation": "公开接口无稳定SLA",
        }
        if requested_date and selected_date:
            bars = list(history_payload.get("bars") or [])
            if minute_points:
                minute_points = self._merge_flow_and_bars(minute_points, bars)
            elif bars:
                minute_points = self._direction_proxy_points(bars)
                data_mode = "historical_direction_proxy"
                source = history_payload.get("source") or {}
                source_disclosure = {
                    "title": "历史个股成交资金方向代理",
                    "provider": source.get("provider") or "通达信行情协议 / pytdx",
                    "endpoint": source.get("endpoint") or "get_history_minute_time_data",
                    "method": "分钟价格较上分钟上涨记正、下跌记负、平盘记0；带符号成交额累计",
                    "limitation": "不是逐笔主动买卖，也不是原生主力净流",
                }
        reference_price = _number(price_points[-1].get("close")) if price_points else _number((realtime_points[-1] if realtime_points else {}).get("price"))
        order_book = (
            self._depth_quote(code, market, reference_price, force=force)
            if not requested_date and isinstance(self.provider, EastmoneyHeatmapProvider)
            else {
                "ok": False,
                "code": code,
                "market": market,
                "asks": [],
                "bids": [],
                "historical_unavailable": bool(requested_date),
                "error": "历史五档盘口无法由分钟行情事后回补" if requested_date else "测试/替代数据源未提供五档盘口",
            }
        )
        price_source = (history_payload.get("source") or {}) if requested_date else (price_payload.get("source") or {})
        if requested_date:
            auction_available = False
            auction_reason = "当前历史分钟源不提供可核验的集合竞价价格轨迹；未模拟"
        elif auction_candidates:
            auction_available = True
            auction_reason = "东方财富 trends2/get 在 iscr=1 下返回真实09:15-09:29观察值"
        else:
            auction_available = False
            auction_reason = "上游本次响应未返回09:15-09:29观察值；未模拟"
        auction_points = auction_candidates if include_auction and auction_available else []
        return {
            "ok": True,
            "code": code,
            "market": market,
            "trade_date": selected_date,
            "minute_points": minute_points,
            "price_points": price_points,
            "auction_points": auction_points,
            "auction": {
                "requested": bool(include_auction),
                "available": auction_available,
                "reason": auction_reason,
                "point_count": len(auction_candidates),
                "displayed_point_count": len(auction_points),
                "source": {
                    "provider": "东方财富公开分时价格接口" if auction_available else "",
                    "endpoint": "/api/qt/stock/trends2/get?iscr=1" if auction_available else "",
                    "contract": "仅透传接口实际返回的集合竞价观察值；不根据开盘价插值或回填",
                },
            },
            "realtime_points": realtime_points,
            "minute_source": (history_payload.get("source") or {}) if data_mode == "historical_direction_proxy" else minute_payload.get("source") or {},
            "data_mode": data_mode,
            "source_disclosure": source_disclosure,
            "price_source": price_source,
            "price_volume_contract": {
                "unit": "股" if requested_date else "手",
                "share_multiplier": 1 if requested_date else 100,
                "display": (
                    "TDX历史分钟源的vol已在本地适配器中按100股/手换算为股"
                    if requested_date else
                    "东方财富trends2/get f56按手返回；页面同时按普通A股100股/手显示约合股数"
                ),
                "limitation": "约合股数是普通A股手数换算；特殊证券的每手规则应以交易所合约为准",
            },
            "order_book": order_book,
            "session_contract": {
                "call_auction": "09:15-09:29（可选，仅真实接口可得时显示）",
                "morning": "09:30-11:30",
                "afternoon": "13:00-15:00",
                "market_close": "15:00",
                "chart_axis": "完整交易分钟骨架；11:30与13:00视觉相邻，尚未发生的分钟留白，不补午休或15:00以后数据",
            },
            "available_dates": self._recent_trade_dates(30),
            "realtime_source": {
                "provider": "本地8772连续采集SQLite",
                "path": str(self.history_store.path) if self.history_store is not None else "",
                "resolution": "盘中3秒取数；每个代码每分钟仅保留一个有效帧",
                "row_count": len(realtime_points),
            },
            "generated_at": _iso_now(),
            **self._session_fields(selected_date, include_auction=include_auction),
        }

    def update_collector_state(self, **changes: Any) -> None:
        with self._lock:
            self._collector_state.update(changes)

    def source_catalog(self) -> dict[str, Any]:
        history = self.history_store.stats() if self.history_store is not None else {}
        return {
            "ok": True,
            "generated_at": _iso_now(),
            "collector": dict(self._collector_state),
            "history": history,
            "sources": [
                {
                    "surface": "行业/概念热力图与双榜",
                    "provider": "东方财富公开行情页接口",
                    "endpoint": "/api/qt/clist/get",
                    "host_policy": "优先 push2.eastmoney.com，失败降级 push2delay.eastmoney.com",
                    "query": "行业 fs=m:90+t:2；概念 fs=m:90+t:3；按100条分页读取全量",
                    "fields": "f6成交额、f62估算主力净流入、f184净流占比、f104/f105涨跌家数、f124数据时间",
                    "cadence": "盘中行业目标3秒；概念后台15秒，页面选中时3秒",
                    "contract": "非官方稳定契约，无SLA；必须校验时间戳和延迟域",
                },
                {
                    "surface": "板块成分与核心个股热力图",
                    "provider": "东方财富公开行情页接口",
                    "endpoint": "/api/qt/clist/get",
                    "host_policy": "同上",
                    "query": "fs=b:BKxxxx，按成交额获取板块成分",
                    "fields": "f2价格、f3涨跌幅、f6成交额、f8换手、f10量比、f62估算主力净流入、f100行业、f103概念列表、f124数据时间",
                    "cadence": "当前选中板块目标3秒",
                    "contract": "非官方稳定契约",
                },
                {
                    "surface": "全天分钟资金流",
                    "provider": "东方财富公开分钟资金流接口",
                    "endpoint": "/api/qt/stock/fflow/kline/get",
                    "host_policy": "优先push2，失败使用push2delay",
                    "query": "板块 secid=90.BKxxxx；沪股 secid=1.xxxxxx；深股 secid=0.xxxxxx；klt=1",
                    "fields": "f51分钟、f52主力、f53小单、f54中单、f55大单、f56超大单净流入累计值",
                    "cadence": "页面3秒取帧；单板块上游分钟流最多缓存6秒；返回数量以供应商实际分钟行数为准",
                    "contract": "供应商估算口径，不是交易所逐账户现金流",
                },
                {
                    "surface": "多板块资金赛马与历史回看",
                    "provider": "TOP5用东方财富原生分钟资金流；更大范围优先用本地f62分钟观察；无本地历史时才用TDX方向代理",
                    "endpoint": "/api/market_heatmap/sector_race 与 /sector_sparklines；上游 fflow/kline/get、clist/get、pytdx",
                    "host_policy": "TOP10/20/全部不逐板块轰炸上游，统一批量读SQLite；各模式不混淆命名",
                    "query": "每侧TOP5/TOP10/TOP20/全部；trade_date=YYYY-MM-DD；迷你分时按代码批量查询",
                    "fields": "原生f51/f52；本地f124/f62；历史代理分钟价格/成交量/带符号成交额累计",
                    "cadence": "横截面3秒；本地大范围曲线最多12秒重绘；历史日按日缓存",
                    "contract": "本地f62只代表本机实际观察分钟；历史成交方向代理不是原生主力净流",
                },
                {
                    "surface": "全页面历史分钟回放",
                    "provider": "8772本地SQLite真实分钟留档",
                    "endpoint": "/api/market_heatmap/replay_manifest + /replay_frame",
                    "host_policy": "只读 market_heatmap_intraday.sqlite3，不为缺失日或分钟访问外部接口补造截面",
                    "query": "board_type、trade_date、frame_time、selected_code、top_each",
                    "fields": "sector_intraday精确分钟横截面；stock_intraday精确分钟流动性样本与采集时分类；板块轨迹截断到当前帧",
                    "cadence": "播放1×/2×/5×；每步推进一个本地已观察分钟，回放期间暂停3秒实时刷新",
                    "contract": "缺口、旧库缺少分类、未进入当时采集池的股票均明确披露；不插值、不前向填充、不用当前成分冒充历史成分",
                },
                {
                    "surface": "个股仿真分时与五档盘口",
                    "provider": "东方财富分钟价格/成交量 + 东方财富分钟资金流 + 通达信实时盘口",
                    "endpoint": "trends2/get + fflow/kline/get + pytdx get_security_quotes",
                    "host_policy": "分钟数据优先东方财富延迟/主域可用节点；盘口由TDX可用主机路由",
                    "query": "沪股secid=1.xxxxxx、深股secid=0.xxxxxx；trends2使用iscr=1探测集合竞价；盘口市场号沪1深0",
                    "fields": "价格/均价/OHLC/分钟量/分钟额；iscr=1真实返回时另列09:15-09:29竞价观察；f52-f56资金；买卖五档价格与委托量",
                    "cadence": "选中标的随页面3秒刷新；交互期间继续取数但延迟重绘",
                    "contract": "盘口只表示当前快照，历史盘口不可事后回补；集合竞价只透传上游真实行、不可得即标记available=false；公开资金是供应商估算",
                },
                {
                    "surface": "交易分钟骨架与进度留白",
                    "provider": "A股交易时段规则 + 本地当前时间",
                    "endpoint": "/api/market_heatmap/session_axis",
                    "host_policy": "本地计算，不请求上游行情",
                    "query": "trade_date=YYYY-MM-DD；include_auction=0/1",
                    "fields": "session_axis完整标签、session_progress已发生槽位/留白起点；午休压缩",
                    "cadence": "每次请求按Asia/Shanghai当前时间重算",
                    "contract": "连续交易09:30-11:30、13:00-15:00；收盘固定15:00，不延长到15:30；骨架不代表真实行情点",
                },
                {
                    "surface": "本地连续分钟轨迹（3秒取数）",
                    "provider": "8772后台采集器 + SQLite WAL",
                    "endpoint": "/api/market_heatmap/timeline 与 /stock_timeline",
                    "host_policy": "本机127.0.0.1",
                    "query": str(self.history_store.path) if self.history_store is not None else "未启用",
                    "fields": "数据时间、价格/指数、涨跌、成交额、f62、相邻增量、排名",
                    "cadence": "交易日09:30-11:30、13:00-15:00每3秒取数；每代码每分钟只保存一个有效帧；保留14个自然日",
                    "contract": "存储层拒绝午休/盘前/盘后冻结帧；图上压缩午休但不补造行情点",
                },
                {
                    "surface": "同花顺核验",
                    "provider": "同花顺行业/概念资金流公开页面",
                    "endpoint": "data.10jqka.com.cn/funds/hyzjl/ 与 /funds/gnzjl/",
                    "host_policy": "仅人工/抽样核验，不绕过反爬和签名",
                    "query": "行业指数、涨跌、流入、流出、净额、公司家数、领涨股",
                    "fields": "不进入当前3秒主链",
                    "cadence": "盘中抽样与盘后核对",
                    "contract": "未取得稳定开放API授权前不自动高频抓取",
                },
            ],
            "exclusions": {
                "new_listing": "证券简称带N/C上市初期标识，或涨跌幅绝对值达到40%，从全市场核心流动性图、队列和排名剔除",
                "overlap": "行业多层级与概念成分重叠，板块f62不可横向求和当作全市场现金净流入",
                "concept_aggregate": "概念赛马排除融资融券、沪股通、深股通、MSCI中国、富时罗素、标普道琼斯A股等全市场资格/指数聚合桶",
            },
        }

    def health(self) -> dict[str, Any]:
        cached_types = sorted(key for key in self._cache if key in {"industry", "concept"})
        return {
            "ok": True,
            "generated_at": _iso_now(),
            "service": "市场流动性雷达",
            "refresh_interval_ms": int(self.ttl_seconds * 1000),
            "cached_board_types": cached_types,
            "timeline_symbols": len(self._timeline),
            "collector": dict(self._collector_state),
            "history": self.history_store.stats() if self.history_store is not None else {},
            "policy": "独立 8772 服务；不修改 8771 采集进程；上游失败时保留旧快照并标记 stale。",
        }


def create_service(data_dir: Path | str | None = None) -> MarketHeatmapService:
    """Build one isolated service instance for the selected local data directory."""
    root = Path(data_dir or DATA_DIR).expanduser().resolve()
    return MarketHeatmapService(
        history_store=MarketHeatmapHistoryStore(root / "market_heatmap" / "market_heatmap_intraday.sqlite3"),
        cache_dir=root / "market_heatmap",
    )
