#!/usr/bin/env bash
# Balanced Portfolio — 服务器端发版脚本(PM2 + Nginx)
# 在仓库根目录执行: bash deploy/deploy.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export APP_ROOT="$ROOT"

echo "==> 工作目录: $ROOT"

if [[ ! -f .env ]]; then
  echo "错误: 缺少 .env (从 .env.example 复制并填写, 该文件不在 git 中)" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

if [[ "${BP_SKIP_PULL:-0}" == "1" ]]; then
  echo "==> 跳过 git pull (BP_SKIP_PULL=1)"
else
  echo "==> git pull"
  git pull --ff-only
fi

echo "==> Python 依赖"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -U pip -q
pip install -r requirements.txt -q

echo "==> 前端构建"
cd web
if [[ -f package-lock.json ]]; then
  npm ci --legacy-peer-deps
else
  npm install -f
fi
export BP_API_BASE="${BP_API_BASE:-http://127.0.0.1:8000}"
export BP_SITE_URL="${BP_SITE_URL:-http://localhost:3000}"
npm run build
cd "$ROOT"

echo "==> PM2 重载"
if pm2 describe bp-api &>/dev/null; then
  pm2 reload deploy/ecosystem.config.cjs --update-env
else
  pm2 start deploy/ecosystem.config.cjs
fi
pm2 save

echo "==> 健康检查"
sleep 5
for i in 1 2 3; do
  if curl -sf "http://127.0.0.1:8000/api/health" >/dev/null 2>&1; then
    echo "API OK"; break
  elif [ "$i" -eq 3 ]; then
    echo "警告: API 健康检查失败 (3次重试)"
  else
    sleep 2
  fi
done
curl -sf -o /dev/null -w "%{http_code}" "http://127.0.0.1:3000/" 2>/dev/null | grep -qE '200|304' && echo "Web OK" || echo "警告: Web 检查失败"
if command -v redis-cli &>/dev/null; then
  redis-cli ping >/dev/null 2>&1 && echo "Redis OK" || echo "警告: Redis 检查失败"
fi
pm2 describe bp-worker &>/dev/null && echo "Worker OK" || echo "警告: bp-worker 未运行"

if command -v nginx &>/dev/null; then
  if sudo nginx -t 2>/dev/null; then
    sudo systemctl reload nginx && echo "Nginx 已 reload"
  fi
fi

echo "==> 完成. pm2 status:"
pm2 status
