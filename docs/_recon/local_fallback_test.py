# -*- coding: utf-8 -*-
"""本机回填测试：force fallback（本机无法连东财，走新浪降级链）。"""
import os, sys
for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(key, None)
os.environ["PGHOST"] = "81.71.158.239"
os.environ["BP_REQUEST_INTERVAL"] = "0.2"
os.environ["BP_REQUEST_JITTER"] = "0.3"
os.environ["BP_MAX_RETRIES"] = "1"
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.config import load_config, setup_logging
from bp_ingest import ingest
from bp_ingest.db import connect

setup_logging()
app = load_config()
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("""
        select c.symbol from bp_index_config c
        where c.is_deleted = 0 and c.category = %s and c.index_code is not null
          and not exists (select 1 from bp_index_quote_daily q where q.symbol = c.symbol and q.adjust = %s)
          and (c.symbol like %s or c.symbol like %s or c.symbol like %s)
        limit 5
    """, ("index", "bfq", "000%", "399%", "H30%"))
    samples = [row[0] for row in cur.fetchall()]
print("samples:", samples)
if samples:
    results = ingest.run(app, symbols=samples, refresh_clean=False)
    for r in results:
        print("result:", r.symbol, r.status, r.rows, r.detail)
