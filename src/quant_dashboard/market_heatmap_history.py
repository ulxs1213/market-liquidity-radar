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
                    source_host TEXT NOT NULL,
                    possibly_delayed INTEGER NOT NULL,
                    PRIMARY KEY (code, data_time)
                );
                CREATE INDEX IF NOT EXISTS idx_stock_intraday_lookup
                    ON stock_intraday(code, trade_date, data_time);
                """
            )

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
                    float(row.get("breadth") or 0), float(row.get("strength_score") or 0), source_host, delayed,
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
                    source_host, possibly_delayed
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                    float(row.get("activity_score") or 0), int(row.get("rank") or 0), source_host, delayed,
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
                    rank_no, source_host, possibly_delayed
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
