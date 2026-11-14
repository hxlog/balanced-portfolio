$env:CLOUDFLARE_API_KEY = [Environment]::GetEnvironmentVariable("CLOUDFLARE_API","User")
$env:CLOUDFLARE_EMAIL = "xingyuliu@outlook.sg"
$env:CLOUDFLARE_ACCOUNT_ID = "acce062a33bf59a76ad7158cbff5fc75"
Set-Location workers\binance-proxy
npx --no-install wrangler deploy 2>&1 | Select-Object -Last 2