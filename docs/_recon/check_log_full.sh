#!/usr/bin/env bash
echo "--- 日志行数 ---"
wc -l /tmp/xueqiu_backfill3.log
echo "--- 前 12 行 ---"
tail -6 /tmp/xueqiu_backfill3.log
echo "--- 是否含 skip 标普 ---"
grep -c "标普" /tmp/xueqiu_backfill3.log || true
echo "--- 进程 ---"
pgrep -fc xueqiu_quote_backfill || echo done