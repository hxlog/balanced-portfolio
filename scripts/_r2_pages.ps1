$chrome='C:\Program Files\Google\Chrome\Application\chrome.exe'
$dir='D:\balanced-portfolio\docs\qa\round2-final'
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$urls=@('https://xushilu.com/','https://xushilu.com/valuation','https://xushilu.com/valuation/000016','https://xushilu.com/dashboard?mode=basket','https://xushilu.com/valuation/HSI')
foreach($u in $urls){ $tmp=Join-Path $env:TEMP ('c-'+[guid]::NewGuid().ToString('N')); $log=Join-Path $dir ([guid]::NewGuid().ToString('N')+'.log'); & $chrome --headless=new --disable-gpu --no-sandbox --user-data-dir=$tmp --enable-logging=stderr --virtual-time-budget=8000 --dump-dom $u 2> $log 1> $null | Out-Null; $h=(Select-String -Path $log -Pattern 'Uncaught|HierarchyRequestError|React error' | Measure-Object).Count; Write-Output ($u+' errors='+$h) }
