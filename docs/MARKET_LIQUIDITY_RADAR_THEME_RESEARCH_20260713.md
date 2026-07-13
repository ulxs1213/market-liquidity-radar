# 市场流动性雷达主题研究（2026-07-13）

## 1. 目标与边界

本研究服务于高密度 A 股盘中监控，不做品牌换肤，也不复制第三方代码、图标或品牌资产。重点是：长时间盯盘不刺眼、表格与图表层级清楚、红涨绿跌语义稳定、深浅主题都能读、控件焦点可见、主题选择可持久化。

许可证列以调研日期仓库公开声明为准；本项目只提炼颜色层级和交互规律，任何后续代码复用仍须逐文件复核许可证及 NOTICE 要求。

## 2. 开源样本清单（28 个）

| # | 项目与官方仓库 | 许可证 | 深/浅 | 可借鉴点 | 采用 / 不采用 |
|---:|---|---|---|---|---|
| 1 | Grafana — `github.com/grafana/grafana` | AGPL-3.0 | 深浅 | 深色监控面板的低反光背景、清楚边框与状态色 | 采用层级；不采用橙色品牌主导和高饱和渐变 |
| 2 | Apache Superset — `github.com/apache/superset` | Apache-2.0 | 浅为主 | 大量图表并置时仍以中性底色维持可读性 | 采用白底分析面板；不采用过多装饰色 |
| 3 | Metabase — `github.com/metabase/metabase` | AGPL-3.0 | 浅为主 | 亲和但克制的浅灰背景、白色卡片、清楚表单状态 | 采用雾灰层次；不采用品牌青色大面积铺陈 |
| 4 | Redash — `github.com/getredash/redash` | BSD-2-Clause | 浅为主 | 查询和图表工具的紧凑控制密度 | 采用紧凑控件；不采用年代较早的弱层级阴影 |
| 5 | Netdata — `github.com/netdata/netdata` | GPL-3.0 | 深浅 | 秒级指标密集刷新下的暗底、细网格和状态色 | 采用墨黑监控基调；不采用彩虹式图表配色 |
| 6 | OpenObserve — `github.com/openobserve/openobserve` | AGPL-3.0 | 深浅 | 日志/指标多面板的紧凑暗色布局 | 采用低亮表面；不采用过强紫蓝品牌色 |
| 7 | ThingsBoard — `github.com/thingsboard/thingsboard` | Apache-2.0 | 深浅 | 设备实时面板的卡片层次、告警语义 | 采用状态层级；不采用物联网专属控件形态 |
| 8 | Homepage — `github.com/gethomepage/homepage` | GPL-3.0 | 深浅 | 大量小组件在有限空间中的一致间距和中性色 | 采用紧凑小组件；不采用透明毛玻璃效果 |
| 9 | Appsmith — `github.com/appsmithorg/appsmith` | Apache-2.0 | 深浅 | 企业工具的表单、选中、悬停和键盘焦点状态 | 采用可访问焦点；不采用编辑器式多栏结构 |
| 10 | ToolJet — `github.com/ToolJet/ToolJet` | AGPL-3.0 | 深浅 | 数据工具的中性面板和控件状态 | 采用控件对比；不采用品牌紫作为全局主色 |
| 11 | Budibase — `github.com/Budibase/budibase` | GPL-3.0 | 深浅 | 内部工具的密集表格与浅色层级 | 采用表格边界；不采用大圆角和营销式色块 |
| 12 | Plane — `github.com/makeplane/plane` | AGPL-3.0 | 深浅 | 现代生产力界面的克制中性色和夜蓝模式 | 采用夜蓝层次；不采用任务管理专属彩色标签密度 |
| 13 | OpenBB — `github.com/OpenBB-finance/OpenBB` | AGPL-3.0 | 深色倾向 | 金融研究终端的深底、数据优先和紧凑密度 | 采用金融终端克制感；不复制品牌和专属组件 |
| 14 | Ghostfolio — `github.com/ghostfolio/ghostfolio` | AGPL-3.0 | 深浅 | 个人资产页面的留白、收益红绿与数字层级 | 采用金额层级；不采用消费级大卡片比例 |
| 15 | rotki — `github.com/rotki/rotki` | AGPL-3.0 | 深浅 | 资产追踪中表格、状态与货币数字的清晰组织 | 采用金额与状态层级；不采用加密资产图形语言或终端绿基调 |
| 16 | Carbon Design System — `github.com/carbon-design-system/carbon` | Apache-2.0 | 深浅 | 严谨灰阶、明确层级、数据可视化与无障碍基线 | 采用灰阶和边框纪律；不直接复制组件代码 |
| 17 | PatternFly — `github.com/patternfly/patternfly` | MIT | 深浅 | 运维控制台的信息密度、状态层级和键盘可达性 | 采用高密度控制台原则；不采用复杂企业导航 |
| 18 | Fluent UI — `github.com/microsoft/fluentui` | MIT | 深浅 | 白色基调、可见焦点、语义令牌 | 采用明纸白与焦点环；不采用 Fluent 品牌细节 |
| 19 | Ant Design — `github.com/ant-design/ant-design` | MIT | 深浅 | 中文企业应用的紧凑表单与表格可读性 | 采用紧凑尺寸；不采用蓝色全局泛滥 |
| 20 | Primer CSS — `github.com/primer/css` | MIT | 深浅 | GitHub 式中性白/黑、细边框和低阴影 | 采用明纸白与墨黑；不采用 GitHub 品牌标识 |
| 21 | Material UI — `github.com/mui/material-ui` | MIT | 深浅 | 主题令牌、color-scheme 与组件状态一致性 | 采用令牌架构；不采用高海拔阴影和大面积涟漪 |
| 22 | Mantine — `github.com/mantinedev/mantine` | MIT | 深浅 | 主题切换、颜色层级和无障碍状态 | 采用浅灰/暗色映射；不采用多品牌色并列 |
| 23 | Tabler — `github.com/tabler/tabler` | MIT | 深浅 | 开源管理面板的清晰白底、紧凑卡片、图表容器 | 采用白底仪表盘节奏；不采用装饰性插图 |
| 24 | shadcn/ui — `github.com/shadcn-ui/ui` | MIT | 深浅 | 极简中性色、边框优先、浅阴影 | 采用低装饰表面；不采用过大留白和内容稀疏化 |
| 25 | Chakra UI — `github.com/chakra-ui/chakra-ui` | MIT | 深浅 | 语义颜色、焦点可见、颜色模式切换 | 采用语义变量；不采用组件默认大间距 |
| 26 | Tremor — `github.com/tremorlabs/tremor` | Apache-2.0 | 浅为主 | 分析卡片、KPI 数字和图表注释的克制表现 | 采用 KPI 数字层级；不采用营销化彩色卡片 |
| 27 | Apache ECharts — `github.com/apache/echarts` | Apache-2.0 | 深浅 | 金融/时序图的主题机制、轴线与 tooltip 层级 | 采用主题重绘原则；不采用默认多彩分类色 |
| 28 | NocoDB — `github.com/nocodb/nocodb` | AGPL-3.0 | 深浅 | 高密度数据表、筛选器与浅色工作区 | 采用数据优先布局；不采用数据库编辑器专属导航 |

