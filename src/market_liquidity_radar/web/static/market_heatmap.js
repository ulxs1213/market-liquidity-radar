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
    showAuction: false,
    currentStockPayload: null,
    sparklines: new Map(),
    sparkRequestSeq: 0,
    selectedSectorDetail: null,
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
  const THEMES = ["cloud", "midnight", "ocean", "sand", "slate", "violet"];
  const DETAIL_LABELS = ["简洁", "标准", "详细"];
  const LAYOUT_KEY = "market-liquidity-radar-layout-v1";
  const PREF_KEY = "market-liquidity-radar-preferences-v2";

  const fmtMoney = (value) => {
    const n = Number(value || 0);
    if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)}亿`;
    if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(0)}万`;
    return n.toFixed(0);
  };
  const fmtPct = (value) => `${Number(value || 0) >= 0 ? "+" : ""}${Number(value || 0).toFixed(2)}%`;
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
  const stableColor = value => {
    let hash = 0;
    for (const char of String(value || "未分类")) hash = ((hash << 5) - hash + char.charCodeAt(0)) | 0;
    return `hsl(${Math.abs(hash) % 360} 58% 56% / .78)`;
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
    const replay = ["historical_replay", "cached_replay", "closed"].includes(payload.mode);
    mode.textContent = payload.mode === "morning" || payload.mode === "afternoon" ? "盘中动态" : replay ? "历史回放" : payload.mode || "状态未知";
    mode.className = `badge ${replay ? "replay" : payload.ok ? "" : "error"}`;
    $("dataTime").textContent = payload.data_time || "--";
    $("fetchedAt").textContent = payload.generated_at || "--";
    $("sourceName").textContent = payload.source?.provider || "--";
    $("sourceLatency").textContent = payload.source?.elapsed_ms != null ? `${payload.source.elapsed_ms}ms` : "--";
    const provenance = [
      payload.source?.provider || "来源未知",
      payload.source?.possibly_delayed ? "可能延迟" : "主域",
      payload.source?.elapsed_ms != null ? `${payload.source.elapsed_ms}ms` : "",
    ].filter(Boolean).join(" · ");
    banner(`${payload.status_message || "数据已更新。"} 来源：${provenance}`, replay || payload.source?.possibly_delayed ? "warn" : "");
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
      return `<div class="rank-row ${row.code === STATE.selectedCode ? "selected" : ""}" data-code="${row.code}"><span class="num">${String(index + 1).padStart(2, "0")}</span><span><b>${esc(row.name)}</b><small>${row.code} · ${fmtPct(row.change_pct)} · 占比 ${fmtPct(row.main_net_ratio)}</small></span><span class="rank-spark" title="${esc(sparkMoment(points))}">${sparkSvg(points, direction)}<i>${esc(sparkMoment(points))}</i></span><strong class="${cls(row.main_net_inflow)}">${fmtMoney(row.main_net_inflow)}</strong></div>`;
    };
    const incomingAll = [...rows].filter(row => row.main_net_inflow > 0).sort((a, b) => b.main_net_inflow - a.main_net_inflow);
    const outgoingAll = [...rows].filter(row => row.main_net_inflow < 0).sort((a, b) => a.main_net_inflow - b.main_net_inflow);
    const incoming = STATE.heatmapLimit ? incomingAll.slice(0, STATE.heatmapLimit) : incomingAll;
    const outgoing = STATE.heatmapLimit ? outgoingAll.slice(0, STATE.heatmapLimit) : outgoingAll;
    $("inflowList").innerHTML = incoming.map(rowHtml("inflow")).join("") || `<div class="empty">暂无数据</div>`;
    $("outflowList").innerHTML = outgoing.map(rowHtml("outflow")).join("") || `<div class="empty">暂无数据</div>`;
    document.querySelectorAll(".rank-row").forEach(node => node.addEventListener("click", () => selectSector(node.dataset.code)));
  }
  function renderSectorTreemap() {
    const rows = topFlowSectors(visibleSectors(), STATE.heatmapLimit);
    const sizeMetric = $("sizeMetric").value;
    const colorMetric = $("colorMetric").value;
    $("heatmapHint").textContent = `流入${limitLabel(STATE.heatmapLimit)} + 流出${limitLabel(STATE.heatmapLimit)} · ${DETAIL_LABELS[STATE.heatmapDetail]} · 面积=${sizeMetric === "amount" ? "成交额" : "净流绝对值"}`;
    if (!rows.length) {
      sectorChart.clear();
      sectorChart.setOption({
        title: { text: "没有匹配的板块", subtext: "清除筛选词或切换板块类型", left: "center", top: "42%", textStyle: { color: "#9db5ae", fontSize: 15 }, subtextStyle: { color: "#617c75", fontSize: 11 } },
      });
      return;
    }
    const colorValues = rows.map(row => Math.abs(Number(row[colorMetric] || 0))).sort((a, b) => a - b);
    const maxAbs = colorValues[Math.floor(colorValues.length * .9)] || 1;
    const data = rows.map(row => ({
      name: row.name,
      code: row.code,
      value: [Math.max(1, sizeMetric === "abs_flow" ? Math.abs(row.main_net_inflow) : row.amount), row[colorMetric]],
      itemStyle: { color: colorBy(row[colorMetric], maxAbs), borderColor: "#07100f", borderWidth: 2 },
      raw: row,
    }));
    sectorChart.setOption({
      animation: false,
      tooltip: { backgroundColor: "#07110f", borderColor: "#295249", textStyle: { color: "#e8f3ef" }, formatter: p => { const r = p?.data?.raw; if (!r) return esc(p?.name || ""); return `<b>${r.name}</b> ${r.code}<br>涨跌 ${fmtPct(r.change_pct)}<br>成交额 ${fmtMoney(r.amount)}<br>主力净流 ${fmtMoney(r.main_net_inflow)} (${fmtPct(r.main_net_ratio)})<br>3秒增量 ${fmtMoney(r.delta_flow)}<br>上涨/下跌 ${r.rise_count}/${r.fall_count}<br>强弱分 ${r.strength_score.toFixed(2)}`; } },
      series: [{ type: "treemap", roam: false, nodeClick: false, breadcrumb: { show: false }, sort: "desc", data, label: { show: true, color: "#f4fbf8", formatter: p => { const r = p?.data?.raw; if (!r) return ""; if (STATE.heatmapDetail === 0) return `{name|${r.name}}\n{flow|${fmtMoney(r.main_net_inflow)}}`; if (STATE.heatmapDetail === 1) return `{name|${r.name}}\n{val|${fmtPct(r.change_pct)}}\n{flow|${fmtMoney(r.main_net_inflow)}}`; return `{name|${r.name}}\n{code|${r.code}}\n{val|${fmtMetric(r, colorMetric)}}\n{flow|${fmtMoney(r.main_net_inflow)}}\n{ratio|占比 ${fmtPct(r.main_net_ratio)}}`; }, rich: { name: { fontSize: 13, fontWeight: 700, lineHeight: 19 }, code: { fontSize: 9, color: "#b9ccc7", lineHeight: 15 }, val: { fontSize: 11, lineHeight: 16 }, flow: { fontSize: 9, color: "#d2e1dd" }, ratio: { fontSize: 8, color: "#8eaaa3" } } }, upperLabel: { show: false }, levels: [{ itemStyle: { gapWidth: 2, borderWidth: 1 } }] }],
    }, { notMerge: false, replaceMerge: ["series"], lazyUpdate: true, silent: true });
  }
  function renderStocks(payload) {
    STATE.selectedSectorDetail = payload;
    const allStocks = [...(payload.stocks || [])].sort((a, b) => b.amount - a.amount);
    const stocks = STATE.stockLimit ? allStocks.slice(0, STATE.stockLimit) : allStocks;
    const stockTime = stocks.map(row => row.data_time || "").sort().at(-1) || "--";
    $("stockSource").textContent = `${stocks.length}/${allStocks.length}只 · ${DETAIL_LABELS[STATE.stockDetail]} · ${payload.source?.provider || "来源未知"}${payload.source?.possibly_delayed ? "·可能延迟" : ""} · ${stockTime.replace("T", " ")}`;
    const maxChange = Math.max(1, ...stocks.map(row => Math.abs(row.change_pct)));
    stockChart.setOption({
      animation: false,
      tooltip: { backgroundColor: "#07110f", borderColor: "#295249", formatter: p => { const r = p?.data?.raw; if (!r) return esc(p?.name || ""); return `<b>${r.name}</b> ${r.code}.${r.market}<br>涨跌 ${fmtPct(r.change_pct)}<br>成交额 ${fmtMoney(r.amount)}<br>量比 ${r.volume_ratio.toFixed(2)} · 换手 ${fmtPct(r.turnover_pct)}<br>主力净流 ${fmtMoney(r.main_net_inflow)}`; } },
      series: [{ type: "treemap", roam: false, nodeClick: false, breadcrumb: { show: false }, data: stocks.map(row => ({ name: row.name, value: Math.max(1, row.amount), raw: row, itemStyle: { color: colorBy(row.change_pct, maxChange), borderColor: "#07100f", borderWidth: 2 } })), label: { color: "#f1faf7", formatter: p => { const r = p?.data?.raw; if (!r) return ""; if (STATE.stockDetail === 0) return `${r.name}\n${fmtMoney(r.amount)}`; if (STATE.stockDetail === 1) return `${r.name}\n${fmtPct(r.change_pct)}\n${fmtMoney(r.amount)}`; return `${r.name} ${r.code}\n${fmtPct(r.change_pct)} · 量比${Number(r.volume_ratio || 0).toFixed(2)}\n${fmtMoney(r.amount)} · 净流${fmtMoney(r.main_net_inflow)}`; } } }],
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
        return `<button type="button" data-race-code="${row.code}" class="${row.code === STATE.selectedCode ? "active" : ""}" style="--race-color:${color}" title="选择 ${esc(row.name)}"><b>${esc(row.name)}</b><i>${fmtMoney(latest?.flow || 0)}</i></button>`;
      }).join("") || `<div class="race-rail-empty">暂无${group.title}曲线</div>`;
      return `<section class="race-rail-group" data-direction="${group.direction}"><div class="race-rail-group-head"><b>${group.title}</b><span>${group.scale}</span></div>${buttons}</section>`;
    }).join("");
    rail.querySelectorAll("[data-race-code]").forEach(button => button.addEventListener("click", () => selectSector(button.dataset.raceCode)));
    const signature = `${payload.trade_date}|${payload.data_mode}|${STATE.raceScaleMode}|${STATE.selectedCode}|${series.map(item => `${item.id}:${item.data.length}:${item.data.at(-1)?.value?.join(":")}`).join("|")}`;
    if (signature === STATE.lastRaceSignature) return;
    STATE.lastRaceSignature = signature;
    const axisBase = {
      type: "category",
      data: allTimes,
      boundaryGap: false,
      axisLine: { lineStyle: { color: "#24423d" } },
      splitLine: { show: false },
    };
    const grids = independentScale
      ? [
          { id: "race-inflow-grid", left: 78, right: 20, top: "4%", height: "60%", containLabel: false },
          { id: "race-outflow-grid", left: 78, right: 20, top: "69%", height: "27%", containLabel: false },
        ]
      : [{ id: "race-shared-grid", left: 72, right: 24, top: 26, bottom: 48 }];
    const xAxes = independentScale
      ? [
          { ...axisBase, gridIndex: 0, axisLabel: { show: false }, axisTick: { show: false } },
          { ...axisBase, gridIndex: 1, axisLabel: { color: "#708b84", formatter: value => value, hideOverlap: true } },
        ]
      : [{ ...axisBase, gridIndex: 0, axisLabel: { color: "#708b84", formatter: value => value, hideOverlap: true } }];
    const yAxes = independentScale
      ? [
          { type: "value", gridIndex: 0, scale: true, name: "净流入 · 独立轴", nameTextStyle: { color: "#b85854" }, axisLabel: { color: "#b85854", formatter: v => fmtMoney(v) }, splitLine: { lineStyle: { color: "rgba(176,82,78,.18)" } } },
          { type: "value", gridIndex: 1, scale: true, name: "净流出 · 独立轴", nameTextStyle: { color: "#398b76" }, axisLabel: { color: "#398b76", formatter: v => fmtMoney(v) }, splitLine: { lineStyle: { color: "rgba(45,135,110,.18)" } } },
        ]
      : [{ type: "value", gridIndex: 0, scale: true, name: payload.data_mode === "historical_direction_proxy" ? "累计成交方向代理" : "累计主力净流", nameTextStyle: { color: "#78938c" }, axisLabel: { color: "#708b84", formatter: v => fmtMoney(v) }, splitLine: { lineStyle: { color: "rgba(45,75,69,.30)" } } }];
    timelineChart.setOption({
      animation: false,
      color: [...reds, ...greens],
      axisPointer: independentScale ? { link: [{ xAxisIndex: [0, 1] }] } : {},
      tooltip: {
        trigger: "axis",
        order: "valueDesc",
        confine: true,
        backgroundColor: "rgba(5,15,13,.96)",
        borderColor: "#295249",
        textStyle: { fontSize: 11 },
        formatter: params => {
          const rows = Array.isArray(params) ? params : [params];
          const time = rows[0]?.axisValueLabel || rows[0]?.axisValue || "--";
          return [`<b>${esc(time)}</b>`].concat(rows.map(item => {
            const raw = Array.isArray(item.value) ? Number(item.value[1] || 0) : Number(item.value || 0);
            const exact = `${raw > 0 ? "+" : ""}${raw.toLocaleString("zh-CN", { maximumFractionDigits: 0 })} 元`;
            return `${item.marker || ""}${esc(item.seriesName || "")}：<b>${exact}</b>（${fmtMoney(raw)}）`;
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
      ? "显示：独立双尺度，净流入使用上区约60%高度、净流出使用下区约27%高度并分别缩放；该布局只用于提高可读性，两区的线高、斜率和纵轴间距不可跨方向比较；悬浮金额始终为真实有符号人民币元"
      : "显示：共同尺度，流入与流出共用同一纵轴，可直接比较绝对金额；当净流出远大于净流入时，流入曲线可能被视觉压缩；悬浮金额始终为真实有符号人民币元";
    sourceNode.querySelector("span").textContent = `${scaleDisclosure}；来源：${source.provider || "--"}；接口：${source.endpoint || "--"}；字段：${source.fields || "--"}；算法：${source.method || "--"}；边界：${source.limitation || "--"}${excludedNames ? `；已排除聚合板块：${excludedNames}` : ""}`;
    $("raceTitle").textContent = `多板块资金赛马 · 净流入${limitLabel(STATE.raceLimit)} vs 净流出${limitLabel(STATE.raceLimit)} · ${scaleTitle}`;
    $("raceLatest").classList.toggle("active", !STATE.raceTradeDate);
  }
  function renderStockTimeline(payload) {
    STATE.currentStockPayload = payload;
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
    const flowDelta = categories.map(time => {
      const point = flowByTime.get(time);
      if (!point) return null;
      const current = Number(point.flow ?? previousFlow ?? 0);
      const delta = previousFlow == null ? 0 : current - previousFlow;
      previousFlow = current;
      return delta;
    });
    $("stockTimelineSource").textContent = `${payload.trade_date || "--"} · 价格/量 ${priceRows.length}点 · 资金 ${flowRows.length}点 · ${includeAuction ? "含真实09:15–09:29竞价 · " : ""}完整15:00交易轴，未发生分钟留白`;
    stockTimelineChart.setOption({
      animation: false,
      tooltip: { trigger: "axis", confine: true, backgroundColor: "#07110f", borderColor: "#295249" },
      legend: { top: 5, data: ["最新价", "当日均价", "分钟成交量", "累计主力净流", "资金分钟变化"], textStyle: { color: "#8ca59e", fontSize: 10 } },
      grid: [
        { left: 66, right: 64, top: 42, height: "48%" },
        { left: 66, right: 64, top: "61%", height: "12%" },
        { left: 66, right: 64, top: "78%", bottom: 34 },
      ],
      xAxis: [
        { type: "category", data: categories, boundaryGap: false, axisLabel: { show: false }, axisLine: { lineStyle: { color: "#24423d" } } },
        { type: "category", gridIndex: 1, data: categories, boundaryGap: true, axisLabel: { show: false }, axisLine: { show: false } },
        { type: "category", gridIndex: 2, data: categories, boundaryGap: true, axisLabel: { color: "#708b84", hideOverlap: true }, axisLine: { lineStyle: { color: "#24423d" } } },
      ],
      yAxis: [
        { type: "value", scale: true, name: "价格", nameTextStyle: { color: "#6f8c84" }, axisLabel: { color: "#708b84" }, splitLine: { lineStyle: { color: "rgba(45,75,69,.35)" } } },
        { type: "value", gridIndex: 1, name: "量", nameTextStyle: { color: "#6f8c84" }, axisLabel: { color: "#708b84", formatter: v => fmtMoney(v) }, splitLine: { show: false } },
        { type: "value", gridIndex: 2, name: payload.data_mode === "historical_direction_proxy" ? "资金代理" : "主力资金", nameTextStyle: { color: "#6f8c84" }, axisLabel: { color: "#708b84", formatter: v => fmtMoney(v) }, splitLine: { lineStyle: { color: "rgba(45,75,69,.28)" } } },
      ],
      series: [
        { name: "最新价", type: "line", showSymbol: false, data: categories.map(time => priceByTime.get(time)?.close ?? null), lineStyle: { color: "#e95f55", width: 2 }, connectNulls: true, markLine: preClose ? { silent: true, symbol: "none", lineStyle: { color: "#667c76", type: "dashed" }, label: { formatter: `昨收 ${preClose.toFixed(2)}`, color: "#8ca59e" }, data: [{ yAxis: preClose }] } : undefined },
        { name: "当日均价", type: "line", showSymbol: false, data: categories.map(time => Number(priceByTime.get(time)?.average || 0) || null), lineStyle: { color: "#efb85b", width: 1.2 }, connectNulls: true },
        { name: "分钟成交量", type: "bar", xAxisIndex: 1, yAxisIndex: 1, barMaxWidth: 5, data: categories.map(time => { const row = priceByTime.get(time); if (!row) return null; const up = Number(row.close || 0) >= Number(row.open || row.close || 0); return { value: Number(row.volume || 0), itemStyle: { color: up ? "rgba(233,95,85,.58)" : "rgba(39,180,143,.58)" } }; }) },
        { name: "累计主力净流", type: "line", xAxisIndex: 2, yAxisIndex: 2, showSymbol: false, data: categories.map(time => flowByTime.get(time)?.flow ?? null), lineStyle: { color: "#8aa9ff", width: 1.6 }, connectNulls: true },
        { name: "资金分钟变化", type: "bar", xAxisIndex: 2, yAxisIndex: 2, barMaxWidth: 4, data: flowDelta.map(value => ({ value, itemStyle: { color: value >= 0 ? "rgba(233,95,85,.42)" : "rgba(39,180,143,.42)" } })) },
      ],
    }, { notMerge: true, lazyUpdate: true, silent: true });
    const disclosure = payload.source_disclosure || {};
    const priceSource = payload.price_source || {};
    const sourceNode = $("stockDetailSource");
    sourceNode.querySelector("b").textContent = `${payload.trade_date || "--"} · ${disclosure.title || "个股分时"}`;
    sourceNode.querySelector("span").textContent = `价格/成交量：${priceSource.provider || "本地留档"} ${priceSource.endpoint || ""}；资金：${disclosure.provider || "--"} ${disclosure.endpoint || ""}；算法/边界：${disclosure.method || "--"}，${disclosure.limitation || "--"}。午休不补点，11:30与13:00直接相邻；收盘固定15:00，未来分钟留空。${auction.reason ? ` 集合竞价：${auction.reason}。` : ""}`;
    renderOrderBook(payload);
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
    const rowHtml = side => row => `<div class="book-row ${side}" style="--depth:${Math.min(100, Number(row.volume_lots || 0) / maxVolume * 100).toFixed(1)}%;--depth-color:${side === "ask" ? "#27b48f" : "#e95f55"}"><span class="side">${side === "ask" ? "卖" : "买"}${row.level}</span><span class="price">${row.price ? Number(row.price).toFixed(2) : "--"}</span><span class="volume">${row.volume_lots ? Number(row.volume_lots).toFixed(0) : "--"}手</span></div>`;
    $("orderBookRows").innerHTML = book.ok ? `${(book.asks || []).map(rowHtml("ask")).join("")}<div class="book-mid"><span>最新</span><b class="${cls(last - preClose)}">${last ? last.toFixed(2) : "--"} ${preClose ? fmtPct((last / preClose - 1) * 100) : ""}</b></div>${(book.bids || []).map(rowHtml("bid")).join("")}` : `<div class="empty">${esc(book.error || "盘口暂无可用快照")}</div>`;
    const source = book.source || {};
    $("orderBookSource").textContent = book.ok ? `来源：${source.provider || "--"}；接口：${source.endpoint || "--"}；主机：${source.host || "--"}。${source.limitation || "盘口仅为当前快照。"}` : `${book.error || "盘口不可用"}；历史盘口不能由分钟行情事后回补。`;
  }
  function renderQueue(id, rows) {
    $(id).innerHTML = (rows || []).map(row => {
      const move = row.rank_change == null ? "新" : row.rank_change > 0 ? `↑${row.rank_change}` : row.rank_change < 0 ? `↓${Math.abs(row.rank_change)}` : "—";
      return `<div class="queue-row" data-code="${esc(row.code)}" data-market="${esc(row.market)}" data-name="${esc(row.name)}"><span><b>${esc(row.name)}</b><small> ${esc(row.code)} · 量比${Number(row.volume_ratio || 0).toFixed(2)} · ${move}</small></span><span class="${cls(row.change_pct)}">${fmtPct(row.change_pct)}</span><span>${fmtMoney(row.amount)}</span></div>`;
    }).join("") || `<div class="empty">暂无满足阈值的标的</div>`;
    $(id).querySelectorAll(".queue-row").forEach(node => node.addEventListener("click", () => selectStock({ code: node.dataset.code, market: node.dataset.market, name: node.dataset.name })));
  }
  function renderLiquidity(payload) {
    const allStocks = payload.stocks || [];
    const stocks = allStocks.slice(0, STATE.liquidityLimit);
    const liquidityTime = stocks.map(row => row.data_time || "").sort().at(-1) || "--";
    $("liquiditySource").textContent = `前${stocks.length}/${allStocks.length}只 · ${payload.source?.provider || "来源未知"}${payload.source?.possibly_delayed ? "·可能延迟" : ""} · ${liquidityTime.replace("T", " ")}`;
    const policy = payload.exclusion_policy || {};
    const excluded = (policy.excluded || []).slice(0, 6).map(row => `${row.name} ${fmtPct(row.change_pct)}`).join("、");
    $("liquidityExclusion").textContent = `${policy.rule || "新股与上市初期极端涨幅样本不进入核心流动性面板"}；本帧已剔除 ${Number(policy.excluded_count || 0)} 只${excluded ? `（${excluded}）` : ""}。`;
    const amounts = stocks.map(row => row.amount).sort((a, b) => a - b);
    const p90 = amounts[Math.floor(amounts.length * .9)] || 1;
    const groupField = STATE.liquidityColorMode === "industry" ? "industry" : "primary_concept";
    const groupCounts = new Map();
    if (STATE.liquidityColorMode !== "performance") stocks.forEach(row => groupCounts.set(row[groupField] || "未分类", (groupCounts.get(row[groupField] || "未分类") || 0) + 1));
    $("liquidityLegend").innerHTML = STATE.liquidityColorMode === "performance" ? "" : [...groupCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 18).map(([name, count]) => `<span class="legend-chip"><i style="background:${stableColor(name)}"></i>${esc(name)} ${count}</span>`).join("");
    const pointColor = row => STATE.liquidityColorMode === "performance" ? (row.change_pct >= 0 ? "rgba(225,82,74,.75)" : "rgba(35,182,141,.75)") : stableColor(row[groupField] || "未分类");
    scatterChart.setOption({
      animation: false,
      tooltip: { formatter: p => { const r = p?.data?.raw; if (!r) return esc(p?.name || ""); return `<b>${r.name}</b> ${r.code}.${r.market}<br>行业 ${esc(r.industry || "未分类")} · 主概念 ${esc(r.primary_concept || "未分类")}<br>涨跌 ${fmtPct(r.change_pct)} · 量比 ${r.volume_ratio.toFixed(2)}<br>成交额 ${fmtMoney(r.amount)} · 主力净流 ${fmtMoney(r.main_net_inflow)}<br>概念 ${esc(r.concepts || "--")}`; }, backgroundColor: "#07110f", borderColor: "#295249" },
      grid: { left: 55, right: 24, top: 24, bottom: 44 },
      xAxis: { type: "value", name: "涨跌幅 %", nameTextStyle: { color: "#6f8c84" }, axisLabel: { color: "#6f8c84", formatter: "{value}%" }, splitLine: { lineStyle: { color: "rgba(45,75,69,.3)" } } },
      yAxis: { type: "value", name: "量比", nameTextStyle: { color: "#6f8c84" }, axisLabel: { color: "#6f8c84" }, splitLine: { lineStyle: { color: "rgba(45,75,69,.3)" } } },
      series: [{ type: "scatter", data: stocks.map(row => ({ value: [row.change_pct, Math.min(12, row.volume_ratio), row.amount], raw: row, symbolSize: Math.max(7, Math.min(34, 7 + 27 * Math.sqrt(row.amount / p90))), itemStyle: { color: pointColor(row), borderColor: pointColor(row), borderWidth: 0 } })), markLine: { silent: true, lineStyle: { color: "#516b65", type: "dashed" }, data: [{ xAxis: 0 }, { yAxis: 1 }] } }],
    }, { notMerge: true, lazyUpdate: true, silent: true });
    renderQueue("surgingQueue", payload.queues?.surging);
    renderQueue("activeQueue", payload.queues?.active);
    renderQueue("fallingQueue", payload.queues?.falling);
  }
  async function selectStock(row, force = false) {
    if (!row?.code || !row?.market) return;
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
    } catch (error) {
      if (requestId === STATE.stockRequestSeq && row.code === STATE.selectedStockCode) banner(`个股分时读取失败：${error.message}`, "error");
    }
  }
  async function selectSector(code, force = false) {
    const sector = STATE.sectors.find(row => row.code === code) || STATE.raceSeriesByCode.get(code);
    if (!sector) return;
    STATE.selectedCode = code;
    STATE.selectedName = sector.name;
    $("selectedSector").textContent = sector.name;
    $("selectedSectorMeta").textContent = `${code} · ${fmtPct(sector.change_pct ?? sector.snapshot_change_pct)} · ${fmtMoney(sector.main_net_inflow ?? sector.snapshot_flow)}`;
    STATE.lastRaceSignature = "";
    if (STATE.racePayload) renderRace(STATE.racePayload);
    renderRanks(visibleSectors());
    const requestId = ++STATE.sectorRequestSeq;
    try {
      const suffix = force ? "&refresh=1" : "";
      const detail = await json(`/api/market_heatmap/sector?code=${encodeURIComponent(code)}&limit=500${suffix}`);
      if (requestId !== STATE.sectorRequestSeq || code !== STATE.selectedCode) return;
      renderStocks(detail);
      STATE.lastDetailFetchAt = Date.now();
    } catch (error) {
      if (requestId === STATE.sectorRequestSeq && code === STATE.selectedCode) banner(`板块下钻失败：${error.message}`, "error");
    }
  }
  function applyLivePayload(payload) {
    renderMeta(payload.snapshot);
    if (STATE.interacting) {
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
  async function refreshRace(force = false) {
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
    if (!STATE.paused) STATE.timer = setTimeout(() => refresh(false), STATE.interval);
  }
  function setRaceTradeDate(value) {
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
      if (THEMES.includes(saved.theme)) STATE.theme = saved.theme;
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
    document.documentElement.dataset.theme = STATE.theme;
    document.querySelectorAll("[data-theme-choice]").forEach(button => button.classList.toggle("active", button.dataset.themeChoice === STATE.theme));
    document.querySelectorAll("[data-liquidity-color]").forEach(button => button.classList.toggle("active", button.dataset.liquidityColor === STATE.liquidityColorMode));
  }
  const chartsForModule = module => [sectorChart, stockChart, timelineChart, scatterChart, stockTimelineChart].filter(chart => module.contains(chart.getDom()));
  function resizeModuleCharts(module) {
    requestAnimationFrame(() => chartsForModule(module).forEach(chart => chart.resize()));
  }
  function saveLayout() {
    const modules = {};
    document.querySelectorAll("[data-module-id]").forEach(module => {
      if (module.style.width || module.style.height) modules[module.dataset.moduleId] = { width: module.style.width, height: module.style.height };
    });
    try { localStorage.setItem(LAYOUT_KEY, JSON.stringify({ version: 1, modules })); } catch (_error) { /* best effort */ }
  }
  function initResizableModules() {
    let saved = {};
    try {
      const payload = JSON.parse(localStorage.getItem(LAYOUT_KEY) || "{}");
      if (payload.version === 1 && payload.modules && typeof payload.modules === "object") saved = payload.modules;
    } catch (_error) { saved = {}; }
    document.querySelectorAll(".user-resizable[data-module-id]").forEach(module => {
      const dimensions = saved[module.dataset.moduleId] || {};
      const maxWidth = Math.max(280, window.innerWidth - 52);
      const rawWidth = parseFloat(dimensions.width);
      const rawHeight = parseFloat(dimensions.height);
      if (Number.isFinite(rawWidth)) module.style.width = `${Math.min(maxWidth, Math.max(280, rawWidth))}px`;
      if (Number.isFinite(rawHeight)) module.style.height = `${Math.min(1200, Math.max(120, rawHeight))}px`;
      if (Number.isFinite(rawWidth) || Number.isFinite(rawHeight)) module.classList.add("has-user-size");
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
            if (growX) module.style.width = `${Math.min(window.innerWidth - 52, Math.max(280, start.width + growX))}px`;
            if (growY) module.style.height = `${Math.min(1200, Math.max(120, start.height + growY))}px`;
            resizeModuleCharts(module);
          };
          const finish = () => {
            window.removeEventListener("mousemove", move);
            window.removeEventListener("mouseup", finish);
            module.classList.remove("is-resizing");
            setInteracting(false);
            saveLayout();
            resizeModuleCharts(module);
          };
          window.addEventListener("mousemove", move);
          window.addEventListener("mouseup", finish);
        });
      });
    });
    if (typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(entries => entries.forEach(entry => resizeModuleCharts(entry.target)));
      document.querySelectorAll(".user-resizable[data-module-id]").forEach(module => observer.observe(module));
    }
  }
  function resetLayout() {
    try { localStorage.removeItem(LAYOUT_KEY); } catch (_error) { /* best effort */ }
    document.querySelectorAll(".user-resizable[data-module-id]").forEach(module => { module.style.width = ""; module.style.height = ""; module.classList.remove("has-user-size"); });
    requestAnimationFrame(() => [sectorChart, stockChart, timelineChart, scatterChart, stockTimelineChart].forEach(chart => chart.resize()));
    banner("已恢复默认模块尺寸；刷新后仍保持默认布局。", "");
  }
  function applyTheme(theme) {
    STATE.theme = THEMES.includes(theme) ? theme : "cloud";
    document.documentElement.dataset.theme = STATE.theme;
    document.querySelectorAll("[data-theme-choice]").forEach(button => button.classList.toggle("active", button.dataset.themeChoice === STATE.theme));
    savePreferences();
    requestAnimationFrame(() => {
      [sectorChart, stockChart, timelineChart, scatterChart, stockTimelineChart].forEach(chart => chart.resize());
      if (STATE.sectors.length) renderSectorSurfaces();
      if (STATE.racePayload) renderRace(STATE.racePayload);
      if (STATE.selectedSectorDetail) renderStocks(STATE.selectedSectorDetail);
      if (STATE.liquidity) renderLiquidity(STATE.liquidity);
      if (STATE.currentStockPayload) renderStockTimeline(STATE.currentStockPayload);
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
  function bindStockTerminalDialog() {
    const openButton = $("stockTerminalOpen");
    const dialog = $("stockTerminalDialog");
    const closeButton = $("stockTerminalClose");
    const terminal = $("stockTerminal");
    const home = $("stockTerminalHome");
    const modalMount = $("stockTerminalModalMount");
    if (!openButton || !dialog || !terminal || !home || !modalMount) return;
    const moveToModal = () => {
      modalMount.querySelector(".modal-mount-hint")?.remove();
      modalMount.appendChild(terminal);
      if (typeof dialog.showModal === "function") dialog.showModal(); else dialog.setAttribute("open", "");
      requestAnimationFrame(() => stockTimelineChart.resize());
    };
    const restore = () => {
      home.appendChild(terminal);
      if (dialog.hasAttribute("open")) {
        if (typeof dialog.close === "function") dialog.close(); else dialog.removeAttribute("open");
      }
      requestAnimationFrame(() => stockTimelineChart.resize());
    };
    openButton.addEventListener("click", moveToModal);
    closeButton?.addEventListener("click", restore);
    dialog.addEventListener("cancel", event => { event.preventDefault(); restore(); });
    dialog.addEventListener("click", event => { if (event.target === dialog) restore(); });
    dialog.addEventListener("close", () => { if (terminal.parentElement !== home) home.appendChild(terminal); requestAnimationFrame(() => stockTimelineChart.resize()); });
  }
  loadPreferences();
  initResizableModules();
  document.querySelectorAll("[data-theme-choice]").forEach(button => button.addEventListener("click", () => applyTheme(button.dataset.themeChoice)));
  bindDialog("settingsButton", "settingsDialog", "settingsClose");
  bindStockTerminalDialog();
  document.querySelectorAll("[data-board]").forEach(button => button.addEventListener("click", () => {
    document.querySelectorAll("[data-board]").forEach(node => node.classList.toggle("active", node === button));
    STATE.boardType = button.dataset.board; STATE.selectedCode = ""; STATE.selectedName = ""; STATE.sectorRequestSeq += 1; STATE.sparklines = new Map(); STATE.lastSparkKey = ""; STATE.lastRaceSignature = "";
    STATE.liquidityColorMode = STATE.boardType === "concept" ? "concept" : "industry";
    document.querySelectorAll("[data-liquidity-color]").forEach(node => node.classList.toggle("active", node.dataset.liquidityColor === STATE.liquidityColorMode));
    if (STATE.liquidity) renderLiquidity(STATE.liquidity);
    savePreferences();
    $("selectedSector").textContent = "加载中…"; $("selectedSectorMeta").textContent = "正在切换板块类型";
    refresh(true);
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
  $("raceLatest").addEventListener("click", () => setRaceTradeDate(""));
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
  document.querySelectorAll(".chart").forEach(node => {
    node.addEventListener("pointerenter", () => setInteracting(true), { passive: true });
    node.addEventListener("pointerleave", () => setInteracting(false), { passive: true });
  });
  window.addEventListener("scroll", () => {
    STATE.interacting = true;
    clearTimeout(STATE.interactionTimer);
    STATE.interactionTimer = setTimeout(() => { STATE.interacting = STATE.pointerInside; if (!STATE.interacting) flushDeferredPayload(); }, 260);
  }, { passive: true });
  window.addEventListener("resize", () => [sectorChart, stockChart, timelineChart, scatterChart, stockTimelineChart].forEach(chart => chart.resize()));
  refresh(true);
})();
