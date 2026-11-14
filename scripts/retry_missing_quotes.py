# -*- coding: utf-8 -*-
"""每小时重试：只补缺失行情的指数（EM 封禁多为临时，解除后自动补齐）。"""
import os, sys, time
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("BP_REQUEST_INTERVAL", "1.2")
os.environ.setdefault("BP_REQUEST_JITTER", "1.5")
os.environ.setdefault("BP_MAX_RETRIES", "1")
from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import connect
from bp_ingest import ingest

BUDGET_SECONDS = 900  # 单次最多跑 15 分钟，避免长时间占用
CHUNK = 25

setup_logging()
app = load_config()
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("""
        select c.symbol from bp_index_config c
        where c.is_deleted = 0 and c.category = %s and c.index_code is not null
          and not exists (
            select 1 from bp_index_quote_daily q
            where q.symbol = c.symbol and q.adjust = %s
          )
        order by c.symbol
    """, ("index", "bfq"))
    missing = [row[0] for row in cur.fetchall()]
print("missing", len(missing), flush=True)
started = time.time()
ok_total = 0
for idx in range(0, len(missing), CHUNK):
    if time.time() - started > BUDGET_SECONDS:
        print("budget exhausted", flush=True)
        break
    batch = missing[idx:idx + CHUNK]
    try:
        results = ingest.run(app, symbols=batch, refresh_clean=False)
        ok_total += sum(1 for r in results if r.status in ("ok", "stale"))
    except Exception as exc:  # noqa: BLE001
        print("chunk fail:", type(exc).__name__, exc, flush=True)
    print("progress %d/%d ok=%d elapsed=%.0fs" % (
        min(idx + CHUNK, len(missing)), len(missing), ok_total, time.time() - started), flush=True)
print("retry done ok", ok_total, "elapsed %.0fs" % (time.time() - started), flush=True)
