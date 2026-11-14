#!/usr/bin/env bash
set -euo pipefail
cd /opt/balanced-portfolio
OUT=$(.venv/bin/python /tmp/issue_token.py 2>/dev/null | tail -2)
TOKEN=$(echo "$OUT" | tail -1)
echo "token issued: ${#TOKEN} chars"
echo "--- /api/v1 smoke ---"
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/v1/index/detail?code=930641" | head -c 300
echo
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/v1/index/percentile?codes=930641&metrics=pe_ttm&windows=5y" | head -c 300
echo
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/v1/market/daily?codes=000300&start=2026-10-01&end=2026-11-14" | head -c 300
echo
echo "--- csv ---"
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/v1/index/valuation?codes=930641&format=csv" | head -c 200