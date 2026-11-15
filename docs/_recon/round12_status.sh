#!/usr/bin/env bash
echo "--- retry cron log ---"
tail -6 /var/log/bp-index-quotes-retry.log 2>/dev/null || echo "no log yet"
echo "--- EM reachable? ---"
curl -s -o /dev/null -w "em:%{http_code} %{time_total}\n" --max-time 12 "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.000300&fields1=f1&fields2=f51,f53&klt=101&fqt=0&beg=20240101&end=20240110" || echo "em fail"
echo "--- coverage ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""
echo "--- health ---"
curl -s -o /dev/null -w "api:%{http_code} " --max-time 8 http://127.0.0.1:8000/api/health
curl -s -o /dev/null -w "web:%{http_code}\n" --max-time 8 http://127.0.0.1:3000/valuation
free -h | head -2
date