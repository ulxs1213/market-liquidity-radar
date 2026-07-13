# 市场流动性雷达

本地优先、可局域网访问的 A 股盘中流动性可视化。它把板块资金赛马、头部流入/流出热力图、核心流动性个股、行业/概念聚类以及个股价格/成交量/资金/五档盘口放在同一页面，并把每张图的数据来源与算法边界写在图下和“设置 → 数据源与时间口径”中。

![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB)
![License](https://img.shields.io/badge/License-MIT-0b8f78)

## 已实现功能

- 行业/概念板块头部热力图，只展示净流入和净流出头部，可调 TOP10/TOP20/TOP30/全部以及信息密度。
- 多板块资金“赛马”分时曲线，可调 TOP5/TOP10/TOP20/全部；右侧名称独立于图面，点击线或名称联动核心个股。
- 概念赛马排除“融资融券、沪股通、深股通、MSCI中国、富时罗素、标普道琼斯A股”等市场资格聚合桶。
- 全市场核心流动性散点图，可调 TOP30/50/100/200/500，默认 TOP50；可按行业或主概念单色分组。
- 自动剔除名称带 N/C 或绝对涨跌达到 40% 的上市初期极端样本，防止气泡压缩正常标的。
- 个股价格、均价、分钟成交量、累计主力资金、资金分钟变化与当前五档盘口，可在页面底部查看，也可弹窗放大。
- 完整 A 股交易分钟轴：09:30–11:30 与 13:00–15:00；午休不补点，未来分钟留白，绝不延长到 15:30。
- 可选 09:15–09:29 集合竞价；只有东方财富本次真实返回竞价观察点时才允许开启，不插值、不模拟。
- 六套主题（云白、深夜、海洋、沙岩、石墨、紫罗兰），模块八方向缩放并保存本机布局。
- 3 秒轻量刷新、12 秒重模块刷新；交互和滚动时继续取数但推迟重绘，减少卡顿。
- SQLite WAL 保存本机实际观察到的分钟轨迹，支持历史交易日回看，默认保留 14 个自然日。

## 一键启动

需要 Python 3.9 或更高版本。首次一键启动会创建项目专用 `.venv`，并联网安装 `requests` 与可选 `pytdx`；之后直接使用本地环境。

### Windows

双击 `start_windows.bat`。黑色终端窗口会显示本机地址、局域网地址、数据目录和运行日志。也可在 PowerShell 中运行：

```powershell
.\start_windows.ps1
```

如果 Windows 防火墙询问是否允许 Python 访问网络，只在需要手机或另一台电脑访问时允许“专用网络”，不要对公共网络放行。

### macOS

双击 `start_macos.command`，或在终端运行：

```bash
./start_macos.command
```

首次运行如果被系统阻止，可在“系统设置 → 隐私与安全性”确认打开，或先执行 `chmod +x start_macos.command`。

### Linux / 通用方式

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[tdx]"
python start.py
```

服务默认监听 `0.0.0.0:8772`，本机页面是 <http://127.0.0.1:8772/market-liquidity-radar>，终端同时打印可用的局域网地址。

常用参数：

```bash
python start.py --host 127.0.0.1       # 只允许本机访问
python start.py --port 8872 --no-browser
python start.py --data-dir /path/to/local-data
python start.py --print-urls-only
python start.py --self-check
```

## 局域网访问

1. 让电脑和手机/平板处在同一可信 Wi-Fi 或有线局域网。
2. 启动脚本，在终端找到类似 `http://192.168.1.20:8772/` 的地址。
3. 在另一台设备的浏览器中打开该地址。

项目没有登录认证。不要把 8772 端口映射到公网；在不可信网络上应使用 `--host 127.0.0.1`。访客网络、AP 隔离、VPN 或系统防火墙可能阻止局域网访问。

## 数据来源与算法口径

### 东方财富公开行情页接口（实时主链）

- 板块/个股横截面：`push2.eastmoney.com/api/qt/clist/get`，失败时使用 `push2delay`；板块或个股代码、涨跌、成交额、量比、换手、`f62` 主力净流等字段。
- 板块/个股分钟资金：`/api/qt/stock/fflow/kline/get`；`f51` 为分钟，`f52` 为供应商估算的累计主力净流，其他列为不同单量级别。
- 个股价格/均价/成交量：`/api/qt/stock/trends2/get?iscr=1`；同一次响应中若真实出现 09:15–09:29 行，才标记集合竞价可用。

这些是公开行情页面使用的第三方接口，没有稳定 SLA。`f62/f52` 是供应商资金分类估算，不是交易所逐账户现金流，也不是银行账户现金净流。

### 通达信公开行情网络（可选增强）

安装 `pytdx` 后，使用 `get_security_quotes` 读取当前买卖五档，使用 `get_history_minute_time_data` 补充历史分钟价格与成交量。历史接口没有主动买卖字段；项目按相邻分钟价格方向给成交额加正负号并累计时，会明确标注为“历史成交方向代理”，绝不冒充原生主力净流。

### 本机 SQLite

后台在 A 股交易窗口每 3 秒抓取一次，按代码每分钟保留一个有效观察值到 `data/market_heatmap/market_heatmap_intraday.sqlite3`。这里保存的是本机实际抓到的公开行情观察值，不是交易所完整逐笔历史。盘前、午休和 15:00 后冻结帧不会写入。

### 强弱分

横截面先做 2.5%/97.5% 缩尾，再计算：

```text
0.35 × 涨跌幅Z
+ 0.35 × 主力净流入占成交额比Z
+ 0.20 × 上涨/下跌家数广度Z
+ 0.10 × 相邻快照净流入增量Z
```

每个分项贡献均在 API 中可审计。行业和概念成分存在重叠，板块 `f62` 不可横向求和当作全市场现金总额。

## 页面性能策略

- 行情快照 3 秒请求，流动性大图等重模块约 12 秒更新。
- 鼠标悬停图表、拖动缩放和滚动期间保留新数据，交互结束后再合并绘制。
- ECharts 关闭重动画，折线不显示逐点符号，大序列使用 LTTB 采样。
- 分时图使用完整分钟骨架定位真实点；`blank_from_index` 之后保持 `null`，所以未发生行情不会铺满全宽。

## 本地数据与隐私

启动时会创建 `data/`，也可用 `--data-dir` 或 `MLR_DATA_DIR` 改到其他位置。`.gitignore` 排除数据库、WAL、缓存、日志、虚拟环境、环境变量、Cookie、Token 和密钥；仓库不附带开发者本机行情库。

环境变量：

```text
MLR_HOST=0.0.0.0
MLR_PORT=8772
MLR_DATA_DIR=/absolute/private/path
MLR_NO_BROWSER=1
```

## 目录结构

```text
market-liquidity-radar/
├── src/quant_dashboard/                 # 行情适配、算法、交易时段与 SQLite
├── src/market_liquidity_radar/
│   ├── cli.py                           # 启动参数与局域网地址发现
│   ├── server.py                        # API、静态页与后台采集器
│   └── web/                             # 完整页面、主题、ECharts
├── tests/                               # 业务算法和启动/API 回归
├── docs/                                # 完整需求与口径文档
├── data/                                # 本机运行数据，不进入 Git
├── start_windows.bat / .ps1             # Windows 一键启动
├── start_macos.command                  # macOS 一键启动
└── start.py                             # 通用入口
```

## 开发与测试

```bash
python -m unittest discover -s tests -v
python -m compileall -q start.py src tests
python start.py --self-check
```

提交前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)、[SECURITY.md](SECURITY.md) 和 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。项目代码采用 [MIT License](LICENSE)。

## 风险声明

本项目仅用于数据可视化、研究和软件开发，不构成投资建议、交易信号或收益承诺。公开行情可能延迟、中断、缺失或变更字段；用于真实交易前，应与持牌行情源和券商终端交叉验证，并遵守数据提供方条款及所在地法律。
