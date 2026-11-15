import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.config import load_config
from bp_ingest.db import connect
cfg = load_config()
with connect(cfg.db) as conn, conn.cursor() as cur:
    cur.execute("select column_name from information_schema.columns where table_name='bp_index_valuation_series' order by ordinal_position")
    print("cols:", [r[0] for r in cur.fetchall()])
    cur.execute("select metric, count(*), min(trade_date), max(trade_date) from bp_index_valuation_series where index_code='000300' group by 1 order by 1")
    for r in cur.fetchall(): print(r)
