#!/usr/bin/env bash
echo "--- tail err ---"
tail -8 /root/.pm2/logs/bp-ingest-error.log 2>/dev/null
echo "--- scheduler started? ---"
grep -a "Scheduler started" /root/.pm2/logs/bp-ingest-error.log 2>/dev/null | tail -2
echo "--- crypto-futures job ---"
grep -a -iE "crypto-futures|加密合约|Adding job" /root/.pm2/logs/bp-ingest-error.log 2>/dev/null | tail -5
echo "--- time ---"; date
echo "--- snapshots ---"
su - postgres -c "psql -d postgres -tAc \"select count(*), max(captured_at) from bp_crypto_futures_snapshot_5m\""