### 2.1 在线复核说明

2026-07-13 通过 GitHub Repository API 重新核对上述 28 个官方仓库：28/28 均可访问，且 `archived=false`。API 能直接识别其中 23 个仓库的 SPDX 许可证；Metabase、Budibase、OpenBB、Fluent UI、NocoDB 当前由该接口返回 `NOASSERTION`，所以上表这 5 项仅作为仓库声明的调研记录，不把 GitHub 自动识别结果误写成已确认。若未来复制第三方代码，必须继续逐文件核对 `LICENSE`、`NOTICE` 和提交版本；本轮实现没有复制这些项目的代码、品牌资产或截图。

## 3. 提炼出的九套预设与自定义主题

九套预设以低饱和背景、稳定面板和弱阴影为主。只有“绚彩”在页面外层和面板表层使用不动画的柔和静态渐变，不使用霓虹描边、发光文字或赛博朋克黑紫效果。红色固定表示上涨/买盘方向，绿色固定表示下跌/卖盘方向；主题强调色只用于选中、焦点和链接，不与红绿语义争夺注意力。

| 主题 | 属性 | 背景 / 面板 / 正文 / 次要文字 | 强调 / 上涨 / 下跌 | 主要来源 |
|---|---|---|---|---|
| 明纸 `cloud` | 白色浅色，默认 | `#f5f7fa` / `#ffffff` / `#1f2328` / `#59636e` | `#0969da` / `#cf222e` / `#16835c` | Primer、Fluent、Carbon、Tabler |
| 雾灰 `mist` | 灰白浅色 | `#edf2f4` / `#f9fbfc` / `#18323a` / `#5c727a` | `#087f8c` / `#c43d45` / `#087a5c` | Metabase、PatternFly、Mantine |
| 暖沙 `sand` | 米黄浅色 | `#f3eee3` / `#fffcf5` / `#3a332b` / `#74695b` | `#33715e` / `#c2413b` / `#28765d` | 现有暖沙偏好 + Carbon 灰阶纪律 |
| 墨黑 `ink` | 纯黑深色 | `#050607` / `#0b0d0f` / `#f1f3f5` / `#a6adb5` | `#4ca6ff` / `#ff6b6b` / `#36c692` | Grafana、Netdata、Primer Dark |
| 石墨 `slate` | 中性深灰 | `#16181b` / `#202328` / `#f1f3f5` / `#aab2bb` | `#7aa2f7` / `#ff7b72` / `#54c89a` | PatternFly、Ant、Appsmith |
| 夜蓝 `midnight` | 深蓝 | `#0b1220` / `#111a2a` / `#e9eef7` / `#9dafc6` | `#6ea8fe` / `#ff746c` / `#45c49a` | Plane、Superset、OpenBB |
| 酒红 `red` | 深红酒红 | `#19090d` / `#271016` / `#fff1f3` / `#cfadb4` | `#f05b73` / `#ff7b72` / `#55c69a` | 金融终端暗底层级 + 克制酒红 |
| 浅红 `rose` | 柔和浅红 | `#fff0f3` / `#fffafb` / `#4c202a` / `#76555d` | `#c83255` / `#c7253e` / `#237a5b` | 暖纸张表面 + 玫瑰红交互色 |
| 绚彩 `prismatic` | 低饱和浅色 | `#f3f1f8→#faeee8` / `#fffdfb` / `#302b3a` / `#696174` | `#6d58bd` / `#c7384f` / `#25775e` | 多色玻璃釉色感，但无霓虹和动画 |
| 自定义 `custom` | 浅/深可选 | 用户拖拽主色后自动派生可读背景、面板、正文与边界 | 强调色自动保护；上涨红和下跌绿固定 | 本地 HSV 渐变色板与语义令牌 |

