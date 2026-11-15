#!/usr/bin/env bash
cd /opt/balanced-portfolio
mkdir -p docs/index-valuation
timeout 300 .venv/bin/python scripts/research_mvi.py 2>&1 | grep -v "UserWarning\|df = pd.read_sql" | tail -12
echo "=== 输出文件 ==="
ls -la docs/index-valuation/mvi-research.json 2>/dev/null || echo missing
