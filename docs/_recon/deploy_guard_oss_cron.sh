#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
git add -A bp_api/repositories_valuation.py scripts/csindex_oss_sync.py
git -c user.name=deploy -c user.email=deploy@local commit -qm "fix: 52周高低需>=200交易日样本；新增中证OSS行情同步" || true
pm2 restart bp-api >/dev/null
sleep 5
curl -s --max-time 60 "http://127.0.0.1:8000/api/valuation/indices?limit=600" | .venv/bin/python -c "import sys,json; d=json.load(sys.stdin)['data']; f=lambda k: sum(1 for r in d if r.get(k) is not None); print('rows',len(d),'close',f('close_price'),'7d',f('change_7d_pct'),'52wH',f('high_52w'),'pos',f('position_52w_pct'))"
echo "--- 安装每日 OSS 同步 cron ---"
cat > /etc/cron.d/bp-csindex-oss <<'EOF'
# 每日 17:30 用中证 OSS perf 文件同步最近 24 日行情（低突发，避免 WAF）
30 17 * * 1-5 root cd /opt/balanced-portfolio && nice -n 12 ionice -c2 -n7 .venv/bin/python scripts/csindex_oss_sync.py >> /var/log/bp-csindex-oss.log 2>&1
EOF
chmod 644 /etc/cron.d/bp-csindex-oss
cat /etc/cron.d/bp-csindex-oss