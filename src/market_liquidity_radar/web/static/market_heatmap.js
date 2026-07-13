(() => {
  const $ = (id) => document.getElementById(id);
  const STATE = {
    boardType: "industry",
    sectors: [],
    selectedCode: "",
    selectedName: "",
    selectedStockCode: "",
    selectedStockMarket: "",
    selectedStockName: "",
    paused: false,
    loading: false,
    pendingRefresh: false,
    refreshSeq: 0,
    sectorRequestSeq: 0,
    stockRequestSeq: 0,
    raceTradeDate: "",
    raceDates: [],
    raceLimit: 5,
    raceScaleMode: "independent",
    heatmapLimit: 10,
    heatmapDetail: 1,
    stockLimit: 20,
    stockDetail: 1,
    liquidityColorMode: "industry",
    liquidityLimit: 50,
    theme: "cloud",
    customTheme: { name: "我的主题", hex: "#d84a68", hue: 350, saturation: 66, value: 85, mode: "light" },
    customThemeSaved: { name: "我的主题", hex: "#d84a68", hue: 350, saturation: 66, value: 85, mode: "light" },
    customThemePrevious: "cloud",
    customThemeDragging: false,
    customThemeFrame: 0,
    showAuction: false,
    currentStockPayload: null,
    stockHoverActive: false,
    stockHoverTime: "",
    lastStockTimelineSignature: "",
    stockThemeRefreshTimer: 0,
    stockThemeRefreshNotBefore: 0,
    themeChartRefreshTimer: 0,
    themeChartRefreshNotBefore: 0,
    sparklines: new Map(),
    sparkRequestSeq: 0,
    selectedSectorDetail: null,
    selectedSectorDetailCode: "",
    raceSeriesByCode: new Map(),
    racePayload: null,
    lastRaceSignature: "",
    liquidity: null,
    sources: null,
    interacting: false,
    pointerInside: false,
    deferredPayload: null,
    deferredRace: null,
    interactionTimer: 0,
    lastHeavyRenderAt: 0,
    lastHeavyFetchAt: 0,
    lastSourceRenderAt: 0,
    lastDetailFetchAt: 0,
    replayMode: false,
    replayPlaying: false,
    replayManifest: null,
    replayIndex: 0,
    replaySpeed: 1,
    replayTimer: 0,
    replayRequestSeq: 0,
    timer: 0,
    interval: 3000,
    heavyInterval: 12000,
  };
  const sectorChart = echarts.init($("sectorTreemap"));
  const stockChart = echarts.init($("stockTreemap"));
  const timelineChart = echarts.init($("flowTimeline"));
  const scatterChart = echarts.init($("liquidityScatter"));
  const stockTimelineChart = echarts.init($("stockTimeline"));
  const COUNT_CHOICES = [10, 20, 30, 0];
  const RACE_CHOICES = [5, 10, 20, 0];
  const LIQUIDITY_CHOICES = [30, 50, 100, 200, 500];
  const THEMES = ["cloud", "mist", "sand", "ink", "slate", "midnight", "red", "rose", "prismatic", "custom"];
  const THEME_ALIASES = { ocean: "midnight", violet: "slate", terminal: "midnight" };
  const DEFAULT_CUSTOM_THEME = Object.freeze({ name: "我的主题", hex: "#d84a68", hue: 350, saturation: 66, value: 85, mode: "light" });
  const CUSTOM_THEME_PROPERTIES = ["--bg", "--bg-accent", "--panel", "--panel-2", "--panel-gradient-a", "--panel-gradient-b", "--surface", "--control", "--topbar", "--line", "--line-soft", "--text", "--muted", "--mint", "--mint-2", "--up", "--down", "--amber", "--panel-shadow", "--overlay", "--status-bg", "--dialog-bg"];
  const DETAIL_LABELS = ["简洁", "标准", "详细"];
  const LAYOUT_KEY = "market-liquidity-radar-layout-v1";
  const PREF_KEY = "market-liquidity-radar-preferences-v2";
  const PACK_COLUMNS = 10;
  const PACK_GAP = 12;
  let packFrame = 0;
  let stockTerminalDialogController = null;

  const fmtMoney = (value) => {
    const n = Number(value || 0);
    if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)}亿`;
    if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(0)}万`;
    return n.toFixed(0);
  };
  const fmtYiInteger = value => {
    const rounded = Math.round(Number(value || 0) / 1e8);
    return `${Object.is(rounded, -0) ? 0 : rounded}亿`;
  };
  const fmtVolumeLots = value => {
    const lots = Number(value);
    if (!Number.isFinite(lots) || lots <= 0) return "--";
    if (lots >= 1e8) return `${(lots / 1e8).toFixed(2)}亿手`;
    if (lots >= 1e4) return `${(lots / 1e4).toFixed(2)}万手`;
    return `${Math.round(lots).toLocaleString("zh-CN")}手`;
  };
  const fmtVolumeAxis = value => {
    const lots = Number(value);
    if (!Number.isFinite(lots) || lots <= 0) return "0";
    if (lots >= 1e8) return `${Number((lots / 1e8).toPrecision(2))}亿`;
    if (lots >= 1e4) return `${Number((lots / 1e4).toPrecision(2))}万`;
    return String(Math.round(lots));
  };
  const fmtSharesFromLots = value => {
    const shares = Number(value) * 100;
    if (!Number.isFinite(shares) || shares <= 0) return "--";
    if (shares >= 1e8) return `${(shares / 1e8).toFixed(2)}亿股`;
    if (shares >= 1e4) return `${(shares / 1e4).toFixed(2)}万股`;
    return `${Math.round(shares).toLocaleString("zh-CN")}股`;
  };
  const fmtPct = (value) => `${Number(value || 0) >= 0 ? "+" : ""}${Number(value || 0).toFixed(2)}%`;
  const clamp = (value, minimum, maximum) => Math.max(minimum, Math.min(maximum, Number(value)));
  const normalizeHex = value => {
    const raw = String(value || "").trim().replace(/^#/, "");
    if (/^[0-9a-f]{3}$/i.test(raw)) return `#${raw.split("").map(char => char + char).join("")}`.toLowerCase();
    return /^[0-9a-f]{6}$/i.test(raw) ? `#${raw.toLowerCase()}` : "";
  };
  const hexToRgb = value => {
    const hex = normalizeHex(value) || DEFAULT_CUSTOM_THEME.hex;
    return [1, 3, 5].map(index => Number.parseInt(hex.slice(index, index + 2), 16));
  };
  const rgbToHex = rgb => `#${rgb.map(value => Math.round(clamp(value, 0, 255)).toString(16).padStart(2, "0")).join("")}`;
  const hsvToHex = (hue, saturation, value) => {
    const h = ((Number(hue) % 360) + 360) % 360;
    const s = clamp(saturation, 0, 100) / 100;
    const v = clamp(value, 0, 100) / 100;
    const chroma = v * s;
    const section = h / 60;
    const x = chroma * (1 - Math.abs(section % 2 - 1));
    const [r1, g1, b1] = section < 1 ? [chroma, x, 0] : section < 2 ? [x, chroma, 0] : section < 3 ? [0, chroma, x] : section < 4 ? [0, x, chroma] : section < 5 ? [x, 0, chroma] : [chroma, 0, x];
    const offset = v - chroma;
    return rgbToHex([(r1 + offset) * 255, (g1 + offset) * 255, (b1 + offset) * 255]);
  };
  const hexToHsv = value => {
    const [red, green, blue] = hexToRgb(value).map(channel => channel / 255);
    const maximum = Math.max(red, green, blue);
    const minimum = Math.min(red, green, blue);
    const delta = maximum - minimum;
    let hue = 0;
    if (delta) {
      if (maximum === red) hue = 60 * (((green - blue) / delta) % 6);
      else if (maximum === green) hue = 60 * ((blue - red) / delta + 2);
      else hue = 60 * ((red - green) / delta + 4);
    }
    return { hue: Math.round((hue + 360) % 360), saturation: Math.round(maximum ? delta / maximum * 100 : 0), value: Math.round(maximum * 100) };
  };
  const mixHex = (from, to, amount) => {
    const start = hexToRgb(from);
    const end = hexToRgb(to);
    const weight = clamp(amount, 0, 1);
    return rgbToHex(start.map((value, index) => value + (end[index] - value) * weight));
  };
  const relativeLuminance = value => {
    const channels = hexToRgb(value).map(channel => {
      const normalized = channel / 255;
      return normalized <= .04045 ? normalized / 12.92 : ((normalized + .055) / 1.055) ** 2.4;
    });
    return .2126 * channels[0] + .7152 * channels[1] + .0722 * channels[2];
  };
  const contrastRatio = (foreground, background) => {
    const values = [relativeLuminance(foreground), relativeLuminance(background)].sort((a, b) => b - a);
    return (values[0] + .05) / (values[1] + .05);
  };
  const contrastSafeColor = (color, surfaces, toward, minimum = 4.5) => {
    const backgrounds = Array.isArray(surfaces) ? surfaces : [surfaces];
    const passes = candidate => backgrounds.every(surface => contrastRatio(candidate, surface) >= minimum);
    if (passes(color)) return color;
    for (let step = 1; step <= 24; step += 1) {
      const candidate = mixHex(color, toward, step / 24);
      if (passes(candidate)) return candidate;
    }
    return toward;
  };
  const sanitizeCustomTheme = value => {
    const input = value && typeof value === "object" ? value : {};
    const hex = normalizeHex(input.hex) || DEFAULT_CUSTOM_THEME.hex;
    const derived = hexToHsv(hex);
    return {
      name: String(input.name || DEFAULT_CUSTOM_THEME.name).trim().slice(0, 12) || DEFAULT_CUSTOM_THEME.name,
      hex,
      hue: clamp(Number.isFinite(Number(input.hue)) ? input.hue : derived.hue, 0, 359),
      saturation: clamp(Number.isFinite(Number(input.saturation)) ? input.saturation : derived.saturation, 0, 100),
      value: clamp(Number.isFinite(Number(input.value)) ? input.value : derived.value, 0, 100),
      mode: input.mode === "dark" ? "dark" : "light",
    };
  };
  const customThemeTokens = rawTheme => {
    const theme = sanitizeCustomTheme(rawTheme);
    const accent = theme.hex;
    const companion = hsvToHex((theme.hue + 46) % 360, Math.max(30, theme.saturation * .72), theme.mode === "dark" ? 76 : 72);
    if (theme.mode === "dark") {
      const bg = mixHex(accent, "#08070a", .94);
      const bgAccent = mixHex(companion, "#08070a", .94);
      const panel = mixHex(accent, "#151217", .92);
      const panel2 = mixHex(accent, "#1b171d", .89);
      const surface = mixHex(accent, "#0f0c11", .94);
      const control = mixHex(accent, "#211c23", .90);
      const visibleAccent = contrastSafeColor(accent, [panel, bg], "#ffffff");
      return { companion, tokens: {
        "--bg": bg, "--bg-accent": bgAccent, "--panel": panel, "--panel-2": panel2,
        "--panel-gradient-a": panel, "--panel-gradient-b": mixHex(companion, "#171319", .91),
        "--surface": surface, "--control": control, "--topbar": panel,
        "--line": mixHex(panel, "#ffffff", .19), "--line-soft": `color-mix(in srgb,${mixHex(panel, "#ffffff", .19)} 76%,transparent)`,
        "--text": "#fff4f6", "--muted": "#cdb9c0", "--mint": visibleAccent, "--mint-2": mixHex(visibleAccent, panel, .52),
        "--up": "#ff7b72", "--down": "#55c69a", "--amber": "#e5b968", "--panel-shadow": "0 1px 3px rgba(0,0,0,.30)",
        "--overlay": "rgba(5,2,4,.74)", "--status-bg": `color-mix(in srgb,${visibleAccent} 11%,transparent)`, "--dialog-bg": panel,
      } };
    }
    const bg = mixHex(accent, "#ffffff", .94);
    const bgAccent = mixHex(companion, "#ffffff", .94);
    const panel = mixHex(accent, "#ffffff", .985);
    const panel2 = mixHex(accent, "#ffffff", .95);
    const surface = mixHex(accent, "#ffffff", .97);
    const control = mixHex(accent, "#ffffff", .93);
    const visibleAccent = contrastSafeColor(accent, [panel, bg], "#000000");
    return { companion, tokens: {
      "--bg": bg, "--bg-accent": bgAccent, "--panel": panel, "--panel-2": panel2,
      "--panel-gradient-a": panel, "--panel-gradient-b": mixHex(companion, "#ffffff", .965),
      "--surface": surface, "--control": control, "--topbar": panel,
      "--line": mixHex("#30272b", "#ffffff", .74), "--line-soft": `color-mix(in srgb,${mixHex("#30272b", "#ffffff", .74)} 76%,transparent)`,
      "--text": "#30272b", "--muted": "#6d5c63", "--mint": visibleAccent, "--mint-2": mixHex(visibleAccent, "#ffffff", .58),
      "--up": "#c7253e", "--down": "#237a5b", "--amber": "#976117", "--panel-shadow": "0 1px 3px rgba(77,42,51,.08)",
      "--overlay": "rgba(48,39,43,.43)", "--status-bg": `color-mix(in srgb,${visibleAccent} 8%,transparent)`, "--dialog-bg": panel,
    } };
  };
  const clearCustomThemeVars = () => {
    CUSTOM_THEME_PROPERTIES.forEach(property => document.documentElement.style.removeProperty(property));
    document.documentElement.style.removeProperty("color-scheme");
  };
  const applyCustomThemeVars = rawTheme => {
    const theme = sanitizeCustomTheme(rawTheme);
    const { tokens } = customThemeTokens(theme);
    CUSTOM_THEME_PROPERTIES.forEach(property => document.documentElement.style.setProperty(property, tokens[property]));
    document.documentElement.style.setProperty("color-scheme", theme.mode);
    return theme;
  };
  const chartTheme = () => {
    const style = getComputedStyle(document.documentElement);
    const token = (name, fallback) => style.getPropertyValue(name).trim() || fallback;
    return {
      text: token("--text", "#e8f3ef"), muted: token("--muted", "#8ca59e"), panel: token("--panel", "#07110f"),
      surface: token("--surface", "#0d1d1a"), line: token("--line", "#295249"), mint: token("--mint", "#35d7b2"),
      mint2: token("--mint-2", "#24423d"), up: token("--up", "#e95f55"), down: token("--down", "#27b48f"), amber: token("--amber", "#efb85b"),
    };
  };
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  const fmtMetric = (row, metric) => {
    if (metric === "delta_flow") return fmtMoney(row[metric]);
    if (metric === "strength_score") return Number(row[metric] || 0).toFixed(2);
    return fmtPct(row[metric]);
  };
  const cls = (n) => Number(n) > 0 ? "up" : Number(n) < 0 ? "down" : "flat";
  const colorBy = (value, maxAbs) => {
    const x = Math.max(-1, Math.min(1, Number(value || 0) / Math.max(.0001, maxAbs)));
    if (x > 0) return `rgba(219,72,66,${.28 + .62 * x})`;
    if (x < 0) return `rgba(28,168,132,${.28 + .62 * Math.abs(x)})`;
    return "rgba(64,84,79,.72)";
  };
  const limitLabel = (value) => value ? `TOP${value}` : "全部";
  const timeText = value => String(value || "").slice(11, 16);
  const minuteRange = (startHour, startMinute, endHour, endMinute) => {
    const result = [];
    for (let minute = startHour * 60 + startMinute; minute <= endHour * 60 + endMinute; minute += 1) {
      result.push(`${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`);
    }
    return result;
  };
  const sessionCategories = (includeAuction = false) => [
    ...(includeAuction ? minuteRange(9, 15, 9, 29) : []),
    ...minuteRange(9, 30, 11, 30),
    ...minuteRange(13, 0, 15, 0),
  ];
  const sessionIndex = (value, includeAuction = false) => {
    const text = timeText(value);
    if (!/^\d{2}:\d{2}$/.test(text)) return -1;
    const [hour, minute] = text.split(":").map(Number);
    const total = hour * 60 + minute;
    const auctionOffset = includeAuction ? 15 : 0;
    if (includeAuction && total >= 555 && total < 570) return total - 555;
    if (total >= 570 && total <= 690) return auctionOffset + total - 570;
    if (total >= 780 && total <= 900) return auctionOffset + 121 + total - 780;
    return -1;
  };
  const tradingPoints = (points, timeKey = "time", includeAuction = false) => {
    const byTime = new Map();
    (points || []).forEach(point => {
      const rawTime = point?.[timeKey] || point?.time || point?.data_time || "";
      const index = sessionIndex(rawTime, includeAuction);
      if (index >= 0) byTime.set(timeText(rawTime), { ...point, _time: timeText(rawTime), _sessionIndex: index });
    });
    return [...byTime.values()].sort((a, b) => a._sessionIndex - b._sessionIndex);
  };
  const tradingCategories = (_groups, includeAuction = false) => sessionCategories(includeAuction);
  const payloadCategories = (payload, includeAuction = false) => {
    const labels = payload?.session_axis?.labels;
    const sameAuctionMode = Boolean(payload?.session_axis?.include_auction) === Boolean(includeAuction);
    return sameAuctionMode && Array.isArray(labels) && labels.length ? labels : sessionCategories(includeAuction);
  };
  const elapsedBoundary = (payload, categories) => {
    const raw = Number(payload?.session_progress?.blank_from_index);
    return Number.isFinite(raw) ? Math.max(0, Math.min(categories.length, raw)) : categories.length;
  };
  // Classification colors deliberately avoid the A-share semantic red/green
  // lanes, which remain reserved for gain/inflow and loss/outflow.
  const CLASSIFICATION_COLORS = [
    "#2563eb", "#4f46e5", "#7c3aed", "#9333ea", "#c026d3", "#db2777",
    "#d97706", "#b7791f", "#0891b2", "#0e7490", "#475569", "#6d5dfc",
  ];
  const stableColor = value => {
    let hash = 0;
    for (const char of String(value || "未分类")) hash = ((hash << 5) - hash + char.charCodeAt(0)) | 0;
    return CLASSIFICATION_COLORS[Math.abs(hash) % CLASSIFICATION_COLORS.length];
  };
  const semanticTextColor = (value, palette) => Number(value) > 0 ? palette.up : Number(value) < 0 ? palette.down : palette.muted;
  const classificationTextColor = (value, palette) => {
    const toward = relativeLuminance(palette.panel) > .5 ? "#000000" : "#ffffff";
    return contrastSafeColor(stableColor(value), [palette.panel, palette.surface], toward);
  };
  const classificationTag = (label, title, palette) => {
    const name = String(label || "未分类");
    const base = stableColor(name);
    const textColor = classificationTextColor(name, palette);
    return `<span style="display:inline-flex;align-items:center;gap:5px;padding:2px 7px;border:1px solid ${base};border-radius:999px;background:${palette.surface};color:${textColor};white-space:nowrap"><i style="width:7px;height:7px;border-radius:50%;background:${base};display:inline-block"></i>${esc(title)} ${esc(name)}</span>`;
  };
  function sparkSvg(points, direction) {
    const rows = tradingPoints(points);
    if (rows.length < 2) return `<svg viewBox="0 0 92 25" aria-hidden="true"><line x1="2" y1="13" x2="90" y2="13" stroke="#344d47"/></svg>`;
    const values = rows.map(row => Number(row.flow || 0));
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = Math.max(1, max - min);
    const coords = rows.map(row => `${(row._sessionIndex / 241 * 90 + 1).toFixed(1)},${(23 - (Number(row.flow || 0) - min) / span * 21).toFixed(1)}`).join(" ");
    const color = direction === "inflow" ? "#e95f55" : "#27b48f";
    return `<svg viewBox="0 0 92 25" aria-hidden="true"><line x1="1" y1="23" x2="91" y2="23" stroke="#253d38"/><polyline points="${coords}" stroke="${color}"/></svg>`;
  }
  function sparkMoment(points) {
    const rows = tradingPoints(points);
    let best = null;
    for (let index = 1; index < rows.length; index += 1) {
      const delta = Math.abs(Number(rows[index].flow || 0) - Number(rows[index - 1].flow || 0));
      if (!best || delta > best.delta) best = { delta, time: rows[index]._time };
    }
    return best ? `主变化 ${best.time}` : "分钟轨迹待积累";
  }
  async function json(url) {
    const response = await fetch(url, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    return payload;
  }
  function banner(message, kind = "") {
    const node = $("statusBanner");
    node.textContent = message;
    node.className = `status-banner ${kind}`;
  }
  function renderMeta(payload) {
    const mode = $("modeBadge");
    const replay = ["historical_replay", "cached_replay"].includes(payload.mode);
    const closed = payload.mode === "closed";
    mode.textContent = payload.mode === "morning" || payload.mode === "afternoon"
      ? "盘中动态"
      : replay
        ? "历史回放"
        : closed
          ? "收盘快照"
          : payload.mode || "状态未知";
    mode.className = `badge ${replay || closed ? "replay" : payload.ok ? "" : "error"}`;
    $("dataTime").textContent = payload.data_time || "--";
    $("fetchedAt").textContent = payload.generated_at || "--";
    $("sourceName").textContent = payload.source?.provider || "--";
    $("sourceLatency").textContent = payload.source?.elapsed_ms != null ? `${payload.source.elapsed_ms}ms` : "--";
    const provenance = [
      payload.source?.provider || "来源未知",
      payload.source?.possibly_delayed ? "可能延迟" : "主域",
      payload.source?.elapsed_ms != null ? `${payload.source.elapsed_ms}ms` : "",
    ].filter(Boolean).join(" · ");
    banner(`${payload.status_message || "数据已更新。"} 来源：${provenance}`, replay || closed || payload.source?.possibly_delayed ? "warn" : "");
  }
  function visibleSectors() {
    const q = $("sectorSearch").value.trim().toLowerCase();
    return q ? STATE.sectors.filter(row => `${row.name}${row.code}`.toLowerCase().includes(q)) : STATE.sectors;
  }
  function topFlowSectors(rows, each = 10) {
    const incomingAll = [...rows].filter(row => Number(row.main_net_inflow) > 0).sort((a, b) => b.main_net_inflow - a.main_net_inflow);
    const outgoingAll = [...rows].filter(row => Number(row.main_net_inflow) < 0).sort((a, b) => a.main_net_inflow - b.main_net_inflow);
    const incoming = each ? incomingAll.slice(0, each) : incomingAll;
    const outgoing = each ? outgoingAll.slice(0, each) : outgoingAll;
    return [...incoming, ...outgoing];
  }
  function bindSingleAndDouble(node, onSingle, onDouble) {
    let clickTimer = 0;
    node.addEventListener("click", event => {
      clearTimeout(clickTimer);
      if (event.detail > 1) return;
      clickTimer = setTimeout(() => {
        if (node.isConnected) onSingle();
      }, 280);
    });
    node.addEventListener("dblclick", event => {
      clearTimeout(clickTimer);
      event.preventDefault();
      event.stopPropagation();
      onDouble();
    });
  }
  function renderSummary(rows) {
    const inflow = rows.filter(row => row.main_net_inflow > 0);
    const outflow = rows.filter(row => row.main_net_inflow < 0);
    const strongestIn = [...inflow].sort((a, b) => b.main_net_inflow - a.main_net_inflow)[0];
    const strongestOut = [...outflow].sort((a, b) => a.main_net_inflow - b.main_net_inflow)[0];
    const up = rows.filter(row => row.change_pct > 0).length;
    const down = rows.filter(row => row.change_pct < 0).length;
    $("inflowCount").textContent = inflow.length;
    $("outflowCount").textContent = outflow.length;
    $("inflowAmount").textContent = strongestIn ? `最大 ${strongestIn.name} ${fmtMoney(strongestIn.main_net_inflow)}` : "--";
    $("outflowAmount").textContent = strongestOut ? `最大 ${strongestOut.name} ${fmtMoney(strongestOut.main_net_inflow)}` : "--";
    $("breadthCount").textContent = `${up} / ${down}`;
    $("breadthText").textContent = `平盘 ${Math.max(0, rows.length - up - down)}`;
  }
  function renderRanks(rows) {
    const rowHtml = direction => (row, index) => {
      const points = STATE.sparklines.get(row.code) || [];
      return `<div class="rank-row ${row.code === STATE.selectedCode ? "selected" : ""}" data-entity-kind="sector" data-code="${row.code}" role="button" tabindex="0" aria-label="${esc(row.name)}，单击联动，双击打开核心股05B终端"><span class="num">${String(index + 1).padStart(2, "0")}</span><span><b>${esc(row.name)}</b><small>${row.code} · ${fmtPct(row.change_pct)} · 占比 ${fmtPct(row.main_net_ratio)}</small></span><span class="rank-spark" title="${esc(sparkMoment(points))}">${sparkSvg(points, direction)}<i>${esc(sparkMoment(points))}</i></span><strong class="${cls(row.main_net_inflow)}">${fmtMoney(row.main_net_inflow)}</strong></div>`;
    };
    const incomingAll = [...rows].filter(row => row.main_net_inflow > 0).sort((a, b) => b.main_net_inflow - a.main_net_inflow);
    const outgoingAll = [...rows].filter(row => row.main_net_inflow < 0).sort((a, b) => a.main_net_inflow - b.main_net_inflow);
    const incoming = STATE.heatmapLimit ? incomingAll.slice(0, STATE.heatmapLimit) : incomingAll;
    const outgoing = STATE.heatmapLimit ? outgoingAll.slice(0, STATE.heatmapLimit) : outgoingAll;
    $("inflowList").innerHTML = incoming.map(rowHtml("inflow")).join("") || `<div class="empty">暂无数据</div>`;
    $("outflowList").innerHTML = outgoing.map(rowHtml("outflow")).join("") || `<div class="empty">暂无数据</div>`;
    document.querySelectorAll(".rank-row").forEach(node => bindSingleAndDouble(
      node,
      () => selectSector(node.dataset.code),
      () => openSectorTarget(node.dataset.code, node),
    ));
  }
  function renderSectorTreemap() {
    const palette = chartTheme();
    const rows = topFlowSectors(visibleSectors(), STATE.heatmapLimit);
    const sizeMetric = $("sizeMetric").value;
    const colorMetric = $("colorMetric").value;
    $("heatmapHint").textContent = `流入${limitLabel(STATE.heatmapLimit)} + 流出${limitLabel(STATE.heatmapLimit)} · ${DETAIL_LABELS[STATE.heatmapDetail]} · 面积=${sizeMetric === "amount" ? "成交额" : "净流绝对值"}`;
    if (!rows.length) {
      sectorChart.clear();
      sectorChart.setOption({
        title: { text: "没有匹配的板块", subtext: "清除筛选词或切换板块类型", left: "center", top: "42%", textStyle: { color: palette.text, fontSize: 15 }, subtextStyle: { color: palette.muted, fontSize: 11 } },
      });
      return;
    }
    const colorValues = rows.map(row => Math.abs(Number(row[colorMetric] || 0))).sort((a, b) => a - b);
    const maxAbs = colorValues[Math.floor(colorValues.length * .9)] || 1;
    const data = rows.map(row => ({
      name: row.name,
      code: row.code,
      value: [Math.max(1, sizeMetric === "abs_flow" ? Math.abs(row.main_net_inflow) : row.amount), row[colorMetric]],
      itemStyle: { color: colorBy(row[colorMetric], maxAbs), borderColor: palette.panel, borderWidth: 2 },
      raw: row,
    }));
    sectorChart.setOption({
      animation: false,
      tooltip: { backgroundColor: palette.panel, borderColor: palette.line, textStyle: { color: palette.text }, formatter: p => { const r = p?.data?.raw; if (!r) return esc(p?.name || ""); return `<b>${r.name}</b> ${r.code}<br>涨跌 ${fmtPct(r.change_pct)}<br>成交额 ${fmtMoney(r.amount)}<br>主力净流 ${fmtMoney(r.main_net_inflow)} (${fmtPct(r.main_net_ratio)})<br>3秒增量 ${fmtMoney(r.delta_flow)}<br>上涨/下跌 ${r.rise_count}/${r.fall_count}<br>强弱分 ${r.strength_score.toFixed(2)}`; } },
      series: [{ type: "treemap", roam: false, nodeClick: false, breadcrumb: { show: false }, sort: "desc", data, label: { show: true, color: "#f4fbf8", formatter: p => { const r = p?.data?.raw; if (!r) return ""; if (STATE.heatmapDetail === 0) return `{name|${r.name}}\n{flow|${fmtMoney(r.main_net_inflow)}}`; if (STATE.heatmapDetail === 1) return `{name|${r.name}}\n{val|${fmtPct(r.change_pct)}}\n{flow|${fmtMoney(r.main_net_inflow)}}`; return `{name|${r.name}}\n{code|${r.code}}\n{val|${fmtMetric(r, colorMetric)}}\n{flow|${fmtMoney(r.main_net_inflow)}}\n{ratio|占比 ${fmtPct(r.main_net_ratio)}}`; }, rich: { name: { fontSize: 13, fontWeight: 700, lineHeight: 19 }, code: { fontSize: 9, color: "#b9ccc7", lineHeight: 15 }, val: { fontSize: 11, lineHeight: 16 }, flow: { fontSize: 9, color: "#d2e1dd" }, ratio: { fontSize: 8, color: "#8eaaa3" } } }, upperLabel: { show: false }, levels: [{ itemStyle: { gapWidth: 2, borderWidth: 1 } }] }],
    }, { notMerge: false, replaceMerge: ["series"], lazyUpdate: true, silent: true });
  }
  function renderStocks(payload) {
    const palette = chartTheme();
    STATE.selectedSectorDetail = payload;
    STATE.selectedSectorDetailCode = payload.code || payload.sector_code || STATE.selectedCode;
    const allStocks = [...(payload.stocks || [])].sort((a, b) => b.amount - a.amount);
    const stocks = STATE.stockLimit ? allStocks.slice(0, STATE.stockLimit) : allStocks;
    const stockTime = stocks.map(row => row.data_time || "").sort().at(-1) || "--";
    $("stockSource").textContent = `${stocks.length}/${allStocks.length}只 · ${DETAIL_LABELS[STATE.stockDetail]} · ${payload.source?.provider || "来源未知"}${payload.source?.possibly_delayed ? "·可能延迟" : ""} · ${stockTime.replace("T", " ")}`;
    const maxChange = Math.max(1, ...stocks.map(row => Math.abs(row.change_pct)));
    stockChart.setOption({
      animation: false,
      tooltip: { backgroundColor: palette.panel, borderColor: palette.line, textStyle: { color: palette.text }, formatter: p => { const r = p?.data?.raw; if (!r) return esc(p?.name || ""); return `<b>${r.name}</b> ${r.code}.${r.market}<br>涨跌 ${fmtPct(r.change_pct)}<br>成交额 ${fmtMoney(r.amount)}<br>量比 ${r.volume_ratio.toFixed(2)} · 换手 ${fmtPct(r.turnover_pct)}<br>主力净流 ${fmtMoney(r.main_net_inflow)}`; } },
      series: [{ type: "treemap", roam: false, nodeClick: false, breadcrumb: { show: false }, data: stocks.map(row => ({ name: row.name, value: Math.max(1, row.amount), raw: row, itemStyle: { color: colorBy(row.change_pct, maxChange), borderColor: palette.panel, borderWidth: 2 } })), label: { color: "#f1faf7", formatter: p => { const r = p?.data?.raw; if (!r) return ""; if (STATE.stockDetail === 0) return `${r.name}\n${fmtMoney(r.amount)}`; if (STATE.stockDetail === 1) return `${r.name}\n${fmtPct(r.change_pct)}\n${fmtMoney(r.amount)}`; return `${r.name} ${r.code}\n${fmtPct(r.change_pct)} · 量比${Number(r.volume_ratio || 0).toFixed(2)}\n${fmtMoney(r.amount)} · 净流${fmtMoney(r.main_net_inflow)}`; } } }],
    }, { notMerge: false, replaceMerge: ["series"], lazyUpdate: true, silent: true });
  }
  function renderSourceCatalog(payload) {
    const collector = payload.collector || {};
    const history = payload.history || {};
    const sector = history.sector || {};
    const stock = history.stock || {};
    $("collectorState").textContent = `后台连续采集器：${collector.status_label || collector.status || "状态未知"}${collector.last_cycle_at ? ` · 最近 ${collector.last_cycle_at.replace("T", " ")}` : ""}`;
    $("historyPath").textContent = history.path || "未启用";
    $("historyPath").title = history.path || "";
    $("sectorHistoryStats").textContent = `${Number(sector.rows || 0)} 行 · ${Number(sector.codes || 0)} 个板块 · ${sector.last_date || "暂无"}`;
    $("stockHistoryStats").textContent = `${Number(stock.rows || 0)} 行 · ${Number(stock.codes || 0)} 只股票 · ${stock.last_date || "暂无"}`;
    $("historyRetention").textContent = `${Number(history.retention_days || 0)} 个自然日`;
    $("sourceRows").innerHTML = (payload.sources || []).map(row => `<tr>
      <td>${esc(row.surface)}</td>
      <td><b>${esc(row.provider)}</b><br><code>${esc(row.endpoint)}</code><br>${esc(row.host_policy)}</td>
      <td>${esc(row.query)}<br><span class="muted-line">字段：${esc(row.fields)}</span></td>
      <td>${esc(row.cadence)}<br><span class="muted-line">边界：${esc(row.contract)}</span></td>
    </tr>`).join("") || `<tr><td colspan="4">暂无数据源定义</td></tr>`;
    const exclusion = payload.exclusions?.new_listing || "";
    const overlap = payload.exclusions?.overlap || "";
    $("sourceWarning").textContent = `口径边界：${overlap}；新股处理：${exclusion}。`;
  }
  function renderRace(payload) {
    const palette = chartTheme();
    STATE.racePayload = payload;
    const populated = (payload.series || []).filter(row => (row.points || []).length);
    STATE.raceDates = payload.available_dates || [];
    STATE.raceSeriesByCode = new Map(populated.map(row => [row.code, row]));
    if (!STATE.raceTradeDate) $("raceTradeDate").value = payload.trade_date || "";
    const reds = ["#ff6258", "#e94f49", "#cf3f3d", "#ff8a72", "#bb5b54", "#ffb08e", "#a94444", "#ff7b7b"];
    const greens = ["#35d7b2", "#24bd96", "#169f82", "#60e4c5", "#2e8f78", "#7bd4bd", "#18705e", "#53b99f"];
    let inIndex = 0;
    let outIndex = 0;
    const allTimes = payloadCategories(payload, false);
    const blankFrom = elapsedBoundary(payload, allTimes);
    const independentScale = STATE.raceScaleMode === "independent";
    const colorByCode = new Map();
    const series = populated.map(row => {
      const color = row.direction === "inflow" ? reds[inIndex++ % reds.length] : greens[outIndex++ % greens.length];
      const selected = row.code === STATE.selectedCode;
      colorByCode.set(row.code, color);
      return {
        id: `race-${row.code}`,
        name: row.name,
        sectorCode: row.code,
        flowDirection: row.direction,
        type: "line",
        xAxisIndex: independentScale && row.direction === "outflow" ? 1 : 0,
        yAxisIndex: independentScale && row.direction === "outflow" ? 1 : 0,
        triggerLineEvent: true,
        showSymbol: false,
        sampling: "lttb",
        data: tradingPoints(row.points)
          .filter(point => point._sessionIndex < blankFrom)
          .map(point => ({ value: [point._time, point.flow], amount: point.amount || 0, signedAmount: point.signed_amount || 0, rawTime: point.time })),
        lineStyle: { color, width: selected ? 4 : 1.8, opacity: STATE.selectedCode && !selected ? .38 : .95 },
        itemStyle: { color },
        endLabel: { show: false },
        emphasis: { focus: "series", lineStyle: { width: 4 } },
        z: selected ? 12 : 2,
      };
    });
    const rail = $("raceClickRail");
    const railScrollTop = new Map([...rail.querySelectorAll("[data-race-scroll]")].map(node => [node.dataset.raceScroll, node.scrollTop]));
    const railRows = direction => {
      const rows = populated.filter(row => row.direction === direction);
      if (populated.length <= 60) return rows;
      const selected = rows.find(row => row.code === STATE.selectedCode);
      const limited = rows.slice(0, 30);
      return selected && !limited.some(row => row.code === selected.code) ? [selected, ...limited] : limited;
    };
    rail.innerHTML = [
      { direction: "inflow", title: "净流入", scale: independentScale ? "上区独立轴" : "共同轴" },
      { direction: "outflow", title: "净流出", scale: independentScale ? "下区独立轴" : "共同轴" },
    ].map(group => {
      const rows = railRows(group.direction);
      const buttons = rows.map(row => {
        const color = colorByCode.get(row.code) || (row.direction === "inflow" ? reds[0] : greens[0]);
        const latest = tradingPoints(row.points).filter(point => point._sessionIndex < blankFrom).at(-1);
        return `<button type="button" data-entity-kind="sector" data-code="${row.code}" data-race-code="${row.code}" class="${row.code === STATE.selectedCode ? "active" : ""}" style="--race-color:${color}" title="单击联动 ${esc(row.name)}；双击打开核心股05B终端"><b>${esc(row.name)}</b><i>${fmtYiInteger(latest?.flow || 0)}</i></button>`;
      }).join("") || `<div class="race-rail-empty">暂无${group.title}曲线</div>`;
      return `<section class="race-rail-group" data-direction="${group.direction}"><div class="race-rail-group-head"><b>${group.title}</b><span>${group.scale}</span></div><div class="race-rail-scroll" data-race-scroll="${group.direction}">${buttons}</div></section>`;
    }).join("");
    rail.querySelectorAll("[data-race-scroll]").forEach(node => {
      const previous = railScrollTop.get(node.dataset.raceScroll) || 0;
      node.scrollTop = Math.min(previous, Math.max(0, node.scrollHeight - node.clientHeight));
    });
    rail.querySelectorAll("[data-race-code]").forEach(button => bindSingleAndDouble(
      button,
      () => selectSector(button.dataset.raceCode),
      () => openSectorTarget(button.dataset.raceCode, button),
    ));
    const signature = `${payload.trade_date}|${payload.data_mode}|${STATE.raceScaleMode}|${STATE.selectedCode}|${series.map(item => `${item.id}:${item.data.length}:${item.data.at(-1)?.value?.join(":")}`).join("|")}`;
    if (signature === STATE.lastRaceSignature) return;
    STATE.lastRaceSignature = signature;
    const axisBase = {
      type: "category",
      data: allTimes,
      boundaryGap: false,
      axisLine: { lineStyle: { color: palette.line } },
      splitLine: { show: false },
    };
    const grids = independentScale
      ? [
          { id: "race-inflow-grid", left: 96, right: 20, top: "5%", height: "55%", containLabel: false },
          { id: "race-outflow-grid", left: 96, right: 20, top: "72%", height: "22%", containLabel: false },
        ]
      : [{ id: "race-shared-grid", left: 96, right: 24, top: 30, bottom: 48 }];
    const xAxes = independentScale
      ? [
          { ...axisBase, gridIndex: 0, axisLabel: { show: false }, axisTick: { show: false } },
          { ...axisBase, gridIndex: 1, axisLabel: { color: palette.muted, formatter: value => value, hideOverlap: true } },
        ]
      : [{ ...axisBase, gridIndex: 0, axisLabel: { color: palette.muted, formatter: value => value, hideOverlap: true } }];
    const yAxes = independentScale
      ? [
          { type: "value", gridIndex: 0, scale: true, name: "净流入（亿）", nameLocation: "middle", nameRotate: 90, nameGap: 72, nameTextStyle: { color: palette.up, fontWeight: 700 }, axisLabel: { color: palette.up, formatter: fmtYiInteger, hideOverlap: true, margin: 10 }, axisLine: { show: true, lineStyle: { color: palette.up } }, splitLine: { lineStyle: { color: palette.line } } },
          { type: "value", gridIndex: 1, scale: true, name: "净流出（亿）", nameLocation: "middle", nameRotate: 90, nameGap: 72, nameTextStyle: { color: palette.down, fontWeight: 700 }, axisLabel: { color: palette.down, formatter: fmtYiInteger, hideOverlap: true, margin: 10 }, axisLine: { show: true, lineStyle: { color: palette.down } }, splitLine: { lineStyle: { color: palette.line } } },
        ]
      : [{ type: "value", gridIndex: 0, scale: true, name: payload.data_mode === "historical_direction_proxy" ? "成交方向代理（亿）" : "主力净流（亿）", nameLocation: "middle", nameRotate: 90, nameGap: 72, nameTextStyle: { color: palette.muted, fontWeight: 700 }, axisLabel: { color: palette.muted, formatter: fmtYiInteger, hideOverlap: true, margin: 10 }, axisLine: { show: true, lineStyle: { color: palette.line } }, splitLine: { lineStyle: { color: palette.line } } }];
    const seriesMeta = new Map(series.map(item => [item.id, item]));
    timelineChart.setOption({
      animation: false,
      color: [...reds, ...greens],
      axisPointer: independentScale ? { link: [{ xAxisIndex: [0, 1] }] } : {},
      tooltip: {
        trigger: "axis",
        order: "valueDesc",
        confine: true,
        backgroundColor: palette.panel,
        borderColor: palette.line,
        textStyle: { color: palette.text, fontSize: 11 },
        formatter: params => {
          const rows = Array.isArray(params) ? params : [params];
          const time = rows[0]?.axisValueLabel || rows[0]?.axisValue || "--";
          return [`<b>${esc(time)}</b>`].concat(rows.map(item => {
            const raw = Array.isArray(item.value) ? Number(item.value[1] || 0) : Number(item.value || 0);
            const meta = seriesMeta.get(item.seriesId);
            const direction = meta?.flowDirection === "outflow" ? "净流出" : "净流入";
            return `${item.marker || ""}${esc(item.seriesName || "")} · ${direction}：<b>${fmtYiInteger(raw)}</b>`;
          })).join("<br>");
        },
      },
      grid: grids,
      xAxis: xAxes,
      yAxis: yAxes,
      series,
    }, { notMerge: false, replaceMerge: ["grid", "xAxis", "yAxis", "series"], lazyUpdate: true, silent: true });
    const source = payload.source_disclosure || {};
    const sourceNode = $("raceSourceNote");
    const progress = payload.session_progress || {};
    const scaleTitle = independentScale ? "独立双尺度" : "共同尺度";
    sourceNode.querySelector("b").textContent = `${payload.trade_date || "--"} · ${source.title || "板块资金赛马"} · ${populated.length} 条曲线 · ${scaleTitle} · 交易轴至15:00${progress.is_complete ? "（完整）" : `（${progress.last_elapsed_label || "尚未开盘"}后留白）`}`;
    const excludedNames = (payload.excluded_aggregate_names || []).join("、");
    const scaleDisclosure = independentScale
      ? "显示：独立双尺度，净流入使用上区、净流出使用下区并分别缩放；该布局只用于提高可读性，两区的线高、斜率和纵轴间距不可跨方向比较；坐标与悬浮值统一四舍五入为整数亿元，底层仍保留真实有符号人民币元"
      : "显示：共同尺度，流入与流出共用同一纵轴，可直接比较绝对金额；当净流出远大于净流入时，流入曲线可能被视觉压缩；坐标与悬浮值统一四舍五入为整数亿元，底层仍保留真实有符号人民币元";
    sourceNode.querySelector("span").textContent = `${scaleDisclosure}；来源：${source.provider || "--"}；接口：${source.endpoint || "--"}；字段：${source.fields || "--"}；算法：${source.method || "--"}；边界：${source.limitation || "--"}${excludedNames ? `；已排除聚合板块：${excludedNames}` : ""}`;
    $("raceTitle").textContent = `多板块资金赛马 · 净流入${limitLabel(STATE.raceLimit)} vs 净流出${limitLabel(STATE.raceLimit)} · ${scaleTitle}`;
    $("raceLatest").classList.toggle("active", !STATE.raceTradeDate);
  }
  function renderStockTimeline(payload) {
    STATE.currentStockPayload = payload;
    const themeRefreshWait = STATE.stockThemeRefreshNotBefore - Date.now();
    if (themeRefreshWait > 0) {
      clearTimeout(STATE.stockThemeRefreshTimer);
      STATE.stockThemeRefreshTimer = setTimeout(() => {
        STATE.stockThemeRefreshTimer = 0;
        STATE.stockThemeRefreshNotBefore = 0;
        STATE.lastStockTimelineSignature = "";
        stockTimelineChart.getZr().trigger("globalout", { event: {} });
        stockTimelineChart.dispatchAction({ type: "hideTip" });
        if (STATE.currentStockPayload) renderStockTimeline(STATE.currentStockPayload);
      }, themeRefreshWait + 24);
      return;
    }
    const palette = chartTheme();
    const auction = payload.auction || {};
    const includeAuction = Boolean(STATE.showAuction && auction.available);
    const auctionToggle = $("auctionToggle");
    auctionToggle.disabled = !auction.available;
    auctionToggle.checked = includeAuction;
    $("auctionStatus").textContent = auction.available ? `${auction.point_count || 0}点真实数据` : "当前不可用";
    $("auctionStatus").title = auction.reason || "";
    const minute = payload.minute_points || [];
    const realtime = payload.realtime_points || [];
    const regularPrice = (payload.price_points || []).length ? payload.price_points : realtime.map(point => ({ time: point.data_time, close: point.price, open: point.price, high: point.price, low: point.price, average: 0, volume: 0, amount: 0 }));
    const price = includeAuction ? [...(payload.auction_points || []), ...regularPrice] : regularPrice;
    const categories = payloadCategories(payload, includeAuction);
    const blankFrom = elapsedBoundary(payload, categories);
    const priceRows = tradingPoints(price, "time", includeAuction).filter(point => point._sessionIndex < blankFrom);
    const flowRows = tradingPoints(minute, "time", includeAuction).filter(point => point._sessionIndex < blankFrom);
    const preClose = Number(payload.price_source?.pre_close || payload.order_book?.pre_close || 0);
    const priceByTime = new Map(priceRows.map(point => [point._time, point]));
    const flowByTime = new Map(flowRows.map(point => [point._time, point]));
    let previousFlow = null;
    const flowDeltaByTime = new Map();
    const flowDelta = categories.map(time => {
      const point = flowByTime.get(time);
      if (!point) return null;
      const current = Number(point.flow ?? previousFlow ?? 0);
      const delta = previousFlow == null ? null : current - previousFlow;
      previousFlow = current;
      flowDeltaByTime.set(time, delta);
      return delta;
    });
    const volumeContract = payload.price_volume_contract || { unit: "手", share_multiplier: 100, display: "成交量单位以行情源为准" };
    const volumeUnit = volumeContract.unit === "股" ? "股" : "手";
    const shareMultiplier = Number(volumeContract.share_multiplier || (volumeUnit === "手" ? 100 : 1));
    const signedMoney = value => value == null || !Number.isFinite(Number(value)) ? "--" : `${Number(value) > 0 ? "+" : ""}${fmtMoney(Number(value))}`;
    const netDirection = value => Number(value) > 0 ? "净流入" : Number(value) < 0 ? "净流出" : "净额为零";
    const minuteDirection = value => Number(value) > 0 ? "该分钟净流入" : Number(value) < 0 ? "该分钟净流出" : "该分钟净额不变";
    const formatVolume = point => {
      if (!point || point.volume == null || !Number.isFinite(Number(point.volume))) return "--";
      const raw = Number(point.volume);
      if (volumeUnit === "手") return `${Math.round(raw).toLocaleString("zh-CN")}手（约${Math.round(raw * shareMultiplier).toLocaleString("zh-CN")}股）`;
      return `${Math.round(raw).toLocaleString("zh-CN")}股（约${(raw / 100).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}手）`;
    };
    const tooltipFormatter = params => {
      const rows = Array.isArray(params) ? params : [params];
      const time = String(rows[0]?.axisValueLabel || rows[0]?.axisValue || "");
      const pricePoint = priceByTime.get(time);
      const flowPoint = flowByTime.get(time);
      const close = pricePoint?.close == null ? null : Number(pricePoint.close);
      const average = pricePoint?.average == null || Number(pricePoint.average) === 0 ? null : Number(pricePoint.average);
      const cumulative = flowPoint?.flow == null ? null : Number(flowPoint.flow);
      const delta = flowDeltaByTime.has(time) ? flowDeltaByTime.get(time) : null;
      return [
        `<b>${esc(payload.trade_date || "--")} ${esc(time || "--")}</b> · ${esc(STATE.selectedStockName || payload.code || "")}`,
        `最新价：<b>${close == null ? "--" : close.toFixed(2)}</b>`,
        `当日均价：<b>${average == null ? "--" : average.toFixed(2)}</b>`,
        `分钟成交量：<b>${formatVolume(pricePoint)}</b>`,
        `累计主力净流：<b class="${cls(cumulative)}">${signedMoney(cumulative)}</b>${cumulative == null ? "" : `（${netDirection(cumulative)}）`}`,
        `本分钟净流变化：<b class="${cls(delta)}">${signedMoney(delta)}</b>${delta == null ? "（首个可用资金点，无法计算相邻变化）" : `（${minuteDirection(delta)}）`}`,
      ].join("<br>");
    };
    $("stockTimelineSource").textContent = `${payload.trade_date || "--"} · 价格/量 ${priceRows.length}点 · 资金 ${flowRows.length}点 · 成交量=${volumeUnit}${volumeUnit === "手" ? "（约合股数=手×100）" : "（TDX手数已换算为股）"} · ${includeAuction ? "含真实09:15–09:29竞价 · " : ""}完整15:00交易轴，未发生分钟留白`;
    const timelineSignature = `${payload.code}|${payload.trade_date}|${includeAuction}|${STATE.theme}|${categories.map(time => {
      const p = priceByTime.get(time);
      const f = flowByTime.get(time);
      return `${p?.close ?? ""},${p?.average ?? ""},${p?.volume ?? ""},${f?.flow ?? ""},${flowDeltaByTime.get(time) ?? ""}`;
    }).join(";")}`;
    if (timelineSignature !== STATE.lastStockTimelineSignature) {
      STATE.lastStockTimelineSignature = timelineSignature;
      stockTimelineChart.getZr().trigger("globalout", { event: {} });
      stockTimelineChart.dispatchAction({ type: "hideTip" });
      stockTimelineChart.setOption({
      animation: false,
      axisPointer: {
        link: [{ xAxisIndex: [0, 1, 2] }],
        lineStyle: { color: palette.muted, width: 1, type: "dashed" },
        label: { show: true, backgroundColor: palette.surface, color: palette.text },
      },
      tooltip: {
        trigger: "axis",
        triggerOn: "mousemove|click",
        confine: true,
        transitionDuration: 0,
        backgroundColor: palette.panel,
        borderColor: palette.line,
        textStyle: { color: palette.text, fontSize: 11, lineHeight: 18 },
        axisPointer: { type: "line", axis: "x", snap: true, animation: false },
        formatter: tooltipFormatter,
      },
      legend: { top: 5, data: ["最新价", "当日均价", "分钟成交量", "累计主力净流", "资金分钟变化"], textStyle: { color: palette.muted, fontSize: 10 } },
      grid: [
        { left: 66, right: 64, top: 42, height: "48%" },
        { left: 66, right: 64, top: "61%", height: "12%" },
        { left: 66, right: 64, top: "78%", bottom: 34 },
      ],
      xAxis: [
        { type: "category", data: categories, boundaryGap: false, axisPointer: { show: true, type: "line", snap: true }, axisLabel: { show: false }, axisLine: { lineStyle: { color: palette.line } } },
        { type: "category", gridIndex: 1, data: categories, boundaryGap: false, axisPointer: { show: true, type: "line", snap: true }, axisLabel: { show: false }, axisLine: { show: false } },
        { type: "category", gridIndex: 2, data: categories, boundaryGap: false, axisPointer: { show: true, type: "line", snap: true }, axisLabel: { color: palette.muted, hideOverlap: true }, axisLine: { lineStyle: { color: palette.line } } },
      ],
      yAxis: [
        { type: "value", scale: true, name: "价格", nameTextStyle: { color: palette.muted }, axisLabel: { color: palette.muted }, splitLine: { lineStyle: { color: palette.line } } },
        { type: "value", gridIndex: 1, name: `成交量（${volumeUnit}）`, nameTextStyle: { color: palette.muted }, axisLabel: { color: palette.muted, formatter: v => fmtMoney(v) }, splitLine: { show: false } },
        { type: "value", gridIndex: 2, name: payload.data_mode === "historical_direction_proxy" ? "资金代理" : "主力资金", nameTextStyle: { color: palette.muted }, axisLabel: { color: palette.muted, formatter: v => fmtMoney(v) }, splitLine: { lineStyle: { color: palette.line } } },
      ],
      series: [
        { name: "最新价", type: "line", showSymbol: false, data: categories.map(time => priceByTime.get(time)?.close ?? null), lineStyle: { color: palette.up, width: 2 }, connectNulls: true, markLine: preClose ? { silent: true, symbol: "none", lineStyle: { color: palette.line, type: "dashed" }, label: { formatter: `昨收 ${preClose.toFixed(2)}`, color: palette.muted }, data: [{ yAxis: preClose }] } : undefined },
        { name: "当日均价", type: "line", showSymbol: false, data: categories.map(time => Number(priceByTime.get(time)?.average || 0) || null), lineStyle: { color: palette.amber, width: 1.2 }, connectNulls: true },
        { name: "分钟成交量", type: "bar", xAxisIndex: 1, yAxisIndex: 1, barMaxWidth: 5, data: categories.map(time => { const row = priceByTime.get(time); if (!row) return null; const up = Number(row.close || 0) >= Number(row.open || row.close || 0); return { value: Number(row.volume || 0), itemStyle: { color: up ? palette.up : palette.down, opacity: .58 } }; }) },
        { name: "累计主力净流", type: "line", xAxisIndex: 2, yAxisIndex: 2, showSymbol: false, data: categories.map(time => flowByTime.get(time)?.flow ?? null), lineStyle: { color: palette.mint, width: 1.6 }, connectNulls: true },
        { name: "资金分钟变化", type: "bar", xAxisIndex: 2, yAxisIndex: 2, barMaxWidth: 4, data: flowDelta.map(value => value == null ? null : ({ value, itemStyle: { color: value >= 0 ? palette.up : palette.down, opacity: .42 } })) },
      ],
      }, { notMerge: false, replaceMerge: ["grid", "xAxis", "yAxis", "series"], lazyUpdate: false, silent: true });
    }
    const disclosure = payload.source_disclosure || {};
    const priceSource = payload.price_source || {};
    const sourceNode = $("stockDetailSource");
    sourceNode.querySelector("b").textContent = `${payload.trade_date || "--"} · ${disclosure.title || "个股分时"}`;
    sourceNode.querySelector("span").textContent = `价格/成交量：${priceSource.provider || "本地留档"} ${priceSource.endpoint || ""}；成交量口径：${volumeContract.display || `单位${volumeUnit}`}，${volumeContract.limitation || ""}；资金：${disclosure.provider || "--"} ${disclosure.endpoint || ""}；悬浮卡中的“累计主力净流”和“本分钟净流变化”均为有符号净额，不拆成或伪造成总流入/总流出；算法/边界：${disclosure.method || "--"}，${disclosure.limitation || "--"}。午休不补点，11:30与13:00直接相邻；收盘固定15:00，未来分钟留空。${auction.reason ? ` 集合竞价：${auction.reason}。` : ""}`;
    renderOrderBook(payload);
    stockTerminalDialogController?.syncHeading();
  }
  function renderOrderBook(payload) {
    const book = payload.order_book || {};
    const last = Number(book.last || payload.price_points?.at(-1)?.close || 0);
    const preClose = Number(book.pre_close || payload.price_source?.pre_close || 0);
    $("bookStockName").textContent = STATE.selectedStockName || payload.code || "--";
    $("bookStockCode").textContent = `${payload.code || "--"}.${payload.market || "--"} · ${book.generated_at?.replace("T", " ") || payload.trade_date || "--"}`;
    $("bookLastPrice").textContent = last ? last.toFixed(2) : "--";
    $("bookLastPrice").className = cls(last - preClose);
    $("bookQuoteStats").innerHTML = `<span>开 ${book.open ? Number(book.open).toFixed(2) : "--"}</span><span>高 ${book.high ? Number(book.high).toFixed(2) : "--"}</span><span>低 ${book.low ? Number(book.low).toFixed(2) : "--"}</span><span>昨 ${preClose ? preClose.toFixed(2) : "--"}</span>`;
    const levels = [...(book.asks || []), ...(book.bids || [])];
    const maxVolume = Math.max(1, ...levels.map(row => Number(row.volume_lots || 0)));
    const rowHtml = side => row => `<div class="book-row ${side}" style="--depth:${Math.min(100, Number(row.volume_lots || 0) / maxVolume * 100).toFixed(1)}%;--depth-color:var(${side === "ask" ? "--down" : "--up"})"><span class="side">${side === "ask" ? "卖" : "买"}${row.level}</span><span class="price">${row.price ? Number(row.price).toFixed(2) : "--"}</span><span class="volume">${row.volume_lots ? Number(row.volume_lots).toFixed(0) : "--"}手</span></div>`;
    $("orderBookRows").innerHTML = book.ok ? `${(book.asks || []).map(rowHtml("ask")).join("")}<div class="book-mid"><span>最新</span><b class="${cls(last - preClose)}">${last ? last.toFixed(2) : "--"} ${preClose ? fmtPct((last / preClose - 1) * 100) : ""}</b></div>${(book.bids || []).map(rowHtml("bid")).join("")}` : `<div class="empty">${esc(book.error || "盘口暂无可用快照")}</div>`;
    const source = book.source || {};
    $("orderBookSource").textContent = book.ok ? `来源：${source.provider || "--"}；接口：${source.endpoint || "--"}；主机：${source.host || "--"}。${source.limitation || "盘口仅为当前快照。"}` : `${book.error || "盘口不可用"}；历史盘口不能由分钟行情事后回补。`;
  }
  function renderQueue(id, rows) {
    $(id).innerHTML = (rows || []).map(row => {
      const move = row.rank_change == null ? "新" : row.rank_change > 0 ? `↑${row.rank_change}` : row.rank_change < 0 ? `↓${Math.abs(row.rank_change)}` : "—";
      return `<div class="queue-row" data-entity-kind="stock" data-code="${esc(row.code)}" data-market="${esc(row.market)}" data-name="${esc(row.name)}" role="button" tabindex="0" aria-label="${esc(row.name)}，单击联动，双击打开05B终端"><span><b>${esc(row.name)}</b><small> ${esc(row.code)} · 量比${Number(row.volume_ratio || 0).toFixed(2)} · ${move}</small></span><span class="${cls(row.change_pct)}">${fmtPct(row.change_pct)}</span><span>${fmtMoney(row.amount)}</span></div>`;
    }).join("") || `<div class="empty">暂无满足阈值的标的</div>`;
    $(id).querySelectorAll(".queue-row").forEach(node => {
      const stock = () => ({ code: node.dataset.code, market: node.dataset.market, name: node.dataset.name });
      bindSingleAndDouble(node, () => selectStock(stock()), () => openStockTarget(stock(), node));
    });
  }
  function renderLiquidity(payload) {
    const palette = chartTheme();
    const allStocks = [...(payload.stocks || [])].sort((a, b) => Number(b.volume || 0) - Number(a.volume || 0) || Number(b.amount || 0) - Number(a.amount || 0) || String(a.code || "").localeCompare(String(b.code || "")));
    const stocks = allStocks.slice(0, STATE.liquidityLimit);
    const liquidityTime = stocks.map(row => row.data_time || "").sort().at(-1) || "--";
    const universeTotal = Number(payload.source?.reported_total || allStocks.length);
    const candidateCount = Number(payload.source?.row_count || allStocks.length);
    $("liquiditySource").textContent = `成交量TOP${stocks.length} · 候选池${candidateCount}/${universeTotal}只 · 横轴=涨跌幅 · 纵轴=成交量（手，对数轴） · 气泡=成交额 · ${payload.source?.provider || "来源未知"}${payload.source?.possibly_delayed ? "·可能延迟" : ""} · ${liquidityTime.replace("T", " ")}`;
    const policy = payload.exclusion_policy || {};
    const excluded = (policy.excluded || []).slice(0, 6).map(row => `${row.name} ${fmtPct(row.change_pct)}`).join("、");
    $("liquidityExclusion").textContent = `${policy.rule || "新股与上市初期极端涨幅样本不进入核心流动性面板"}；本帧已剔除 ${Number(policy.excluded_count || 0)} 只${excluded ? `（${excluded}）` : ""}。`;
    const amounts = stocks.map(row => row.amount).sort((a, b) => a - b);
    const p90 = amounts[Math.floor(amounts.length * .9)] || 1;
    const groupField = STATE.liquidityColorMode === "industry" ? "industry" : "primary_concept";
    const groupCounts = new Map();
    if (STATE.liquidityColorMode !== "performance") stocks.forEach(row => groupCounts.set(row[groupField] || "未分类", (groupCounts.get(row[groupField] || "未分类") || 0) + 1));
    $("liquidityLegend").innerHTML = STATE.liquidityColorMode === "performance"
      ? `<span class="legend-chip" style="--legend-color:${palette.up};--legend-text:${palette.up}"><i style="background:${palette.up}"></i>↑ 上涨</span><span class="legend-chip" style="--legend-color:${palette.down};--legend-text:${palette.down}"><i style="background:${palette.down}"></i>↓ 下跌</span><span class="legend-chip" style="--legend-color:${palette.muted};--legend-text:${palette.muted}"><i style="background:${palette.muted}"></i>— 平盘</span>`
      : [...groupCounts.entries()].sort((a, b) => b[1] - a[1]).map(([name, count]) => {
      const base = stableColor(name);
      const textColor = classificationTextColor(name, palette);
      return `<span class="legend-chip" style="--legend-color:${base};--legend-text:${textColor}"><i style="background:${base}"></i>${esc(name)} ${count}</span>`;
    }).join("");
    const pointColor = row => STATE.liquidityColorMode === "performance" ? semanticTextColor(row.change_pct, palette) : stableColor(row[groupField] || "未分类");
    scatterChart.setOption({
      animation: false,
      tooltip: {
        confine: true,
        backgroundColor: palette.panel,
        borderColor: palette.line,
        borderWidth: 1,
        padding: [10, 12],
        textStyle: { color: palette.text, fontSize: 11, lineHeight: 18 },
        extraCssText: "border-radius:10px;box-shadow:0 8px 26px rgba(0,0,0,.18);max-width:440px;",
        formatter: p => {
          const r = p?.data?.raw;
          if (!r) return esc(p?.name || "");
          const industry = r.industry || "未分类";
          const primaryConcept = r.primary_concept || "未分类";
          const regionBoard = r.region_board || r.industry_code || "未分类";
          const conceptItems = String(r.concepts || "").split(/[,;，；]/).map(item => item.trim()).filter(Boolean);
          const otherConcepts = conceptItems.filter(item => item !== primaryConcept).slice(0, 6);
          const remainingConcepts = Math.max(0, conceptItems.length - otherConcepts.length - (conceptItems.includes(primaryConcept) ? 1 : 0));
          const changeColor = semanticTextColor(r.change_pct, palette);
          const flowColor = semanticTextColor(r.main_net_inflow, palette);
          const groupColor = STATE.liquidityColorMode === "performance" ? changeColor : stableColor(r[groupField] || "未分类");
          const changeDirection = Number(r.change_pct || 0) > 0 ? "↑ 上涨" : Number(r.change_pct || 0) < 0 ? "↓ 下跌" : "— 平盘";
          const flowDirection = Number(r.main_net_inflow || 0) > 0 ? "↑ 净流入" : Number(r.main_net_inflow || 0) < 0 ? "↓ 净流出" : "— 净额为零";
          const volumeText = fmtVolumeLots(r.volume);
          return `<div style="min-width:300px;color:${palette.text}">
            <div style="display:flex;justify-content:space-between;gap:12px;align-items:baseline;margin-bottom:7px"><b style="font-size:14px;color:${palette.text};display:inline-flex;align-items:center;gap:6px"><i style="width:9px;height:9px;border-radius:50%;background:${groupColor};display:inline-block"></i>${esc(r.name)}</b><span style="color:${palette.muted};font-variant-numeric:tabular-nums">${esc(r.code)}.${esc(r.market)}</span></div>
            <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">${classificationTag(industry, "行业", palette)}${classificationTag(primaryConcept, "概念板块", palette)}${classificationTag(regionBoard, "地域板块", palette)}</div>
            <div style="display:grid;grid-template-columns:auto 1fr;column-gap:12px;row-gap:3px;color:${palette.muted}">
              <span>涨跌幅</span><b style="color:${changeColor};font-variant-numeric:tabular-nums">${changeDirection} ${fmtPct(r.change_pct)}</b>
              <span>成交量</span><b style="color:${palette.text};font-variant-numeric:tabular-nums">${volumeText}${volumeText === "--" ? "（暂无有效 f5）" : `（约${fmtSharesFromLots(r.volume)}）`}</b>
              <span>成交额</span><b style="color:${palette.text};font-variant-numeric:tabular-nums">${fmtMoney(r.amount)}</b>
              <span>量比 / 换手</span><b style="color:${palette.text};font-variant-numeric:tabular-nums">${Number(r.volume_ratio || 0).toFixed(2)} / ${fmtPct(r.turnover_pct)}</b>
              <span>主力资金</span><b style="color:${flowColor};font-variant-numeric:tabular-nums">${flowDirection} ${fmtMoney(r.main_net_inflow)}</b>
            </div>
            <div style="margin-top:8px;color:${palette.muted};white-space:normal;max-width:410px">其他概念：${otherConcepts.length ? esc(otherConcepts.join("、")) : "--"}${remainingConcepts ? ` 等${conceptItems.length}项` : ""}</div>
          </div>`;
        },
      },
      grid: { left: 78, right: 24, top: 28, bottom: 48 },
      xAxis: { type: "value", name: "涨跌幅 %", nameTextStyle: { color: palette.muted }, axisLabel: { color: palette.muted, formatter: "{value}%" }, splitLine: { lineStyle: { color: palette.line } } },
      yAxis: { type: "log", logBase: 10, min: 1, name: "成交量（手，对数轴）", nameTextStyle: { color: palette.muted }, axisLabel: { color: palette.muted, formatter: fmtVolumeAxis }, splitLine: { lineStyle: { color: palette.line } } },
      series: [{ type: "scatter", data: stocks.map(row => ({ value: [Number(row.change_pct || 0), Math.max(1, Number(row.volume || 0)), Number(row.amount || 0)], raw: row, symbolSize: Math.max(7, Math.min(34, 7 + 27 * Math.sqrt(Math.max(0, Number(row.amount || 0)) / p90))), itemStyle: { color: pointColor(row), borderColor: pointColor(row), opacity: .82, borderWidth: 0 } })), markLine: { silent: true, lineStyle: { color: palette.line, type: "dashed" }, data: [{ xAxis: 0 }] } }],
    }, { notMerge: true, lazyUpdate: true, silent: true });
    renderQueue("surgingQueue", payload.queues?.surging);
    renderQueue("activeQueue", payload.queues?.active);
    renderQueue("fallingQueue", payload.queues?.falling);
  }
  async function selectStock(row, force = false) {
    if (!row?.code || !row?.market) return null;
    STATE.selectedStockCode = row.code;
    STATE.selectedStockMarket = row.market;
    STATE.selectedStockName = row.name || row.code;
    $("selectedStockTitle").textContent = `${STATE.selectedStockName} ${row.code}.${row.market} · ${STATE.raceTradeDate || "当天"}连续分时 + 成交量 + 资金流 + 五档盘口`;
    const requestId = ++STATE.stockRequestSeq;
    try {
      const suffix = force ? "&refresh=1" : "";
      const dateQuery = STATE.raceTradeDate ? `&trade_date=${encodeURIComponent(STATE.raceTradeDate)}` : "";
      const auctionQuery = `&include_auction=${STATE.showAuction ? "1" : "0"}`;
      const payload = await json(`/api/market_heatmap/stock_timeline?code=${encodeURIComponent(row.code)}&market=${encodeURIComponent(row.market)}${dateQuery}${auctionQuery}${suffix}`);
      if (requestId !== STATE.stockRequestSeq || row.code !== STATE.selectedStockCode) return;
      renderStockTimeline(payload);
      return payload;
    } catch (error) {
      if (requestId === STATE.stockRequestSeq && row.code === STATE.selectedStockCode) banner(`个股分时读取失败：${error.message}`, "error");
      return null;
    }
  }
  async function selectSector(code, force = false) {
    const sector = STATE.sectors.find(row => row.code === code) || STATE.raceSeriesByCode.get(code);
    if (!sector) return null;
    STATE.selectedCode = code;
    STATE.selectedName = sector.name;
    $("selectedSector").textContent = sector.name;
    $("selectedSectorMeta").textContent = `${code} · ${fmtPct(sector.change_pct ?? sector.snapshot_change_pct)} · ${fmtMoney(sector.main_net_inflow ?? sector.snapshot_flow)}`;
    STATE.lastRaceSignature = "";
    if (STATE.racePayload) renderRace(STATE.racePayload);
    renderRanks(visibleSectors());
    if (STATE.replayMode) {
      const frame = await loadReplayFrame(STATE.replayIndex, code);
      return frame?.core_stocks || null;
    }
    const requestId = ++STATE.sectorRequestSeq;
    try {
      const suffix = force ? "&refresh=1" : "";
      const detail = await json(`/api/market_heatmap/sector?code=${encodeURIComponent(code)}&limit=500${suffix}`);
      if (requestId !== STATE.sectorRequestSeq || code !== STATE.selectedCode) return;
      renderStocks(detail);
      STATE.lastDetailFetchAt = Date.now();
      return detail;
    } catch (error) {
      if (requestId === STATE.sectorRequestSeq && code === STATE.selectedCode) banner(`板块下钻失败：${error.message}`, "error");
      return null;
    }
  }
  function applyLivePayload(payload) {
    renderMeta(payload.snapshot);
    if (STATE.interacting || Date.now() < STATE.themeChartRefreshNotBefore) {
      STATE.deferredPayload = payload;
      return;
    }
    requestAnimationFrame(() => {
      if (payload.sources) {
        STATE.sources = payload.sources;
        renderSourceCatalog(payload.sources);
        STATE.lastSourceRenderAt = Date.now();
      }
      renderRace(payload.race);
      if (payload.stockDetail && payload.stockDetail.code === STATE.selectedStockCode) renderStockTimeline(payload.stockDetail);
      if (payload.heavy) {
        renderSectorSurfaces();
        refreshSectorSparklines(false);
        if (payload.liquidity) {
          STATE.liquidity = payload.liquidity;
          renderLiquidity(payload.liquidity);
        }
        STATE.lastHeavyRenderAt = Date.now();
      }
      if (!STATE.selectedCode && STATE.sectors.length) {
        const defaultSector = [...topFlowSectors(STATE.sectors, 5)].sort((a, b) => b.main_net_inflow - a.main_net_inflow)[0];
        if (defaultSector) selectSector(defaultSector.code, false);
      }
      if (!STATE.selectedStockCode && STATE.liquidity) {
        const defaultStock = STATE.liquidity.queues?.active?.[0] || STATE.liquidity.stocks?.[0];
        if (defaultStock) selectStock(defaultStock, false);
      }
    });
  }
  function flushDeferredPayload() {
    if (STATE.interacting) return;
    if (STATE.deferredPayload) {
      const payload = STATE.deferredPayload;
      STATE.deferredPayload = null;
      STATE.deferredRace = null;
      applyLivePayload(payload);
    } else if (STATE.deferredRace) {
      const race = STATE.deferredRace;
      STATE.deferredRace = null;
      requestAnimationFrame(() => renderRace(race));
    }
  }
  function renderReplayCoverage(manifest) {
    const coverage = manifest?.coverage || {};
    const frames = manifest?.frames || [];
    const first = String(coverage.first_observed || "").slice(11, 16) || "--";
    const last = String(coverage.last_observed || "").slice(11, 16) || "--";
    const sectorGaps = coverage.sector_missing_minutes_within_coverage || [];
    const stockGaps = coverage.stock_missing_minutes_within_coverage || [];
    const stockOnlyFrames = coverage.stock_only_frame_labels || [];
    $("replayCoverage").textContent = frames.length
      ? `${manifest.trade_date} · ${frames.length}个真实帧 · ${first}–${last} · ${coverage.complete_day ? "全天完整" : "部分留档"}`
      : "本地没有可播放的板块分钟截面";
    const sample = [...new Set([...sectorGaps, ...stockGaps])].slice(0, 10);
    $("replayGapNotice").textContent = frames.length
      ? `覆盖口径：板块缺口${sectorGaps.length}分钟，个股缺口${stockGaps.length}分钟${sample.length ? `（如 ${sample.join("、")}）` : ""}；另有仅个股留档${stockOnlyFrames.length}分钟${stockOnlyFrames.length ? `（${stockOnlyFrames.slice(0, 8).join("、")}）` : ""}，不列入可播放帧。只播放SQLite真实板块留档，不插值、不沿用上一帧；旧留档缺少行业/概念时，04核心个股会明确留空。`
      : (manifest?.error || "只播放本机8772实际保存的分钟截面；未留档分钟不会伪造。");
  }
  function setReplayPlaying(playing) {
    STATE.replayPlaying = Boolean(playing && STATE.replayMode && (STATE.replayManifest?.frames || []).length);
    clearTimeout(STATE.replayTimer);
    const button = $("replayPlay");
    button.textContent = STATE.replayPlaying ? "Ⅱ 暂停" : "▶ 播放";
    button.classList.toggle("active", STATE.replayPlaying);
    if (STATE.replayPlaying) scheduleReplayStep();
  }
  function scheduleReplayStep() {
    clearTimeout(STATE.replayTimer);
    if (!STATE.replayPlaying) return;
    STATE.replayTimer = setTimeout(async () => {
      if (!STATE.replayPlaying) return;
      const frames = STATE.replayManifest?.frames || [];
      if (STATE.replayIndex >= frames.length - 1) {
        setReplayPlaying(false);
        banner(`历史回放已到 ${frames.at(-1)?.label || "最后一帧"}；可拖动进度条复看或回到实时。`, "warn");
        return;
      }
      await loadReplayFrame(STATE.replayIndex + 1, STATE.selectedCode);
      if (STATE.replayPlaying) scheduleReplayStep();
    }, Math.max(140, 1000 / Math.max(1, STATE.replaySpeed)));
  }
  async function loadReplayCatalog(activate = false, requestedDate = "") {
    const date = requestedDate || $("replayTradeDate")?.value || "";
    try {
      const query = date ? `&trade_date=${encodeURIComponent(date)}` : "";
      const manifest = await json(`/api/market_heatmap/replay_manifest?board_type=${encodeURIComponent(STATE.boardType)}${query}`);
      STATE.replayManifest = manifest;
      const select = $("replayTradeDate");
      const dates = (manifest.available_dates || []).map(row => String(row.trade_date || "")).filter(Boolean);
      select.innerHTML = dates.map(value => `<option value="${esc(value)}">${esc(value)}</option>`).join("") || `<option value="">暂无本地留档</option>`;
      if (manifest.trade_date && dates.includes(manifest.trade_date)) select.value = manifest.trade_date;
      renderReplayCoverage(manifest);
      const frames = manifest.frames || [];
      $("replayProgress").max = String(Math.max(0, frames.length - 1));
      $("replayProgress").disabled = !frames.length;
      $("replayPlay").disabled = !frames.length;
      if (!activate || !frames.length) return;
      STATE.replayMode = true;
      STATE.raceTradeDate = manifest.trade_date;
      $("raceTradeDate").value = manifest.trade_date;
      $("raceLatest").classList.remove("active");
      $("replayConsole").dataset.replayMode = "active";
      $("replayLive").disabled = false;
      clearTimeout(STATE.timer);
      setReplayPlaying(false);
      await loadReplayFrame(0, STATE.selectedCode);
    } catch (error) {
      if (activate) banner(`历史回放载入失败：${error.message}`, "error");
      $("replayCoverage").textContent = "本地没有可用回放日期";
      $("replayGapNotice").textContent = `回放不可用：${error.message}。不会改用当前截面冒充历史。`;
      $("replayPlay").disabled = true;
      $("replayProgress").disabled = true;
    }
  }
  function applyReplayFrame(payload) {
    const frames = STATE.replayManifest?.frames || [];
    STATE.replayIndex = Number(payload.frame_index || 0);
    STATE.sectors = payload.snapshot?.sectors || [];
    STATE.racePayload = payload.race;
    STATE.liquidity = payload.liquidity;
    STATE.sparklines = new Map((payload.sparklines || []).map(row => [row.code, row.points || []]));
    STATE.selectedCode = payload.selected_code || STATE.selectedCode;
    const selected = STATE.sectors.find(row => row.code === STATE.selectedCode);
    if (selected) {
      STATE.selectedName = selected.name;
      $("selectedSector").textContent = selected.name;
      $("selectedSectorMeta").textContent = `${selected.code} · ${fmtPct(selected.change_pct)} · ${fmtMoney(selected.main_net_inflow)}`;
    }
    $("replayProgress").value = String(STATE.replayIndex);
    $("replayCurrentTime").textContent = `${payload.trade_date} ${payload.frame_time}`;
    renderMeta(payload.snapshot);
    renderSectorSurfaces();
    renderRace(payload.race);
    renderLiquidity(payload.liquidity || { stocks: [], queues: {} });
    renderStocks(payload.core_stocks || { stocks: [], queues: {}, source: {} });
    if (payload.core_stocks?.coverage_message) $("stockSource").textContent = payload.core_stocks.coverage_message;
    const meta = payload.frame || {};
    const coverage = payload.coverage || {};
    banner(
      `历史回放 ${payload.trade_date} ${payload.frame_time} · 板块${Number(meta.sector_count || 0)} · 个股${Number(meta.stock_count || 0)} · ${coverage.core_stock_limitation || "严格使用本地留档"}`,
      meta.sector_complete && meta.stock_complete ? "warn" : "error"
    );
    if (STATE.replayIndex >= frames.length - 1 && STATE.replayPlaying) setReplayPlaying(false);
  }
  async function loadReplayFrame(index, selectedCode = "") {
    const frames = STATE.replayManifest?.frames || [];
    if (!STATE.replayMode || !frames.length) return;
    const safeIndex = Math.max(0, Math.min(frames.length - 1, Number(index || 0)));
    const frame = frames[safeIndex];
    const requestId = ++STATE.replayRequestSeq;
    try {
      const top = STATE.raceLimit || 500;
      const selectedQuery = selectedCode ? `&selected_code=${encodeURIComponent(selectedCode)}` : "";
      const payload = await json(`/api/market_heatmap/replay_frame?board_type=${encodeURIComponent(STATE.boardType)}&trade_date=${encodeURIComponent(STATE.replayManifest.trade_date)}&frame_time=${encodeURIComponent(frame.label)}&top_each=${top}${selectedQuery}`);
      if (requestId !== STATE.replayRequestSeq || !STATE.replayMode) return;
      applyReplayFrame(payload);
      return payload;
    } catch (error) {
      if (requestId === STATE.replayRequestSeq) {
        setReplayPlaying(false);
        banner(`历史回放帧读取失败：${error.message}；没有沿用或插值上一帧。`, "error");
      }
      return null;
    }
  }
  function returnToLive() {
    setReplayPlaying(false);
    STATE.replayMode = false;
    STATE.replayRequestSeq += 1;
    STATE.raceTradeDate = "";
    $("raceTradeDate").value = "";
    $("raceLatest").classList.add("active");
    $("replayConsole").dataset.replayMode = "live";
    $("replayCurrentTime").textContent = "实时";
    $("replayLive").disabled = true;
    STATE.lastHeavyFetchAt = 0;
    STATE.lastRaceSignature = "";
    refresh(true);
  }
  async function refreshRace(force = false) {
    if (STATE.replayMode) {
      await loadReplayFrame(STATE.replayIndex, STATE.selectedCode);
      return;
    }
    const boardType = STATE.boardType;
    const dateQuery = STATE.raceTradeDate ? `&trade_date=${encodeURIComponent(STATE.raceTradeDate)}` : "";
    const forceQuery = force ? "&refresh=1" : "";
    const note = $("raceSourceNote");
    note.querySelector("b").textContent = `${STATE.raceTradeDate || "最近交易日"} · 正在读取多板块分钟曲线…`;
    note.querySelector("span").textContent = "当前图保持上一帧；读取完成后会同时替换曲线和对应的数据源、字段、算法与边界说明。";
    try {
      const raceLimit = STATE.raceLimit || "all";
      const race = await json(`/api/market_heatmap/sector_race?board_type=${boardType}&top_each=${raceLimit}${dateQuery}${forceQuery}`);
      if (boardType !== STATE.boardType) return;
      if (STATE.interacting) {
        STATE.deferredRace = race;
      } else {
        requestAnimationFrame(() => renderRace(race));
      }
    } catch (error) {
      banner(`板块赛马读取失败，保留上一帧：${error.message}`, "error");
    }
  }
  async function refresh(force = false) {
    if (STATE.replayMode) {
      if (force) await loadReplayFrame(STATE.replayIndex, STATE.selectedCode);
      return;
    }
    if (STATE.loading) {
      STATE.pendingRefresh = STATE.pendingRefresh || force;
      return;
    }
    if (STATE.paused && !force) return;
    STATE.loading = true;
    const requestId = ++STATE.refreshSeq;
    const boardType = STATE.boardType;
    const now = Date.now();
    const heavy = force || !STATE.lastHeavyFetchAt || now - STATE.lastHeavyFetchAt >= STATE.heavyInterval;
    if (heavy) STATE.lastHeavyFetchAt = now;
    const needSources = !STATE.sources || now - STATE.lastSourceRenderAt >= 60000;
    try {
      const snapshotSuffix = force ? "&refresh=1" : "";
      const dateQuery = STATE.raceTradeDate ? `&trade_date=${encodeURIComponent(STATE.raceTradeDate)}` : "";
      const raceLimit = STATE.raceLimit || "all";
      const largeRace = STATE.raceLimit === 0 || STATE.raceLimit > 5;
      const needRace = !largeRace || heavy || !STATE.racePayload;
      const racePromise = needRace ? json(`/api/market_heatmap/sector_race?board_type=${boardType}&top_each=${raceLimit}${dateQuery}`).catch(error => ({ ok: false, _error: error })) : Promise.resolve(STATE.racePayload);
      const liquidityPromise = heavy ? json(`/api/market_heatmap/liquidity_watch?limit=500${snapshotSuffix}`).catch(() => null) : Promise.resolve(null);
      const sourcesPromise = needSources ? json("/api/market_heatmap/sources").catch(() => null) : Promise.resolve(null);
      const stockCode = STATE.selectedStockCode;
      const stockMarket = STATE.selectedStockMarket;
      const stockPromise = stockCode && !STATE.raceTradeDate ? json(`/api/market_heatmap/stock_timeline?code=${encodeURIComponent(stockCode)}&market=${encodeURIComponent(stockMarket)}&include_auction=${STATE.showAuction ? "1" : "0"}`).catch(() => null) : Promise.resolve(null);
      const [snapshot, race, liquidity, sources, stockDetail] = await Promise.all([
        json(`/api/market_heatmap/snapshot?board_type=${boardType}${snapshotSuffix}`),
        racePromise,
        liquidityPromise,
        sourcesPromise,
        stockPromise,
      ]);
      if (requestId !== STATE.refreshSeq || boardType !== STATE.boardType) return;
      STATE.interval = snapshot.refresh_interval_ms || 3000;
      STATE.sectors = snapshot.sectors || [];
      if (STATE.selectedCode && !STATE.sectors.some(row => row.code === STATE.selectedCode)) {
        STATE.selectedCode = "";
        STATE.selectedName = "";
      }
      if (!race.ok) {
        renderMeta(snapshot);
        if (race._error) banner(`板块赛马更新失败，保留上一帧：${race._error.message}`, "error");
      } else {
        applyLivePayload({ snapshot, race, liquidity, sources, stockDetail, heavy });
      }
    } catch (error) { banner(`更新失败，保留上一帧：${error.message}`, "error"); }
    finally {
      STATE.loading = false;
      if (STATE.pendingRefresh) {
        STATE.pendingRefresh = false;
        refresh(true);
      } else {
        schedule();
      }
    }
  }
  function renderSectorSurfaces() {
    const rows = visibleSectors();
    renderSummary(STATE.sectors);
    renderRanks(rows);
    renderSectorTreemap();
  }
  async function refreshSectorSparklines(force = false) {
    const rows = topFlowSectors(visibleSectors(), STATE.heatmapLimit);
    const codes = rows.map(row => row.code);
    const key = `${STATE.boardType}|${codes.join(",")}`;
    if (!force && STATE.lastSparkKey === key && Date.now() - Number(STATE.lastSparkFetchAt || 0) < 30000) return;
    const requestId = ++STATE.sparkRequestSeq;
    STATE.lastSparkKey = key;
    try {
      const payload = await json(`/api/market_heatmap/sector_sparklines?board_type=${encodeURIComponent(STATE.boardType)}&codes=${encodeURIComponent(codes.join(","))}&max_points=48`);
      if (requestId !== STATE.sparkRequestSeq || key !== STATE.lastSparkKey) return;
      STATE.sparklines = new Map((payload.series || []).map(row => [row.code, row.points || []]));
      STATE.lastSparkFetchAt = Date.now();
      renderRanks(visibleSectors());
    } catch (error) {
      banner(`板块迷你分时读取失败，金额榜仍可用：${error.message}`, "warn");
    }
  }
  function schedule() {
    clearTimeout(STATE.timer);
    if (!STATE.paused && !STATE.replayMode) STATE.timer = setTimeout(() => refresh(false), STATE.interval);
  }
  function setRaceTradeDate(value) {
    if (STATE.replayMode) {
      setReplayPlaying(false);
      loadReplayCatalog(true, value || STATE.replayManifest?.trade_date || "");
      return;
    }
    STATE.raceTradeDate = value || "";
    $("raceTradeDate").value = value || "";
    $("raceLatest").classList.toggle("active", !value);
    refreshRace(true);
  }
  function shiftRaceDate(towardOlder) {
    const current = $("raceTradeDate").value || STATE.raceDates[0] || "";
    const index = STATE.raceDates.indexOf(current);
    if (index < 0) return;
    const target = STATE.raceDates[index + (towardOlder ? 1 : -1)];
    if (target) setRaceTradeDate(target);
  }
  function setInteracting(active) {
    STATE.pointerInside = active;
    STATE.interacting = active;
    clearTimeout(STATE.interactionTimer);
    if (!active) STATE.interactionTimer = setTimeout(flushDeferredPayload, 220);
  }
  function savePreferences() {
    try {
      localStorage.setItem(PREF_KEY, JSON.stringify({
        heatmapLimit: STATE.heatmapLimit,
        heatmapDetail: STATE.heatmapDetail,
        raceLimit: STATE.raceLimit,
        raceScaleMode: STATE.raceScaleMode,
        stockLimit: STATE.stockLimit,
        stockDetail: STATE.stockDetail,
        liquidityColorMode: STATE.liquidityColorMode,
        liquidityLimit: STATE.liquidityLimit,
        theme: STATE.theme,
        customTheme: STATE.customThemeSaved,
        showAuction: STATE.showAuction,
      }));
    } catch (_error) { /* localStorage can be disabled; the page remains usable. */ }
  }
  function loadPreferences() {
    try {
      const saved = JSON.parse(localStorage.getItem(PREF_KEY) || "{}");
      if (COUNT_CHOICES.includes(saved.heatmapLimit)) STATE.heatmapLimit = saved.heatmapLimit;
      if ([0, 1, 2].includes(saved.heatmapDetail)) STATE.heatmapDetail = saved.heatmapDetail;
      if (RACE_CHOICES.includes(saved.raceLimit)) STATE.raceLimit = saved.raceLimit;
      if (["independent", "shared"].includes(saved.raceScaleMode)) STATE.raceScaleMode = saved.raceScaleMode;
      if (COUNT_CHOICES.includes(saved.stockLimit)) STATE.stockLimit = saved.stockLimit;
      if ([0, 1, 2].includes(saved.stockDetail)) STATE.stockDetail = saved.stockDetail;
      if (["performance", "industry", "concept"].includes(saved.liquidityColorMode)) STATE.liquidityColorMode = saved.liquidityColorMode;
      if (LIQUIDITY_CHOICES.includes(saved.liquidityLimit)) STATE.liquidityLimit = saved.liquidityLimit;
      STATE.customThemeSaved = sanitizeCustomTheme(saved.customTheme);
      STATE.customTheme = { ...STATE.customThemeSaved };
      const savedTheme = THEME_ALIASES[saved.theme] || saved.theme;
      if (THEMES.includes(savedTheme)) STATE.theme = savedTheme;
      if (typeof saved.showAuction === "boolean") STATE.showAuction = saved.showAuction;
    } catch (_error) { /* Ignore old or damaged preference payloads. */ }
    $("heatmapCount").value = String(Math.max(0, COUNT_CHOICES.indexOf(STATE.heatmapLimit)));
    $("heatmapDetail").value = String(STATE.heatmapDetail);
    $("raceCount").value = String(Math.max(0, RACE_CHOICES.indexOf(STATE.raceLimit)));
    $("stockCount").value = String(Math.max(0, COUNT_CHOICES.indexOf(STATE.stockLimit)));
    $("stockDetail").value = String(STATE.stockDetail);
    $("heatmapCountLabel").textContent = limitLabel(STATE.heatmapLimit);
    $("heatmapDetailLabel").textContent = DETAIL_LABELS[STATE.heatmapDetail];
    $("raceCountLabel").textContent = limitLabel(STATE.raceLimit);
    document.querySelectorAll("[data-race-scale]").forEach(button => {
      const active = button.dataset.raceScale === STATE.raceScaleMode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    $("stockCountLabel").textContent = limitLabel(STATE.stockLimit);
    $("stockDetailLabel").textContent = DETAIL_LABELS[STATE.stockDetail];
    if ($("liquidityCount")) $("liquidityCount").value = String(Math.max(0, LIQUIDITY_CHOICES.indexOf(STATE.liquidityLimit)));
    if ($("liquidityCountLabel")) $("liquidityCountLabel").textContent = `TOP${STATE.liquidityLimit}`;
    if (STATE.theme === "custom") STATE.customTheme = applyCustomThemeVars(STATE.customThemeSaved);
    else clearCustomThemeVars();
    document.documentElement.dataset.theme = STATE.theme;
    syncThemeButtons();
    document.querySelectorAll("[data-liquidity-color]").forEach(button => button.classList.toggle("active", button.dataset.liquidityColor === STATE.liquidityColorMode));
  }
  const chartsForModule = module => [sectorChart, stockChart, timelineChart, scatterChart, stockTimelineChart].filter(chart => module.contains(chart.getDom()));
  function resizeModuleCharts(module) {
    requestAnimationFrame(() => chartsForModule(module).forEach(chart => chart.resize()));
  }
  const moduleDefaultSpan = module => Math.max(1, Math.min(PACK_COLUMNS, Number(module.dataset.layoutSpan || PACK_COLUMNS)));
  const moduleSpan = module => {
    const raw = Number.parseInt(module.style.getPropertyValue("--module-span"), 10);
    return Number.isFinite(raw) ? Math.max(1, Math.min(PACK_COLUMNS, raw)) : moduleDefaultSpan(module);
  };
  function spanForWidth(width) {
    const pack = $("dashboardPack");
    const packWidth = Math.max(1, pack?.getBoundingClientRect().width || document.documentElement.clientWidth - 52);
    const gap = PACK_GAP;
    const track = Math.max(1, (packWidth - gap * (PACK_COLUMNS - 1)) / PACK_COLUMNS);
    return Math.max(1, Math.min(PACK_COLUMNS, Math.round((Number(width || 0) + gap) / (track + gap))));
  }
  function packModules() {
    packFrame = 0;
    const pack = $("dashboardPack");
    if (!pack) return;
    const wasPacked = pack.classList.contains("is-packed");
    pack.querySelectorAll(":scope > .user-resizable[data-module-id]").forEach(module => {
      const height = Math.ceil(module.getBoundingClientRect().height);
      module.style.setProperty("--module-row-span", String(Math.max(1, height + PACK_GAP)));
    });
    pack.classList.add("is-packed");
    if (!wasPacked) requestAnimationFrame(packModules);
  }
  function schedulePack() {
    if (packFrame) return;
    packFrame = requestAnimationFrame(packModules);
  }
  function saveLayout() {
    const modules = {};
    document.querySelectorAll(".user-resizable[data-module-id]").forEach(module => {
      const height = Number.parseFloat(module.style.height);
      modules[module.dataset.moduleId] = {
        span: moduleSpan(module),
        ...(Number.isFinite(height) ? { height: Math.round(height) } : {}),
      };
    });
    try { localStorage.setItem(LAYOUT_KEY, JSON.stringify({ version: 2, gap: PACK_GAP, modules })); } catch (_error) { /* best effort */ }
  }
  function initResizableModules() {
    let saved = {};
    let savedVersion = 0;
    try {
      const payload = JSON.parse(localStorage.getItem(LAYOUT_KEY) || "{}");
      if ([1, 2].includes(payload.version) && payload.modules && typeof payload.modules === "object") {
        saved = payload.modules;
        savedVersion = payload.version;
      }
    } catch (_error) { saved = {}; }
    document.querySelectorAll(".user-resizable[data-module-id]").forEach(module => {
      const dimensions = saved[module.dataset.moduleId] || {};
      const legacyWidth = Number.parseFloat(dimensions.width);
      const savedSpan = Number.parseInt(dimensions.span, 10);
      const span = savedVersion === 2 && Number.isFinite(savedSpan)
        ? Math.max(1, Math.min(PACK_COLUMNS, savedSpan))
        : Number.isFinite(legacyWidth) ? spanForWidth(legacyWidth) : moduleDefaultSpan(module);
      const rawHeight = Number.parseFloat(dimensions.height);
      module.style.setProperty("--module-span", String(span));
      if (Number.isFinite(rawHeight)) {
        const minHeight = Number.parseFloat(getComputedStyle(module).minHeight) || 120;
        module.style.height = `${Math.min(1200, Math.max(minHeight, rawHeight))}px`;
        module.classList.add("has-user-height");
      }
      if (span !== moduleDefaultSpan(module) || Number.isFinite(rawHeight)) module.classList.add("has-user-size");
      ["n", "ne", "e", "se", "s", "sw", "w", "nw"].forEach(direction => {
        const handle = document.createElement("i");
        handle.className = `resize-handle ${direction}`;
        handle.dataset.direction = direction;
        handle.setAttribute("aria-hidden", "true");
        module.appendChild(handle);
        handle.addEventListener("mousedown", event => {
          event.preventDefault();
          module.classList.add("is-resizing");
          module.classList.add("has-user-size");
          setInteracting(true);
          const start = { x: event.clientX, y: event.clientY, width: module.getBoundingClientRect().width, height: module.getBoundingClientRect().height };
          const move = moveEvent => {
            const dx = moveEvent.clientX - start.x;
            const dy = moveEvent.clientY - start.y;
            const growX = direction.includes("w") ? -dx : direction.includes("e") ? dx : 0;
            const growY = direction.includes("n") ? -dy : direction.includes("s") ? dy : 0;
            if (growX) module.style.setProperty("--module-span", String(spanForWidth(start.width + growX)));
            if (growY) {
              const minHeight = Number.parseFloat(getComputedStyle(module).minHeight) || 120;
              module.style.height = `${Math.min(1200, Math.max(minHeight, start.height + growY))}px`;
              module.classList.add("has-user-height");
            }
            schedulePack();
            resizeModuleCharts(module);
          };
          const finish = () => {
            window.removeEventListener("mousemove", move);
            window.removeEventListener("mouseup", finish);
            module.classList.remove("is-resizing");
            setInteracting(false);
            saveLayout();
            schedulePack();
            resizeModuleCharts(module);
          };
          window.addEventListener("mousemove", move);
          window.addEventListener("mouseup", finish);
        });
      });
    });
    if (typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(entries => {
        entries.forEach(entry => resizeModuleCharts(entry.target));
        schedulePack();
      });
      document.querySelectorAll(".user-resizable[data-module-id]").forEach(module => observer.observe(module));
    }
    saveLayout();
    schedulePack();
  }
  function resetLayout() {
    try { localStorage.removeItem(LAYOUT_KEY); } catch (_error) { /* best effort */ }
    document.querySelectorAll(".user-resizable[data-module-id]").forEach(module => {
      module.style.width = "";
      module.style.height = "";
      module.style.removeProperty("--module-span");
      module.style.removeProperty("--module-row-span");
      module.classList.remove("has-user-size", "has-user-height");
      module.style.setProperty("--module-span", String(moduleDefaultSpan(module)));
    });
    schedulePack();
    requestAnimationFrame(() => [sectorChart, stockChart, timelineChart, scatterChart, stockTimelineChart].forEach(chart => chart.resize()));
    banner("已恢复默认模块尺寸并自动紧凑重排；刷新后不会保存空洞。", "");
  }
  function syncThemeButtons() {
    document.querySelectorAll("[data-theme-choice]").forEach(button => {
      const active = button.dataset.themeChoice === STATE.theme;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    const customButton = $("customThemeButton");
    if (customButton) {
      customButton.style.setProperty("--theme-accent", STATE.customThemeSaved.hex);
      customButton.title = `${STATE.customThemeSaved.name} · ${STATE.customThemeSaved.hex.toUpperCase()}`;
    }
  }
  function refreshThemeCharts() {
    STATE.stockHoverActive = false;
    STATE.stockHoverTime = "";
    [sectorChart, stockChart, timelineChart, scatterChart, stockTimelineChart].forEach(chart => {
      chart.getZr().trigger("globalout", { event: {} });
      chart.dispatchAction({ type: "hideTip" });
    });
    STATE.lastRaceSignature = "";
    clearTimeout(STATE.stockThemeRefreshTimer);
    STATE.stockThemeRefreshNotBefore = Date.now() + 1800;
    STATE.stockThemeRefreshTimer = setTimeout(() => {
      STATE.stockThemeRefreshTimer = 0;
      STATE.stockThemeRefreshNotBefore = 0;
      STATE.lastStockTimelineSignature = "";
      stockTimelineChart.getZr().trigger("globalout", { event: {} });
      stockTimelineChart.dispatchAction({ type: "hideTip" });
      stockTimelineChart.resize();
      if (STATE.currentStockPayload) renderStockTimeline(STATE.currentStockPayload);
    }, 1800);
    clearTimeout(STATE.themeChartRefreshTimer);
    STATE.themeChartRefreshNotBefore = Date.now() + 500;
    STATE.themeChartRefreshTimer = setTimeout(() => {
      STATE.themeChartRefreshTimer = 0;
      STATE.themeChartRefreshNotBefore = 0;
      requestAnimationFrame(() => requestAnimationFrame(() => {
        [sectorChart, stockChart, timelineChart, scatterChart].forEach(chart => chart.resize());
        if (STATE.sectors.length) renderSectorSurfaces();
        if (STATE.racePayload) renderRace(STATE.racePayload);
        if (STATE.selectedSectorDetail) renderStocks(STATE.selectedSectorDetail);
        if (STATE.liquidity) renderLiquidity(STATE.liquidity);
        flushDeferredPayload();
      }));
    }, 500);
  }
  function hideCustomThemePanel() {
    const panel = $("customThemePanel");
    if (panel) panel.hidden = true;
    $("customThemeButton")?.setAttribute("aria-expanded", "false");
  }
  function applyTheme(theme, options = {}) {
    const normalizedTheme = THEME_ALIASES[theme] || theme;
    STATE.theme = THEMES.includes(normalizedTheme) ? normalizedTheme : "cloud";
    if (STATE.theme === "custom") STATE.customTheme = applyCustomThemeVars(STATE.customTheme);
    else {
      clearCustomThemeVars();
      if (!options.keepEditorOpen) hideCustomThemePanel();
    }
    document.documentElement.dataset.theme = STATE.theme;
    syncThemeButtons();
    if (options.persist !== false) savePreferences();
    if (options.refreshCharts !== false) refreshThemeCharts();
  }
  function updateCustomThemeControls() {
    const theme = sanitizeCustomTheme(STATE.customTheme);
    STATE.customTheme = theme;
    const field = $("customColorField");
    const cursor = $("customColorCursor");
    field?.style.setProperty("--picker-hue", String(theme.hue));
    if (cursor) {
      cursor.style.left = `${theme.saturation}%`;
      cursor.style.top = `${100 - theme.value}%`;
    }
    if (field) {
      field.setAttribute("aria-valuenow", String(Math.round(theme.value)));
      field.setAttribute("aria-valuetext", `饱和度${Math.round(theme.saturation)}%，明度${Math.round(theme.value)}%`);
    }
    if ($("customHue")) $("customHue").value = String(Math.round(theme.hue));
    if ($("customHex")) {
      $("customHex").value = theme.hex.toUpperCase();
      $("customHex").setAttribute("aria-invalid", "false");
    }
    if ($("customThemeSave")) $("customThemeSave").disabled = false;
    if ($("customThemeName")) $("customThemeName").value = theme.name;
    document.querySelectorAll("[data-custom-mode]").forEach(button => {
      const active = button.dataset.customMode === theme.mode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    const { companion, tokens } = customThemeTokens(theme);
    $("customPreviewAccent")?.style.setProperty("background", theme.hex);
    $("customPreviewSurface")?.style.setProperty("background", tokens["--panel"]);
    $("customPreviewCompanion")?.style.setProperty("background", companion);
    if ($("customPreviewLabel")) $("customPreviewLabel").textContent = `${theme.name} · ${theme.hex.toUpperCase()} · ${theme.mode === "dark" ? "深色" : "浅色"}`;
  }
  function previewCustomTheme(refreshCharts = false) {
    if (STATE.customThemeFrame) cancelAnimationFrame(STATE.customThemeFrame);
    STATE.customThemeFrame = requestAnimationFrame(() => {
      STATE.customThemeFrame = 0;
      STATE.customTheme = applyCustomThemeVars(STATE.customTheme);
      STATE.theme = "custom";
      document.documentElement.dataset.theme = "custom";
      syncThemeButtons();
      updateCustomThemeControls();
      if (refreshCharts) refreshThemeCharts();
    });
  }
  function openCustomThemeEditor() {
    const panel = $("customThemePanel");
    if (!panel) return;
    if (!panel.hidden) {
      cancelCustomThemeEditor();
      return;
    }
    STATE.customThemePrevious = STATE.theme;
    STATE.customTheme = { ...STATE.customThemeSaved };
    panel.hidden = false;
    $("customThemeButton")?.setAttribute("aria-expanded", "true");
    applyTheme("custom", { persist: false, keepEditorOpen: true });
    updateCustomThemeControls();
    requestAnimationFrame(() => $("customColorField")?.focus());
  }
  function cancelCustomThemeEditor() {
    STATE.customTheme = { ...STATE.customThemeSaved };
    const previous = STATE.customThemePrevious === "custom" ? "custom" : STATE.customThemePrevious;
    hideCustomThemePanel();
    applyTheme(previous, { persist: false });
  }
  function saveCustomTheme() {
    const hexInput = $("customHex");
    if (!normalizeHex(hexInput?.value)) {
      hexInput?.setAttribute("aria-invalid", "true");
      hexInput?.focus();
      banner("自定义颜色格式无效，未保存；请使用 #RRGGBB。", "warn");
      return;
    }
    STATE.customThemeSaved = sanitizeCustomTheme(STATE.customTheme);
    STATE.customTheme = { ...STATE.customThemeSaved };
    hideCustomThemePanel();
    applyTheme("custom");
    banner(`已保存自定义主题“${STATE.customThemeSaved.name}”；刷新页面后仍会保留。`, "");
  }
  function resetCustomThemeDraft() {
    STATE.customTheme = { ...DEFAULT_CUSTOM_THEME };
    previewCustomTheme(true);
  }
  function updateCustomThemeFromField(event) {
    const field = $("customColorField");
    if (!field) return;
    const bounds = field.getBoundingClientRect();
    const saturation = clamp((event.clientX - bounds.left) / Math.max(1, bounds.width) * 100, 0, 100);
    const value = clamp(100 - (event.clientY - bounds.top) / Math.max(1, bounds.height) * 100, 0, 100);
    STATE.customTheme = { ...STATE.customTheme, saturation, value, hex: hsvToHex(STATE.customTheme.hue, saturation, value) };
    previewCustomTheme(false);
  }
  function bindCustomThemeEditor() {
    const field = $("customColorField");
    if (!field) return;
    field.addEventListener("pointerdown", event => {
      STATE.customThemeDragging = true;
      setInteracting(true);
      field.setPointerCapture?.(event.pointerId);
      updateCustomThemeFromField(event);
    });
    field.addEventListener("pointermove", event => { if (STATE.customThemeDragging) updateCustomThemeFromField(event); });
    const finishDrag = event => {
      if (!STATE.customThemeDragging) return;
      STATE.customThemeDragging = false;
      field.releasePointerCapture?.(event.pointerId);
      setInteracting(false);
      previewCustomTheme(true);
    };
    field.addEventListener("pointerup", finishDrag);
    field.addEventListener("pointercancel", finishDrag);
    field.addEventListener("keydown", event => {
      const step = event.shiftKey ? 5 : 1;
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
      event.preventDefault();
      const saturation = clamp(STATE.customTheme.saturation + (event.key === "ArrowLeft" ? -step : event.key === "ArrowRight" ? step : 0), 0, 100);
      const value = clamp(STATE.customTheme.value + (event.key === "ArrowDown" ? -step : event.key === "ArrowUp" ? step : 0), 0, 100);
      STATE.customTheme = { ...STATE.customTheme, saturation, value, hex: hsvToHex(STATE.customTheme.hue, saturation, value) };
      previewCustomTheme(true);
    });
    const hueInput = $("customHue");
    hueInput?.addEventListener("pointerdown", () => setInteracting(true));
    hueInput?.addEventListener("pointerup", () => setInteracting(false));
    hueInput?.addEventListener("pointercancel", () => setInteracting(false));
    hueInput?.addEventListener("input", event => {
      const hue = clamp(event.target.value, 0, 359);
      STATE.customTheme = { ...STATE.customTheme, hue, hex: hsvToHex(hue, STATE.customTheme.saturation, STATE.customTheme.value) };
      previewCustomTheme(false);
    });
    hueInput?.addEventListener("change", () => previewCustomTheme(true));
    const commitHex = () => {
      const input = $("customHex");
      const hex = normalizeHex(input?.value);
      if (!hex) {
        input?.setAttribute("aria-invalid", "true");
        banner("自定义颜色需要使用 #RRGGBB 格式。", "warn");
        return;
      }
      const hsv = hexToHsv(hex);
      STATE.customTheme = { ...STATE.customTheme, ...hsv, hex };
      previewCustomTheme(true);
    };
    $("customHex")?.addEventListener("input", event => {
      const valid = Boolean(normalizeHex(event.target.value));
      event.target.setAttribute("aria-invalid", String(!valid));
      if ($("customThemeSave")) $("customThemeSave").disabled = !valid;
    });
    $("customHex")?.addEventListener("change", commitHex);
    $("customHex")?.addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); commitHex(); } });
    $("customThemeName")?.addEventListener("input", event => {
      STATE.customTheme = { ...STATE.customTheme, name: String(event.target.value || "").slice(0, 12) || DEFAULT_CUSTOM_THEME.name };
      updateCustomThemeControls();
    });
    document.querySelectorAll("[data-custom-mode]").forEach(button => button.addEventListener("click", () => {
      STATE.customTheme = { ...STATE.customTheme, mode: button.dataset.customMode };
      previewCustomTheme(true);
    }));
    $("customThemeSave")?.addEventListener("click", saveCustomTheme);
    $("customThemeReset")?.addEventListener("click", resetCustomThemeDraft);
    $("customThemeCancel")?.addEventListener("click", cancelCustomThemeEditor);
    $("customThemeClose")?.addEventListener("click", cancelCustomThemeEditor);
    $("customThemePanel")?.addEventListener("keydown", event => {
      if (event.key === "Escape") { event.preventDefault(); cancelCustomThemeEditor(); }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); saveCustomTheme(); }
    });
  }
  function bindDialog(openId, dialogId, closeId) {
    const openButton = $(openId);
    const dialog = $(dialogId);
    const closeButton = $(closeId);
    if (!openButton || !dialog) return;
    const open = () => typeof dialog.showModal === "function" ? dialog.showModal() : dialog.setAttribute("open", "");
    const close = () => typeof dialog.close === "function" ? dialog.close() : dialog.removeAttribute("open");
    openButton.addEventListener("click", open);
    closeButton?.addEventListener("click", close);
    dialog.addEventListener("click", event => { if (event.target === dialog) close(); });
  }
  async function openStockTarget(row, origin) {
    if (!row?.code || !row?.market) return false;
    const current = STATE.currentStockPayload;
    const alreadyRendered = current?.code === row.code && current?.market === row.market;
    if (!alreadyRendered) {
      const payload = await selectStock(row, false);
      if (!payload) return false;
    }
    stockTerminalDialogController?.open(origin);
    return Boolean(stockTerminalDialogController);
  }
  async function openSectorTarget(code, origin) {
    if (!code) return false;
    let detail = STATE.selectedSectorDetailCode === code ? STATE.selectedSectorDetail : null;
    if (!detail) detail = await selectSector(code, false);
    const coreStocks = [...(detail?.stocks || [])].filter(row => row?.code && row?.market).sort((a, b) => Number(b.amount || 0) - Number(a.amount || 0));
    const target = coreStocks[0] || (STATE.selectedStockCode && STATE.selectedStockMarket ? {
      code: STATE.selectedStockCode,
      market: STATE.selectedStockMarket,
      name: STATE.selectedStockName,
    } : null);
    if (!target) {
      banner(`板块 ${STATE.selectedName || code} 暂无可路由的核心个股，未打开空白05B终端。`, "warn");
      return false;
    }
    return openStockTarget(target, origin);
  }
  function bindEntityDoubleClicks() {
    document.addEventListener("dblclick", event => {
      const target = event.target instanceof Element ? event.target.closest("[data-entity-kind]") : null;
      if (!target) return;
      event.preventDefault();
      if (target.dataset.entityKind === "sector") openSectorTarget(target.dataset.code, target);
      if (target.dataset.entityKind === "stock") openStockTarget({ code: target.dataset.code, market: target.dataset.market, name: target.dataset.name }, target);
    });
    document.addEventListener("keydown", event => {
      if (event.key !== "Enter") return;
      const target = event.target instanceof Element ? event.target.closest("[data-entity-kind]") : null;
      if (!target) return;
      event.preventDefault();
      if (target.dataset.entityKind === "sector") openSectorTarget(target.dataset.code, target);
      if (target.dataset.entityKind === "stock") openStockTarget({ code: target.dataset.code, market: target.dataset.market, name: target.dataset.name }, target);
    });
  }
  function bindStockTerminalDialog() {
    const openButton = $("stockTerminalOpen");
    const dialog = $("stockTerminalDialog");
    const closeButton = $("stockTerminalClose");
    const terminal = $("stockTerminalWorkspace");
    const home = $("stockTerminalHome");
    const modalMount = $("stockTerminalModalMount");
    const title = $("stockTerminalDialogTitle");
    const source = $("stockTerminalDialogSource");
    if (!openButton || !dialog || !terminal || !home || !modalMount || !title || !source) return;
    let returnFocus = null;
    let returnScrollY = 0;
    let restoring = false;
    const syncHeading = () => {
      const identity = STATE.selectedStockCode
        ? `${STATE.selectedStockName || STATE.selectedStockCode} ${STATE.selectedStockCode}.${STATE.selectedStockMarket}`
        : "尚未选择标的";
      title.textContent = `05B · ${identity} · 连续分时成交终端`;
      source.textContent = `${$("stockTimelineSource")?.textContent || "分钟行情读取中"} · ${$("stockDetailSource")?.querySelector("b")?.textContent || "来源读取中"}`;
    };
    const focusableNodes = () => [...dialog.querySelectorAll('button:not([disabled]),input:not([disabled]),select:not([disabled]),[href],[tabindex]:not([tabindex="-1"])')].filter(node => !node.hidden && node.getClientRects().length);
    const moveToModal = (origin = document.activeElement) => {
      if (restoring) return;
      returnFocus = origin instanceof HTMLElement ? origin : document.activeElement;
      returnScrollY = window.scrollY;
      modalMount.querySelector(".modal-mount-hint")?.remove();
      modalMount.appendChild(terminal);
      syncHeading();
      if (!dialog.hasAttribute("open")) {
        if (typeof dialog.showModal === "function") dialog.showModal(); else dialog.setAttribute("open", "");
      }
      requestAnimationFrame(() => {
        stockTimelineChart.resize();
        closeButton?.focus({ preventScroll: true });
      });
    };
    const restore = (closeDialog = true) => {
      if (restoring) return;
      restoring = true;
      if (terminal.parentElement !== home) home.appendChild(terminal);
      if (closeDialog && dialog.hasAttribute("open")) {
        if (typeof dialog.close === "function") dialog.close(); else dialog.removeAttribute("open");
      }
      requestAnimationFrame(() => {
        stockTimelineChart.resize();
        schedulePack();
        requestAnimationFrame(() => {
          window.scrollTo({ top: returnScrollY, left: window.scrollX, behavior: "auto" });
          const focusTarget = returnFocus?.isConnected ? returnFocus : openButton;
          if (typeof focusTarget?.focus === "function") focusTarget.focus({ preventScroll: true });
          restoring = false;
        });
      });
    };
    stockTerminalDialogController = { open: moveToModal, close: () => restore(true), syncHeading };
    openButton.addEventListener("click", event => moveToModal(event.currentTarget));
    closeButton?.addEventListener("click", () => restore(true));
    dialog.addEventListener("cancel", event => { event.preventDefault(); restore(); });
    dialog.addEventListener("click", event => { if (event.target === dialog) restore(); });
    dialog.addEventListener("keydown", event => {
      if (event.key !== "Tab") return;
      const focusable = focusableNodes();
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    });
    dialog.addEventListener("close", () => restore(false));
  }
  loadPreferences();
  initResizableModules();
  document.querySelectorAll('[data-theme-choice]:not([data-theme-choice="custom"])').forEach(button => button.addEventListener("click", () => applyTheme(button.dataset.themeChoice)));
  $("customThemeButton")?.addEventListener("click", openCustomThemeEditor);
  bindCustomThemeEditor();
  bindDialog("settingsButton", "settingsDialog", "settingsClose");
  bindStockTerminalDialog();
  bindEntityDoubleClicks();
  $("replayLoad")?.addEventListener("click", () => loadReplayCatalog(true, $("replayTradeDate").value));
  $("replayPlay")?.addEventListener("click", () => setReplayPlaying(!STATE.replayPlaying));
  $("replaySpeed")?.addEventListener("change", event => {
    STATE.replaySpeed = [1, 2, 5].includes(Number(event.target.value)) ? Number(event.target.value) : 1;
    if (STATE.replayPlaying) scheduleReplayStep();
  });
  $("replayProgress")?.addEventListener("input", event => {
    setReplayPlaying(false);
    loadReplayFrame(Number(event.target.value), STATE.selectedCode);
  });
  $("replayLive")?.addEventListener("click", returnToLive);
  document.querySelectorAll("[data-board]").forEach(button => button.addEventListener("click", () => {
    document.querySelectorAll("[data-board]").forEach(node => node.classList.toggle("active", node === button));
    STATE.boardType = button.dataset.board; STATE.selectedCode = ""; STATE.selectedName = ""; STATE.sectorRequestSeq += 1; STATE.sparklines = new Map(); STATE.lastSparkKey = ""; STATE.lastRaceSignature = "";
    STATE.liquidityColorMode = STATE.boardType === "concept" ? "concept" : "industry";
    document.querySelectorAll("[data-liquidity-color]").forEach(node => node.classList.toggle("active", node.dataset.liquidityColor === STATE.liquidityColorMode));
    if (STATE.liquidity) renderLiquidity(STATE.liquidity);
    savePreferences();
    $("selectedSector").textContent = "加载中…"; $("selectedSectorMeta").textContent = "正在切换板块类型";
    if (STATE.replayMode) loadReplayCatalog(true, STATE.replayManifest?.trade_date || ""); else refresh(true);
  }));
  $("sizeMetric").addEventListener("change", renderSectorTreemap);
  $("colorMetric").addEventListener("change", renderSectorTreemap);
  $("sectorSearch").addEventListener("input", renderSectorSurfaces);
  $("heatmapDetail").addEventListener("input", event => { STATE.heatmapDetail = Number(event.target.value); $("heatmapDetailLabel").textContent = DETAIL_LABELS[STATE.heatmapDetail]; renderSectorTreemap(); savePreferences(); });
  $("heatmapCount").addEventListener("input", event => { STATE.heatmapLimit = COUNT_CHOICES[Number(event.target.value)]; $("heatmapCountLabel").textContent = limitLabel(STATE.heatmapLimit); renderSectorSurfaces(); savePreferences(); });
  $("heatmapCount").addEventListener("change", () => refreshSectorSparklines(true));
  document.querySelectorAll("[data-race-scale]").forEach(button => button.addEventListener("click", () => {
    const mode = button.dataset.raceScale;
    if (!["independent", "shared"].includes(mode) || mode === STATE.raceScaleMode) return;
    STATE.raceScaleMode = mode;
    document.querySelectorAll("[data-race-scale]").forEach(node => {
      const active = node.dataset.raceScale === mode;
      node.classList.toggle("active", active);
      node.setAttribute("aria-pressed", String(active));
    });
    STATE.lastRaceSignature = "";
    if (STATE.racePayload) renderRace(STATE.racePayload);
    savePreferences();
  }));
  $("raceCount").addEventListener("input", event => { STATE.raceLimit = RACE_CHOICES[Number(event.target.value)]; $("raceCountLabel").textContent = limitLabel(STATE.raceLimit); $("raceTitle").textContent = `多板块资金赛马 · 净流入${limitLabel(STATE.raceLimit)} vs 净流出${limitLabel(STATE.raceLimit)} · ${STATE.raceScaleMode === "independent" ? "独立双尺度" : "共同尺度"}`; savePreferences(); });
  $("raceCount").addEventListener("change", () => { STATE.lastRaceSignature = ""; refreshRace(true); });
  $("stockDetail").addEventListener("input", event => { STATE.stockDetail = Number(event.target.value); $("stockDetailLabel").textContent = DETAIL_LABELS[STATE.stockDetail]; if (STATE.selectedSectorDetail) renderStocks(STATE.selectedSectorDetail); savePreferences(); });
  $("stockCount").addEventListener("input", event => { STATE.stockLimit = COUNT_CHOICES[Number(event.target.value)]; $("stockCountLabel").textContent = limitLabel(STATE.stockLimit); if (STATE.selectedSectorDetail) renderStocks(STATE.selectedSectorDetail); savePreferences(); });
  if ($("liquidityCount")) $("liquidityCount").addEventListener("input", event => { STATE.liquidityLimit = LIQUIDITY_CHOICES[Number(event.target.value)]; $("liquidityCountLabel").textContent = `TOP${STATE.liquidityLimit}`; if (STATE.liquidity) renderLiquidity(STATE.liquidity); savePreferences(); });
  if ($("auctionToggle")) $("auctionToggle").addEventListener("change", event => {
    STATE.showAuction = Boolean(event.target.checked);
    savePreferences();
    if (STATE.selectedStockCode) selectStock({ code: STATE.selectedStockCode, market: STATE.selectedStockMarket, name: STATE.selectedStockName }, true);
  });
  document.querySelectorAll("[data-liquidity-color]").forEach(button => button.addEventListener("click", () => {
    STATE.liquidityColorMode = button.dataset.liquidityColor;
    document.querySelectorAll("[data-liquidity-color]").forEach(node => node.classList.toggle("active", node === button));
    if (STATE.liquidity) renderLiquidity(STATE.liquidity);
    savePreferences();
  }));
  $("raceTradeDate").addEventListener("change", event => setRaceTradeDate(event.target.value));
  $("raceOlder").addEventListener("click", () => shiftRaceDate(true));
  $("raceNewer").addEventListener("click", () => shiftRaceDate(false));
  $("raceLatest").addEventListener("click", () => STATE.replayMode ? returnToLive() : setRaceTradeDate(""));
  $("pauseButton").addEventListener("click", () => { STATE.paused = !STATE.paused; $("pauseButton").classList.toggle("active", STATE.paused); $("pauseButton").textContent = STATE.paused ? "继续更新" : "冻结排序"; banner(STATE.paused ? "已冻结自动更新；仍可手动立即刷新。" : "已恢复 3 秒更新。", STATE.paused ? "warn" : ""); if (STATE.paused) clearTimeout(STATE.timer); else refresh(false); });
  $("refreshButton").addEventListener("click", () => refresh(true));
  $("resetLayoutButton").addEventListener("click", resetLayout);
  sectorChart.on("click", params => params.data?.code && selectSector(params.data.code));
  stockChart.on("click", params => params.data?.raw && selectStock(params.data.raw));
  scatterChart.on("click", params => params.data?.raw && selectStock(params.data.raw));
  timelineChart.on("click", params => {
    const code = String(params.seriesId || "").replace(/^race-/, "");
    if (code.startsWith("BK")) selectSector(code);
  });
  sectorChart.on("dblclick", params => params.data?.code && openSectorTarget(params.data.code, $("sectorTreemap")));
  stockChart.on("dblclick", params => params.data?.raw && openStockTarget(params.data.raw, $("stockTreemap")));
  scatterChart.on("dblclick", params => params.data?.raw && openStockTarget(params.data.raw, $("liquidityScatter")));
  timelineChart.on("dblclick", params => {
    const code = String(params.seriesId || "").replace(/^race-/, "");
    if (code.startsWith("BK")) openSectorTarget(code, $("flowTimeline"));
  });
  stockTimelineChart.on("updateAxisPointer", event => {
    const axis = (event.axesInfo || []).find(item => item.axisDim === "x" && Number(item.axisIndex) >= 0);
    if (axis?.value != null) {
      const raw = axis.value;
      const categories = payloadCategories(STATE.currentStockPayload, Boolean(STATE.showAuction && STATE.currentStockPayload?.auction?.available));
      STATE.stockHoverTime = typeof raw === "number" && categories[raw] != null ? String(categories[raw]) : String(raw);
    }
  });
  $("stockTimeline")?.addEventListener("pointerenter", () => { STATE.stockHoverActive = true; }, { passive: true });
  $("stockTimeline")?.addEventListener("pointerleave", () => {
    STATE.stockHoverActive = false;
    STATE.stockHoverTime = "";
  }, { passive: true });
  document.querySelectorAll(".chart").forEach(node => {
    node.addEventListener("pointerenter", () => setInteracting(true), { passive: true });
    node.addEventListener("pointerleave", () => setInteracting(false), { passive: true });
  });
  window.addEventListener("scroll", () => {
    STATE.interacting = true;
    clearTimeout(STATE.interactionTimer);
    STATE.interactionTimer = setTimeout(() => { STATE.interacting = STATE.pointerInside; if (!STATE.interacting) flushDeferredPayload(); }, 260);
  }, { passive: true });
  window.addEventListener("resize", () => {
    schedulePack();
    [sectorChart, stockChart, timelineChart, scatterChart, stockTimelineChart].forEach(chart => chart.resize());
  });
  loadReplayCatalog(false);
  refresh(true);
})();
