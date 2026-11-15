#!/usr/bin/env bash
echo "=== 东财备用域名 ==="
for host in "push2his.eastmoney.com" "82.push2his.eastmoney.com" "push2delay.eastmoney.com" "push2.eastmoney.com" "datacenter-web.eastmoney.com"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 "https://$host/api/qt/stock/kline/get?secid=1.000300&fields1=f1&fields2=f51,f53&klt=101&fqt=0" 2>/dev/null || echo fail)
  echo "  $host -> $code"
done
echo "=== 中证官网行情 API ==="
curl -s -o /tmp/cs.json -w "csindex-perf: %{http_code} %{time_total}\n" --max-time 15 "https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode=930641&startDate=20260101&endDate=20261114" || echo fail
head -c 200 /tmp/cs.json 2>/dev/null || true
echo
echo "=== 中证官网首页可达性 ==="
curl -s -o /dev/null -w "csindex: %{http_code} %{time_total}\n" --max-time 12 "https://www.csindex.com.cn/" || echo fail