#!/usr/bin/env bash
echo "--- EM https push2his ---"
curl -s -o /dev/null -w "%{http_code} %{time_total}\n" --max-time 15 "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.000300&fields1=f1&fields2=f51,f53&klt=101&fqt=0&beg=20240101&end=20240110" || echo fail
echo "--- EM http ---"
curl -s -o /dev/null -w "%{http_code} %{time_total}\n" --max-time 15 "http://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.000300&fields1=f1&fields2=f51,f53&klt=101&fqt=0&beg=20240101&end=20240110" || echo fail
echo "--- EM push2 clist ---"
curl -s -o /dev/null -w "%{http_code} %{time_total}\n" --max-time 15 "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=5&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:1+t:2&fields=f12,f14" || echo fail
echo "--- EM with UA ---"
curl -s -o /dev/null -w "%{http_code} %{time_total}\n" --max-time 15 -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0" "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.000300&fields1=f1&fields2=f51,f53&klt=101&fqt=0&beg=20240101&end=20240110" || echo fail