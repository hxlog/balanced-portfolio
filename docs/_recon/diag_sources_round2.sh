#!/usr/bin/env bash
echo "=== cron 文件 ==="
ls /etc/cron.d/ 2>/dev/null
echo "=== 数据源可达性 ==="
curl -s -o /dev/null -w "em-push2his: %{http_code} %{time_total}\n" --max-time 12 "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.000300&fields1=f1&fields2=f51,f53&klt=101&fqt=0" || echo "em fail"
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
curl -s -o /tmp/xq.html -w "xueqiu-home: %{http_code} %{size_download}\n" --max-time 15 -A "$UA" "https://xueqiu.com/about" || echo "xq fail"
curl -s -o /tmp/xq2.json -w "xueqiu-kline: %{http_code} %{size_download}\n" --max-time 15 -A "$UA" -H "Referer: https://xueqiu.com/" "https://stock.xueqiu.com/v5/stock/chart/kline.json?symbol=SH000905&begin=$(date +%s)000&period=day&type=before&count=-5&indicator=kline" || echo "xq kline fail"
head -c 120 /tmp/xq2.json; echo
echo "=== 中证 relay ==="
curl -s -o /dev/null -w "csindex-relay: %{http_code} %{time_total}\n" --proxy http://127.0.0.1:10809 --max-time 25 "https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode=000905&startDate=20260101&endDate=20261114" || echo "cs fail"
echo "=== 雪球增量 cron 是否存在 ==="
cat /etc/cron.d/bp-xueqiu-quotes 2>/dev/null || echo missing
