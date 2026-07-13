from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "market_liquidity_radar" / "web"
HTML = (WEB / "index.html").read_text(encoding="utf-8")
CSS = (WEB / "static" / "market_heatmap.css").read_text(encoding="utf-8")
JS = (WEB / "static" / "market_heatmap.js").read_text(encoding="utf-8")

PRESETS = ["cloud", "mist", "sand", "ink", "slate", "midnight", "red", "rose", "prismatic"]
ALL_THEME_CHOICES = [*PRESETS, "custom"]


def _block(start_marker: str, end_marker: str) -> str:
    start = JS.index(start_marker)
    return JS[start : JS.index(end_marker, start)]


def _production_custom_theme_tokens(samples: list[dict[str, object]]) -> list[dict[str, str]]:
    """Execute the production color algorithm itself, isolated from browser globals."""
    default_start = JS.index("const DEFAULT_CUSTOM_THEME")
    default_statement = JS[default_start : JS.index("\n", default_start)]
    color_functions = _block("const clamp =", "const clearCustomThemeVars")
    program = "\n".join(
        (
            default_statement,
            color_functions,
            f"const __samples = {json.dumps(samples)};",
            "globalThis.__result = __samples.map(sample => customThemeTokens(sample).tokens);",
        )
    )
    runner = (
        'const vm=require("node:vm");'
        "const context={};"
        f"vm.runInNewContext({json.dumps(program)},context);"
        "process.stdout.write(JSON.stringify(context.__result));"
    )
    node = shutil.which("node") or "/Users/ulxs/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
    completed = subprocess.run(
        [node, "-e", runner],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return json.loads(completed.stdout)


def _rgb(value: str) -> tuple[float, float, float]:
    raw = value.lstrip("#")
    return tuple(int(raw[index : index + 2], 16) / 255 for index in (0, 2, 4))


def _luminance(value: str) -> float:
    components = [item / 12.92 if item <= 0.04045 else ((item + 0.055) / 1.055) ** 2.4 for item in _rgb(value)]
    return 0.2126 * components[0] + 0.7152 * components[1] + 0.0722 * components[2]


def _contrast(foreground: str, background: str) -> float:
    high, low = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class _IdAndAttributeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.attributes_by_id: dict[str, dict[str, str | None]] = {}

    def handle_starttag(self, _tag: str, attrs) -> None:
        values = dict(attrs)
        node_id = values.get("id")
        if node_id:
            self.ids.append(node_id)
            self.attributes_by_id[node_id] = values


class MarketHeatmapThemeCustomizerUiContractTest(unittest.TestCase):
    def test_terminal_preset_is_removed_but_legacy_preference_maps_to_midnight(self) -> None:
        buttons = re.findall(r'data-theme-choice="([^"]+)"', HTML)
        self.assertNotIn("terminal", buttons)
        self.assertNotIn('[data-theme-choice="terminal"]', CSS)
        themes_declaration = re.search(r"const THEMES = \[([^;]+)\];", JS)
        self.assertIsNotNone(themes_declaration)
        self.assertNotIn("terminal", themes_declaration.group(1))
        self.assertIn('terminal: "midnight"', JS)
        self.assertIn("const savedTheme = THEME_ALIASES[saved.theme] || saved.theme", JS)

    def test_nine_presets_then_custom_are_exposed_in_one_stable_order(self) -> None:
        self.assertEqual(re.findall(r'data-theme-choice="([^"]+)"', HTML), ALL_THEME_CHOICES)
        self.assertIn(
            'const THEMES = ["cloud", "mist", "sand", "ink", "slate", "midnight", "red", "rose", "prismatic", "custom"]',
            JS,
        )
        for theme in ("red", "rose", "prismatic", "custom"):
            self.assertEqual(HTML.count(f'data-theme-choice="{theme}"'), 1)
            self.assertEqual(CSS.count(f':root[data-theme="{theme}"]'), 1)
            self.assertEqual(CSS.count(f'[data-theme-choice="{theme}"]'), 1)

    def test_custom_editor_ids_are_unique_and_controls_have_accessible_contracts(self) -> None:
        parser = _IdAndAttributeParser()
        parser.feed(HTML)
        counts = Counter(parser.ids)
        custom_ids = {
            "customThemeButton",
            "customThemePanel",
            "customThemeClose",
            "customColorField",
            "customColorCursor",
            "customHue",
            "customHex",
            "customThemeName",
            "customPreviewAccent",
            "customPreviewSurface",
            "customPreviewCompanion",
            "customPreviewLabel",
            "customThemeReset",
            "customThemeCancel",
            "customThemeSave",
        }
        for node_id in custom_ids:
            self.assertEqual(counts[node_id], 1, node_id)

        button = parser.attributes_by_id["customThemeButton"]
        self.assertEqual(button["aria-controls"], "customThemePanel")
        self.assertEqual(button["aria-expanded"], "false")
        self.assertEqual(button["aria-pressed"], "false")
        self.assertTrue(button["aria-label"])

        panel = parser.attributes_by_id["customThemePanel"]
        self.assertIn("hidden", panel)
        self.assertTrue(panel["aria-label"])

        field = parser.attributes_by_id["customColorField"]
        self.assertEqual(field["role"], "slider")
        self.assertEqual(field["tabindex"], "0")
        for attribute in ("aria-label", "aria-valuemin", "aria-valuemax", "aria-valuenow", "aria-valuetext"):
            self.assertIn(attribute, field)

        self.assertEqual(parser.attributes_by_id["customColorCursor"]["aria-hidden"], "true")
        self.assertEqual(parser.attributes_by_id["customHue"]["type"], "range")
        self.assertEqual(parser.attributes_by_id["customHex"]["aria-label"], "自定义主题十六进制颜色")
        self.assertEqual(parser.attributes_by_id["customThemeName"]["maxlength"], "12")
        self.assertIn('class="custom-theme-preview" aria-live="polite"', HTML)
        self.assertIn('role="group" aria-label="自定义主题明暗模式"', HTML)

    def test_dragging_uses_pointer_capture_interaction_guard_and_raf_coalescing(self) -> None:
        bind = _block("function bindCustomThemeEditor()", "function bindDialog(")
        preview = _block("function previewCustomTheme", "function openCustomThemeEditor")
        self.assertIn("field.setPointerCapture?.(event.pointerId)", bind)
        self.assertIn("field.releasePointerCapture?.(event.pointerId)", bind)
        self.assertIn("setInteracting(true)", bind)
        self.assertIn("setInteracting(false)", bind)
        self.assertIn('field.addEventListener("pointermove"', bind)
        self.assertIn('field.addEventListener("pointercancel", finishDrag)', bind)
        self.assertIn("cancelAnimationFrame(STATE.customThemeFrame)", preview)
        self.assertIn("STATE.customThemeFrame = requestAnimationFrame(() =>", preview)

    def test_pointer_move_and_hue_input_do_not_persist_or_trigger_full_chart_render(self) -> None:
        field_update = _block("function updateCustomThemeFromField", "function bindCustomThemeEditor")
        bind = _block("function bindCustomThemeEditor()", "function bindDialog(")
        pointer_move = re.search(
            r'field\.addEventListener\("pointermove", event => \{([^\n]+)\}\);',
            bind,
        )
        hue_input = re.search(
            r'hueInput\?\.addEventListener\("input", event => \{(.*?)\n    \}\);',
            bind,
            re.DOTALL,
        )
        self.assertIsNotNone(pointer_move)
        self.assertIsNotNone(hue_input)
        self.assertIn("updateCustomThemeFromField(event)", pointer_move.group(1))
        self.assertIn("previewCustomTheme(false)", field_update)
        self.assertNotIn("savePreferences", field_update)
        self.assertNotIn("refreshThemeCharts", field_update)
        self.assertIn("previewCustomTheme(false)", hue_input.group(1))
        self.assertNotIn("savePreferences", hue_input.group(1))
        self.assertNotIn("refreshThemeCharts", hue_input.group(1))

        preview = _block("function previewCustomTheme", "function openCustomThemeEditor")
        self.assertIn("if (refreshCharts) refreshThemeCharts()", preview)

    def test_custom_draft_is_persisted_only_by_save_and_cancel_or_escape_restores(self) -> None:
        opening = _block("function openCustomThemeEditor", "function cancelCustomThemeEditor")
        cancel = _block("function cancelCustomThemeEditor", "function saveCustomTheme")
        save = _block("function saveCustomTheme", "function resetCustomThemeDraft")
        bind = _block("function bindCustomThemeEditor()", "function bindDialog(")

        self.assertIn('applyTheme("custom", { persist: false, keepEditorOpen: true })', opening)
        self.assertNotIn("savePreferences", opening)
        self.assertIn("STATE.customTheme = { ...STATE.customThemeSaved }", cancel)
        self.assertIn("STATE.customThemePrevious", cancel)
        self.assertIn("applyTheme(previous, { persist: false })", cancel)
        self.assertNotIn("savePreferences", cancel)

        self.assertIn("STATE.customThemeSaved = sanitizeCustomTheme(STATE.customTheme)", save)
        self.assertIn('applyTheme("custom")', save)
        apply_theme = _block("function applyTheme", "function updateCustomThemeControls")
        self.assertIn("if (options.persist !== false) savePreferences()", apply_theme)
        self.assertIn('if (event.key === "Escape") { event.preventDefault(); cancelCustomThemeEditor(); }', bind)
        self.assertIn('$("customThemeCancel")?.addEventListener("click", cancelCustomThemeEditor)', bind)

    def test_visible_accent_guard_handles_low_contrast_extreme_custom_colors(self) -> None:
        tokens = _block("const customThemeTokens", "const clearCustomThemeVars")
        color_math = _block("const relativeLuminance", "const sanitizeCustomTheme")
        self.assertIn("const relativeLuminance", color_math)
        self.assertIn("const contrastRatio", color_math)
        self.assertIn("const contrastSafeColor", color_math)
        self.assertIn('contrastSafeColor(accent, [panel, bg], "#ffffff")', tokens)
        self.assertIn('contrastSafeColor(accent, [panel, bg], "#000000")', tokens)
        self.assertEqual(tokens.count('"--mint": visibleAccent'), 2)
        self.assertIn(".mini-button.primary{color:var(--bg)}", CSS)
        self.assertIn(".source-strip .badge:not(.error):not(.muted){color:var(--bg)}", CSS)

    def test_production_custom_tokens_meet_contrast_contract_for_extreme_colors(self) -> None:
        colors = [
            ("white", "#ffffff", 0, 0, 100),
            ("black", "#000000", 0, 0, 0),
            ("gray", "#808080", 0, 0, 50),
            ("yellow", "#ffff00", 60, 100, 100),
            ("cyan", "#00ffff", 180, 100, 100),
            ("blue", "#0000ff", 240, 100, 100),
            ("hsv-60-35-70", "#b3b374", 60, 35, 70),
        ]
        samples = [
            {
                "name": name,
                "hex": hex_value,
                "hue": hue,
                "saturation": saturation,
                "value": value,
                "mode": mode,
            }
            for mode in ("light", "dark")
            for name, hex_value, hue, saturation, value in colors
        ]
        token_sets = _production_custom_theme_tokens(samples)
        self.assertEqual(len(token_sets), len(samples))

        for sample, tokens in zip(samples, token_sets):
            case = f"{sample['mode']}/{sample['name']}"
            for surface in ("--panel", "--surface", "--control"):
                with self.subTest(case=case, contract=f"text/{surface}"):
                    self.assertGreaterEqual(_contrast(tokens["--text"], tokens[surface]), 7.0)
                with self.subTest(case=case, contract=f"muted/{surface}"):
                    self.assertGreaterEqual(_contrast(tokens["--muted"], tokens[surface]), 4.5)
            for semantic in ("--mint", "--up", "--down"):
                with self.subTest(case=case, contract=f"{semantic}/panel"):
                    self.assertGreaterEqual(_contrast(tokens[semantic], tokens["--panel"]), 4.5)
            with self.subTest(case=case, contract="active-text/accent"):
                self.assertGreaterEqual(_contrast(tokens["--bg"], tokens["--mint"]), 4.5)

    def test_theme_commit_invalidates_race_and_05b_without_reinitializing_echarts(self) -> None:
        refresh = _block("function refreshThemeCharts", "function hideCustomThemePanel")
        self.assertIn('STATE.lastRaceSignature = ""', refresh)
        self.assertIn('STATE.lastStockTimelineSignature = ""', refresh)
        self.assertIn("STATE.stockHoverActive = false", refresh)
        self.assertIn('STATE.stockHoverTime = ""', refresh)
        self.assertIn('stockTimelineChart.getZr().trigger("globalout", { event: {} })', refresh)
        self.assertIn('stockTimelineChart.dispatchAction({ type: "hideTip" })', refresh)
        self.assertIn("STATE.stockThemeRefreshNotBefore = Date.now() + 1800", refresh)
        self.assertIn("STATE.stockThemeRefreshTimer = setTimeout(() =>", refresh)
        self.assertIn("STATE.themeChartRefreshNotBefore = Date.now() + 500", refresh)
        self.assertIn("STATE.themeChartRefreshTimer = setTimeout(() =>", refresh)
        self.assertIn("requestAnimationFrame(() => requestAnimationFrame(() =>", refresh)
        self.assertIn("renderRace(STATE.racePayload)", refresh)
        self.assertIn("renderStockTimeline(STATE.currentStockPayload)", refresh)
        first_frame = refresh.split("STATE.stockThemeRefreshTimer = setTimeout", 1)[1].split("requestAnimationFrame", 1)[1]
        self.assertNotIn("renderStockTimeline(STATE.currentStockPayload)", first_frame)
        self.assertNotIn("echarts.init", refresh)

        expected_targets = ["sectorTreemap", "stockTreemap", "flowTimeline", "liquidityScatter", "stockTimeline"]
        self.assertEqual(JS.count("echarts.init("), len(expected_targets))
        for target in expected_targets:
            self.assertEqual(JS.count(f'echarts.init($("{target}"))'), 1, target)

    def test_theme_assets_use_the_20260714_30_cache_version(self) -> None:
        self.assertEqual(HTML.count("20260714.30"), 2)
        self.assertIn('href="/static/market_heatmap.css?v=20260714.30"', HTML)
        self.assertIn('src="/static/market_heatmap.js?v=20260714.30"', HTML)


if __name__ == "__main__":
    unittest.main()
