#!/usr/bin/env bash
cd /opt/balanced-portfolio
set -a; . ./.env; set +a
.venv/bin/python /tmp/test_baskets_crud.py 2>&1 | tail -10
