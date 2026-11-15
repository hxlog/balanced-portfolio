#!/usr/bin/env bash
echo "--- EM via bp-relay (SG) ---"
curl -s -o /tmp/em_test.json -w "%{http_code} %{time_total}\n" --proxy http://127.0.0.1:10809 --max-time 40 "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.000300&fields1=f1&fields2=f51,f53&klt=101&fqt=0&beg=20240101&end=20240110" || echo fail
head -c 200 /tmp/em_test.json 2>/dev/null || true
echo
echo "--- sina direct ---"
curl -s -o /dev/null -w "%{http_code} %{time_total}\n" --max-time 15 "https://finance.sina.com.cn" || echo fail