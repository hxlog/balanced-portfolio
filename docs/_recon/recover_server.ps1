for ($i = 1; $i -le 40; $i++) {
  $t = Get-Date -Format HH:mm:ss
  Write-Output "[$i] $t trying ssh..."
  $out = ssh -o BatchMode=yes -o ConnectTimeout=25 root@81.71.158.239 "echo connected; uptime" 2>&1
  if ($LASTEXITCODE -eq 0) {
    Write-Output "SSH OK at attempt ${i}: $out"
    $kill = ssh -o BatchMode=yes -o ConnectTimeout=25 root@81.71.158.239 "pkill -f run_quote_batch12; pkill -f run_quote_batch; pkill -f cleanup_after_quote_backfill; sleep 3; echo killed; uptime; curl -s -o /dev/null -w api:%{http_code} --max-time 10 http://127.0.0.1:8000/api/health" 2>&1
    Write-Output $kill
    break
  }
  Start-Sleep -Seconds 20
}