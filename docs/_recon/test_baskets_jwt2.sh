#!/usr/bin/env bash
cd /opt/balanced-portfolio && .venv/bin/python /tmp/test_baskets_jwt2.py 2>&1 | tail -10
