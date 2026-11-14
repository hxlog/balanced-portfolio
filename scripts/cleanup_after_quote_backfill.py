# -*- coding: utf-8 -*-
"""回填收尾：为全部指数 symbol 重建清洗表。"""
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.config import load_config
from bp_ingest.db import connect
from bp_api.quant.cleaning import rebuild_clean

app = load_config()
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("""
        select distinct symbol from bp_index_config
        where is_deleted = 0 and category = chr(105)||chr(110)||chr(100)||chr(101)||chr(120)
    """)
    symbols = [row[0] for row in cur.fetchall()]
print("cleaning symbols:", len(symbols), flush=True)
with connect(app.db) as conn:
    conn.autocommit = False
    n = rebuild_clean(conn, symbols=symbols)
print("clean rows:", n, flush=True)
