#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_ingest scripts || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat: Binance 历史回补脚本（OI/多空比/主动买卖/标记价 30 天 + 日线 + 资金费率）" || true
BP_BINANCE_HTTP_PROXY=http://127.0.0.1:10809 setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/crypto_history_backfill.py > /tmp/crypto_backfill.log 2>&1 < /dev/null &
echo launched
sleep 45
head -8 /tmp/crypto_backfill.log
tail -3 /tmp/crypto_backfill.log
