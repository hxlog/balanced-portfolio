#!/usr/bin/env bash
echo "--- 日志尾部 ---"
tail -c 1200 /tmp/csindex_relay.log | tr -d "\r" | tail -8
echo "--- 进程状态 ---"
ps -o pid,etime,stat,cmd -p $(pgrep -f csindex_quote_backfill | head -1) 2>/dev/null || echo "no proc"
echo "--- relay 连通性 ---"
curl -s -o /dev/null -w "relay-csindex:%{http_code} %{time_total}\n" --proxy http://127.0.0.1:10809 --max-time 25 "https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode=000300&startDate=20260101&endDate=20261114" || echo "relay fail"