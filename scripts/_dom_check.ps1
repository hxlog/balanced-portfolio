$chrome='C:\Program Files\Google\Chrome\Application\chrome.exe'
$dir='D:\balanced-portfolio\docs\qa\round2-dom'
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$pages=@(@('val','https://xushilu.com/valuation'),@('d16','https://xushilu.com/valuation/000016'),@('basket','https://xushilu.com/dashboard?mode=basket'))
foreach($p in $pages){ $tmp=Join-Path $env:TEMP ('d-'+[guid]::NewGuid().ToString('N')); $out=Join-Path $dir ($p[0]+'.html'); & $chrome --headless=new --disable-gpu --no-sandbox --user-data-dir=$tmp --virtual-time-budget=8000 --dump-dom $p[1] 2>$null 1> $out | Out-Null }
$checks=@{
 'val'=@('指标切换本地完成','沪深300 · Valuation Band','· 数据截至','Valuation Band','红利指数吸引力','打开图表');
 'd16'=@('隐藏非前 10','隐藏非前10','PB · 1 年估值与点位','· 右轴为指数点位','描述统计','跟踪基金');
 'basket'=@('一篮子资产','年化换手','Sortino','Calmar','后复权 hfq','不复权');
}
foreach($k in $checks.Keys){ $html=Get-Content (Join-Path $dir ($k+'.html')) -Raw; Write-Output ('== '+$k+' =='); foreach($t in $checks[$k]){ if($html.Contains($t)){ Write-Output ('PRESENT: '+$t) } else { Write-Output ('ABSENT: '+$t) } } }
