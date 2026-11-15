#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
grep -n "_BROAD_PROXY_CODES" -A1 bp_api/valuation.py | head -4
pm2 restart bp-api >/dev/null
sleep 5
.venv/bin/python /tmp/verify_proxies.py
