#!/usr/bin/env bash
echo "=== 回补进度 ==="
pgrep -fc crypto_history_backfill || echo "done"
grep -c "^ok " /tmp/crypto_backfill.log || true
tail -2 /tmp/crypto_backfill.log
