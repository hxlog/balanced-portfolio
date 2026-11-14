# -*- coding: utf-8 -*-
"""指数行情回填 v3：分块调用 ingest（避免失败重扫的 32s 静默拖慢整体）。"""
import os, re, sys, time
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("BP_REQUEST_INTERVAL", "0.45")
os.environ.setdefault("BP_REQUEST_JITTER", "0.5")
os.environ.setdefault("BP_MAX_RETRIES", "1")
from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import connect
from bp_ingest import ingest

SKIP_RE = re.compile(r"^\d+L$|^FI|^SG|^DC|^CZ|^CICS|^INESC|^XI\d")
CHUNK = 20

setup_logging()
app = load_config()
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("select symbol from bp_index_config where is_deleted = 0 and category = %s and index_code is not null", ("index",))
    all_syms = sorted({row[0] for row in cur.fetchall()})
    cur.execute("select distinct symbol from bp_index_quote_daily where adjust = %s", ("bfq",))
    have = {row[0] for row in cur.fetchall()}
missing = [s for s in all_syms if s not in have and not SKIP_RE.search(s)]
print("missing usable", len(missing), flush=True)
started = time.time()
ok_total = 0
for idx in range(0, len(missing), CHUNK):
    batch = missing[idx:idx + CHUNK]
    try:
        results = ingest.run(app, symbols=batch, refresh_clean=False)
        ok_total += sum(1 for r in results if r.status in ("ok", "stale"))
    except Exception as exc:  # noqa: BLE001
        print("chunk fail:", type(exc).__name__, exc, flush=True)
    print("progress %d/%d ok_total=%d elapsed=%.0fs" % (
        min(idx + CHUNK, len(missing)), len(missing), ok_total, time.time() - started), flush=True)
print("done ok_total", ok_total, "elapsed %.0fs" % (time.time() - started), flush=True)
