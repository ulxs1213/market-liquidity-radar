# 市场流动性雷达交叉验收 B：主题与 05B 统一游标（2026-07-13）

验收边界：本轮只检查 T1 七主题和 C1/C2 统一 Tooltip/游标；不重复验收紧凑布局、03 赛马和 05B 弹窗交互本身。浏览器实际点击与 hover 由主验收 Agent 执行，本文件记录静态合同、数据口径和自动测试证据。

## 结论

| 编号 | 项目 | 结果 | 证据 |
|---|---|---|---|
| T1.1 | 七个主题按钮 | PASS | HTML 与 JS 顺序一致：`cloud, mist, sand, ink, slate, midnight, terminal` |
| T1.2 | 3 浅色 + 4 深色 | PASS | cloud/mist/sand 为 `color-scheme:light`；ink/slate/midnight/terminal 为 `dark` |
| T1.3 | 持久化与旧别名 | PASS | `PREF_KEY` 保存 theme；载入时 `ocean→midnight`、`violet→slate`；按钮同步 active 与 `aria-pressed` |
| T1.4 | 正文对比度 | PASS | 七主题 `--text` 对 `--panel` 均高于 12:1 |
| T1.5 | 次要文字对比度 | PASS（修复后） | `--muted` 对 panel/surface/control 的最小值均 ≥4.5:1 |
| C1.1 | 统一 Tooltip 字段 | PASS | 同一时间切片包含最新价、当日均价、分钟成交量、累计主力净流、本分钟净流变化 |
| C1.2 | 成交量与资金口径 | PASS | 实时为手并显示约合股数；历史为股；累计值与分钟变化均明确为有符号净额，不伪造成总流入/总流出 |
| C2.1 | 三 Grid 同步 | PASS | `axisPointer.link` 明确连接 xAxis `[0,1,2]`，三条 category xAxis 都启用 snap line |
| C2.2 | 首个资金点 | PASS | `previousFlow == null ? null`，柱图保留 null，Tooltip 显示“无法计算相邻变化”，不冒充 0 |
| C2.3 | 3 秒重绘保留 hover | PASS | hover 时实时帧延迟应用；签名未变化不 setOption；变化时记录时间并 `dispatchAction(showTip)` 恢复 |
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
| terminal | 深 | 15.90 | 7.39 |

## 自动测试

新增独立交叉测试：`tests/test_market_heatmap_cross_qa_b.py`

```bash
.dashboard_venv/bin/python -m unittest \
  tests.test_market_heatmap_cross_qa_b \
  tests.test_market_heatmap_05b_crosshair_ui -v
```

结果：11/11 PASS。

覆盖：七主题数量/分类/别名/ARIA/持久化、WCAG 对比度计算、统一 Tooltip 字段、首点 null、三轴 link、hover 重绘恢复、唯一 ECharts/DOM 复用，以及实时/历史成交量单位的服务端返回合同。

最终 `market_heatmap.js` 已通过 Node VM 语法编译；8772 在线 JS SHA 与本地 SHA 一致。

## 主 Agent 浏览器补充项

- 逐个点击七个主题，刷新后核对主题保持和按钮 `aria-pressed`。
- 在 05B 三个子图之间移动光标，核对竖线和 Tooltip 使用同一分钟。
- 光标停留超过一个 3 秒刷新周期，核对 Tooltip 不消失、不跳回最后时刻。
- 打开复用 Workspace 的模态层后继续移动光标，再关闭回原位，核对游标与 Tooltip 仍工作。
