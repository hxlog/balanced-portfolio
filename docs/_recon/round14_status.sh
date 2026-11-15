#!/usr/bin/env bash
echo "=== 数据源可达性 ==="
curl -s -o /dev/null -w "em:%{http_code} %{time_total}\n" --max-time 8 "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.000300&fields1=f1&fields2=f51,f53&klt=101&fqt=0" || echo "em fail"
curl -s -o /dev/null -w "csindex:%{http_code} %{time_total}\n" --max-time 12 "https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode=930641&startDate=20260101&endDate=20261114" || echo "cs fail"
echo "=== 覆盖率 ==="
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""
echo "=== 自愈 cron 日志 ==="
tail -3 /var/log/bp-index-quotes-retry.log 2>/dev/null || echo "retry: no log"
tail -3 /var/log/bp-csindex-quotes.log 2>/dev/null || echo "csindex: no log"
echo "=== 页面健康 ==="
curl -s -o /dev/null -w "valuation:%{http_code} " --max-time 10 http://127.0.0.1:3000/valuation
curl -s -o /dev/null -w "api:%{http_code}\n" --max-time 8 http://127.0.0.1:8000/api/health
date