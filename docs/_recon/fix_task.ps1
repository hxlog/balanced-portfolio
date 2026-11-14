$tr = '"C:\Program Files\PowerShell\7\pwsh.exe" -NoProfile -WindowStyle Hidden -File "C:\Users\Xingyu Liu\Desktop\Balanced Portfolio\scripts\crypto_futures_collector.ps1"'
Unregister-ScheduledTask -TaskName "bp-crypto-futures" -Confirm:$false -ErrorAction SilentlyContinue
$args = @("/Create", "/TN", "bp-crypto-futures", "/SC", "MINUTE", "/MO", "5", "/TR", $tr, "/F")
$p = Start-Process -FilePath "schtasks.exe" -ArgumentList $args -Wait -PassThru -WindowStyle Hidden
Write-Output ("schtasks exit=" + $p.ExitCode)
(Get-ScheduledTask -TaskName "bp-crypto-futures").Actions | Format-List Execute,Arguments | Out-String
Start-ScheduledTask -TaskName "bp-crypto-futures"
Start-Sleep -Seconds 20
(Get-ScheduledTaskInfo -TaskName "bp-crypto-futures") | Select-Object LastRunTime,LastTaskResult | Out-String