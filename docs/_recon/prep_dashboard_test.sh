#!/usr/bin/env bash
cd /opt/balanced-portfolio
set -a; . ./.env; set +a
.venv/bin/python /tmp/prep_dashboard_test.py 2>&1 | tail -6
