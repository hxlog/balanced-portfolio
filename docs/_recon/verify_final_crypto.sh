#!/usr/bin/env bash
echo "--- snapshots ---"
su - postgres -c "psql -d postgres -tAc \"select count(*), max(captured_at) from bp_crypto_futures_snapshot_5m\""
echo "--- last 3 buckets ---"
su - postgres -c "psql -d postgres -tAc \"select captured_at, count(*) from bp_crypto_futures_snapshot_5m group by 1 order by 1 desc limit 3\""
echo "--- cron log ---"
tail -3 /var/log/bp-crypto-futures.log 2>/dev/null