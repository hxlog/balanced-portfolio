$env:CLOUDFLARE_API_KEY = [Environment]::GetEnvironmentVariable("CLOUDFLARE_API","User")
$env:CLOUDFLARE_EMAIL = "xingyuliu@outlook.sg"
$env:CLOUDFLARE_ACCOUNT_ID = "acce062a33bf59a76ad7158cbff5fc75"
Set-Location workers\binance-proxy
npx --no-install wrangler deploy 2>&1 | Select-Object -Last 2
Start-Sleep -Seconds 6
$base = "https://binance-proxy.xushilu.com/?path="
$tests = @(
  @("/bybit/market/instruments-info", "category=linear&limit=5"),
  @("/bybit/market/open-interest", "category=linear&symbol=BTCUSDT&intervalTime=5min&limit=1"),
  @("/bybit/market/account-ratio", "category=linear&symbol=BTCUSDT&period=5min&limit=1")
)
foreach ($t in $tests) {
  $u = $base + [uri]::EscapeDataString($t[0]) + "&" + $t[1]
  $resp = Invoke-WebRequest -Uri $u -SkipHttpErrorCheck -TimeoutSec 40
  Write-Output ($t[0] + " -> " + $resp.StatusCode)
  Write-Output ("   " + $resp.Content.Substring(0, [Math]::Min(280, $resp.Content.Length)))
}