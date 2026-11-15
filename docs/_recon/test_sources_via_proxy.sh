#!/usr/bin/env bash
echo "--- CSIndex via bp-relay (SG) ---"
curl -s -o /tmp/cs2.json -w "csindex-proxy http=%{http_code} time=%{time_total}\n" --proxy http://127.0.0.1:10809 --max-time 30 "https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode=930641&startDate=20250101&endDate=20261114" || echo fail
head -c 150 /tmp/cs2.json 2>/dev/null; echo
echo "--- EM via bp-relay (SG) ---"
curl -s -o /tmp/em2.json -w "em-proxy http=%{http_code} time=%{time_total}\n" --proxy http://127.0.0.1:10809 --max-time 30 "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.000300&fields1=f1&fields2=f51,f53&klt=101&fqt=0" || echo fail
head -c 120 /tmp/em2.json 2>/dev/null; echo