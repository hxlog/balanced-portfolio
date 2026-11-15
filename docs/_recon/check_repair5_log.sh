#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "=== 日志头 ==="
tr -d "\r" < /tmp/repair_quotes5.log | grep -aE "repair targets|Traceback|Error|repair done|fixed " | head -20
echo "=== 行数/大小 ==="
wc -lc /tmp/repair_quotes5.log
