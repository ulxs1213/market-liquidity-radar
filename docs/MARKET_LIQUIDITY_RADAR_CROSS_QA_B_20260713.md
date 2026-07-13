# 市场流动性雷达交叉验收 B：主题与 05B 统一游标（2026-07-13）

验收边界：本轮检查 T1 九套预设、自定义主题和 C1/C2 统一 Tooltip/游标；不重复验收紧凑布局、03 赛马和 05B 弹窗交互本身。浏览器实际点击、拖拽、保存与 hover 由主验收 Agent 执行，本文件记录静态合同、数据口径和自动测试证据。

## 结论

| 编号 | 项目 | 结果 | 证据 |
|---|---|---|---|
| T1.1 | 九套预设 + 自定义 | PASS | HTML 与 JS 顺序一致：`cloud, mist, sand, ink, slate, midnight, red, rose, prismatic, custom`；终端绿预设不存在 |
| T1.2 | 5 浅色 + 4 深色 | PASS | cloud/mist/sand/rose/prismatic 为浅色；ink/slate/midnight/red 为深色；custom 可切浅/深 |
| T1.3 | 持久化与旧别名 | PASS | `PREF_KEY` 保存 theme/customTheme；载入时 `ocean→midnight`、`violet→slate`、`terminal→midnight`；按钮同步 active、`aria-pressed/expanded` |
| T1.4 | 正文与次要文字对比度 | PASS | 九预设与 custom fallback 的正文/面板均 ≥7:1，`--muted` 对 panel/surface/control 均 ≥4.5:1 |
| T1.5 | 自定义保存与恢复 | PASS | 拖拽仅 rAF 预览；显式保存才持久化；取消、关闭、Esc 恢复进入前主题；无效 HEX 禁止保存 |
| T1.6 | 换肤性能 | PASS | pointer capture + interaction guard；换肤前对五个现有 ECharts 实例统一 `globalout + hideTip` 清理旧提示，普通图延迟 500ms、05B 延迟 1800ms 安全重绘，不 re-init |
| C1.1 | 统一 Tooltip 字段 | PASS | 同一时间切片包含最新价、当日均价、分钟成交量、累计主力净流、本分钟净流变化 |
| C1.2 | 成交量与资金口径 | PASS | 实时为手并显示约合股数；历史为股；累计值与分钟变化均明确为有符号净额，不伪造成总流入/总流出 |
| C2.1 | 三 Grid 同步 | PASS | `axisPointer.link` 明确连接 xAxis `[0,1,2]`，三条 category xAxis 都启用 snap line |
| C2.2 | 首个资金点 | PASS | `previousFlow == null ? null`，柱图保留 null，Tooltip 显示“无法计算相邻变化”，不冒充 0 |
| C2.3 | 3 秒重绘保留 hover | PASS | hover/滚动时实时帧延迟应用；签名未变化不 setOption；不再程序化 `showTip`；换肤先清空五图旧 Tooltip，再错峰重绘，避免 ECharts stale-item 竞态 |
| C2.4 | 原位/弹窗共同复用 | PASS | `stockTimeline` 只有一个 DOM ID 和一个 ECharts init；移动的是包含它的同一 Workspace，事件与 hover state 不重建 |

## 本轮发现并修复的确定缺陷

初检时两套浅色主题的小号次要文字未达到 WCAG AA 4.5:1：

- mist：`--muted` 对 `--control` 为 4.33:1；调整 `#5c727a → #596f77` 后为 4.52:1。
- sand：`--muted` 对 `--control` 为 4.37:1；调整 `#74695b → #726759` 后为 4.50:1。

只调整了两个次要文字变量，没有改变主题结构、图表颜色或业务功能。

## 对比度复核

| 主题 | 类型 | 正文/面板 | 次要文字最小值（面板、surface、control） |
|---|---:|---:|---:|
| cloud | 浅 | 15.80 | 5.55 |
| mist | 浅 | 13.00 | 4.52 |
| sand | 浅 | 12.14 | 4.50 |
| ink | 深 | 17.50 | 7.86 |
| slate | 深 | 14.17 | 6.29 |
| midnight | 深 | 14.97 | 6.86 |
| red | 深 | ≥7.00 | ≥4.50 |
| rose | 浅 | ≥7.00 | ≥4.50 |
| prismatic | 浅 | ≥7.00 | ≥4.50 |
| custom fallback | 浅 | ≥7.00 | ≥4.50 |

## 自动测试

新增独立交叉测试：`tests/test_market_heatmap_cross_qa_b.py`

```bash
.dashboard_venv/bin/python -m unittest \
  tests.test_market_heatmap_cross_qa_b \
  tests.test_market_heatmap_theme_customizer_ui \
  tests.test_market_heatmap_05b_crosshair_ui -v
```

结果：21/21 PASS；市场流动性雷达完整主项目套件为 67/67 PASS，独立开源版完整套件为 73/73 PASS。

覆盖：九套预设与自定义顺序/分类/别名/ARIA/持久化、WCAG 对比度、浅/深×白黑灰黄青蓝及低饱和黄共14组生产算法极端色数值验证、pointer capture+rAF、保存/取消/Esc、缓存失效与唯一 ECharts 实例；以及统一 Tooltip 字段、首点 null、三轴 link、hover 重绘恢复、唯一 DOM 复用和实时/历史成交量单位合同。

最终 `market_heatmap.js` 已通过 Node VM 语法编译；8772 在线 JS SHA 与本地 SHA 一致。

## 主 Agent 浏览器补充项

- 逐个点击九套预设，核对酒红/浅红/绚彩、刷新保持和按钮 `aria-pressed`。
- 拖拽自定义色板四角与中心，测试无效 HEX、保存后刷新、取消/关闭/Esc，并跨 3 个 3 秒刷新周期观察浮层与滚动位置。
- 在 05B 三个子图之间移动光标，核对竖线和 Tooltip 使用同一分钟。
- 光标停留超过一个 3 秒刷新周期，核对 Tooltip 不消失、不跳回最后时刻；再执行“05B 悬停→快速滚顶→立即打开主题并改色”，控制台应保持空。
- 打开复用 Workspace 的模态层后继续移动光标，再关闭回原位，核对游标与 Tooltip 仍工作。
