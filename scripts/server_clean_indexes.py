# -*- coding: utf-8 -*-
"""为已有原始行情的指数重建清洗表（可重复执行）。"""
import sys, time
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import connect
from bp_api.quant.cleaning import rebuild_clean

setup_logging()
app = load_config()
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("""
        select distinct q.symbol from bp_index_quote_daily q
        join bp_index_config c on c.symbol = q.symbol and c.source = q.source
        where q.adjust = %s and c.is_deleted = 0 and c.category = %s
    """, ("bfq", "index"))
    symbols = [row[0] for row in cur.fetchall()]
print("cleaning symbols:", len(symbols), flush=True)
conn2 = app.db
from bp_ingest.db import connect as _connect
started = time.time()
with _connect(conn2) as conn3:
    conn3.autocommit = False
    rows = rebuild_clean(conn3, symbols=symbols)
print("clean rows:", rows, "elapsed=%.0fs" % (time.time() - started), flush=True)