## 4. 可读性与实现决策

1. 九套预设为五套浅色、四套深色，覆盖白、灰白、米黄、纯黑、石墨、夜蓝、酒红、浅红和柔和绚彩；终端绿预设已删除。
2. 面板主要靠 `background / panel / surface / control / line` 五级语义令牌形成层次；绚彩和自定义只允许静态低饱和渐变，不允许动画或霓虹效果。
3. 浅色正文和次要文字均使用深色，不用低对比浅灰；深色主题次要文字提升亮度，避免长时间盯盘时“灰成一片”。
4. 主题按钮改为纯色双环样本，选中时有 2px 外轮廓，键盘焦点有 3px 强调色焦点环；按钮持续同步 `aria-pressed`。
5. 旧偏好平滑迁移：`ocean → midnight`、`violet → slate`、`terminal → midnight`，避免旧本地存储失效。
6. 主题和自定义值仍写入 `market-liquidity-radar-preferences-v2`，刷新后恢复；只有“保存自定义”写入草稿，取消、关闭或 Esc 恢复进入编辑器前的主题。
7. 自定义色板使用 pointer capture 和 `requestAnimationFrame` 合并拖拽帧；拖动时暂停重模块提交，松开后才统一重绘五张 ECharts，避免与 3 秒行情刷新争抢主线程。
8. 自定义明暗模式自动派生可读正文、次要文字和边界；对白、黑、灰和低饱和高亮极端值生成安全强调色。主题不改变 A 股红涨绿跌语义。

## 5. 未采用方向

- 不采用玻璃拟态、透明毛玻璃和背景照片：降低文字/行情数据对比度，也增加合成开销。
- 不采用大面积高饱和紫、荧光蓝、动画渐变或霓虹描边：它们会与红涨绿跌及资金赛马颜色竞争；绚彩仅保留低饱和静态外层渐变。
- 不采用纯白卡片叠大阴影：高密度面板会显得割裂，并在长时间观看时刺眼。
- 不因主题改变红涨绿跌含义；主题仅改变背景、边框、正文、次要文字和交互强调色。
- 不直接复制任何项目的代码、品牌色表、图标或截图资产。
