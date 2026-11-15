#!/usr/bin/env bash
cd /opt/balanced-portfolio
pm2 restart bp-api >/dev/null
sleep 5
.venv/bin/python /tmp/verify_list_fields.py
