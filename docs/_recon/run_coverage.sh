#!/usr/bin/env bash
cd /opt/balanced-portfolio
.venv/bin/python scripts/asset_coverage_report.py --json /tmp/coverage.json 2>&1 | tail -42
