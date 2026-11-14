# -*- coding: utf-8 -*-
"""P3 收尾：清理与指数代码冲突的股票配置，改用不冲突的股票验证三复权。"""
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")

from bp_ingest import ingest
from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import connect
from bp_api.quant.cleaning import rebuild_clean

REMOVE = ["000001", "000858"]  # 与指数代码冲突（000001=上证指数，000858 已有指数配置）
ADD = {"601318": "中国平安", "002594": "比亚迪"}

setup_logging()
app = load_config()
with connect(app.db) as conn, conn.cursor() as cur:
    for symbol in REMOVE:
        cur.execute("update bp_index_config set is_deleted = 1 where symbol = %s and source = %s", (symbol, "stock_sina"))
        cur.execute("delete from bp_index_quote_daily where symbol = %s and source = %s", (symbol, "stock_sina"))
        cur.execute("delete from bp_quote_clean where symbol = %s and source = %s", (symbol, "stock_sina"))
    for symbol, name in ADD.items():
        cur.execute(
            """
            insert into bp_index_config
                (symbol, source, name, category, adjust_modes, adjust, is_selectable, currency,
                 start_date, is_deleted)
            values (%s, %s, %s, %s, %s, %s, true, %s, null, 0)
            on conflict (symbol, source) do update set
                adjust_modes = excluded.adjust_modes, adjust = excluded.adjust,
                is_selectable = true, is_deleted = 0
            """,
            (symbol, "stock_sina", name, "stock", ["bfq", "qfq", "hfq"], "hfq", "CNY"),
        )
    conn.commit()
print("removed:", REMOVE, "added:", list(ADD), flush=True)

results = ingest.run(app, symbols=list(ADD), refresh_clean=False)
for item in results:
    print("ingest:", item.symbol, item.status, item.rows, item.detail, flush=True)

with connect(app.db) as conn:
    conn.autocommit = False
    rows = rebuild_clean(conn, symbols=list(ADD))
print("clean rows:", rows, flush=True)

with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute(
        "select symbol, adjust, count(*) from bp_index_quote_daily"
        " where category = 'stock' group by 1,2 order by 1,2",
    )
    for row in cur.fetchall():
        print("raw:", row, flush=True)
    cur.execute(
        "select symbol, count(*), count(distinct trade_date) from bp_quote_clean"
        " where symbol in (select symbol from bp_index_config where category = 'stock' and is_deleted = 0)"
        " group by 1 order by 1",
    )
    for row in cur.fetchall():
        print("clean:", row, flush=True)
