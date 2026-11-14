#!/usr/bin/env bash
echo "--- snapshots ---"
su - postgres -c "psql -d postgres -tAc \"select count(*), max(captured_at) from bp_crypto_futures_snapshot_5m\""
echo "--- cron log ---"
grep -a "contracts" /var/log/bp-crypto-futures.log 2>/dev/null | tail -3
echo "--- scheduler crypto ---"
grep -a "加密合约采集" /root/.pm2/logs/bp-ingest-error.log 2>/dev/null | tail -2 || echo none
date