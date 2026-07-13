from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "src" / "market_liquidity_radar" / "web" / "static" / "market_heatmap.js").read_text(encoding="utf-8")
CSS = (ROOT / "src" / "market_liquidity_radar" / "web" / "static" / "market_heatmap.css").read_text(encoding="utf-8")
RACE = JS[JS.index("function renderRace(payload)") : JS.index("function renderStockTimeline(payload)")]


class MarketHeatmapRaceUiContractTest(unittest.TestCase):
    def test_integer_yi_formatter_rounds_once_and_never_adds_yuan_suffix(self) -> None:
        formatter = JS[JS.index("const fmtYiInteger") : JS.index("const fmtPct")]
        self.assertIn("Math.round(Number(value || 0) / 1e8)", formatter)
        self.assertIn("}亿`", formatter)
        tooltip = RACE[RACE.index("tooltip:") : RACE.index("grid: grids")]
        self.assertIn("fmtYiInteger(raw)", tooltip)
        self.assertIn('"净流出" : "净流入"', tooltip)
        self.assertNotIn(" 元", tooltip)
        self.assertNotIn("toFixed", tooltip)

    def test_independent_axes_have_separated_grids_and_non_overlapping_titles(self) -> None:
        inflow = re.search(r'race-inflow-grid"[^\n]+top: "(\d+)%", height: "(\d+)%"', RACE)
        outflow = re.search(r'race-outflow-grid"[^\n]+top: "(\d+)%", height: "(\d+)%"', RACE)
        self.assertIsNotNone(inflow)
        self.assertIsNotNone(outflow)
        inflow_top, inflow_height = map(int, inflow.groups())
        outflow_top, _ = map(int, outflow.groups())
        self.assertGreaterEqual(outflow_top - (inflow_top + inflow_height), 10)
        self.assertIn('name: "净流入（亿）", nameLocation: "middle", nameRotate: 90, nameGap: 72', RACE)
        self.assertIn('name: "净流出（亿）", nameLocation: "middle", nameRotate: 90, nameGap: 72', RACE)
        self.assertGreaterEqual(RACE.count("formatter: fmtYiInteger"), 3)

    def test_inflow_and_outflow_rails_are_equal_independent_scrollers(self) -> None:
        self.assertIn('data-race-scroll="${group.direction}"', RACE)
        self.assertIn("railScrollTop", RACE)
        self.assertIn("node.scrollTop = Math.min(previous", RACE)
        self.assertIn("grid-template-rows:repeat(2,minmax(0,1fr))", CSS)
        self.assertIn(".race-rail-scroll{", CSS)
        self.assertIn("overflow-y:auto", CSS)
        self.assertIn("overscroll-behavior:contain", CSS)

    def test_true_signed_series_shared_scale_and_click_linkage_are_preserved(self) -> None:
        self.assertIn(".map(point => ({ value: [point._time, point.flow]", RACE)
        self.assertIn('STATE.raceScaleMode === "independent"', RACE)
        self.assertIn('id: "race-shared-grid"', RACE)
        self.assertIn('bindSingleAndDouble(', RACE)
        self.assertIn('() => selectSector(button.dataset.raceCode)', RACE)
        self.assertIn('() => openSectorTarget(button.dataset.raceCode, button)', RACE)
        self.assertIn("底层仍保留真实有符号人民币元", RACE)


if __name__ == "__main__":
    unittest.main()
