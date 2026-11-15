#!/usr/bin/env bash
cd /opt/balanced-portfolio && .venv/bin/python scripts/_diag_series.py 2>&1 | tail -10
