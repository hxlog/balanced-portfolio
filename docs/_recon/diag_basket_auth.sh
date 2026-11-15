#!/usr/bin/env bash
cd /opt/balanced-portfolio
echo "=== pm2 环境 secret 长度 ==="
pm2 env 0 2>/dev/null | grep -c "BP_JWT_SECRET" || true
.venv/bin/python /tmp/diag_basket_auth.py 2>&1 | tail -12
