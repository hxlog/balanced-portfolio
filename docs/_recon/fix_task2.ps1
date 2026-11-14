$ErrorActionPreference = "Stop"
$exe = "C:\Program Files\PowerShell\7\pwsh.exe"
$script = "C:\Users\Xingyu Liu\Desktop\Balanced Portfolio\scripts\crypto_futures_collector.ps1"
$arg = '-NoProfile -WindowStyle Hidden -File "' + $script + '"'
Write-Output ("arg=" + $arg)
Unregister-ScheduledTask -TaskName "bp-crypto-futures" -Confirm:$false -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute $exe -Argument $arg
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 4)
Register-ScheduledTask -TaskName "bp-crypto-futures" -Action $action -Trigger $trigger -Settings $settings -Description "Balanced Portfolio: Binance futures 5-min collector (local Xray egress)" -Force | Out-Null
(Get-ScheduledTask -TaskName "bp-crypto-futures").Actions | Format-List Execute,Arguments | Out-String
Start-ScheduledTask -TaskName "bp-crypto-futures"
Start-Sleep -Seconds 25
(Get-ScheduledTaskInfo -TaskName "bp-crypto-futures") | Select-Object LastRunTime,LastTaskResult,NextRunTime | Out-String