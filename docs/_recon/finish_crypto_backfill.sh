#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 等待回补结束 ==="
for i in $(seq 1 40); do
  if ! pgrep -f crypto_history_backfill > /dev/null; then break; fi
  sleep 10
done
echo "backfill running: $(pgrep -fc crypto_history_backfill || echo 0)"
tail -3 /tmp/crypto_backfill.log
echo "=== 重算分位 ==="
timeout 600 .venv/bin/python scripts/recompute_crypto_percentiles.py 2>&1 | tail -10
echo "=== 序列接口验证 ==="
curl -s --max-time 30 "http://127.0.0.1:8000/api/crypto/futures/BTCUSDT/series?hours=720" | .venv/bin/python -c "
import json,sys
d=json.load(sys.stdin)
rows=d.get('data') or []
print('points:', len(rows))
if rows:
    print('first:', rows[0].get('captured_at'), 'last:', rows[-1].get('captured_at'))
"
