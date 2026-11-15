#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
echo "=== 加密回填状态 ==="
pgrep -fc crypto_extra_backfill || echo done
tail -3 /tmp/crypto_extra_backfill2.log | tr -d "\r"
su - postgres -c "psql -d postgres -tAc \"select (select count(*) from bp_crypto_funding_history), (select count(*) from bp_crypto_top_ratio_history)\""
echo "=== API 验证 ==="
pm2 restart bp-api >/dev/null
sleep 4
.venv/bin/python - <<'PY'
import json, urllib.request
s = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/crypto/futures/summary", timeout=60))
print("summary:", json.dumps(s.get("data"), ensure_ascii=False)[:500])
c = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/crypto/futures/contracts?limit=3", timeout=60))
for row in (c.get("data") or [])[:2]:
    print({k: row.get(k) for k in ("contract_code","funding_rate","funding_percentile_30d","top_position_ratio","smart_money_divergence","oi_change_24h_pct")})
PY
echo "=== cron ==="
cat > /etc/cron.d/bp-crypto-extra <<'EOF'
# 每日 05:20 回填加密合约 30 日资金费率与大户多空历史
20 5 * * * root cd /opt/balanced-portfolio && set -a && . ./.env && set +a && nice -n 12 .venv/bin/python scripts/crypto_extra_backfill.py >> /var/log/bp-crypto-extra.log 2>&1
EOF
chmod 644 /etc/cron.d/bp-crypto-extra
echo installed
