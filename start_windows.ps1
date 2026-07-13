$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (Get-Command py -ErrorAction SilentlyContinue) {
    $Python = "py"
    $PythonArgs = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $Python = "python"
    $PythonArgs = @()
} else {
    Write-Error "Python 3.9 或更高版本未安装，或未加入 PATH。"
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "首次启动：正在创建项目专用 Python 环境…"
    & $Python @PythonArgs -m venv .venv
}
if (-not (Test-Path ".venv\.market-liquidity-radar-1.0")) {
    Write-Host "首次启动：正在安装行情与可选盘口依赖…"
    & .venv\Scripts\python.exe -m pip install --upgrade pip
    & .venv\Scripts\python.exe -m pip install -e .
    if ($LASTEXITCODE -ne 0) { throw "基础行情依赖安装失败。请检查网络后重新双击启动。" }
    & .venv\Scripts\python.exe -m pip install "pytdx>=1.72"
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "可选 pytdx 安装失败；东方财富行情和主页面仍可用，五档盘口/TDX历史增强将不可用。"
    }
    New-Item -ItemType File -Path ".venv\.market-liquidity-radar-1.0" -Force | Out-Null
}
& .venv\Scripts\python.exe start.py @args
