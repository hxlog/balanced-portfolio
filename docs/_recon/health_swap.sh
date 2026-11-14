#!/usr/bin/env bash
set -euo pipefail
echo "[1] 应用健康检查"
printf "  api overview: "; curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/valuation/overview || true
printf "  api assets:   "; curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/assets | head -1 || true
printf "  web home:     "; curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/ || true
echo "[2] 增加 2G swap（防 OOM）"
if swapon --show | grep -q swapfile; then echo "  swap already on"; else
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q "/swapfile" /etc/fstab || echo "/swapfile none swap sw 0 0" >> /etc/fstab
  echo "  swap enabled"
fi
echo "[3] 资源"
free -h | head -3
uptime