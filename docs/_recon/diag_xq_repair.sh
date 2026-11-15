#!/usr/bin/env bash
echo "=== 雪球增量日志（周五） ==="
tail -12 /var/log/bp-xueqiu-quotes.log 2>/dev/null || echo "no log"
echo "=== 修复抓取诊断 ==="
cd /opt/balanced-portfolio && timeout 240 .venv/bin/python /tmp/diag_xq_repair.py 2>&1 | tail -20
