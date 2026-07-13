from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "src" / "market_liquidity_radar" / "web" / "index.html"
CSS = ROOT / "src" / "market_liquidity_radar" / "web" / "static" / "market_heatmap.css"
JS = ROOT / "src" / "market_liquidity_radar" / "web" / "static" / "market_heatmap.js"


class _PackParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.pack_depth: int | None = None
        self.direct_modules: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if values.get("id") == "dashboardPack":
            self.pack_depth = len(self.stack)
        elif self.pack_depth is not None and len(self.stack) == self.pack_depth + 1:
            module_id = values.get("data-module-id")
            if module_id:
                self.direct_modules.append((module_id, values.get("data-layout-span", "")))
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.stack:
            self.stack.pop()
        if self.pack_depth is not None and len(self.stack) <= self.pack_depth:
            self.pack_depth = None


def _dense_pack(items: list[tuple[str, int, int]], columns: int = 10) -> dict[str, tuple[int, int, int]]:
    """Small model of CSS grid-auto-flow:dense with one-pixel rows."""
    occupied: set[tuple[int, int]] = set()
    placed: dict[str, tuple[int, int, int]] = {}
    for name, span, visible_height in items:
        row_span = visible_height + 12
        row = 0
        while True:
            found = False
            for column in range(columns - span + 1):
                if all(
                    (check_row, check_column) not in occupied
                    for check_row in range(row, row + row_span)
                    for check_column in range(column, column + span)
                ):
                    for check_row in range(row, row + row_span):
                        for check_column in range(column, column + span):
                            occupied.add((check_row, check_column))
                    placed[name] = (row, column, visible_height)
                    found = True
                    break
            if found:
                break
            row += 1
    return placed


class MarketHeatmapCompactLayoutTest(unittest.TestCase):
    def test_modules_are_direct_children_of_one_pack_with_expected_default_spans(self) -> None:
        parser = _PackParser()
        parser.feed(TEMPLATE.read_text(encoding="utf-8"))
        self.assertEqual(
            parser.direct_modules,
            [
                ("sector-heatmap", "7"),
                ("inflow-ranking", "3"),
                ("outflow-ranking", "3"),
                ("sector-race", "7"),
                ("core-stocks", "3"),
                ("liquidity-core", "10"),
                ("method-notes", "10"),
            ],
        )

    def test_css_contract_uses_dense_one_pixel_rows_and_twelve_pixel_pack_gap(self) -> None:
        css = CSS.read_text(encoding="utf-8")
        packed_rule = re.search(r"\.dashboard-pack-grid\.is-packed\{([^}]+)\}", css)
        self.assertIsNotNone(packed_rule)
        contract = packed_rule.group(1)
        self.assertIn("grid-template-columns:repeat(10,minmax(0,1fr))", contract)
        self.assertIn("grid-auto-flow:row dense", contract)
        self.assertIn("grid-auto-rows:1px", contract)
        self.assertIn("column-gap:12px", contract)
        self.assertIn("row-gap:0", contract)
        self.assertIn("min-width:0", css)
        self.assertIn("grid-column:1/-1!important", css)

    def test_persistence_stores_only_span_and_height_not_pixel_positions(self) -> None:
        js = JS.read_text(encoding="utf-8")
        save_block = js[js.index("function saveLayout()") : js.index("function initResizableModules()")]
        self.assertIn("version: 2", save_block)
        self.assertIn("span: moduleSpan(module)", save_block)
        self.assertIn("height:", save_block)
        self.assertNotIn("top:", save_block)
        self.assertNotIn("left:", save_block)
        self.assertNotIn("width:", save_block)
        self.assertIn("schedulePack()", js)

    def test_resizing_right_ranking_does_not_push_left_race_and_gaps_stay_twelve(self) -> None:
        defaults = [
            ("heatmap", 7, 620),
            ("inflow", 3, 335),
            ("outflow", 3, 335),
            ("race", 7, 540),
            ("core", 3, 430),
            ("liquidity", 10, 900),
        ]
        taller_outflow = [item if item[0] != "outflow" else ("outflow", 3, 450) for item in defaults]
        before = _dense_pack(defaults)
        after = _dense_pack(taller_outflow)

        self.assertEqual(before["race"][0], after["race"][0])
        self.assertEqual(before["race"][0] - (before["heatmap"][0] + before["heatmap"][2]), 12)
        self.assertEqual(before["outflow"][0] - (before["inflow"][0] + before["inflow"][2]), 12)
        self.assertEqual(after["core"][0] - (after["outflow"][0] + after["outflow"][2]), 12)


if __name__ == "__main__":
    unittest.main()
