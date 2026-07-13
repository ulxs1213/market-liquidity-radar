"""Standalone HTTP/API server for the market-liquidity dashboard."""

from __future__ import annotations

import json
import mimetypes
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


WEB_ROOT = Path(__file__).resolve().parent / "web"
STATIC_ROOT = WEB_ROOT / "static"
REQUIRED_ASSETS = (
    WEB_ROOT / "index.html",
    STATIC_ROOT / "market_heatmap.css",
    STATIC_ROOT / "market_heatmap.js",
    STATIC_ROOT / "echarts.min.js",
)


def validate_web_assets() -> None:
    missing = [str(path) for path in REQUIRED_ASSETS if not path.is_file()]
    if missing:
        raise OSError("缺少静态资源：" + ", ".join(missing))


def _int(value: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def _collector(service: Any, stop: threading.Event) -> None:
    from quant_dashboard.trading_calendar import a_share_session_status, trading_day_reason

    cycle = 0
    last_purge_date = ""
    while not stop.is_set():
        now = datetime.now()
        session = a_share_session_status(now)
        if session not in {"auction", "open"}:
            service.update_collector_state(
                status=session,
                status_label={"lunch_break": "午间休市等待", "closed": "非交易时段等待"}.get(session, "等待交易窗口"),
                last_checked_at=now.isoformat(timespec="seconds"),
                trading_day_reason=trading_day_reason(now),
                next_cycle_in_sec=10,
            )
            stop.wait(10)
            continue
        started = time.monotonic()
        cycle += 1
        try:
            industry = service.snapshot("industry", force=False)
            concept = service.snapshot("concept", force=False) if cycle == 1 or cycle % 5 == 0 else None
            liquidity = service.liquidity_watch(limit=500, force=False)
            if last_purge_date != now.date().isoformat() and service.history_store is not None:
                service.history_store.purge()
                last_purge_date = now.date().isoformat()
            service.update_collector_state(
                status="running",
                status_label="盘中连续采集中",
                last_checked_at=now.isoformat(timespec="seconds"),
                last_cycle_at=datetime.now().isoformat(timespec="seconds"),
                last_error="",
                cycle_count=cycle,
                industry_ok=bool(industry.get("ok")),
                concept_ok=None if concept is None else bool(concept.get("ok")),
                liquidity_ok=bool(liquidity.get("ok")),
                elapsed_ms=round((time.monotonic() - started) * 1000, 2),
                next_cycle_in_sec=3,
            )
        except Exception as exc:  # noqa: BLE001
            service.update_collector_state(
                status="degraded",
                status_label="连续采集降级",
                last_checked_at=now.isoformat(timespec="seconds"),
                last_error=str(exc),
                cycle_count=cycle,
                next_cycle_in_sec=3,
            )
        stop.wait(max(0.2, 3.0 - (time.monotonic() - started)))


def _handler(service: Any, data_dir: Path) -> type[BaseHTTPRequestHandler]:
    class RadarHandler(BaseHTTPRequestHandler):
        server_version = "MarketLiquidityRadar/1.0"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            try:
                if path in {"/", "/market-heatmap", "/market-liquidity-radar"}:
                    self._file(WEB_ROOT / "index.html", "text/html; charset=utf-8")
                elif path.startswith("/static/"):
                    target = STATIC_ROOT / Path(path).name
                    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                    self._file(target, content_type)
                elif path in {"/api/health", "/api/market_heatmap/health"}:
                    payload = service.health()
                    payload["data_dir"] = str(data_dir)
                    self._json(payload)
                elif path == "/api/market_heatmap/snapshot":
                    board_type = (query.get("board_type") or ["industry"])[0]
                    force = (query.get("refresh") or ["0"])[0] == "1"
                    payload = service.snapshot(board_type=board_type, force=force)
                    self._json(payload, 200 if payload.get("ok") else 400)
                elif path == "/api/market_heatmap/sector":
                    code = (query.get("code") or [""])[0]
                    limit = _int((query.get("limit") or ["120"])[0], 120, 10, 500)
                    force = (query.get("refresh") or ["0"])[0] == "1"
                    payload = service.sector(code=code, limit=limit, force=force)
                    self._json(payload, 200 if payload.get("ok") else 400)
                elif path == "/api/market_heatmap/liquidity_watch":
                    limit = _int((query.get("limit") or ["160"])[0], 160, 20, 500)
                    force = (query.get("refresh") or ["0"])[0] == "1"
                    self._json(service.liquidity_watch(limit=limit, force=force))
                elif path == "/api/market_heatmap/session_axis":
                    trade_date = (query.get("trade_date") or [""])[0]
                    include_auction = (query.get("include_auction") or ["0"])[0].lower() in {"1", "true", "yes", "on"}
                    payload = service.session_axis(trade_date=trade_date, include_auction=include_auction)
                    self._json(payload, 200 if payload.get("ok") else 400)
                elif path == "/api/market_heatmap/replay_manifest":
                    board_type = (query.get("board_type") or ["industry"])[0]
                    trade_date = (query.get("trade_date") or [""])[0]
                    payload = service.replay_manifest(board_type=board_type, trade_date=trade_date)
                    self._json(payload, 200 if payload.get("ok") else 404)
                elif path == "/api/market_heatmap/replay_frame":
                    board_type = (query.get("board_type") or ["industry"])[0]
                    trade_date = (query.get("trade_date") or [""])[0]
                    frame_time = (query.get("frame_time") or [""])[0]
                    selected_code = (query.get("selected_code") or [""])[0]
                    top_each = _int((query.get("top_each") or ["5"])[0], 5, 1, 500)
                    payload = service.replay_frame(
                        board_type=board_type,
                        trade_date=trade_date,
                        frame_time=frame_time,
                        selected_code=selected_code,
                        top_each=top_each,
                    )
                    self._json(payload, 200 if payload.get("ok") else 404)
                elif path == "/api/market_heatmap/timeline":
                    code = (query.get("code") or [""])[0]
                    limit = _int((query.get("limit") or ["10000"])[0], 10000, 1, 20000)
                    trade_date = (query.get("trade_date") or [""])[0]
                    force = (query.get("refresh") or ["0"])[0] == "1"
                    self._json(service.timeline(code=code, limit=limit, trade_date=trade_date, force=force))
                elif path == "/api/market_heatmap/sector_race":
                    board_type = (query.get("board_type") or ["industry"])[0]
                    top_raw = (query.get("top_each") or ["5"])[0]
                    top_each = 0 if str(top_raw).lower() in {"0", "all", "全部"} else _int(top_raw, 5, 1, 500)
                    trade_date = (query.get("trade_date") or [""])[0]
                    force = (query.get("refresh") or ["0"])[0] == "1"
                    payload = service.sector_race(board_type=board_type, top_each=top_each, trade_date=trade_date, force=force)
                    self._json(payload, 200 if payload.get("ok") else 400)
                elif path == "/api/market_heatmap/sector_sparklines":
                    board_type = (query.get("board_type") or ["industry"])[0]
                    codes = [item for item in (query.get("codes") or [""])[0].split(",") if item]
                    trade_date = (query.get("trade_date") or [""])[0]
                    max_points = _int((query.get("max_points") or ["48"])[0], 48, 12, 120)
                    payload = service.sector_sparklines(board_type=board_type, codes=codes, trade_date=trade_date, max_points=max_points)
                    self._json(payload, 200 if payload.get("ok") else 400)
                elif path == "/api/market_heatmap/stock_timeline":
                    code = (query.get("code") or [""])[0]
                    market = (query.get("market") or ["SH"])[0]
                    limit = _int((query.get("limit") or ["10000"])[0], 10000, 1, 20000)
                    trade_date = (query.get("trade_date") or [""])[0]
                    force = (query.get("refresh") or ["0"])[0] == "1"
                    include_auction = (query.get("include_auction") or ["0"])[0].lower() in {"1", "true", "yes", "on"}
                    payload = service.stock_timeline(code=code, market=market, limit=limit, trade_date=trade_date, force=force, include_auction=include_auction)
                    self._json(payload, 200 if payload.get("ok") else 400)
                elif path == "/api/market_heatmap/sources":
                    self._json(service.source_catalog())
                else:
                    self._json({"ok": False, "error": "not_found", "path": path}, 404)
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc), "path": path}, 500)

        def _file(self, path: Path, content_type: str) -> None:
            try:
                payload = path.read_bytes()
            except OSError:
                self._json({"ok": False, "error": "asset_unavailable"}, 500)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(payload)

        def _json(self, payload: dict[str, Any], status: int = 200) -> None:
            raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: object) -> None:
            sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), format % args))

    return RadarHandler


class RadarHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], service: Any, start_collector: bool) -> None:
        super().__init__(address, handler)
        self.service = service
        self.collector_stop = threading.Event()
        self.collector_thread: threading.Thread | None = None
        if start_collector:
            self.collector_thread = threading.Thread(target=_collector, args=(service, self.collector_stop), name="market-liquidity-collector", daemon=True)
            self.collector_thread.start()

    def server_close(self) -> None:
        self.collector_stop.set()
        super().server_close()
        if self.collector_thread and self.collector_thread is not threading.current_thread():
            self.collector_thread.join(timeout=2)


def create_server(host: str, port: int, data_dir: Path, *, start_collector: bool = False) -> RadarHTTPServer:
    validate_web_assets()
    data_dir = data_dir.expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    from quant_dashboard.market_heatmap import create_service

    service = create_service(data_dir)
    return RadarHTTPServer((host, port), _handler(service, data_dir), service, start_collector)
