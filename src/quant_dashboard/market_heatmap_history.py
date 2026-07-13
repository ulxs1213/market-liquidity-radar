from __future__ import annotations

import sqlite3
import threading
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("MLR_DATA_DIR", str(ROOT / "data"))).expanduser().resolve()
DEFAULT_DB_PATH = DATA_DIR / "market_heatmap" / "market_heatmap_intraday.sqlite3"


class MarketHeatmapHistoryStore:
    """Bounded SQLite history for the radar's locally observed intraday frames."""

    def __init__(self, path: Path | str = DEFAULT_DB_PATH, retention_days: int = 14) -> None:
        self.path = Path(path)
        self.retention_days = max(3, int(retention_days))
        self._lock = threading.RLock()
        self._last_sector_bucket: dict[str, str] = {}
        self._last_stock_bucket = ""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._purge_off_session_rows()
        self._load_last_buckets()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    def _init_db(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sector_intraday (
                    trade_date TEXT NOT NULL,
                    board_type TEXT NOT NULL,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    data_time TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    price REAL NOT NULL,
                    change_pct REAL NOT NULL,
                    amount REAL NOT NULL,
                    main_net_inflow REAL NOT NULL,
                    main_net_ratio REAL NOT NULL,
                    delta_flow REAL NOT NULL,
                    breadth REAL NOT NULL,
                    strength_score REAL NOT NULL,
                    rise_count INTEGER NOT NULL DEFAULT 0,
                    fall_count INTEGER NOT NULL DEFAULT 0,
                    source_host TEXT NOT NULL,
                    possibly_delayed INTEGER NOT NULL,
                    PRIMARY KEY (board_type, code, data_time)
                );
                CREATE INDEX IF NOT EXISTS idx_sector_intraday_lookup
                    ON sector_intraday(code, trade_date, data_time);

                CREATE TABLE IF NOT EXISTS stock_intraday (
                    trade_date TEXT NOT NULL,
                    code TEXT NOT NULL,
                    market TEXT NOT NULL,
                    name TEXT NOT NULL,
                    data_time TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    price REAL NOT NULL,
                    change_pct REAL NOT NULL,
                    amount REAL NOT NULL,
                    main_net_inflow REAL NOT NULL,
                    main_net_ratio REAL NOT NULL,
                    volume_ratio REAL NOT NULL,
                    turnover_pct REAL NOT NULL,
                    activity_score REAL NOT NULL,
                    rank_no INTEGER NOT NULL,
                    volume REAL NOT NULL DEFAULT 0,
                    industry TEXT NOT NULL DEFAULT '',
                    industry_code TEXT NOT NULL DEFAULT '',
                    concepts TEXT NOT NULL DEFAULT '',
                    primary_concept TEXT NOT NULL DEFAULT '',
                    source_host TEXT NOT NULL,
                    possibly_delayed INTEGER NOT NULL,
                    PRIMARY KEY (code, data_time)
                );
                CREATE INDEX IF NOT EXISTS idx_stock_intraday_lookup
                    ON stock_intraday(code, trade_date, data_time);
                """
            )
            # Older 8772 files did not retain replay classification fields.
            # Migrate in place; old rows remain blank/zero and the replay
            # coverage contract reports that limitation instead of guessing.
            sector_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(sector_intraday)")}
            stock_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(stock_intraday)")}
            for name, definition in (
                ("rise_count", "INTEGER NOT NULL DEFAULT 0"),
                ("fall_count", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if name not in sector_columns:
                    connection.execute(f"ALTER TABLE sector_intraday ADD COLUMN {name} {definition}")
            for name, definition in (
                ("volume", "REAL NOT NULL DEFAULT 0"),
                ("industry", "TEXT NOT NULL DEFAULT ''"),
                ("industry_code", "TEXT NOT NULL DEFAULT ''"),
                ("concepts", "TEXT NOT NULL DEFAULT ''"),
                ("primary_concept", "TEXT NOT NULL DEFAULT ''"),
            ):
                if name not in stock_columns:
                    connection.execute(f"ALTER TABLE stock_intraday ADD COLUMN {name} {definition}")

    def _load_last_buckets(self) -> None:
        with self._lock, self._connect() as connection:
            sector_rows = connection.execute(
                "SELECT board_type, MAX(data_time) AS data_time FROM sector_intraday GROUP BY board_type"
            ).fetchall()
            stock_row = connection.execute("SELECT MAX(data_time) AS data_time FROM stock_intraday").fetchone()
        self._last_sector_bucket = {
            str(row["board_type"]): str(row["data_time"] or "")[:16]
            for row in sector_rows
        }
        self._last_stock_bucket = str(stock_row["data_time"] or "")[:16] if stock_row else ""

    @staticmethod
    def _in_trading_session(data_time: str) -> bool:
        """Accept only continuous A-share quote observations through 15:00.

        Call-auction observations are optional presentation data and are not
        mixed into the continuous f62/stock snapshot archive.  In particular,
        15:01-15:30 is post-close and must never be persisted as market data.
        """
        minute = str(data_time or "")[11:16]
        return "09:30" <= minute <= "11:30" or "13:00" <= minute <= "15:00"

    def _purge_off_session_rows(self) -> None:
        """Remove lunch/pre-open/after-close rows accidentally written by GETs.

        The HTTP endpoints can still be polled every three seconds while the
        exchange is closed for lunch.  Storage is guarded here, at the final
        write boundary, so callers cannot accidentally archive frozen frames.
        """
        condition = "NOT ((substr(data_time,12,5) BETWEEN '09:30' AND '11:30') OR (substr(data_time,12,5) BETWEEN '13:00' AND '15:00'))"
        with self._lock, self._connect() as connection:
            connection.execute(f"DELETE FROM sector_intraday WHERE length(data_time) >= 16 AND {condition}")  # noqa: S608 - constant expression
            connection.execute(f"DELETE FROM stock_intraday WHERE length(data_time) >= 16 AND {condition}")  # noqa: S608 - constant expression

    def record_sectors(self, payload: dict[str, Any]) -> int:
        board_type = str(payload.get("board_type") or "industry")
        fetched_at = str(payload.get("generated_at") or "")
        source = payload.get("source") or {}
        source_host = str(source.get("host") or "")
        delayed = int(bool(source.get("possibly_delayed")))
        values = []
        for row in payload.get("sectors") or []:
            data_time = str(row.get("data_time") or "")
            if len(data_time) < 10 or not self._in_trading_session(data_time):
                continue
            values.append(
                (
                    data_time[:10], board_type, str(row.get("code") or ""), str(row.get("name") or ""),
                    data_time, fetched_at, float(row.get("price") or 0), float(row.get("change_pct") or 0),
                    float(row.get("amount") or 0), float(row.get("main_net_inflow") or 0),
                    float(row.get("main_net_ratio") or 0), float(row.get("delta_flow") or 0),
                    float(row.get("breadth") or 0), float(row.get("strength_score") or 0),
                    int(row.get("rise_count") or 0), int(row.get("fall_count") or 0), source_host, delayed,
                )
            )
        if not values:
            return 0
        with self._lock, self._connect() as connection:
            bucket = max(str(row[4] or "") for row in values)[:16]
            if bucket and self._last_sector_bucket.get(board_type) == bucket:
                return 0
            before = connection.total_changes
            connection.executemany(
                """
                INSERT OR IGNORE INTO sector_intraday (
                    trade_date, board_type, code, name, data_time, fetched_at, price, change_pct,
                    amount, main_net_inflow, main_net_ratio, delta_flow, breadth, strength_score,
                    rise_count, fall_count, source_host, possibly_delayed
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                values,
            )
            inserted = connection.total_changes - before
            if bucket:
                self._last_sector_bucket[board_type] = bucket
        return inserted

    def record_stocks(self, payload: dict[str, Any]) -> int:
        fetched_at = str(payload.get("generated_at") or "")
        source = payload.get("source") or {}
        source_host = str(source.get("host") or "")
        delayed = int(bool(source.get("possibly_delayed")))
        values = []
        for row in payload.get("stocks") or []:
            data_time = str(row.get("data_time") or "")
            if len(data_time) < 10 or not self._in_trading_session(data_time):
                continue
            values.append(
                (
                    data_time[:10], str(row.get("code") or ""), str(row.get("market") or ""),
                    str(row.get("name") or ""), data_time, fetched_at, float(row.get("price") or 0),
                    float(row.get("change_pct") or 0), float(row.get("amount") or 0),
                    float(row.get("main_net_inflow") or 0), float(row.get("main_net_ratio") or 0),
                    float(row.get("volume_ratio") or 0), float(row.get("turnover_pct") or 0),
                    float(row.get("activity_score") or 0), int(row.get("rank") or 0),
                    float(row.get("volume") or 0), str(row.get("industry") or ""),
                    str(row.get("industry_code") or ""), str(row.get("concepts") or ""),
                    str(row.get("primary_concept") or ""), source_host, delayed,
                )
            )
        if not values:
            return 0
        with self._lock, self._connect() as connection:
            bucket = max(str(row[4] or "") for row in values)[:16]
            if bucket and self._last_stock_bucket == bucket:
                return 0
            before = connection.total_changes
            connection.executemany(
                """
                INSERT OR IGNORE INTO stock_intraday (
                    trade_date, code, market, name, data_time, fetched_at, price, change_pct, amount,
                    main_net_inflow, main_net_ratio, volume_ratio, turnover_pct, activity_score,
                    rank_no, volume, industry, industry_code, concepts, primary_concept,
                    source_host, possibly_delayed
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                values,
            )
            inserted = connection.total_changes - before
            if bucket:
                self._last_stock_bucket = bucket
        return inserted

    def compact_to_minute(self) -> dict[str, int]:
        """Keep the final observed row per symbol/minute and reclaim duplicates."""
        with self._lock, self._connect() as connection:
            before = connection.execute("SELECT COUNT(*) FROM sector_intraday").fetchone()[0]
            connection.execute(
                """
                DELETE FROM sector_intraday
                WHERE rowid IN (
                    SELECT rowid FROM (
                        SELECT rowid,
                               ROW_NUMBER() OVER (
                                   PARTITION BY board_type, code, substr(data_time, 1, 16)
                                   ORDER BY data_time DESC
                               ) AS duplicate_rank
                        FROM sector_intraday
                    ) WHERE duplicate_rank > 1
                )
                """
            )
            sector_after = connection.execute("SELECT COUNT(*) FROM sector_intraday").fetchone()[0]
            stock_before = connection.execute("SELECT COUNT(*) FROM stock_intraday").fetchone()[0]
            connection.execute(
                """
                DELETE FROM stock_intraday
                WHERE rowid IN (
                    SELECT rowid FROM (
                        SELECT rowid,
                               ROW_NUMBER() OVER (
                                   PARTITION BY code, substr(data_time, 1, 16)
                                   ORDER BY data_time DESC
                               ) AS duplicate_rank
                        FROM stock_intraday
                    ) WHERE duplicate_rank > 1
                )
                """
            )
            stock_after = connection.execute("SELECT COUNT(*) FROM stock_intraday").fetchone()[0]
        self._load_last_buckets()
        return {
            "sector_deleted": int(before - sector_after),
            "sector_rows": int(sector_after),
            "stock_deleted": int(stock_before - stock_after),
            "stock_rows": int(stock_after),
        }

    def _selected_date(self, table: str, code: str, requested: str = "") -> str:
        if requested:
            return requested[:10]
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT MAX(trade_date) AS trade_date FROM {table} WHERE code = ?",  # noqa: S608 - fixed table names
                (code,),
            ).fetchone()
        return str(row["trade_date"] or "") if row is not None else ""

    def sector_points(self, code: str, trade_date: str = "", limit: int = 10000) -> tuple[str, list[dict[str, Any]]]:
        selected = self._selected_date("sector_intraday", code, trade_date)
        if not selected:
            return "", []
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT board_type, code, name, data_time, fetched_at, price, change_pct, amount,
                       main_net_inflow AS flow, main_net_ratio, delta_flow, breadth, strength_score,
                       source_host, possibly_delayed
                FROM sector_intraday
                WHERE code = ? AND trade_date = ?
                ORDER BY data_time ASC
                LIMIT ?
                """,
                (code, selected, max(1, min(20000, int(limit)))),
            ).fetchall()
        return selected, [dict(row) for row in rows]

    def sector_points_bulk(
        self,
        board_type: str,
        codes: list[str],
        trade_date: str = "",
        limit_per_code: int = 360,
    ) -> tuple[str, dict[str, list[dict[str, Any]]]]:
        """Load many board trajectories with one bounded query.

        The heatmap sparklines and the larger race modes can request hundreds
        of boards.  One query plus an in-process grouping pass is materially
        cheaper than opening one SQLite connection for every board.
        """
        clean_codes = list(dict.fromkeys(str(code or "").upper() for code in codes if str(code or "").upper().startswith("BK")))[:1000]
        selected = str(trade_date or "")[:10]
        if not clean_codes:
            return selected, {}
        with self._lock, self._connect() as connection:
            if not selected:
                placeholders = ",".join("?" for _ in clean_codes)
                row = connection.execute(
                    f"SELECT MAX(trade_date) AS trade_date FROM sector_intraday WHERE board_type = ? AND code IN ({placeholders})",  # noqa: S608 - placeholders only
                    (board_type, *clean_codes),
                ).fetchone()
                selected = str(row["trade_date"] or "") if row is not None else ""
            if not selected:
                return "", {}
            placeholders = ",".join("?" for _ in clean_codes)
            rows = connection.execute(
                f"""
                SELECT board_type, code, name, data_time, fetched_at, price, change_pct, amount,
                       main_net_inflow AS flow, main_net_ratio, delta_flow, breadth, strength_score,
                       source_host, possibly_delayed
                FROM sector_intraday
                WHERE board_type = ? AND trade_date = ? AND code IN ({placeholders})
                ORDER BY code ASC, data_time ASC
                """,  # noqa: S608 - placeholders only
                (board_type, selected, *clean_codes),
            ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {code: [] for code in clean_codes}
        safe_limit = max(1, min(1440, int(limit_per_code)))
        for row in rows:
            code = str(row["code"])
            bucket = grouped.setdefault(code, [])
            if len(bucket) < safe_limit:
                bucket.append(dict(row))
        return selected, grouped

    def latest_sector_rows(self, board_type: str, trade_date: str) -> list[dict[str, Any]]:
        selected = str(trade_date or "")[:10]
        if not selected:
            return []
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT s.board_type, s.code, s.name, s.data_time, s.price, s.change_pct,
                       s.amount, s.main_net_inflow, s.main_net_ratio, s.delta_flow,
                       s.breadth, s.strength_score, s.source_host, s.possibly_delayed
                FROM sector_intraday AS s
                INNER JOIN (
                    SELECT code, MAX(data_time) AS data_time
                    FROM sector_intraday
                    WHERE board_type = ? AND trade_date = ?
                    GROUP BY code
                ) AS latest
                ON latest.code = s.code AND latest.data_time = s.data_time
                WHERE s.board_type = ? AND s.trade_date = ?
                ORDER BY s.main_net_inflow DESC
                """,
                (board_type, selected, board_type, selected),
            ).fetchall()
        return [dict(row) for row in rows]

    def stock_points(self, code: str, trade_date: str = "", limit: int = 10000) -> tuple[str, list[dict[str, Any]]]:
        selected = self._selected_date("stock_intraday", code, trade_date)
        if not selected:
            return "", []
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT code, market, name, data_time, fetched_at, price, change_pct, amount,
                       main_net_inflow AS flow, main_net_ratio, volume_ratio, turnover_pct,
                       activity_score, rank_no AS rank, source_host, possibly_delayed
                FROM stock_intraday
                WHERE code = ? AND trade_date = ?
                ORDER BY data_time ASC
                LIMIT ?
                """,
                (code, selected, max(1, min(20000, int(limit)))),
            ).fetchall()
        return selected, [dict(row) for row in rows]

    @staticmethod
    def _regular_session_labels() -> list[str]:
        labels: list[str] = []
        for start, end in ((9 * 60 + 30, 11 * 60 + 30), (13 * 60, 15 * 60)):
            labels.extend(f"{minute // 60:02d}:{minute % 60:02d}" for minute in range(start, end + 1))
        return labels

    def replay_manifest(self, board_type: str, trade_date: str = "", date_limit: int = 30) -> dict[str, Any]:
        """Describe only replay frames that were actually archived locally.

        A frame is an observed minute bucket.  Missing buckets are explicit;
        this method never creates a synthetic 242-minute day or forward-fills
        a stock/sector cross-section.
        """
        board_type = str(board_type or "industry").lower()
        if board_type not in {"industry", "concept"}:
            return {"ok": False, "error": "board_type 仅支持 industry 或 concept", "frames": []}
        requested = str(trade_date or "")[:10]
        with self._lock, self._connect() as connection:
            date_rows = connection.execute(
                """
                SELECT trade_date, COUNT(*) AS rows, COUNT(DISTINCT code) AS codes,
                       COUNT(DISTINCT substr(data_time,1,16)) AS frame_count,
                       MIN(data_time) AS first_time, MAX(data_time) AS last_time
                FROM sector_intraday
                WHERE board_type = ?
                GROUP BY trade_date
                ORDER BY trade_date DESC
                LIMIT ?
                """,
                (board_type, max(1, min(120, int(date_limit)))),
            ).fetchall()
            selected = requested or (str(date_rows[0]["trade_date"]) if date_rows else "")
            sector_rows = connection.execute(
                """
                SELECT substr(data_time,1,16) AS frame_time, COUNT(*) AS row_count,
                       COUNT(DISTINCT code) AS code_count
                FROM sector_intraday
                WHERE board_type = ? AND trade_date = ?
                GROUP BY substr(data_time,1,16)
                ORDER BY frame_time ASC
                """,
                (board_type, selected),
            ).fetchall() if selected else []
            stock_rows = connection.execute(
                """
                SELECT substr(data_time,1,16) AS frame_time, COUNT(*) AS row_count,
                       COUNT(DISTINCT code) AS code_count,
                       SUM(CASE WHEN industry <> '' OR concepts <> '' THEN 1 ELSE 0 END) AS classified_count
                FROM stock_intraday
                WHERE trade_date = ?
                GROUP BY substr(data_time,1,16)
                ORDER BY frame_time ASC
                """,
                (selected,),
            ).fetchall() if selected else []

        sector_by_time = {str(row["frame_time"]): dict(row) for row in sector_rows}
        stock_by_time = {str(row["frame_time"]): dict(row) for row in stock_rows}
        # A replay frame must be able to drive 01/02/03 at minimum.  Stock-only
        # buckets are still disclosed below, but are not offered as playable
        # frames because replay_frame() correctly refuses to carry a sector
        # cross-section forward into that minute.
        observed_times = sorted(sector_by_time)
        stock_only_times = sorted(set(stock_by_time) - set(sector_by_time))
        expected_sector_codes = max((int(row["code_count"] or 0) for row in sector_rows), default=0)
        expected_stock_codes = max((int(row["code_count"] or 0) for row in stock_rows), default=0)
        frames = []
        for frame_time in observed_times:
            sector = sector_by_time.get(frame_time) or {}
            stock = stock_by_time.get(frame_time) or {}
            sector_count = int(sector.get("code_count") or 0)
            stock_count = int(stock.get("code_count") or 0)
            frames.append(
                {
                    "time": frame_time,
                    "label": frame_time[11:16],
                    "sector_count": sector_count,
                    "stock_count": stock_count,
                    "classified_stock_count": int(stock.get("classified_count") or 0),
                    "sector_complete": bool(expected_sector_codes and sector_count >= expected_sector_codes),
                    "stock_complete": bool(expected_stock_codes and stock_count >= expected_stock_codes),
                }
            )

        labels = self._regular_session_labels()
        label_index = {label: index for index, label in enumerate(labels)}
        observed_sector_labels = {time[11:16] for time in sector_by_time}
        observed_stock_labels = {time[11:16] for time in stock_by_time}
        first_index = min((label_index[label] for label in observed_sector_labels if label in label_index), default=-1)
        last_index = max((label_index[label] for label in observed_sector_labels if label in label_index), default=-1)
        covered_labels = labels[first_index:last_index + 1] if first_index >= 0 and last_index >= first_index else []
        sector_missing = [label for label in covered_labels if label not in observed_sector_labels]
        stock_missing = [label for label in covered_labels if label not in observed_stock_labels]
        available_dates = [dict(row) for row in date_rows]
        requested_missing = bool(requested and not sector_rows)
        return {
            "ok": bool(frames) and not requested_missing,
            "board_type": board_type,
            "trade_date": selected,
            "available_dates": available_dates,
            "frames": frames,
            "coverage": {
                "first_observed": observed_times[0] if observed_times else "",
                "last_observed": observed_times[-1] if observed_times else "",
                "observed_frame_count": len(observed_times),
                "stock_only_frame_count": len(stock_only_times),
                "stock_only_frame_labels": [time[11:16] for time in stock_only_times],
                "sector_frame_count": len(sector_rows),
                "stock_frame_count": len(stock_rows),
                "expected_session_slots": len(labels),
                "expected_sector_codes_per_frame": expected_sector_codes,
                "expected_stock_codes_per_frame": expected_stock_codes,
                "sector_missing_minutes_within_coverage": sector_missing,
                "stock_missing_minutes_within_coverage": stock_missing,
                "classified_stock_rows_available": any(int(row["classified_count"] or 0) > 0 for row in stock_rows),
                "complete_day": len(sector_rows) == len(labels) and not sector_missing,
                "contract": "仅播放8772本地SQLite真实留档分钟；服务未运行、源失败和旧库未保存分类字段的时段保持缺口，不插值、不前向填充。",
            },
            "error": "所选日期没有本地板块分钟留档" if requested_missing or not frames else "",
        }

    def replay_frame_rows(
        self,
        board_type: str,
        trade_date: str,
        frame_time: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Return exact cross-sections for one archived minute bucket."""
        selected = str(trade_date or "")[:10]
        minute = str(frame_time or "")[-5:]
        if not selected or not self._in_trading_session(f"{selected}T{minute}:00"):
            return [], []
        bucket = f"{selected}T{minute}"
        with self._lock, self._connect() as connection:
            sectors = connection.execute(
                """
                SELECT code, name, data_time, price, change_pct, amount, main_net_inflow,
                       main_net_ratio, delta_flow, breadth, strength_score, rise_count,
                       fall_count, source_host, possibly_delayed
                FROM sector_intraday
                WHERE board_type = ? AND trade_date = ? AND replace(substr(data_time,1,16),' ','T') = ?
                ORDER BY main_net_inflow DESC
                """,
                (board_type, selected, bucket),
            ).fetchall()
            stocks = connection.execute(
                """
                SELECT code, market, name, data_time, price, change_pct, amount,
                       main_net_inflow, main_net_ratio, volume_ratio, turnover_pct,
                       activity_score, rank_no AS rank, volume, industry, industry_code,
                       concepts, primary_concept, source_host, possibly_delayed
                FROM stock_intraday
                WHERE trade_date = ? AND replace(substr(data_time,1,16),' ','T') = ?
                ORDER BY rank_no ASC, activity_score DESC
                """,
                (selected, bucket),
            ).fetchall()
        return [dict(row) for row in sectors], [dict(row) for row in stocks]

    def purge(self) -> dict[str, int]:
        cutoff = (date.today() - timedelta(days=self.retention_days)).isoformat()
        with self._lock, self._connect() as connection:
            before = connection.total_changes
            connection.execute("DELETE FROM sector_intraday WHERE trade_date < ?", (cutoff,))
            sector_deleted = connection.total_changes - before
            before = connection.total_changes
            connection.execute("DELETE FROM stock_intraday WHERE trade_date < ?", (cutoff,))
            stock_deleted = connection.total_changes - before
        return {"sector_deleted": sector_deleted, "stock_deleted": stock_deleted}

    def stats(self) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            sector = connection.execute(
                "SELECT COUNT(*) AS rows, COUNT(DISTINCT code) AS codes, MIN(trade_date) AS first_date, MAX(trade_date) AS last_date FROM sector_intraday"
            ).fetchone()
            stock = connection.execute(
                "SELECT COUNT(*) AS rows, COUNT(DISTINCT code) AS codes, MIN(trade_date) AS first_date, MAX(trade_date) AS last_date FROM stock_intraday"
            ).fetchone()
        return {
            "path": str(self.path),
            "sector": dict(sector),
            "stock": dict(stock),
            "retention_days": self.retention_days,
        }
