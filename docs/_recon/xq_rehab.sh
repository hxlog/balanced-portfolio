#!/usr/bin/env bash
cd /opt/balanced-portfolio && timeout 120 .venv/bin/python /tmp/xq_rehab.py 2>&1 | tail -6
