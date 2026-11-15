#!/usr/bin/env bash
cd /opt/balanced-portfolio && .venv/bin/python scripts/_diag_mvi_data.py 2>&1 | tail -12
