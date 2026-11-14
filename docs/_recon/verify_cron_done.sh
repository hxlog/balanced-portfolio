#!/usr/bin/env bash
sleep 60
echo "--- snapshots ---"
su - postgres -c "psql -d postgres -tAc \"select count(*), max(captured_at) from bp_crypto_futures_snapshot_5m\""
echo "--- cron log tail ---"
tail -6 /var/log/bp-crypto-futures.log 2>/dev/null
echo "--- scheduler crypto ---"
grep -a "加密合约采集" /root/.pm2/logs/bp-ingest-error.log 2>/dev/null | tail -2 || echo none
date