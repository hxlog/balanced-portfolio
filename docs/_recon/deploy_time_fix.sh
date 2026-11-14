#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_ingest/crypto_futures.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "P5: 修复 time 未导入（重试路径会 NameError）" || true
echo "--- 立即验证一次采集 ---"
BP_BINANCE_HTTP_PROXY=http://127.0.0.1:10809 timeout 300 .venv/bin/python -m bp_ingest.crypto_futures 2>&1 | tail -5
echo "--- snapshots ---"
su - postgres -c "psql -d postgres -tAc \"select count(*), max(captured_at) from bp_crypto_futures_snapshot_5m\""