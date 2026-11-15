#!/usr/bin/env bash
set -uo pipefail
echo "=== 回补进度 ==="
pgrep -fc crypto_history_backfill || echo "已结束"
grep -c "^ok " /tmp/crypto_backfill.log || true
tail -3 /tmp/crypto_backfill.log
echo "=== snapshot 统计 ==="
su - postgres -c "psql -d postgres -tAc \"select count(*), count(distinct contract_code), min(captured_at), max(captured_at) from bp_crypto_futures_snapshot_5m\""
echo "=== percentile 统计 ==="
su - postgres -c "psql -d postgres -tAc \"select window_days, count(*), min(sample_size), max(sample_size) from bp_crypto_futures_percentile group by 1 order by 1\""
