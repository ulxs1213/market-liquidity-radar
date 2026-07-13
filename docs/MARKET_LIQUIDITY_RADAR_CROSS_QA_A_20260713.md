# 市场流动性雷达交叉验收 A（2026-07-13）

## 1. 范围与结论

本轮由非实现 Agent 交叉检查紧凑布局 L1/L2、03 资金赛马 R1/R2、历史回放 P1/P2/P3；不检查主题、05B 或双击弹窗。按主 Agent 要求，本轮以静态、单元、编译、JavaScript VM 语法和本地 SQLite 契约为主，浏览器拖拽/悬浮/截图留给最终集成验收。

结论：L1、L2、R1、R2、P1、P2、P3 在本轮范围内全部 PASS。发现并修复 1 个 P2/P3 确定缺陷：个股有留档但板块无留档的孤立分钟曾进入可播放目录，播放到该分钟会因没有 01/02/03 板块截面而失败；现已从可播放帧排除，并在覆盖说明中明确披露。

## 2. 分项结果

| 编号 | 结果 | 证据 |
|---|---|---|
| L1 10 列紧凑打包 | PASS | CSS 使用 `repeat(10,minmax(0,1fr))`、`grid-auto-flow:row dense`、1px 行轨；JS 按模块真实高度写 `--module-row-span=height+12`。本地保存版本 2 只含 `span` 和可选 `height`，静态审查确认没有 `x/y/top/left/position` 坐标，避免保存空洞。 |
| L2 响应式与越界 | PASS（静态契约） | 模块 `min-width:0;width:100%;max-width:100%;overflow-x:hidden`；1180px 以下强制单列并把个股终端、队列改为单列；8 个缩放手柄为模块绝对定位子元素。实际 `scrollWidth` 和截图由主 Agent 最终浏览器验收。 |
| R1 赛马纵轴与单位 | PASS | `fmtYiInteger` 统一 `Math.round(value/1e8)+亿`；独立尺度轴名为“净流入（亿）/净流出（亿）”，共同尺度为“主力净流（亿）”；tooltip 同样调用整数亿元格式。两个绘图区分别为 5%–60% 和 72%–94%，轴名居中、`nameGap=72`，静态结构不共享/叠置标题。 |
| R2 流入/流出双列表 | PASS | 右栏固定两行 `repeat(2,minmax(0,1fr))`，每组单独 `.race-rail-scroll{overflow-y:auto}`；重绘前按 `inflow/outflow` 保存两个 `scrollTop`，重绘后分别恢复，不互相覆盖。 |
| P1 历史回放 | PASS | 日期、播放/暂停、1×/2×/5×、进度条和回到实时均已接线；播放每步请求一个 manifest 中的真实帧；回放时 3 秒实时定时器停止。单测验证 09:31/09:33 两个真实帧，不生成 09:32。 |
| P2 多模块同帧 | PASS（含修复） | 一个 `/replay_frame` 响应同时驱动 01/02 的 `renderSectorSurfaces`、03 的 `renderRace`、04 的 `renderStocks`、05 的 `renderLiquidity`；响应统一携带 `trade_date/frame_time/session_progress`。修复后 manifest 只列出存在板块截面的分钟，避免 stock-only 帧导致中途失败。 |
| P3 缺口与禁止插值 | PASS（含修复） | SQLite 只接受 09:30–11:30、13:00–15:00；精确按所选分钟查询，不存在就返回“不会插值”；manifest 报告板块缺分钟、个股缺分钟及仅个股孤立分钟。实际数据库行业/概念均无午休帧，概念 11:30 的 stock-only 帧已披露并排除。 |

## 3. 缺陷与修复记录

### QA-A-01：stock-only 孤立分钟进入可播放目录

- 复现：本地 `2026-07-13` 概念库在 `11:30` 有 179 条个股记录、0 条概念板块记录；旧 manifest 使用板块分钟与个股分钟的并集，因此仍把 11:30 列为可播放帧。
- 影响：播放到 11:30 时 `/replay_frame` 正确拒绝沿用上一板块帧，导致自动回放中断，不满足 P2 的同帧联动。
- 修复：可播放帧改为真实存在板块横截面的分钟；个股孤立分钟保留在 `coverage.stock_only_frame_labels`，前端显示“仅个股留档，不列入可播放帧”。
- 回归：fixture 新增 09:34 stock-only 数据，断言可播放帧仍只有 09:31/09:33，且覆盖字段披露 09:34。

## 4. 自动验证证据

1. `.dashboard_venv/bin/python -m unittest tests.test_market_heatmap -q`：30 项全部通过。
2. `.dashboard_venv/bin/python -m compileall -q quant_dashboard scripts/run_market_heatmap_dashboard.py tests/test_market_heatmap.py`：通过，无编译错误。
3. `market_heatmap.js` 使用 Node `vm.Script` 解析：PASS。
4. L1/L2/R1/R2/P1/P2/P3 静态契约脚本：PASS。
5. 真实 SQLite manifest 抽样：
   - industry：2026-07-13，241 个可播放板块帧，午休帧 0，stock-only 0。
   - concept：2026-07-13，240 个可播放板块帧，午休帧 0；11:30 为 stock-only，已从播放目录排除并披露。

## 5. 最终浏览器验收保留项

以下不是本轮 FAIL，而是按主 Agent 安排留给最终集成浏览器测试：连续拖拽 01/02A/02B/03/04 后测量实际间距；1180/1420/桌面宽度的 `scrollWidth <= clientWidth`；TOP5/10/20 两列表分别滚到底；独立/共同尺度实际悬浮；从开盘、午休前后、收盘抽样播放并观察五模块时间标签。
