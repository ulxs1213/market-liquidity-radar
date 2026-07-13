from __future__ import annotations

import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from quant_dashboard.market_heatmap import EastmoneyHeatmapProvider, MarketHeatmapService
from quant_dashboard.market_heatmap_history import MarketHeatmapHistoryStore


class FixtureProvider:
    def __init__(self) -> None:
        self.round = 0
        self.last_stock_sort_field = None

    def sectors(self, board_type: str):
        self.round += 1
        shift = self.round * 100.0
        rows = [
            {"f12": "BK0001", "f14": "强势板块", "f2": 100, "f3": 3.2, "f6": 1_000_000, "f62": 100_000 + shift, "f104": 8, "f105": 2, "f124": 1_700_011_860, "f184": 10},
            {"f12": "BK0002", "f14": "弱势板块", "f2": 80, "f3": -2.1, "f6": 800_000, "f62": -80_000 - shift, "f104": 2, "f105": 8, "f124": 1_700_011_860, "f184": -10},
        ]
        return rows, {"provider": "fixture", "possibly_delayed": False, "elapsed_ms": 1}

    def stocks(self, fs: str, limit: int = 120, sort_field: str = "f6"):
        self.last_stock_sort_field = sort_field
        rows = [
            {"f12": "600001", "f13": 1, "f14": "放量上涨", "f2": 10, "f3": 8, "f5": 9_000, "f6": 200_000_000, "f8": 4, "f10": 3, "f62": 30_000_000, "f100": "半导体", "f102": "上海板块", "f103": "芯片,算力", "f124": 1_700_011_860},
            {"f12": "000002", "f13": 0, "f14": "放量下跌", "f2": 8, "f3": -7, "f5": 3_000, "f6": 180_000_000, "f8": 5, "f10": 2.5, "f62": -25_000_000, "f100": "房地产", "f102": "深圳板块", "f103": "深圳板块", "f124": 1_700_011_860},
            {"f12": "600003", "f13": 1, "f14": "平稳活跃", "f2": 12, "f3": 0.2, "f5": 6_000, "f6": 300_000_000, "f8": 2, "f10": 1.2, "f62": 5_000_000, "f100": "半导体", "f102": "北京板块", "f103": "芯片", "f124": 1_700_011_860},
        ]
        return rows, {"provider": "fixture", "possibly_delayed": False, "elapsed_ms": 1}


class MarketHeatmapServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = FixtureProvider()
        self.service = MarketHeatmapService(ttl_seconds=1, provider=self.provider)

    def test_snapshot_has_transparent_score_and_daily_delta(self) -> None:
        first = self.service.snapshot("industry", force=True)
        second = self.service.snapshot("industry", force=True)
        self.assertTrue(first["ok"])
        self.assertEqual(len(second["sectors"]), 2)
        by_code = {row["code"]: row for row in second["sectors"]}
        self.assertEqual(by_code["BK0001"]["delta_flow"], 0.0)
        self.assertEqual(by_code["BK0002"]["delta_flow"], 0.0)
        self.assertGreater(by_code["BK0001"]["strength_score"], by_code["BK0002"]["strength_score"])
        self.assertEqual(set(by_code["BK0001"]["score_contributions"]), {"change_pct", "main_net_ratio", "breadth", "delta_flow"})
        self.assertEqual(second["field_units"]["main_net_inflow"], "人民币元")
        self.assertIn("f62", second["method"]["flow"])

    def test_daily_delta_resets_and_missing_timestamp_never_crosses_days(self) -> None:
        rows_by_round = [
            {"f12": "BK0001", "f14": "板块", "f6": 1000, "f62": 100, "f124": 1_700_000_000},
            {"f12": "BK0001", "f14": "板块", "f6": 1200, "f62": 150, "f124": 1_700_086_400},
            {"f12": "BK0001", "f14": "板块", "f6": 1300, "f62": 180, "f124": None},
        ]
        calls = iter(rows_by_round)
        self.provider.sectors = lambda _board: ([next(calls)], {"provider": "fixture"})
        self.assertEqual(self.service.snapshot("industry", force=True)["sectors"][0]["delta_flow"], 0)
        self.assertEqual(self.service.snapshot("industry", force=True)["sectors"][0]["delta_flow"], 0)
        self.assertEqual(self.service.snapshot("industry", force=True)["sectors"][0]["delta_flow"], 0)

    def test_timeline_deduplicates_equal_market_time(self) -> None:
        self.service.snapshot("industry", force=True)
        self.service.snapshot("industry", force=True)
        timeline = self.service.timeline("BK0001")
        self.assertEqual(len(timeline["points"]), 1)
        self.assertEqual(timeline["points"][0]["delta_flow"], 0.0)

    def test_same_day_new_timestamp_produces_delta(self) -> None:
        rows = iter([
            {"f12": "BK0001", "f14": "板块", "f6": 1000, "f62": 100, "f124": 1_700_000_000},
            {"f12": "BK0001", "f14": "板块", "f6": 1200, "f62": 150, "f124": 1_700_000_003},
        ])
        self.provider.sectors = lambda _board: ([next(rows)], {"provider": "fixture"})
        self.assertEqual(self.service.snapshot("industry", force=True)["sectors"][0]["delta_flow"], 0)
        self.assertEqual(self.service.snapshot("industry", force=True)["sectors"][0]["delta_flow"], 50)

    def test_sector_queues_cover_up_down_and_active(self) -> None:
        payload = self.service.sector("BK0001", force=True)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["queues"]["surging"][0]["name"], "放量上涨")
        self.assertEqual(payload["queues"]["falling"][0]["name"], "放量下跌")
        self.assertTrue(payload["queues"]["active"])

    def test_new_listing_and_extreme_gain_are_excluded_from_liquidity_surfaces(self) -> None:
        original = self.provider.stocks

        def stocks(fs: str, limit: int = 120, sort_field: str = "f6"):
            rows, source = original(fs, limit, sort_field)
            rows.extend([
                {"f12": "001399", "f13": 0, "f14": "N新样本", "f2": 80, "f3": 800, "f6": 9_000_000_000, "f8": 70, "f10": 20, "f62": 600_000_000, "f124": 1_700_000_000},
                {"f12": "001398", "f13": 0, "f14": "极端样本", "f2": 50, "f3": 45, "f6": 8_000_000_000, "f8": 60, "f10": 18, "f62": 500_000_000, "f124": 1_700_000_000},
            ])
            return rows, source

        self.provider.stocks = stocks
        payload = self.service.liquidity_watch(limit=180, force=True)
        visible_codes = {row["code"] for row in payload["stocks"]}
        queue_codes = {row["code"] for rows in payload["queues"].values() for row in rows}
        self.assertNotIn("001399", visible_codes | queue_codes)
        self.assertNotIn("001398", visible_codes | queue_codes)
        self.assertEqual(payload["exclusion_policy"]["excluded_count"], 2)
        self.assertIn("40%", payload["exclusion_policy"]["rule"])

    def test_liquidity_watch_uses_real_f5_and_returns_volume_desc(self) -> None:
        payload = self.service.liquidity_watch(limit=180, force=True)
        self.assertTrue(payload["ok"])
        self.assertEqual(self.provider.last_stock_sort_field, "f5")
        self.assertEqual([row["code"] for row in payload["stocks"]], ["600001", "600003", "000002"])
        self.assertEqual([row["volume"] for row in payload["stocks"]], [9_000, 6_000, 3_000])
        self.assertEqual(payload["field_units"]["volume"], "手")
        self.assertEqual(payload["display_sort"]["upstream_field"], "f5")
        self.assertEqual(payload["stocks"][0]["region_board"], "上海板块")

    def test_missing_region_sentinel_is_not_exposed_as_a_board_name(self) -> None:
        for sentinel in (None, "", "-", "--"):
            with self.subTest(sentinel=sentinel):
                row = self.service._stock_rows([{"f12": "600099", "f13": 1, "f14": "样本", "f5": 100, "f102": sentinel}])[0]
                self.assertEqual(row["region_board"], "未分类")
                self.assertEqual(row["industry_code"], "未分类")

    def test_sqlite_history_and_minute_flow_are_merged_for_full_day_views(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = MarketHeatmapHistoryStore(Path(temp) / "history.sqlite3")
            provider = FixtureProvider()
            provider.fund_flow_timeline = lambda secid: ([
                {"time": "2023-11-15 09:31", "flow": 10, "small_flow": 1, "medium_flow": 2, "large_flow": 3, "super_large_flow": 4},
                {"time": "2023-11-15 09:32", "flow": 20, "small_flow": 2, "medium_flow": 3, "large_flow": 6, "super_large_flow": 9},
            ], {"provider": "fixture-minute", "secid": secid})
            service = MarketHeatmapService(provider=provider, history_store=store)
            service.snapshot("industry", force=True)
            service.liquidity_watch(limit=180, force=True)

            sector = service.timeline("BK0001")
            stock = service.stock_timeline("600001", "SH")
            stats = store.stats()
            self.assertEqual(sector["trade_date"], "2023-11-15")
            self.assertEqual(len(sector["minute_points"]), 2)
            self.assertEqual(len(sector["realtime_points"]), 1)
            self.assertEqual(len(stock["minute_points"]), 2)
            self.assertEqual(len(stock["realtime_points"]), 1)
            self.assertEqual(sector["minute_source"]["provider"], "fixture-minute")
            self.assertEqual(stats["sector"]["rows"], 2)
            self.assertEqual(stats["stock"]["rows"], 3)

    def test_source_catalog_names_endpoints_fields_cadence_and_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            service = MarketHeatmapService(
                provider=self.provider,
                history_store=MarketHeatmapHistoryStore(Path(temp) / "history.sqlite3"),
            )
            catalog = service.source_catalog()
            self.assertGreaterEqual(len(catalog["sources"]), 5)
            for source in catalog["sources"]:
                self.assertTrue(source["provider"])
                self.assertTrue(source["endpoint"])
                self.assertTrue(source["fields"])
                self.assertTrue(source["cadence"])
                self.assertTrue(source["contract"])
            self.assertIn("N/C", catalog["exclusions"]["new_listing"])

    def test_sector_race_combines_top_inflow_and_outflow_native_series(self) -> None:
        self.provider.fund_flow_timeline = lambda secid: ([
            {"time": "2023-11-15 09:31", "flow": 10, "amount": 0},
            {"time": "2023-11-15 09:32", "flow": 20, "amount": 0},
        ], {"provider": "fixture-native", "secid": secid})
        race = self.service.sector_race("industry", top_each=2, force=True)
        self.assertTrue(race["ok"])
        self.assertEqual(race["data_mode"], "native_main_flow")
        self.assertEqual({row["direction"] for row in race["series"]}, {"inflow", "outflow"})
        self.assertTrue(all(len(row["points"]) == 2 for row in race["series"]))
        self.assertIn("多板块同图", race["source_disclosure"]["title"])

    def test_historical_sector_race_uses_disclosed_signed_amount_proxy(self) -> None:
        def historical_bars(symbol, trade_date):
            return [
                {"symbol": symbol, "time": f"{trade_date} 09:31:00", "close": 10, "volume": 100, "amount": 1_000},
                {"symbol": symbol, "time": f"{trade_date} 09:32:00", "close": 11, "volume": 200, "amount": 2_000},
                {"symbol": symbol, "time": f"{trade_date} 09:33:00", "close": 10, "volume": 300, "amount": 3_000},
            ]

        service = MarketHeatmapService(provider=self.provider, historical_bar_fetcher=historical_bars)
        race = service.sector_race("industry", top_each=2, trade_date="2023-11-14", force=True)
        self.assertTrue(race["ok"])
        self.assertEqual(race["data_mode"], "historical_direction_proxy")
        self.assertTrue(all(len(row["points"]) == 3 for row in race["series"]))
        self.assertTrue(all(row["component_count"] == 3 for row in race["series"]))
        first = race["series"][0]["points"]
        self.assertEqual([row["flow"] for row in first], [0, 6_000, -3_000])
        self.assertIn("不是原生主力净流", race["source_disclosure"]["limitation"])

    def test_history_store_keeps_one_cross_section_per_minute(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = MarketHeatmapHistoryStore(Path(temp) / "history.sqlite3")
            base = {
                "board_type": "industry",
                "generated_at": "2026-07-13T09:31:02",
                "source": {"host": "fixture", "possibly_delayed": False},
                "sectors": [
                    {"code": "BK0001", "name": "板块1", "data_time": "2026-07-13T09:31:02"},
                    {"code": "BK0002", "name": "板块2", "data_time": "2026-07-13T09:31:02"},
                ],
            }
            self.assertEqual(store.record_sectors(base), 2)
            later_same_minute = {**base, "generated_at": "2026-07-13T09:31:55"}
            later_same_minute["sectors"] = [
                {**row, "data_time": "2026-07-13T09:31:55"} for row in base["sectors"]
            ]
            self.assertEqual(store.record_sectors(later_same_minute), 0)
            next_minute = {**base, "generated_at": "2026-07-13T09:32:01"}
            next_minute["sectors"] = [
                {**row, "data_time": "2026-07-13T09:32:01"} for row in base["sectors"]
            ]
            self.assertEqual(store.record_sectors(next_minute), 2)
            self.assertEqual(store.stats()["sector"]["rows"], 4)

    def test_history_store_rejects_lunch_rows_and_bulk_query_keeps_sessions_connected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = MarketHeatmapHistoryStore(Path(temp) / "history.sqlite3")
            base = {
                "board_type": "industry",
                "source": {"host": "fixture", "possibly_delayed": False},
                "sectors": [{"code": "BK0001", "name": "板块1", "main_net_inflow": 100}],
            }
            morning = {**base, "generated_at": "2026-07-13T11:30:00", "sectors": [{**base["sectors"][0], "data_time": "2026-07-13T11:30:00"}]}
            lunch = {**base, "generated_at": "2026-07-13T12:00:00", "sectors": [{**base["sectors"][0], "data_time": "2026-07-13T12:00:00", "main_net_inflow": 110}]}
            afternoon = {**base, "generated_at": "2026-07-13T13:00:00", "sectors": [{**base["sectors"][0], "data_time": "2026-07-13T13:00:00", "main_net_inflow": 120}]}
            self.assertEqual(store.record_sectors(morning), 1)
            self.assertEqual(store.record_sectors(lunch), 0)
            self.assertEqual(store.record_sectors(afternoon), 1)
            selected, grouped = store.sector_points_bulk("industry", ["BK0001"], "2026-07-13")
            self.assertEqual(selected, "2026-07-13")
            self.assertEqual([row["data_time"][11:16] for row in grouped["BK0001"]], ["11:30", "13:00"])

    def test_history_store_stops_at_exchange_close_and_never_accepts_1530(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = MarketHeatmapHistoryStore(Path(temp) / "history.sqlite3")
            base = {
                "board_type": "industry",
                "source": {"host": "fixture"},
                "sectors": [{"code": "BK0001", "name": "板块1", "main_net_inflow": 100}],
            }
            at_close = {**base, "generated_at": "2026-07-13T15:00:00", "sectors": [{**base["sectors"][0], "data_time": "2026-07-13T15:00:00"}]}
            after_close = {**base, "generated_at": "2026-07-13T15:01:00", "sectors": [{**base["sectors"][0], "data_time": "2026-07-13T15:01:00"}]}
            user_mistaken_end = {**base, "generated_at": "2026-07-13T15:30:00", "sectors": [{**base["sectors"][0], "data_time": "2026-07-13T15:30:00"}]}
            self.assertEqual(store.record_sectors(at_close), 1)
            self.assertEqual(store.record_sectors(after_close), 0)
            self.assertEqual(store.record_sectors(user_mistaken_end), 0)

    def test_replay_manifest_reports_observed_frames_and_minute_gaps_without_fill(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = MarketHeatmapHistoryStore(Path(temp) / "history.sqlite3")
            for stamp in ("2026-07-13T09:31:00", "2026-07-13T09:33:00"):
                store.record_sectors({
                    "board_type": "industry",
                    "generated_at": stamp,
                    "source": {"host": "fixture"},
                    "sectors": [
                        {"code": "BK0001", "name": "半导体", "data_time": stamp, "main_net_inflow": 100},
                        {"code": "BK0002", "name": "房地产", "data_time": stamp, "main_net_inflow": -80},
                    ],
                })
            store.record_stocks({
                "generated_at": "2026-07-13T09:31:00",
                "source": {"host": "fixture"},
                "stocks": [{
                    "code": "600001", "market": "SH", "name": "芯片股", "data_time": "2026-07-13T09:31:00",
                    "amount": 10_000, "change_pct": 2, "volume_ratio": 2, "activity_score": 5,
                    "industry": "半导体", "concepts": "芯片,算力", "primary_concept": "芯片", "rank": 1,
                }],
            })
            store.record_stocks({
                "generated_at": "2026-07-13T09:34:00",
                "source": {"host": "fixture"},
                "stocks": [{
                    "code": "600001", "market": "SH", "name": "芯片股", "data_time": "2026-07-13T09:34:00",
                    "amount": 10_000, "change_pct": 2, "volume_ratio": 2, "activity_score": 5,
                    "industry": "半导体", "concepts": "芯片,算力", "primary_concept": "芯片", "rank": 1,
                }],
            })

            manifest = store.replay_manifest("industry", "2026-07-13")
            self.assertTrue(manifest["ok"])
            self.assertEqual([row["label"] for row in manifest["frames"]], ["09:31", "09:33"])
            self.assertEqual(manifest["coverage"]["stock_only_frame_labels"], ["09:34"])
            self.assertIn("09:32", manifest["coverage"]["sector_missing_minutes_within_coverage"])
            self.assertIn("09:32", manifest["coverage"]["stock_missing_minutes_within_coverage"])
            self.assertFalse(manifest["coverage"]["complete_day"])
            self.assertTrue(manifest["coverage"]["classified_stock_rows_available"])
            sectors, stocks = store.replay_frame_rows("industry", "2026-07-13", "09:32")
            self.assertEqual(sectors, [])
            self.assertEqual(stocks, [])

    def test_replay_frame_links_exact_heatmap_race_liquidity_and_historical_core_stocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = MarketHeatmapHistoryStore(Path(temp) / "history.sqlite3")
            for minute, factor in (("09:31", 1), ("09:33", 2)):
                stamp = f"2026-07-13T{minute}:00"
                store.record_sectors({
                    "board_type": "industry",
                    "generated_at": stamp,
                    "source": {"host": "fixture"},
                    "sectors": [
                        {"code": "BK0001", "name": "半导体", "data_time": stamp, "main_net_inflow": 100 * factor, "change_pct": factor},
                        {"code": "BK0002", "name": "房地产", "data_time": stamp, "main_net_inflow": -80 * factor, "change_pct": -factor},
                    ],
                })
                store.record_stocks({
                    "generated_at": stamp,
                    "source": {"host": "fixture"},
                    "stocks": [
                        {"code": "600001", "market": "SH", "name": "芯片股", "data_time": stamp, "price": 10 + factor,
                         "amount": 100_000 * factor, "volume": 1_000 * factor, "change_pct": 2 * factor, "volume_ratio": 2, "activity_score": 5,
                         "industry": "半导体", "concepts": "芯片,算力", "primary_concept": "芯片", "rank": 1},
                        {"code": "000002", "market": "SZ", "name": "地产股", "data_time": stamp, "price": 8,
                         "amount": 80_000 * factor, "volume": 2_000 * factor, "change_pct": -2, "volume_ratio": 1.5, "activity_score": 4,
                         "industry": "房地产", "concepts": "地产", "primary_concept": "地产", "rank": 2},
                    ],
                })
            service = MarketHeatmapService(provider=self.provider, history_store=store)

            frame = service.replay_frame("industry", "2026-07-13", "09:31", selected_code="BK0001", top_each=5)
            self.assertTrue(frame["ok"])
            self.assertEqual(frame["snapshot"]["mode"], "historical_replay")
            self.assertEqual({row["code"] for row in frame["snapshot"]["sectors"]}, {"BK0001", "BK0002"})
            self.assertEqual({row["code"] for row in frame["liquidity"]["stocks"]}, {"600001", "000002"})
            self.assertEqual([row["code"] for row in frame["liquidity"]["stocks"]], ["000002", "600001"])
            self.assertEqual(frame["liquidity"]["field_units"]["volume"], "手")
            self.assertEqual([row["code"] for row in frame["core_stocks"]["stocks"]], ["600001"])
            self.assertEqual(frame["race"]["data_mode"], "local_observed_replay")
            self.assertTrue(all(len(row["points"]) == 1 for row in frame["race"]["series"]))
            self.assertEqual(frame["session_progress"]["last_elapsed_label"], "09:31")
            self.assertEqual(frame["session_progress"]["blank_from_index"], 2)

            missing = service.replay_frame("industry", "2026-07-13", "09:32")
            self.assertFalse(missing["ok"])
            self.assertIn("不会插值", missing["error"])

    def test_large_and_all_sector_race_use_one_local_f62_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = MarketHeatmapHistoryStore(Path(temp) / "history.sqlite3")
            rows = []
            for index in range(45):
                flow = (index + 1) * 1_000 if index < 23 else -(index - 22) * 1_000
                rows.append({"code": f"BK{index:04d}", "name": f"板块{index}", "main_net_inflow": flow, "change_pct": index / 10})
            for stamp, factor in (("2026-07-13T09:31:00", 0.5), ("2026-07-13T13:00:00", 1.0)):
                payload = {
                    "board_type": "industry",
                    "generated_at": stamp,
                    "source": {"host": "fixture"},
                    "sectors": [{**row, "data_time": stamp, "main_net_inflow": row["main_net_inflow"] * factor} for row in rows],
                }
                self.assertEqual(store.record_sectors(payload), 45)
            service = MarketHeatmapService(provider=self.provider, history_store=store)
            top20 = service.sector_race("industry", top_each=20, trade_date="2026-07-13", force=True)
            all_rows = service.sector_race("industry", top_each=0, trade_date="2026-07-13", force=True)
            self.assertEqual(top20["data_mode"], "local_observed_f62")
            self.assertEqual(len(top20["series"]), 40)
            self.assertEqual(len(all_rows["series"]), 45)
            self.assertFalse(all_rows["truncated"])
            self.assertTrue(all(len(row["points"]) == 2 for row in all_rows["series"]))

    def test_sector_sparklines_are_batched_and_stock_classification_is_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = MarketHeatmapHistoryStore(Path(temp) / "history.sqlite3")
            service = MarketHeatmapService(provider=self.provider, history_store=store)
            service.snapshot("industry", force=True)
            spark = service.sector_sparklines("industry", ["BK0001", "BK0002"])
            liquidity = service.liquidity_watch(limit=180, force=True)
            self.assertEqual({row["code"] for row in spark["series"]}, {"BK0001", "BK0002"})
            self.assertEqual(spark["source_mode"], "local_observed_f62")
            by_code = {row["code"]: row for row in liquidity["stocks"]}
            self.assertEqual(by_code["600001"]["industry"], "半导体")
            self.assertEqual(by_code["600001"]["primary_concept"], "芯片")
            self.assertIn("算力", by_code["600001"]["concepts"])

    def test_stock_timeline_combines_price_volume_and_native_flow(self) -> None:
        self.provider.fund_flow_timeline = lambda secid: ([
            {"time": "2023-11-15 09:31", "flow": 10},
            {"time": "2023-11-15 09:32", "flow": 20},
        ], {"provider": "fixture-flow", "endpoint": "fixture-flow", "secid": secid})
        self.provider.stock_intraday = lambda secid: ([
            {"time": "2023-11-15 09:31", "open": 10, "high": 10.2, "low": 9.9, "close": 10.1, "average": 10.0, "volume": 100, "amount": 1_000},
            {"time": "2023-11-15 09:32", "open": 10.1, "high": 10.3, "low": 10.0, "close": 10.2, "average": 10.1, "volume": 120, "amount": 1_200},
        ], {"provider": "fixture-price", "endpoint": "fixture-price", "pre_close": 9.8, "secid": secid})
        payload = self.service.stock_timeline("600001", "SH", force=True)
        self.assertEqual(len(payload["price_points"]), 2)
        self.assertEqual(payload["price_points"][1]["volume"], 120)
        self.assertEqual(len(payload["minute_points"]), 2)
        self.assertEqual(payload["price_source"]["provider"], "fixture-price")
        self.assertIn("11:30", payload["session_contract"]["chart_axis"])

    def test_session_axis_progress_keeps_future_minutes_blank_across_boundaries(self) -> None:
        cases = [
            (datetime(2026, 7, 13, 9, 29), "pre_open_wait", 0, ""),
            (datetime(2026, 7, 13, 9, 30), "morning", 1, "09:30"),
            (datetime(2026, 7, 13, 11, 30), "morning", 121, "11:30"),
            (datetime(2026, 7, 13, 11, 31), "lunch_break", 121, "11:30"),
            (datetime(2026, 7, 13, 13, 0), "afternoon", 122, "13:00"),
            (datetime(2026, 7, 13, 15, 0), "afternoon", 242, "15:00"),
            (datetime(2026, 7, 13, 15, 1), "closed_complete", 242, "15:00"),
        ]
        for now, status, elapsed, last_label in cases:
            with self.subTest(now=now):
                payload = self.service.session_axis("2026-07-13", now=now)
                progress = payload["session_progress"]
                axis = payload["session_axis"]
                self.assertEqual(progress["status"], status)
                self.assertEqual(progress["elapsed_slots"], elapsed)
                self.assertEqual(progress["blank_from_index"], elapsed)
                self.assertEqual(progress["last_elapsed_label"], last_label)
                self.assertEqual(len(axis["labels"]), 242)
                self.assertEqual(axis["labels"][120:123], ["11:30", "13:00", "13:01"])
                self.assertEqual(axis["display_end"], "15:00")
                self.assertNotIn("15:30", axis["labels"])

    def test_optional_auction_points_are_only_exposed_when_upstream_returns_them(self) -> None:
        self.provider.fund_flow_timeline = lambda secid: ([], {"provider": "fixture-flow", "secid": secid})
        self.provider.stock_intraday = lambda secid: ([
            {"time": "2026-07-13 09:15", "close": 10.0, "volume": 0},
            {"time": "2026-07-13 09:29", "close": 10.2, "volume": 0},
            {"time": "2026-07-13 09:30", "close": 10.3, "volume": 100},
        ], {"provider": "fixture-price", "endpoint": "trends2/get", "secid": secid})
        visible = self.service.stock_timeline("600001", "SH", force=True, include_auction=True)
        hidden = self.service.stock_timeline("600001", "SH", force=True, include_auction=False)
        self.assertTrue(visible["auction"]["available"])
        self.assertEqual([row["time"][11:16] for row in visible["auction_points"]], ["09:15", "09:29"])
        self.assertEqual([row["time"][11:16] for row in visible["price_points"]], ["09:30"])
        self.assertEqual(len(visible["session_axis"]["labels"]), 257)
        self.assertEqual(hidden["auction_points"], [])
        self.assertEqual(hidden["auction"]["point_count"], 2)

    def test_concept_race_excludes_market_wide_eligibility_aggregates(self) -> None:
        def concepts(_board_type: str):
            return ([
                {"f12": "BK0999", "f14": "融资融券", "f3": 1, "f6": 1_000_000, "f62": 999_000, "f124": 1_700_011_860},
                {"f12": "BK0001", "f14": "芯片", "f3": 2, "f6": 900_000, "f62": 100_000, "f124": 1_700_011_860},
                {"f12": "BK0002", "f14": "中药", "f3": -2, "f6": 800_000, "f62": -80_000, "f124": 1_700_011_860},
            ], {"provider": "fixture", "possibly_delayed": False})

        self.provider.sectors = concepts
        self.provider.fund_flow_timeline = lambda secid: ([
            {"time": "2023-11-15 09:31", "flow": 10},
        ], {"provider": "fixture-native", "secid": secid})
        race = self.service.sector_race("concept", top_each=5, force=True)
        self.assertEqual(race["excluded_aggregate_names"], ["融资融券"])
        self.assertNotIn("融资融券", {row["name"] for row in race["series"]})
        self.assertIn("融资融券", race["source_disclosure"]["limitation"])

    def test_invalid_sector_is_rejected_without_provider_call(self) -> None:
        payload = self.service.sector("600000", force=True)
        self.assertFalse(payload["ok"])
        self.assertIn("BK", payload["error"])

    def test_provider_failure_keeps_disk_snapshot_and_marks_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cache_path = Path(temp) / "latest_industry.json"
            with patch.object(self.service, "_cache_path", return_value=cache_path):
                live = self.service.snapshot("industry", force=True)
                self.assertTrue(cache_path.exists())
                self.provider.sectors = lambda _board: (_ for _ in ()).throw(RuntimeError("offline"))
                fallback = self.service.snapshot("industry", force=True)
                self.assertTrue(fallback["ok"])
                self.assertTrue(fallback["stale"])
                self.assertEqual(fallback["mode"], "cached_replay")
                self.assertIn("offline", fallback["upstream_error"])
                self.assertEqual(live["sectors"][0]["code"], fallback["sectors"][0]["code"])

    def test_sector_and_liquidity_failure_keep_last_memory_snapshot(self) -> None:
        sector = self.service.sector("BK0001", force=True)
        liquidity = self.service.liquidity_watch(limit=120, force=True)
        self.provider.stocks = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline"))
        stale_sector = self.service.sector("BK0001", force=True)
        stale_liquidity = self.service.liquidity_watch(limit=120, force=True)
        self.assertTrue(stale_sector["ok"])
        self.assertTrue(stale_sector["stale"])
        self.assertEqual(stale_sector["stocks"], sector["stocks"])
        self.assertIn("offline", stale_sector["upstream_error"])
        self.assertTrue(stale_liquidity["ok"])
        self.assertTrue(stale_liquidity["stale"])
        self.assertEqual(stale_liquidity["stocks"], liquidity["stocks"])

    def test_normal_concurrent_snapshot_is_single_flight_cached(self) -> None:
        original = self.provider.sectors

        def slow_sectors(board_type: str):
            time.sleep(0.03)
            return original(board_type)

        self.provider.sectors = slow_sectors
        barrier = threading.Barrier(6)
        results = []

        def fetch() -> None:
            barrier.wait()
            results.append(self.service.snapshot("industry"))

        threads = [threading.Thread(target=fetch) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
        self.assertEqual(len(results), 6)
        self.assertEqual(self.provider.round, 1)
        self.assertEqual(sum(not row["response_cached"] for row in results), 1)

    def test_invalid_board_type_is_rejected(self) -> None:
        payload = self.service.snapshot("unexpected", force=True)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_code"], "invalid_board_type")

    def test_replay_frontend_controls_and_api_routes_are_wired(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "src/market_liquidity_radar/web/index.html").read_text(encoding="utf-8")
        script = (root / "src/market_liquidity_radar/web/static/market_heatmap.js").read_text(encoding="utf-8")
        server = (root / "src/market_liquidity_radar/server.py").read_text(encoding="utf-8")
        for control in ("replayTradeDate", "replayPlay", "replaySpeed", "replayProgress", "replayCurrentTime", "replayLive"):
            self.assertIn(f'id="{control}"', html)
        for speed in ('value="1"', 'value="2"', 'value="5"'):
            self.assertIn(speed, html)
        for state_function in ("loadReplayCatalog", "loadReplayFrame", "setReplayPlaying", "returnToLive"):
            self.assertIn(f"function {state_function}", script)
        return_live = script[script.index("async function returnToLive") : script.index("async function refreshRace")]
        self.assertIn("const selectedCode = STATE.selectedCode", return_live)
        self.assertIn("await refresh(true)", return_live)
        self.assertIn("await selectSector(selectedCode, true)", return_live)
        self.assertIn("stock_only_frame_labels", script)
        self.assertIn('if (!STATE.paused && !STATE.replayMode)', script)
        self.assertIn('/api/market_heatmap/replay_manifest', server)
        self.assertIn('/api/market_heatmap/replay_frame', server)

    def test_closed_live_snapshot_is_not_labeled_as_historical_replay(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = (root / "src/market_liquidity_radar/web/static/market_heatmap.js").read_text(encoding="utf-8")
        render_meta = script[script.index("function renderMeta") : script.index("function visibleSectors")]
        self.assertIn('const closed = payload.mode === "closed"', render_meta)
        self.assertIn('? "收盘快照"', render_meta)
        self.assertNotIn('["historical_replay", "cached_replay", "closed"]', render_meta)


class EastmoneyProviderPaginationTest(unittest.TestCase):
    def test_sector_pagination_follows_reported_total_past_eight_pages(self) -> None:
        provider = EastmoneyHeatmapProvider()
        calls = []

        def fake_get(_path, params):
            page = int(params["pn"])
            calls.append(page)
            start = (page - 1) * 100
            end = min(850, start + 100)
            rows = [{"f12": f"BK{index:04d}"} for index in range(start, end)]
            return {"rc": 0, "data": {"total": 850, "diff": rows}}, {"elapsed_ms": 1}

        provider._get = fake_get
        rows, source = provider.sectors("concept")
        self.assertEqual(calls, list(range(1, 10)))
        self.assertEqual(len(rows), 850)
        self.assertEqual(source["reported_total"], 850)
        self.assertTrue(source["complete"])

    def test_sector_pagination_deduplicates_codes_and_marks_incomplete(self) -> None:
        provider = EastmoneyHeatmapProvider()

        def fake_get(_path, params):
            page = int(params["pn"])
            start = 0 if page == 2 else (page - 1) * 100
            rows = [{"f12": f"BK{index:04d}"} for index in range(start, min(200, start + 100))]
            return {"rc": 0, "data": {"total": 200, "diff": rows}}, {"elapsed_ms": 1}

        provider._get = fake_get
        rows, source = provider.sectors("industry")
        self.assertEqual(len(rows), 100)
        self.assertFalse(source["complete"])

    def test_stock_pagination_honors_limit_above_upstream_page_cap(self) -> None:
        provider = EastmoneyHeatmapProvider()
        calls = []

        def fake_get(_path, params):
            page = int(params["pn"])
            calls.append((page, params["pz"], params["fid"]))
            start = (page - 1) * 100
            rows = [{"f12": f"{index:06d}"} for index in range(start, start + 100)]
            return {"rc": 0, "data": {"total": 5000, "diff": rows}}, {"elapsed_ms": 1}

        provider._get = fake_get
        rows, source = provider.stocks("all", limit=180, sort_field="f5")
        self.assertEqual(calls, [(1, 100, "f5"), (2, 100, "f5")])
        self.assertEqual(len(rows), 180)
        self.assertEqual(source["requested_limit"], 180)
        self.assertTrue(source["complete"])
        self.assertEqual(source["sort_field"], "f5")
        self.assertTrue(source["requested_limit_complete"])
        self.assertFalse(source["full_universe_returned"])


if __name__ == "__main__":
    unittest.main()
