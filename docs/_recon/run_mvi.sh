#!/usr/bin/env bash
set -uo pipefail
cd /opt/balanced-portfolio
timeout 300 .venv/bin/python scripts/research_mvi.py 2>&1 | tail -60
