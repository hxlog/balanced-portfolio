#!/usr/bin/env bash
cd /opt/balanced-portfolio/web
echo "--- BUILD_ID ---"
ls -la .next/BUILD_ID 2>/dev/null || echo "no BUILD_ID"
date
echo "--- dmesg oom ---"
dmesg -T 2>/dev/null | grep -iE "out of memory|oom-kill" | tail -3
echo "--- web health ---"
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/valuation/930641