#!/usr/bin/env bash
cd /opt/balanced-portfolio
pm2 restart bp-api >/dev/null
sleep 4
set -a; . ./.env; set +a
.venv/bin/python /tmp/test_baskets_crud.py 2>&1 | tail -10
