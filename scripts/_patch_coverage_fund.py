# -*- coding: utf-8 -*-
import re
p = "scripts/asset_coverage_report.py"
s = open(p, encoding="utf-8", newline="").read()
s = re.sub(
    r'\n(\s*)cur\.execute\("SELECT count\(\*\) FROM bp_fund_master WHERE fund_code ~ \'\^\[0-9\]\{6\}\\\$?\'?"\)\r?\n\s*fund_total = cur\.fetchone\(\)\[0\]',
    '\n        cur.execute(\n            "SELECT count(*) FROM ("\n            " SELECT fund_code FROM bp_fund_master WHERE fund_code ~ \'^[0-9]{6}$\'"\n            " UNION SELECT DISTINCT fund_code FROM bp_fund_nav_daily WHERE fund_code ~ \'^[0-9]{6}$\'"\n            ") u"\n        )\n        fund_total = cur.fetchone()[0]',
    s,
)
open(p, "w", encoding="utf-8", newline="").write(s)
print("patched:", "UNION SELECT DISTINCT fund_code" in s)
