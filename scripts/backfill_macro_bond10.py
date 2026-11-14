# -*- coding: utf-8 -*-
"""把平安 BOND10_TREND 回填到 bp_macro_series（十年期国债收益率）。"""
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import connect
from bp_ingest.valuation_pingan import fetch_bond10_history
from bp_ingest.valuation_ingest import _build_macro_rows
from bp_api.repositories_valuation import upsert_macro_series

setup_logging()
app = load_config()
rows = fetch_bond10_history()
print("bond10 rows fetched:", len(rows))
macro = _build_macro_rows(rows)
with connect(app.db) as conn:
    conn.autocommit = False
    n = upsert_macro_series(conn, macro)
    conn.commit()
print("macro rows upserted:", n)
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("select count(*), min(trade_date), max(trade_date), min(value), max(value) from bp_macro_series where series_code = %s", ("cn_10y_yield",))
    print("db:", cur.fetchone())
