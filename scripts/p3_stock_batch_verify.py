# -*- coding: utf-8 -*-
"""P3 规模化验证：为多只 A 股补齐三复权口径（bfq/qfq/hfq）并清洗 hfq。"""
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")

from bp_ingest import ingest
from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import connect
from bp_api.quant.cleaning import rebuild_clean

STOCKS = {
    "000001": "平安银行",
    "600519": "贵州茅台",
    "300750": "宁德时代",
    "688111": "金山办公",
    "000858": "五粮液",
}

setup_logging()
app = load_config()

with connect(app.db) as conn, conn.cursor() as cur:
    for symbol, name in STOCKS.items():
        cur.execute(
            """
            insert into bp_index_config
                (symbol, source, name, category, adjust_modes, adjust, is_selectable, currency,
                 start_date, is_deleted)
            values (%s, %s, %s, %s, %s, %s, true, %s, null, 0)
            on conflict (symbol, source) do update set
                adjust_modes = excluded.adjust_modes,
                adjust = excluded.adjust,
                is_selectable = true
            """,
            (symbol, "stock_sina", name, "stock", ["bfq", "qfq", "hfq"], "hfq", "CNY"),
        )
    conn.commit()
print("configs ready:", list(STOCKS), flush=True)

results = ingest.run(app, symbols=list(STOCKS), refresh_clean=False)
for item in results:
    print("ingest:", item.symbol, item.status, item.rows, item.detail, flush=True)

with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute(
        "select symbol, adjust, count(*) from bp_index_quote_daily"
        " where category = 'stock' and symbol = any(%s) group by 1,2 order by 1,2",
        (list(STOCKS),),
    )
    for row in cur.fetchall():
        print("raw:", row, flush=True)

with connect(app.db) as conn:
    conn.autocommit = False
    rows = rebuild_clean(conn, symbols=list(STOCKS))
print("clean rows:", rows, flush=True)
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute(
        "select symbol, count(*) from bp_quote_clean where symbol = any(%s) group by 1 order by 1",
        (list(STOCKS),),
    )
    for row in cur.fetchall():
        print("clean:", row, flush=True)
