#!/bin/zsh
set -eu
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then PYTHON=python3
elif command -v python >/dev/null 2>&1; then PYTHON=python
else
  echo "未找到 Python 3.9 或更高版本。请先通过 python.org 或 Homebrew 安装 Python 3。"
  read -r "?按回车键关闭窗口…"
  exit 1
fi

if [[ ! -x ".venv/bin/python" ]]; then
  echo "首次启动：正在创建项目专用 Python 环境…"
  "$PYTHON" -m venv .venv
fi
if [[ ! -f ".venv/.market-liquidity-radar-1.0" ]]; then
  echo "首次启动：正在安装行情与可选盘口依赖…"
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e .
  if ! .venv/bin/python -m pip install "pytdx>=1.72"; then
    echo "提示：可选 pytdx 安装失败；东方财富行情和全部主页面仍可用，五档盘口/TDX历史增强将显示不可用。"
  fi
  : > .venv/.market-liquidity-radar-1.0
fi
exec .venv/bin/python start.py "$@"
