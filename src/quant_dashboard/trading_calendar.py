from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("MLR_DATA_DIR", str(ROOT / "data"))).expanduser().resolve()
CALENDAR_PATH = DATA_DIR / "calendar" / "ashare_trading_calendar.json"
SSE_CLOSED_URL = "https://www.sse.com.cn/disclosure/dealinstruc/closed/"
SSE_CLOSED_LIST_URL = "https://www.sse.com.cn/disclosure/dealinstruc/closed/list/"

AUCTION_START = time(9, 15)
AUCTION_END = time(9, 25)
MORNING_START = time(9, 30)
MORNING_END = time(11, 30)
AFTERNOON_START = time(13, 0)
AFTERNOON_END = time(15, 0)

BUILTIN_CLOSED_DATES = {
    "2026-06-19": "端午节休市",
}


def _date_key(value: date | datetime | str | None = None) -> str:
    if value is None:
        return date.today().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()[:10]


@lru_cache(maxsize=1)
def load_ashare_calendar() -> dict[str, Any]:
    data: dict[str, Any] = {"closed_dates": {}, "open_dates": {}}
    if CALENDAR_PATH.exists():
        try:
            loaded = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update(loaded)
        except Exception:
            pass
    closed = dict(BUILTIN_CLOSED_DATES)
    closed.update(data.get("closed_dates") or {})
    data["closed_dates"] = closed
    data.setdefault("open_dates", {})
    return data


def trading_day_reason(value: date | datetime | str | None = None) -> str:
    key = _date_key(value)
    data = load_ashare_calendar()
    if key in data.get("open_dates", {}):
        return str(data["open_dates"][key] or "交易所特别交易日")
    if key in data.get("closed_dates", {}):
        return str(data["closed_dates"][key] or "交易所休市")
    dt = datetime.strptime(key, "%Y-%m-%d").date()
    if dt.weekday() >= 5:
        return "周末休市"
    return "普通交易日"


def is_trading_day(value: date | datetime | str | None = None) -> bool:
    key = _date_key(value)
    data = load_ashare_calendar()
    if key in data.get("open_dates", {}):
        return True
    if key in data.get("closed_dates", {}):
        return False
    dt = datetime.strptime(key, "%Y-%m-%d").date()
    return dt.weekday() < 5


def previous_trading_day(value: date | datetime | str | None = None, include_self: bool = False) -> date:
    key = _date_key(value)
    cur = datetime.strptime(key, "%Y-%m-%d").date()
    if not include_self:
        cur -= timedelta(days=1)
    for _ in range(3700):
        if is_trading_day(cur):
            return cur
        cur -= timedelta(days=1)
    raise RuntimeError("无法在本地交易日历中找到上一交易日")


def current_or_previous_trading_day(now: datetime | None = None, session_start: time = AUCTION_START) -> date:
    now = now or datetime.now()
    today = now.date()
    if is_trading_day(today) and now.time() >= session_start:
        return today
    return previous_trading_day(today, include_self=False)


def a_share_session_status(now: datetime | None = None) -> str:
    now = now or datetime.now()
    if not is_trading_day(now.date()):
        return "closed"
    t = now.time()
    if AUCTION_START <= t <= AUCTION_END:
        return "auction"
    if MORNING_START <= t <= MORNING_END:
        return "open"
    if AFTERNOON_START <= t <= AFTERNOON_END:
        return "open"
    if MORNING_END < t < AFTERNOON_START:
        return "lunch_break"
    return "closed"


def _date_range(start: date, end: date) -> list[date]:
    days: list[date] = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur += timedelta(days=1)
    return days


def _month_name(year: int, month: int) -> str:
    return f"{year}年{month:02d}月"


def _read_url_text(url: str, timeout: float = 8.0) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "istock-trading-calendar/1.0",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(512 * 1024)
    return raw.decode("utf-8", "replace")


def _read_url_text_retry(url: str, *, attempts: int = 2, timeout: float = 8.0) -> str:
    last_exc: Exception | None = None
    for _ in range(max(1, attempts)):
        try:
            return _read_url_text(url, timeout=timeout)
        except Exception as exc:
            last_exc = exc
    if last_exc:
        raise last_exc
    raise RuntimeError("读取官方交易日历页面失败")


