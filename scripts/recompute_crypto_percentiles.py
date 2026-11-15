"""重算 Binance 合约分位并失效 API 缓存（回补完成后调用）。"""
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
from bp_ingest.config import load_config
from bp_ingest.crypto_futures import compute_percentiles
from bp_ingest.db import connect

app = load_config()
with connect(app.db) as conn:
    result = compute_percentiles(conn)
    conn.commit()
print("percentiles:", result)
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("select window_days, count(*), min(sample_size), max(sample_size) from bp_crypto_futures_percentile group by 1 order by 1")
    for row in cur.fetchall():
        print("window", row)

try:
    from bp_api.crypto import invalidate_crypto_cache
    invalidate_crypto_cache()
    print("cache invalidated")
except Exception as exc:
    print("cache invalidate skipped:", type(exc).__name__, exc)
