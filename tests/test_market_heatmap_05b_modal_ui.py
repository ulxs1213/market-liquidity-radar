from __future__ import annotations

import unittest
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "src" / "market_liquidity_radar" / "web" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "src" / "market_liquidity_radar" / "web" / "static" / "market_heatmap.js").read_text(encoding="utf-8")
CSS = (ROOT / "src" / "market_liquidity_radar" / "web" / "static" / "market_heatmap.css").read_text(encoding="utf-8")


class _IdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, _tag: str, attrs) -> None:
        value = dict(attrs).get("id")
        if value:
            self.ids.append(value)


class MarketHeatmap05BModalUiContractTest(unittest.TestCase):
    def test_modal_reuses_one_complete_workspace_without_duplicate_ids(self) -> None:
        parser = _IdParser()
        parser.feed(HTML)
        duplicates = {key: count for key, count in Counter(parser.ids).items() if count > 1}
        self.assertEqual(duplicates, {})
        self.assertEqual(HTML.count('id="stockTerminalWorkspace"'), 1)
        self.assertEqual(HTML.count('id="stockTimeline"'), 1)
        self.assertEqual(HTML.count('id="orderBookRows"'), 1)
        workspace = HTML[HTML.index('id="stockTerminalWorkspace"') : HTML.index('<div class="watch-queues">')]
        self.assertIn('class="intraday-title"', workspace)
        self.assertIn('id="auctionToggle"', workspace)
        self.assertIn('id="stockTerminal"', workspace)
        self.assertIn('id="stockDetailSource"', workspace)
        self.assertIn('class="order-book"', workspace)

    def test_dialog_has_aria_title_source_and_three_close_paths(self) -> None:
        dialog_tag = HTML[HTML.index('<dialog id="stockTerminalDialog"') : HTML.index(">", HTML.index('<dialog id="stockTerminalDialog"')) + 1]
        self.assertIn('role="dialog"', dialog_tag)
        self.assertIn('aria-modal="true"', dialog_tag)
        self.assertIn('aria-labelledby="stockTerminalDialogTitle"', dialog_tag)
        self.assertIn('aria-describedby="stockTerminalDialogSource"', dialog_tag)
        self.assertIn('id="stockTerminalClose"', HTML)
        bind = JS[JS.index("function bindStockTerminalDialog()") : JS.index("loadPreferences();")]
        self.assertIn('closeButton?.addEventListener("click"', bind)
        self.assertIn('dialog.addEventListener("cancel"', bind)
        self.assertIn('if (event.target === dialog) restore()', bind)

    def test_workspace_is_moved_not_cloned_and_focus_scroll_are_restored(self) -> None:
        bind = JS[JS.index("function bindStockTerminalDialog()") : JS.index("loadPreferences();")]
        self.assertIn('const terminal = $("stockTerminalWorkspace")', bind)
        self.assertIn("modalMount.appendChild(terminal)", bind)
        self.assertIn("home.appendChild(terminal)", bind)
        self.assertNotIn("cloneNode", bind)
        self.assertIn("returnScrollY = window.scrollY", bind)
        self.assertIn("window.scrollTo({ top: returnScrollY", bind)
        self.assertIn("returnFocus?.isConnected", bind)
        self.assertIn('if (event.key !== "Tab") return', bind)
        self.assertIn("focusTarget.focus({ preventScroll: true })", bind)

    def test_all_sector_and_stock_surfaces_have_double_click_routes(self) -> None:
        self.assertGreaterEqual(JS.count('data-entity-kind="sector"'), 2)
        self.assertGreaterEqual(JS.count('data-entity-kind="stock"'), 1)
        self.assertIn('document.addEventListener("dblclick"', JS)
        self.assertIn('sectorChart.on("dblclick"', JS)
        self.assertIn('timelineChart.on("dblclick"', JS)
        self.assertIn('stockChart.on("dblclick"', JS)
        self.assertIn('scatterChart.on("dblclick"', JS)
        self.assertIn("openSectorTarget(target.dataset.code, target)", JS)
        self.assertIn("openStockTarget({ code: target.dataset.code", JS)

    def test_dom_double_click_is_not_destroyed_by_first_click_rerender(self) -> None:
        helper = JS[JS.index("function bindSingleAndDouble") : JS.index("function renderSummary")]
        self.assertIn('if (event.detail > 1) return', helper)
        self.assertIn('event.stopPropagation()', helper)
        self.assertIn('setTimeout(() =>', helper)
        self.assertIn('() => openSectorTarget(node.dataset.code, node)', JS)
        self.assertIn('() => openSectorTarget(button.dataset.raceCode, button)', JS)
        self.assertIn('bindSingleAndDouble(node, () => selectStock(stock()), () => openStockTarget(stock(), node))', JS)

    def test_sector_route_waits_for_core_stocks_then_opens_selected_terminal(self) -> None:
        route = JS[JS.index("async function openStockTarget") : JS.index("function bindEntityDoubleClicks")]
        self.assertIn("detail = await selectSector(code, false)", route)
        self.assertIn("detail?.stocks", route)
        self.assertIn("sort((a, b) => Number(b.amount || 0) - Number(a.amount || 0))", route)
        self.assertIn("return openStockTarget(target, origin)", route)
        self.assertIn("stockTerminalDialogController?.open(origin)", route)

    def test_modal_css_keeps_full_workspace_and_hides_recursive_open_button(self) -> None:
        self.assertIn(".stock-terminal-modal-mount .stock-terminal-workspace", CSS)
        self.assertIn(".stock-terminal-modal-mount .intraday-title", CSS)
        self.assertIn(".stock-terminal-modal-mount #stockTerminalOpen{display:none}", CSS)
        self.assertIn(".terminal-dialog :focus-visible", CSS)


if __name__ == "__main__":
    unittest.main()
