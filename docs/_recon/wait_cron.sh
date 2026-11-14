#!/usr/bin/env bash
sleep 110
echo "--- snapshots ---"
su - postgres -c "psql -d postgres -tAc \"select count(*), max(captured_at) from bp_crypto_futures_snapshot_5m\""
echo "--- cron log ---"
tail -4 /var/log/bp-crypto-futures.log 2>/dev/null || echo "no cron log"
echo "--- scheduler crypto job ---"
grep -a "加密合约采集" /root/.pm2/logs/bp-ingest-error.log 2>/dev/null | tail -2 || echo "none yet"
date