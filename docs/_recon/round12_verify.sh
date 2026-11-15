#!/usr/bin/env bash
cd /opt/balanced-portfolio
for p in / /valuation /crypto-futures /cffex /crypto /dashboard /builder; do
  curl -s -o /dev/null -w "$p -> %{http_code}\n" --max-time 20 "http://127.0.0.1:3000$p"
done
echo "--- EM ---"
curl -s -o /dev/null -w "em:%{http_code} %{time_total}\n" --max-time 10 "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.000300&fields1=f1&fields2=f51,f53&klt=101&fqt=0" || echo em-fail
echo "--- retry log ---"
tail -3 /var/log/bp-index-quotes-retry.log 2>/dev/null || echo none
echo "--- coverage ---"
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""