def _extract_sse_annual_closed_dates(html: str, fallback_year: int | None = None) -> tuple[dict[str, str], dict[str, Any]]:
    plain = re.sub(r"<[^>]+>", "\n", html)
    plain = re.sub(r"\s+", "", plain)
    year_match = re.search(r"(\d{4})年(?:部分节假日)?休市安排", plain)
    if not year_match:
        year_match = re.search(r"(\d{4})年.*?休市安排", plain)
    year = int(year_match.group(1)) if year_match else int(fallback_year or datetime.now().year)
    closed: dict[str, str] = {}
    holiday_names = "元旦|春节|清明节|劳动节|端午节|中秋节|国庆节|国庆节、中秋节|中秋节、国庆节"
    for match in re.finditer(rf"({holiday_names})：([^。；;]+?休市)", plain):
        name, body = match.groups()
        range_match = re.search(
            r"(?:20\d{2}年)?(\d{1,2})月(\d{1,2})日(?:（[^）]*）)?至(?:(?:20\d{2}年)?(\d{1,2})月)?(\d{1,2})日(?:（[^）]*）)?",
            body,
        )
        if range_match:
            start_month, start_day, end_month, end_day = range_match.groups()
        else:
            single_match = re.search(r"(?:20\d{2}年)?(\d{1,2})月(\d{1,2})日", body)
            if not single_match:
                continue
            start_month, start_day = single_match.groups()
            end_month, end_day = start_month, start_day
        sm = int(start_month)
        sd = int(start_day)
        em = int(end_month or start_month)
        ed = int(end_day)
        start = date(year, sm, sd)
        end = date(year, em, ed)
        for day in _date_range(start, end):
            closed[day.isoformat()] = f"{name}休市"
    return closed, {"year": year, "closed_count": len(closed)}


def _sse_list_urls(max_pages: int = 40) -> list[str]:
    urls = [f"{SSE_CLOSED_LIST_URL}s_list.shtml"]
    urls.extend(f"{SSE_CLOSED_LIST_URL}s_list_{idx}.shtml" for idx in range(2, max_pages + 1))
    return urls


def _extract_sse_notice_links(html: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for href, title_html in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, flags=re.S):
        title = re.sub(r"<[^>]+>", "", title_html)
        title = re.sub(r"\s+", "", title)
        if "休市安排" not in title:
            continue
        if "部分节假日休市安排" not in title and "全年休市安排" not in title:
            continue
        year_match = re.search(r"(20\d{2})年", title)
        if not year_match:
            continue
        url = href if href.startswith("http") else f"https://www.sse.com.cn{href}"
        links.append({"year": year_match.group(1), "title": title, "url": url})
    return links


def _fetch_sse_historical_closed_dates(*, lookback_years: int = 20) -> tuple[dict[str, str], dict[str, Any]]:
    start_year = datetime.now().year - lookback_years + 1
    current_year = datetime.now().year
    closed: dict[str, str] = {}
    links_by_year: dict[str, dict[str, str]] = {}
    page_errors: list[str] = []
    recent_required = {str(year) for year in range(max(start_year, current_year - 4), current_year + 1)}
    for _ in range(3):
        links_by_year = {}
        page_errors = []
        for url in _sse_list_urls():
            try:
                html = _read_url_text_retry(url, attempts=2, timeout=5.0)
            except Exception as exc:
                page_errors.append(f"{url}: {str(exc)[:120]}")
                if len(page_errors) >= 8 and links_by_year:
                    break
                continue
            for link in _extract_sse_notice_links(html):
                if int(link["year"]) >= start_year:
                    links_by_year.setdefault(link["year"], link)
            if links_by_year and min(int(year) for year in links_by_year) <= start_year:
                break
        if recent_required.issubset(set(links_by_year)):
            break
    article_errors: list[str] = []
    parsed_years: list[int] = []
    for year, link in sorted(links_by_year.items()):
        try:
            html = _read_url_text_retry(link["url"], attempts=3, timeout=6.0)
            parsed_closed, meta = _extract_sse_annual_closed_dates(html, fallback_year=int(year))
            if parsed_closed:
                closed.update(parsed_closed)
                parsed_years.append(int(year))
        except Exception as exc:
            article_errors.append(f"{year}: {str(exc)[:120]}")
    meta = {
        "name": "上海证券交易所休市安排历史公告",
        "url": SSE_CLOSED_LIST_URL,
        "ok": bool(parsed_years),
        "lookback_years": lookback_years,
        "parsed_years": parsed_years,
        "missing_years": [year for year in range(start_year, datetime.now().year + 1) if year not in parsed_years],
        "closed_count": len(closed),
        "page_errors": page_errors[-5:],
        "article_errors": article_errors[-5:],
    }
    return closed, meta


def _better_calendar_source(existing: dict[str, Any] | None, new_source: dict[str, Any]) -> dict[str, Any]:
    if not existing:
        return new_source
    old_years = set(existing.get("parsed_years") or [])
    new_years = set(new_source.get("parsed_years") or [])
    if old_years and len(old_years) > len(new_years):
        preserved = dict(existing)
        preserved["last_refresh_warning"] = "本次刷新解析年份少于本地已保存口径，已保留上次更完整的官方来源状态。"
        preserved["last_refresh_attempt"] = {
            "parsed_years": sorted(new_years),
            "missing_years": new_source.get("missing_years") or [],
            "closed_count": new_source.get("closed_count"),
        }
        return preserved
    return new_source


