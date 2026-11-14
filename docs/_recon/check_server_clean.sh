#!/usr/bin/env bash
echo "=== 1) 代理/翻墙类进程 ==="
ps aux | grep -iE "[x]ray|[v]2ray|[c]lash|[t]rojan|[s]hadowsocks|[w]ireguard|[o]penvpn" || echo "  none"
echo "=== 2) 监听端口（应只有 22/80/443/5432/3000/8000 等业务端口） ==="
ss -tlnp 2>/dev/null | head -20
echo "=== 3) crontab ==="
crontab -l 2>/dev/null | grep -v "^#" | head -10 || echo "  empty"
echo "=== 4) pm2 进程 ==="
pm2 list --no-color 2>/dev/null | grep -E "│ [0-9]" | head -10
echo "=== 5) .env 里的代理配置 ==="
grep -iE "proxy|xray|binance" /opt/balanced-portfolio/.env 2>/dev/null | sed "s/=.*/=<set>/" || echo "  none"
echo "=== 6) 仓库里 worker/代理痕迹 ==="
grep -rilE "binance-proxy|xray|vless" /opt/balanced-portfolio --include="*.py" --include="*.sh" --include="*.toml" 2>/dev/null | head -5 || echo "  none"