#!/usr/bin/env bash
sleep 60
echo "--- scheduler logs ---"
grep -a -E "Scheduler started|调度器启动|加密合约采集" /root/.pm2/logs/bp-ingest-error.log 2>/dev/null | tail -4
echo "--- tail ---"
tail -4 /root/.pm2/logs/bp-ingest-error.log 2>/dev/null
echo "--- snapshots ---"
su - postgres -c "psql -d postgres -tAc \"select count(*), max(captured_at) from bp_crypto_futures_snapshot_5m\""
echo "--- cron log ---"
tail -3 /var/log/bp-crypto-futures.log 2>/dev/null || echo "no cron log yet"
echo "--- cron file ---"
ls -la /etc/cron.d/bp-crypto-futures
date