from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from quant_dashboard.market_heatmap import MarketHeatmapService


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "src/market_liquidity_radar/web/static/market_heatmap.js").read_text(encoding="utf-8")
STOCK_TIMELINE = SCRIPT[
    SCRIPT.index("function renderStockTimeline") : SCRIPT.index("function renderOrderBook")
]


class CrosshairProvider:
    def fund_flow_timeline(self, _secid: str):
        return [
            {"time": "2026-07-13 09:31", "flow": 100},
            {"time": "2026-07-13 09:32", "flow": -50},
        ], {"provider": "fixture-flow", "endpoint": "fixture-flow"}

    def stock_intraday(self, _secid: str):
        return [
            {"time": "2026-07-13 09:31", "open": 10, "high": 10.1, "low": 9.9, "close": 10, "average": 10, "volume": 923, "amount": 923_000},
            {"time": "2026-07-13 09:32", "open": 10, "high": 10.2, "low": 10, "close": 10.1, "average": 10.05, "volume": 120, "amount": 121_200},
        ], {"provider": "fixture-price", "endpoint": "trends2/get", "pre_close": 9.8}


class MarketHeatmap05BCrosshairTest(unittest.TestCase):
    def test_three_grids_share_one_linked_time_axis_pointer(self) -> None:
        self.assertIn("link: [{ xAxisIndex: [0, 1, 2] }]", STOCK_TIMELINE)
        self.assertGreaterEqual(STOCK_TIMELINE.count('axisPointer: { show: true, type: "line", snap: true }'), 3)
        self.assertIn('axisPointer: { type: "line", axis: "x", snap: true, animation: false }', STOCK_TIMELINE)
        self.assertIn('stockTimelineChart.on("updateAxisPointer"', SCRIPT)
        self.assertIn('item.axisDim === "x"', SCRIPT)

    def test_hover_card_has_all_factual_fields_and_signed_net_language(self) -> None:
        for label in (
            "最新价：",
            "当日均价：",
            "分钟成交量：",
            "累计主力净流：",
            "本分钟净流变化：",
            "净流入",
            "净流出",
        ):
            self.assertIn(label, STOCK_TIMELINE)
        self.assertIn('previousFlow == null ? null : current - previousFlow', STOCK_TIMELINE)
        self.assertIn('首个可用资金点，无法计算相邻变化', STOCK_TIMELINE)
        self.assertIn('不拆成或伪造成总流入/总流出', STOCK_TIMELINE)
        self.assertNotIn('主力总流入', STOCK_TIMELINE)
        self.assertNotIn('主力总流出', STOCK_TIMELINE)

    def test_live_redraw_retains_hover_and_avoids_full_chart_recreation(self) -> None:
        self.assertIn("stockHoverActive", STOCK_TIMELINE)
        self.assertIn("stockHoverTime", STOCK_TIMELINE)
        self.assertIn('dispatchAction({ type: "showTip", seriesIndex, dataIndex: hoverIndex })', STOCK_TIMELINE)
        self.assertIn('transitionDuration: 0', STOCK_TIMELINE)
        self.assertIn('notMerge: false', STOCK_TIMELINE)
        self.assertIn('replaceMerge: ["grid", "xAxis", "yAxis", "series"]', STOCK_TIMELINE)
        self.assertIn("timelineSignature !== STATE.lastStockTimelineSignature", STOCK_TIMELINE)

    def test_same_chart_dom_is_moved_into_popup_not_cloned(self) -> None:
        self.assertIn('const terminal = $("stockTerminalWorkspace")', SCRIPT)
        self.assertIn("modalMount.appendChild(terminal)", SCRIPT)
        self.assertIn("home.appendChild(terminal)", SCRIPT)
        self.assertEqual(SCRIPT.count('echarts.init($("stockTimeline"))'), 1)

    def test_live_and_historical_volume_units_are_explicit(self) -> None:
        provider = CrosshairProvider()
        service = MarketHeatmapService(provider=provider)
        live = service.stock_timeline("600001", "SH", force=True)
        self.assertEqual(live["price_volume_contract"]["unit"], "手")
        self.assertEqual(live["price_volume_contract"]["share_multiplier"], 100)
        self.assertIn("f56", live["price_volume_contract"]["display"])

        def history(_symbol: str, trade_date: date):
            return [
                {"time": f"{trade_date} 09:31:00", "close": 10, "open": 10, "high": 10, "low": 10, "average": 10, "volume": 92_300, "amount": 923_000},
            ]

        historical = MarketHeatmapService(provider=provider, historical_bar_fetcher=history).stock_timeline(
            "600001", "SH", trade_date="2026-07-13", force=True
        )
        self.assertEqual(historical["price_volume_contract"]["unit"], "股")
        self.assertEqual(historical["price_volume_contract"]["share_multiplier"], 1)
        self.assertIn("换算为股", historical["price_volume_contract"]["display"])


if __name__ == "__main__":
    unittest.main()
