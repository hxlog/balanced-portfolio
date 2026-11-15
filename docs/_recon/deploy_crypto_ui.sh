#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 清理低样本分位行 ==="
su - postgres -c "psql -d postgres -c \"
DELETE FROM bp_crypto_futures_percentile p
WHERE (p.window_days = 30  AND p.sample_size < 20)
   OR (p.window_days = 90  AND p.sample_size < 60)
   OR (p.window_days = 180 AND p.sample_size < 120);
SELECT window_days, count(*), min(sample_size), max(sample_size)
FROM bp_crypto_futures_percentile GROUP BY 1 ORDER BY 1;\""
echo "=== 每周回补 cron ==="
cat > /etc/cron.d/bp-crypto-backfill <<'EOF'
# 每周日 03:00 回补 Binance 30 天历史（OI/多空比/主动买卖/标记价/日线/资金费率）
0 3 * * 0 root cd /opt/balanced-portfolio && BP_BINANCE_HTTP_PROXY=http://127.0.0.1:10809 nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/crypto_history_backfill.py >> /var/log/bp-crypto-backfill.log 2>&1
EOF
chmod 644 /etc/cron.d/bp-crypto-backfill
cat /etc/cron.d/bp-crypto-backfill
echo "=== 构建前端 ==="
git add -A web bp_ingest scripts || true
git -c user.name=deploy -c user.email=deploy@local commit -qm "feat(crypto): 合约图支持 24H/7D/30D；相关性页新增数据表；分位窗口最小样本门槛" || true
cd web
NODE_OPTIONS=--max-old-space-size=1536 nice -n 10 npm run build 2>&1 | tail -3
pm2 restart bp-web >/dev/null
sleep 6
curl -s -o /dev/null -w "futures:%{http_code} " --max-time 40 http://127.0.0.1:3000/crypto-futures
curl -s -o /dev/null -w "crypto:%{http_code}\n" --max-time 40 http://127.0.0.1:3000/crypto
