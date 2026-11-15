# -*- coding: utf-8 -*-
"""统计缺失行情的 symbol 分类。"""
import re, sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.config import load_config
from bp_ingest.db import connect

app = load_config()
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("select c.symbol, m.market from bp_index_config c left join bp_index_master m on m.index_code = c.index_code where c.is_deleted = 0 and c.category = %s and c.index_code is not null and not exists (select 1 from bp_index_quote_daily q where q.symbol = c.symbol and q.adjust = %s)", ("index", "bfq"))
    rows = cur.fetchall()
print("missing:", len(rows))
from collections import Counter
by_market = Counter(market for _, market in rows)
print("by market:", dict(by_market))
pref = Counter(re.sub(r"[0-9].*", "", sym) or sym[:2] for sym, _ in rows)
print("top prefixes:", pref.most_common(8))
print("sample:", [s for s, _ in rows[:12]])
