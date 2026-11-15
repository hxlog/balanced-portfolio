#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 迁移 69 重试（生产） ==="
su - postgres -c "psql -d postgres -v ON_ERROR_STOP=1 -f /opt/balanced-portfolio/ddl/69_crypto_smart_money.sql" 2>&1 | tail -2
echo "=== 启动回填 ==="
pkill -f crypto_extra_backfill || true
set -a; . ./.env; set +a
setsid nohup nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/crypto_extra_backfill.py > /tmp/crypto_extra_backfill2.log 2>&1 < /dev/null &
echo launched
sleep 30
tail -4 /tmp/crypto_extra_backfill2.log | tr -d "\r"
