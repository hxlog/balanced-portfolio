#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "=== 加密快照 ==="
su - postgres -c "psql -d postgres -tAc \"select count(*), max(captured_at) from bp_crypto_futures_snapshot_5m\""
curl -s http://127.0.0.1:8000/api/crypto/futures/summary | head -c 260
echo
echo "=== demo 组合 ==="
curl -s -o /dev/null -w "demo:%{http_code}\n" --max-time 20 http://127.0.0.1:8000/api/portfolios/demo
curl -s --max-time 20 http://127.0.0.1:8000/api/portfolios/demo | head -c 300
echo
echo "=== 数据源 ==="
curl -s -o /dev/null -w "em:%{http_code} " --max-time 8 "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.000300&fields1=f1&fields2=f51,f53&klt=101&fqt=0" || echo -n "em-fail "
curl -s -o /dev/null -w "csindex:%{http_code}\n" --max-time 12 "https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode=930641&startDate=20260101&endDate=20261114" || echo "cs-fail"
echo "=== 覆盖率 ==="
su - postgres -c "psql -d postgres -tAc \"select count(distinct q.symbol) from bp_index_quote_daily q join bp_index_master m on m.index_code = q.symbol\""
date