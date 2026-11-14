#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_ingest/scheduler.py bp_ingest/valuation_job.py bp_ingest/market_valuation.py bp_ingest/csindex_value.py bp_ingest/crypto_futures.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "修复调度任务 autocommit 设置失败（连接已处于事务中）" || true
pm2 restart bp-ingest >/dev/null
echo restarted