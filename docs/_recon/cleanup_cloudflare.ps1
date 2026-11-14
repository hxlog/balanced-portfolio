$tok = [Environment]::GetEnvironmentVariable("CLOUDFLARE_API","User")
$h = @{"X-Auth-Email"="xingyuliu@outlook.sg"; "X-Auth-Key"=$tok}
$zid = "ab01a31180b3fc855ccd0c614404ef21"
$aid = "acce062a33bf59a76ad7158cbff5fc75"

Write-Output "=== 1) worker routes ==="
$routes = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/zones/$zid/workers/routes" -Headers $h -TimeoutSec 30
foreach ($rt in $routes.result) {
  Write-Output ("  route " + $rt.pattern + " id=" + $rt.id)
  if ($rt.pattern -like "binance-proxy*") {
    $d = Invoke-WebRequest -Method Delete -Uri "https://api.cloudflare.com/client/v4/zones/$zid/workers/routes/$($rt.id)" -Headers $h -SkipHttpErrorCheck -TimeoutSec 30
    Write-Output ("  deleted status=" + $d.StatusCode)
  }
}

Write-Output "=== 2) DNS record ==="
$recs = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/zones/$zid/dns_records?name=binance-proxy.xushilu.com" -Headers $h -TimeoutSec 30
foreach ($rec in $recs.result) {
  Write-Output ("  record " + $rec.name + " " + $rec.type + " id=" + $rec.id)
  $d = Invoke-WebRequest -Method Delete -Uri "https://api.cloudflare.com/client/v4/zones/$zid/dns_records/$($rec.id)" -Headers $h -SkipHttpErrorCheck -TimeoutSec 30
  Write-Output ("  deleted status=" + $d.StatusCode)
}

Write-Output "=== 3) worker script ==="
$s = Invoke-WebRequest -Method Delete -Uri "https://api.cloudflare.com/client/v4/accounts/$aid/workers/scripts/binance-proxy" -Headers $h -SkipHttpErrorCheck -TimeoutSec 30
Write-Output ("  delete script status=" + $s.StatusCode)

Write-Output "=== 4) verify ==="
$left = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/zones/$zid/workers/routes" -Headers $h -TimeoutSec 30
Write-Output ("  remaining routes: " + $left.result.Count)
$leftdns = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/zones/$zid/dns_records?name=binance-proxy.xushilu.com" -Headers $h -TimeoutSec 30
Write-Output ("  remaining dns: " + $leftdns.result.Count)