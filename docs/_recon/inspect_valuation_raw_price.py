import sys, json
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.config import load_config
from bp_ingest.db import connect
app = load_config()
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute(
        "SELECT index_code, trade_date, raw FROM bp_index_valuation_daily "
        "WHERE is_primary AND index_code IN (%s, %s) ORDER BY trade_date DESC LIMIT 2",
        ("930782", "000300"),
    )
    rows = cur.fetchall()
for code, d, raw in rows:
    keys = sorted(raw.keys()) if isinstance(raw, dict) else []
    print(code, d, "raw_keys:", keys)
    if isinstance(raw, dict):
        hits = {k: raw.get(k) for k in keys if any(t in k.lower() for t in ("close", "price", "index", "value", "point", "nav"))}
        print("  price-like:", hits)
