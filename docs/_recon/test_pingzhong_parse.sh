#!/usr/bin/env bash
cd /opt/balanced-portfolio && timeout 120 .venv/bin/python /tmp/test_pingzhong_parse.py 2>&1 | tail -8
