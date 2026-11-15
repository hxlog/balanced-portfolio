#!/usr/bin/env bash
echo "=== 回补进度 ==="
pgrep -fc crypto_history_backfill || echo "done"
grep -c "^ok " /tmp/crypto_backfill.log || true
tail -3 /tmp/crypto_backfill.log
su - postgres -c "psql -d postgres -tAc \"select count(*) from bp_crypto_futures_snapshot_5m\""
