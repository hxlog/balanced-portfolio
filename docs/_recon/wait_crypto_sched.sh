#!/usr/bin/env bash
echo "等待下一轮 5 分钟调度..."
for i in $(seq 1 40); do
  n=$(su - postgres -c "psql -d postgres -tAc \"select count(*) from bp_crypto_futures_snapshot_5m\"" 2>/dev/null | tr -d " ")
  last=$(su - postgres -c "psql -d postgres -tAc \"select max(captured_at) from bp_crypto_futures_snapshot_5m\"" 2>/dev/null)
  echo "  [$i] snapshots=$n last=$last"
  if pm2 logs bp-ingest --lines 80 --nostream 2>/dev/null | grep -q "加密合约采集完成"; then
    echo "  >>> 调度任务已执行"
    pm2 logs bp-ingest --lines 300 --nostream 2>/dev/null | grep "加密合约采集完成" | tail -2
    break
  fi
  sleep 15
done