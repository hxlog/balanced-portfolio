#!/usr/bin/env bash
set -uo pipefail
echo "=== 服务状态 ==="
systemctl is-active postgresql nginx redis-server | tr "\n" " "; echo
echo "=== PM2 ==="
pm2 list --no-color | grep -E "bp-"
echo "=== 站点 ==="
curl -s -o /dev/null -w "api:%{http_code} " --max-time 10 http://127.0.0.1:8000/api/health
curl -s -o /dev/null -w "web:%{http_code}\n" --max-time 10 http://127.0.0.1:3000/valuation
echo "=== 回填残留进程 ==="
pgrep -af "run_quote_batch|bp_ingest run|cleanup_after" | head -5 || echo none
echo "=== 新插入的指数配置数（今日 22:50 之后） ==="
su - postgres -c "psql -d postgres -tAc \"select count(*) from bp_index_config where category = chr(105)||chr(110)||chr(100)||chr(101)||chr(120) and created_at > chr(50)||chr(48)||chr(50)||chr(54)||chr(45)||chr(49)||chr(49)||chr(45)||chr(49)||chr(52)||chr(32)||chr(50)||chr(50)||chr(58)||chr(53)||chr(48)||chr(58)||chr(48)||chr(48)\""