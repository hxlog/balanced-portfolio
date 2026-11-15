# -*- coding: utf-8 -*-
"""本机拉取全量行情 → 写生产库（先做 1 个 symbol 的连通性验证）。"""
import os, sys
for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(key, None)
os.environ["PGHOST"] = "81.71.158.239"
os.environ["BP_REQUEST_INTERVAL"] = "0.3"
os.environ["BP_REQUEST_JITTER"] = "0.5"
os.environ["BP_MAX_RETRIES"] = "2"
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import connect
from bp_ingest import ingest

setup_logging()
app = load_config()
print("db host:", app.db.host, "dbname:", getattr(app.db, "dbname", "?"))
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("select count(distinct symbol) from bp_index_quote_daily where adjust = %s", ("bfq",))
    print("raw symbols before:", cur.fetchone()[0])
results = ingest.run(app, symbols=["399975"], refresh_clean=False)
for r in results:
    print("result:", r.symbol, r.status, r.rows, r.detail)
