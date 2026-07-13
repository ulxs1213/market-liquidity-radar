from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "src" / "market_liquidity_radar" / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "src" / "market_liquidity_radar" / "web" / "static" / "market_heatmap.css").read_text(encoding="utf-8")
JS = (ROOT / "src" / "market_liquidity_radar" / "web" / "static" / "market_heatmap.js").read_text(encoding="utf-8")
TIMELINE = JS[JS.index("function renderStockTimeline") : JS.index("function renderOrderBook")]


def _rgb(value: str) -> tuple[float, float, float]:
    raw = value.lstrip("#")
    if len(raw) == 3:
        raw = "".join(char * 2 for char in raw)
    return tuple(int(raw[index : index + 2], 16) / 255 for index in (0, 2, 4))


def _luminance(value: str) -> float:
    components = [item / 12.92 if item <= 0.04045 else ((item + 0.055) / 1.055) ** 2.4 for item in _rgb(value)]
    return 0.2126 * components[0] + 0.7152 * components[1] + 0.0722 * components[2]


def _contrast(foreground: str, background: str) -> float:
    high, low = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _theme_variables(theme: str) -> tuple[str, dict[str, str]]:
    start = CSS.index(f':root[data-theme="{theme}"]')
    block = CSS[start : CSS.index("\n}", start)]
    scheme = re.search(r"color-scheme:(light|dark)", block).group(1)
    values = dict(re.findall(r"--([\w-]+):(#[0-9a-fA-F]{3,6})", block))
    return scheme, values


class MarketHeatmapCrossQaBTest(unittest.TestCase):
    def test_t1_has_exactly_three_light_and_four_dark_themes(self) -> None:
        buttons = re.findall(r'data-theme-choice="([^"]+)"', HTML)
        self.assertEqual(buttons, ["cloud", "mist", "sand", "ink", "slate", "midnight", "terminal"])
        schemes = [_theme_variables(theme)[0] for theme in buttons]
        self.assertEqual(schemes.count("light"), 3)
        self.assertEqual(schemes.count("dark"), 4)
        self.assertEqual(JS.count('const THEMES = ["cloud", "mist", "sand", "ink", "slate", "midnight", "terminal"]'), 1)

    def test_t1_theme_persistence_aria_and_legacy_aliases_are_wired(self) -> None:
        self.assertIn('const THEME_ALIASES = { ocean: "midnight", violet: "slate" }', JS)
        self.assertIn("localStorage.setItem(PREF_KEY", JS)
        self.assertIn("const savedTheme = THEME_ALIASES[saved.theme] || saved.theme", JS)
        self.assertIn("document.documentElement.dataset.theme = STATE.theme", JS)
        self.assertIn('button.setAttribute("aria-pressed", String(active))', JS)
        for theme in ("cloud", "mist", "sand", "ink", "slate", "midnight", "terminal"):
            self.assertIn(f'[data-theme-choice="{theme}"]', CSS)

    def test_t1_body_and_secondary_text_meet_wcag_aa_on_dashboard_surfaces(self) -> None:
        for theme in ("cloud", "mist", "sand", "ink", "slate", "midnight", "terminal"):
            _scheme, values = _theme_variables(theme)
            self.assertGreaterEqual(_contrast(values["text"], values["panel"]), 7.0, theme)
            for surface in ("panel", "surface", "control"):
                self.assertGreaterEqual(_contrast(values["muted"], values[surface]), 4.5, f"{theme}/{surface}")

    def test_c1_tooltip_has_one_time_slice_with_all_required_factual_fields(self) -> None:
        for label in ("最新价：", "当日均价：", "分钟成交量：", "累计主力净流：", "本分钟净流变化："):
            self.assertEqual(TIMELINE.count(label), 1, label)
        self.assertIn("priceByTime.get(time)", TIMELINE)
        self.assertIn("flowByTime.get(time)", TIMELINE)
        self.assertIn('trigger: "axis"', TIMELINE)
        self.assertIn("tooltipFormatter", TIMELINE)
        self.assertIn("成交量口径：", TIMELINE)
        self.assertIn("不拆成或伪造成总流入/总流出", TIMELINE)

    def test_c2_three_grids_link_and_first_flow_delta_is_unknown_not_zero(self) -> None:
        self.assertIn("link: [{ xAxisIndex: [0, 1, 2] }]", TIMELINE)
        self.assertEqual(TIMELINE.count('axisPointer: { show: true, type: "line", snap: true }'), 3)
        self.assertIn("const delta = previousFlow == null ? null : current - previousFlow", TIMELINE)
        self.assertIn("value == null ? null", TIMELINE)
        self.assertIn("首个可用资金点，无法计算相邻变化", TIMELINE)
        self.assertNotIn("previousFlow == null ? 0", TIMELINE)

    def test_c2_hover_survives_refresh_and_same_chart_dom_move(self) -> None:
        self.assertIn("if (timelineSignature !== STATE.lastStockTimelineSignature)", TIMELINE)
        self.assertIn("STATE.stockHoverActive && hoverIndex >= 0", TIMELINE)
        self.assertIn('dispatchAction({ type: "showTip", seriesIndex, dataIndex: hoverIndex })', TIMELINE)
        self.assertIn("if (STATE.interacting)", JS)
        self.assertIn("STATE.deferredPayload = payload", JS)
        self.assertEqual(JS.count('echarts.init($("stockTimeline"))'), 1)
        self.assertEqual(HTML.count('id="stockTimeline"'), 1)
        self.assertIn('const terminal = $("stockTerminalWorkspace")', JS)
        self.assertIn("modalMount.appendChild(terminal)", JS)
        self.assertIn('stockTimelineChart.on("updateAxisPointer"', JS)


if __name__ == "__main__":
    unittest.main()
