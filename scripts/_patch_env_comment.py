# -*- coding: utf-8 -*-
import glob, re
files = [
    "scripts/incremental_stock_quotes.py",
    "scripts/incremental_fund_nav.py",
    "scripts/asset_coverage_report.py",
    "scripts/local_backfill_stocks.py",
    "scripts/local_backfill_funds.py",
]
for path in files:
    s = open(path, encoding="utf-8").read()
    if 'value.strip().split(" #")[0]' in s:
        print(path, "already"); continue
    s = s.replace(
        'values[key.strip()] = value.strip().strip(\'"\').strip("\'")',
        'values[key.strip()] = value.split(" #")[0].strip().strip(\'"\').strip("\'")',
    )
    open(path, "w", encoding="utf-8").write(s)
    print(path, "patched:", 'split(" #")' in s)
