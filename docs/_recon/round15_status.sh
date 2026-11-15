#!/usr/bin/env bash
echo "=== 源可达性 ==="
curl -s -o /dev/null -w "em:%{http_code} " --max-time 8 "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.000300&fields1=f1&fields2=f51,f53&klt=101&fqt=0" || echo -n "em-fail "
curl -s -o /dev/null -w "csindex:%{http_code} " --max-time 12 "https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode=930641&startDate=20260101&endDate=20261114" || echo -n "cs-fail "
curl -s -o /dev/null -w "csindex-home:%{http_code}\n" --max-time 10 "https://www.csindex.com.cn/" || echo
echo "=== 覆盖率 ==="
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""
echo "=== 自愈日志 ==="
tail -2 /var/log/bp-index-quotes-retry.log 2>/dev/null | tr -d "\r" | tail -1
tail -2 /var/log/bp-csindex-quotes.log 2>/dev/null || echo "csindex: no log"
echo "=== 健康 ==="
curl -s -o /dev/null -w "valuation:%{http_code} api:" --max-time 10 http://127.0.0.1:3000/valuation
curl -s -o /dev/null -w "%{http_code}\n" --max-time 8 http://127.0.0.1:8000/api/health
date