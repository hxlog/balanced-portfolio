# -*- coding: utf-8 -*-
"""仅重算中证官网与平安口径的差异日志（不重新抓取）。"""
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import connect
from bp_ingest.csindex_value import _log_diff, CALC_SRC

setup_logging()
app = load_config()
total = 0
with connect(app.db) as conn:
    conn.autocommit = False
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT index_code FROM bp_index_valuation_series WHERE calc_src = %s", (CALC_SRC,))
        codes = [r[0] for r in cur.fetchall()]
        for code in codes:
            total += _log_diff(cur, code)
    conn.commit()
print({"codes": len(codes), "diff_rows": total})
