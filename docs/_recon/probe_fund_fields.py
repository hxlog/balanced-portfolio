"""探测：平安跟踪基金接口全字段 + 中证官网 indicator 表字段（PS/ROE 可用性）。"""
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.valuation_pingan import fetch_tracker_funds
rows = fetch_tracker_funds(["SH510300"])
print("rows:", len(rows))
if rows:
    row = rows[0]
    keys = sorted(row.keys())
    print("keys:", keys)
    print("sample:", {k: row[k] for k in keys[:40]})

from bp_ingest.config import load_config
from bp_ingest.db import connect
app = load_config()
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("select column_name from information_schema.columns where table_name = %s order by ordinal_position", ("bp_index_csindex_value",))
    cols = [r[0] for r in cur.fetchall()]
    print("csindex_value columns:", cols)
