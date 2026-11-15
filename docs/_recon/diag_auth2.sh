#!/usr/bin/env bash
cd /opt/balanced-portfolio
set -a; . ./.env; set +a
pm2 env 0 2>/dev/null | grep "^BP_JWT_SECRET:" | sed 's/^BP_JWT_SECRET: //' > /tmp/pm2_secret.txt
.venv/bin/python /tmp/diag_auth2.py 2>&1 | tail -12
