#!/usr/bin/env bash
echo "--- cron log tail 30 ---"
tail -30 /var/log/bp-crypto-futures.log 2>/dev/null
echo "--- snapshots ---"
su - postgres -c "psql -d postgres -tAc \"select count(*), max(captured_at) from bp_crypto_futures_snapshot_5m\""
echo "--- cron env test ---"
cd /opt/balanced-portfolio && env -i HOME=/root PATH=/usr/bin:/bin BP_BINANCE_HTTP_PROXY=http://127.0.0.1:10809 timeout 60 .venv/bin/python -c "import os; print('proxy=', os.getenv('BP_BINANCE_HTTP_PROXY')); from bp_ingest.config import load_config; a=load_config(); print('db host', a.db.host)" 2>&1 | tail -4