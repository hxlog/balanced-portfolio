#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
pm2 restart bp-api >/dev/null
sleep 4
echo "=== baskets ==="
curl -s --max-time 20 http://127.0.0.1:8000/api/baskets | head -c 200; echo
echo "=== backtest 错误日志 ==="
tail -40 /root/.pm2/logs/bp-api-error.log | grep -A6 "Traceback\|Error" | tail -20
