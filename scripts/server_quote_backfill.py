# -*- coding: utf-8 -*-
"""服务器端顺序回填（低并发、分块、带进度与内存自检）。"""
import os, sys, time
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("BP_REQUEST_INTERVAL", "0.25")
os.environ.setdefault("BP_REQUEST_JITTER", "0.35")
os.environ.setdefault("BP_MAX_RETRIES", "2")
from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import connect
from bp_ingest import ingest

CHUNK = 50

def mem_available_mb():
    with open("/proc/meminfo", encoding="utf-8") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    return -1

setup_logging()
app = load_config()
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("select symbol from bp_index_config where is_deleted = 0 and category = %s and index_code is not null", ("index",))
    all_syms = sorted({row[0] for row in cur.fetchall()})
    cur.execute("select distinct symbol from bp_index_quote_daily where adjust = %s", ("bfq",))
    have = {row[0] for row in cur.fetchall()}
missing = [s for s in all_syms if s not in have]
print("index configs:", len(all_syms), "have:", len(have), "missing:", len(missing), flush=True)
started = time.time()
for index in range(0, len(missing), CHUNK):
    batch = missing[index:index + CHUNK]
    try:
        results = ingest.run(app, symbols=batch, refresh_clean=False)
        ok = sum(1 for r in results if r.status in ("ok", "stale"))
    except Exception as exc:
        ok = -1
        print("batch failed:", type(exc).__name__, exc, flush=True)
    print("progress %d/%d ok=%d memFreeMB=%d elapsed=%.0fs" % (
        min(index + CHUNK, len(missing)), len(missing), ok, mem_available_mb(), time.time() - started), flush=True)
    time.sleep(2)
print("fetch done", flush=True)
