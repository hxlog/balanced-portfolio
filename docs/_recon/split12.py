# -*- coding: utf-8 -*-
"""把未回填 symbol 拆成 12 批，写 /tmp/vb12_N.txt。"""
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.config import load_config
from bp_ingest.db import connect
app = load_config()
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("""
        select symbol from bp_index_config
        where is_deleted = 0 and category = chr(105)||chr(110)||chr(100)||chr(101)||chr(120)
          and index_code is not null
    """)
    all_syms = sorted({row[0] for row in cur.fetchall()})
    cur.execute("select distinct symbol from bp_index_quote_daily where adjust = chr(98)||chr(102)||chr(113)")
    have = {row[0] for row in cur.fetchall()}
missing = [s for s in all_syms if s not in have]
print("missing:", len(missing))
for i in range(12):
    chunk = missing[i::12]
    with open("/tmp/vb12_%d.txt" % i, "w", encoding="utf-8") as f:
        f.write("\n".join(chunk))
print("split ok")
