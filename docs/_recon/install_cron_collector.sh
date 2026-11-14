#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 1) 安装独立 cron 采集（每 5 分钟，不依赖 bp-ingest 调度器） ==="
cat > /etc/cron.d/bp-crypto-futures <<'EOF'
# Balanced Portfolio: Binance 合约 5 分钟采集（经本机 bp-relay 出网）
BP_BINANCE_HTTP_PROXY=http://127.0.0.1:10809
*/5 * * * * root cd /opt/balanced-portfolio && .venv/bin/python -m bp_ingest.crypto_futures >> /var/log/bp-crypto-futures.log 2>&1
EOF
chmod 644 /etc/cron.d/bp-crypto-futures
cat /etc/cron.d/bp-crypto-futures
echo "=== 2) 立即试跑一次（模拟 cron 环境） ==="
cd /opt/balanced-portfolio && BP_BINANCE_HTTP_PROXY=http://127.0.0.1:10809 timeout 120 .venv/bin/python -m bp_ingest.crypto_futures 2>&1 | tail -4
echo "=== 3) 清理 230MB 的 pm2 日志 ==="
: > /root/.pm2/logs/bp-ingest-error.log
du -h /root/.pm2/logs/bp-ingest-error.log
echo "=== 4) snapshots ==="
su - postgres -c "psql -d postgres -tAc \"select count(*), max(captured_at) from bp_crypto_futures_snapshot_5m\""
date