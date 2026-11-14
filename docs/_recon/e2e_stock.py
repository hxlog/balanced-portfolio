# -*- coding: utf-8 -*-
"""端到端验证：添加个股资产 → 抓三口径 → 清洗。"""
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from types import SimpleNamespace
from bp_ingest.config import load_config
from bp_ingest.db import connect
from bp_api.repositories import upsert_asset_config

app = load_config()

with connect(app.db) as conn:
    conn.autocommit = False
    upsert_asset_config(conn, SimpleNamespace(
        symbol="600036", source="stock_sina", category="stock",
        name="招商银行", start_date=None, is_deleted=0, adjust=None,
    ))
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("select symbol, category, adjust, adjust_modes from bp_index_config where symbol = %s", ("600036",))
        print("config:", cur.fetchone())

from bp_ingest import ingest
results = ingest.run(app, symbols=["600036"], refresh_clean=True)
for r in results:
    print("sync:", r.symbol, r.source, r.status, r.rows, r.detail)

with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("select adjust, count(*), min(trade_date), max(trade_date) from bp_index_quote_daily where symbol = %s group by adjust order by adjust", ("600036",))
    for row in cur.fetchall():
        print("raw:", row)
    cur.execute("select adjust, count(*), min(trade_date), max(trade_date) from bp_quote_clean where symbol = %s group by adjust order by adjust", ("600036",))
    for row in cur.fetchall():
        print("clean:", row)
