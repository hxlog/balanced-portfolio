#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_ingest/valuation_ingest.py bp_api/repositories_valuation.py scripts/backfill_macro_bond10.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat: 十年期国债收益率落 bp_macro_series（修复 bond-yield 空数据）" || true
echo "=== 回填 ==="
timeout 180 .venv/bin/python scripts/backfill_macro_bond10.py 2>&1 | tail -4
echo "=== 重启 api ==="
pm2 restart bp-api >/dev/null
sleep 5
echo "=== bond-yield API ==="
TOKEN=$(.venv/bin/python scripts/issue_e2e_token.py 2>/dev/null | grep TOKEN= | cut -d= -f2)
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/v1/market/bond-yield?start=2026-10-01" | head -c 400