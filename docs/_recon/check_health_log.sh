#!/usr/bin/env bash
echo "=== 健康日志全部 ==="
grep -aE "repair|fail|Traceback|Error" /tmp/quote_health.log | tail -15
echo "=== 行数 ==="
wc -l /tmp/quote_health.log
