#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_ingest/crypto_futures.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "P5: 采集经 relay 增加重试并降低并发" || true
echo "--- manual run (env like cron) ---"
BP_BINANCE_HTTP_PROXY=http://127.0.0.1:10809 timeout 240 .venv/bin/python -m bp_ingest.crypto_futures 2>&1 | tail -8
echo "--- snapshots ---"
su - postgres -c "psql -d postgres -tAc \"select count(*), max(captured_at) from bp_crypto_futures_snapshot_5m\""
date