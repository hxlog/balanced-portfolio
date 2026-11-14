#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_ingest/crypto_futures.py bp_ingest/scheduler.py ddl/59_crypto_provider.sql
git -c user.name=deploy -c user.email=deploy@local commit -qm "P5: 采集迁移到服务器（bp-relay 出网）+ 5 分钟调度" || true
grep -q "^BP_BINANCE_HTTP_PROXY=" .env || echo "BP_BINANCE_HTTP_PROXY=http://127.0.0.1:10809" >> .env
grep "^BP_BINANCE_HTTP_PROXY=" .env
echo "--- manual run ---"
timeout 180 .venv/bin/python -c "import logging; logging.basicConfig(level=logging.INFO); from bp_ingest.crypto_futures import run_once; print(run_once())" 2>&1 | tail -6