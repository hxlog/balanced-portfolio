#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 启动滞后行情修复（后台，预算 40 分钟） ==="
setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/repair_stale_quotes.py > /tmp/repair_quotes.log 2>&1 < /dev/null &
echo launched
sleep 35
grep -aE "repair targets|fixed|write fail|repair done" /tmp/repair_quotes.log | tail -6
