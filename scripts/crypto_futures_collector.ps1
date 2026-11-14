# 加密合约 5 分钟采集（本机执行；生产服务器不装任何代理）
#
# 为什么在本机跑：Binance 对 Cloudflare Workers 出口返回 403（WAF），
# 国内服务器直连 Binance 也被墙；本机 Xray（VLESS → 新加坡）可直连，
# 因此采集在本机完成，只把结果写入生产库（81.71.158.239:5432）。
$ErrorActionPreference = "Stop"
$repo = "C:\Users\Xingyu Liu\Desktop\Balanced Portfolio"
$xrayDir = "$env:USERPROFILE\.bp-xray"
$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# 1) 确保 Xray 在跑（只监听 127.0.0.1:10808/10809，不做任何系统代理设置）
if (-not (Get-Process -Name xray -ErrorAction SilentlyContinue)) {
    if (Test-Path (Join-Path $xrayDir "xray.exe")) {
        Start-Process -FilePath (Join-Path $xrayDir "xray.exe") -ArgumentList @("run", "-c", (Join-Path $xrayDir "config.json")) -WindowStyle Hidden
        Start-Sleep -Seconds 3
    } else {
        "[$(Get-Date -Format s)] xray.exe 缺失，跳过本轮" | Out-File -Append (Join-Path $logDir "crypto_futures.log")
        exit 1
    }
}

# 2) 采集（写生产库；PGHOST 覆盖 .env 里不可达的 Tailscale 地址）
$env:PGHOST = "81.71.158.239"
$env:HTTPS_PROXY = "http://127.0.0.1:10809"
$env:HTTP_PROXY = "http://127.0.0.1:10809"
$env:NO_PROXY = "81.71.158.239,127.0.0.1,localhost"
Set-Location $repo
$out = & ".venv\Scripts\python.exe" -c "import logging; logging.basicConfig(level=logging.INFO); from bp_ingest.crypto_futures import run_once; print(run_once())" 2>&1
"[$(Get-Date -Format s)] " + ($out | Select-Object -Last 1) | Out-File -Append (Join-Path $logDir "crypto_futures.log")