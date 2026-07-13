from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "market_liquidity_radar" / "web"
HTML = (WEB / "index.html").read_text(encoding="utf-8")
CSS = (WEB / "static" / "market_heatmap.css").read_text(encoding="utf-8")
JS = (WEB / "static" / "market_heatmap.js").read_text(encoding="utf-8")


class MarketHeatmapLiquidityVisualUiContractTest(unittest.TestCase):
    def test_scatter_uses_real_volume_lots_on_log_axis_and_amount_for_size(self) -> None:
        render = JS[JS.index("function renderLiquidity") : JS.index("async function selectStock")]
        self.assertIn('name: "成交量（手，对数轴）"', render)
        self.assertIn("type: \"log\"", render)
        self.assertIn("Math.max(1, Number(row.volume || 0))", render)
        self.assertIn("Number(row.amount || 0)", render)
        self.assertNotIn("Math.min(12, row.volume_ratio)", render)
        self.assertIn("纵轴=成交量（手，对数轴）", render)
        self.assertIn("纵轴=成交量（手，对数轴）", HTML)

    def test_volume_order_is_applied_before_topn_slice_and_missing_values_are_safe(self) -> None:
        render = JS[JS.index("function renderLiquidity") : JS.index("async function selectStock")]
        sort_at = render.index("Number(b.volume || 0) - Number(a.volume || 0)")
        slice_at = render.index("allStocks.slice(0, STATE.liquidityLimit)")
        self.assertLess(sort_at, slice_at)
        self.assertIn('const volumeText = fmtVolumeLots(r.volume)', render)
        self.assertIn('volumeText === "--" ? "（暂无有效 f5）"', render)
        self.assertIn('return "--"', JS[JS.index("const fmtVolumeLots") : JS.index("const fmtVolumeAxis")])

    def test_legend_point_and_tooltip_share_deterministic_classification_colors(self) -> None:
        render = JS[JS.index("function renderLiquidity") : JS.index("async function selectStock")]
        self.assertIn("const base = stableColor(name)", render)
        self.assertIn('stableColor(row[groupField] || "未分类")', render)
        self.assertIn('classificationTag(industry, "行业", palette)', render)
        self.assertIn('classificationTag(primaryConcept, "概念板块", palette)', render)
        self.assertIn('classificationTag(regionBoard, "地域板块", palette)', render)
        self.assertIn("--legend-color", CSS)
        self.assertIn("--legend-text", CSS)
        self.assertNotIn(".watch-queues h3,.legend-chip{color:var(--text)}", CSS)
        self.assertNotIn("slice(0, 18)", render)
        self.assertIn("CLASSIFICATION_COLORS", JS)

    def test_change_and_main_flow_keep_independent_red_green_semantics(self) -> None:
        render = JS[JS.index("function renderLiquidity") : JS.index("async function selectStock")]
        self.assertIn("const changeColor = semanticTextColor(r.change_pct, palette)", render)
        self.assertIn("const flowColor = semanticTextColor(r.main_net_inflow, palette)", render)
        self.assertIn("color:${changeColor}", render)
        self.assertIn("color:${flowColor}", render)
        self.assertIn('> 0 ? "↑ 上涨"', render)
        self.assertIn('< 0 ? "↓ 下跌"', render)
        self.assertIn('> 0 ? "↑ 净流入"', render)
        self.assertIn('< 0 ? "↓ 净流出"', render)
        self.assertIn("semanticTextColor(row.change_pct, palette)", render)

    def test_tooltip_surface_and_text_follow_active_theme(self) -> None:
        render = JS[JS.index("function renderLiquidity") : JS.index("async function selectStock")]
        self.assertIn("backgroundColor: palette.panel", render)
        self.assertIn("borderColor: palette.line", render)
        self.assertIn("textStyle: { color: palette.text", render)
        self.assertIn("color:${palette.text}", render)
        self.assertIn("classificationTextColor", JS)


if __name__ == "__main__":
    unittest.main()