def refresh_ashare_calendar_from_official() -> dict[str, Any]:
    """Refresh A-share holiday overrides from official exchange pages.

    The base rule remains deterministic: weekends are closed and normal
    weekdays are trading days. Official pages only maintain holiday overrides
    and special arrangements.
    """
    data = load_ashare_calendar()
    sources: list[dict[str, Any]] = []
    previous_sources = {
        str(source.get("name")): source
        for source in data.get("sources", [])
        if isinstance(source, dict) and source.get("name")
    }
    closed = dict(data.get("closed_dates") or {})
    historical_closed, historical_meta = _fetch_sse_historical_closed_dates(lookback_years=20)
    closed.update(historical_closed)
    sources.append(_better_calendar_source(previous_sources.get(historical_meta["name"]), historical_meta))
    try:
        html = _read_url_text_retry(SSE_CLOSED_URL, attempts=3)
        parsed_closed, meta = _extract_sse_annual_closed_dates(html)
        closed.update(parsed_closed)
        sources.append({
            "name": "上海证券交易所年度休市安排",
            "url": SSE_CLOSED_URL,
            "ok": True,
            **meta,
        })
    except Exception as exc:
        sources.append({
            "name": "上海证券交易所年度休市安排",
            "url": SSE_CLOSED_URL,
            "ok": False,
            "error": str(exc)[:240],
        })
    data.update({
        "market": "A股",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "说明": "本地交易日历覆盖表。周末默认休市，普通工作日默认交易；closed_dates/open_dates 使用交易所公告覆盖默认规则。",
        "closed_dates": dict(sorted(closed.items())),
        "open_dates": data.get("open_dates") or {},
        "tracking": {
            "lookback_years": 20,
            "base_rule": "周末休市、普通工作日交易，交易所公告覆盖。",
            "primary_source": SSE_CLOSED_URL,
            "source_list": SSE_CLOSED_LIST_URL,
            "deepseek_fallback": "未启用。官方交易所页面可解析时不调用 DeepSeek/搜索兜底。",
        },
        "sources": sources,
    })
    CALENDAR_PATH.parent.mkdir(parents=True, exist_ok=True)
    CALENDAR_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    load_ashare_calendar.cache_clear()
    return trading_calendar_snapshot()


def next_trading_days(start: date | None = None, count: int = 20) -> list[str]:
    out: list[str] = []
    cur = start or date.today()
    while len(out) < count:
        if is_trading_day(cur):
            out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def calendar_months(start: date | None = None, months: int = 4) -> list[dict[str, Any]]:
    start = start or date.today().replace(day=1)
    months_out: list[dict[str, Any]] = []
    year, month = start.year, start.month
    today_key = date.today().isoformat()
    trade_day = current_or_previous_trading_day(datetime.now(), session_start=AUCTION_START).isoformat()
    for _ in range(max(1, months)):
        first = date(year, month, 1)
        next_month = date(year + (month // 12), 1 if month == 12 else month + 1, 1)
        last = next_month - timedelta(days=1)
        pad_start = first - timedelta(days=first.weekday())
        pad_end = last + timedelta(days=(6 - last.weekday()))
        days = []
        for day in _date_range(pad_start, pad_end):
            key = day.isoformat()
            in_month = day.month == month
            trading = is_trading_day(day)
            days.append({
                "date": key,
                "day": day.day,
                "in_month": in_month,
                "trading": trading,
                "reason": trading_day_reason(day),
                "is_today": key == today_key,
                "is_effective_trade_day": key == trade_day,
            })
        months_out.append({
            "year": year,
            "month": month,
            "label": _month_name(year, month),
            "days": days,
        })
        year, month = next_month.year, next_month.month
    return months_out


def trading_calendar_snapshot(months: int = 5, lookback_years: int = 20) -> dict[str, Any]:
    data = load_ashare_calendar()
    now = datetime.now()
    today = now.date()
    current_trade_day = current_or_previous_trading_day(now, session_start=AUCTION_START)
    closed_dates = data.get("closed_dates") or {}
    open_dates = data.get("open_dates") or {}
    future_closed = [
        {"date": key, "reason": str(reason)}
        for key, reason in sorted(closed_dates.items())
        if key >= today.isoformat()
    ][:30]
    start_year = today.year - lookback_years + 1
    end_year = today.year
    return {
        "ok": True,
        "generated_at": now.isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "session": a_share_session_status(now),
        "today_is_trading_day": is_trading_day(today),
        "today_reason": trading_day_reason(today),
        "current_or_previous_trading_day": current_trade_day.isoformat(),
        "next_trading_days": next_trading_days(today, 20),
        "months": calendar_months(today.replace(day=1), months),
        "future_closed_dates": future_closed,
        "coverage": {
            "start_year": start_year,
            "end_year": end_year,
            "lookback_years": lookback_years,
            "closed_override_count": len(closed_dates),
            "open_override_count": len(open_dates),
            "rule": "周末默认休市，普通工作日默认交易，交易所公告覆盖。",
        },
        "calendar_path": str(CALENDAR_PATH),
        "updated_at": data.get("updated_at", ""),
        "sources": data.get("sources", []),
        "tracking": data.get("tracking", {}),
    }
