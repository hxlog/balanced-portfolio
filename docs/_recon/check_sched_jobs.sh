#!/usr/bin/env bash
echo "--- 最近 40 行 ---"
tail -25 /root/.pm2/logs/bp-ingest-error.log 2>/dev/null
echo "--- 估值相关 ---"
grep -a -E "估值|valuation|market" /root/.pm2/logs/bp-ingest-error.log 2>/dev/null | tail -6 || echo none
date