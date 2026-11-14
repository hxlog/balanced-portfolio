# -*- coding: utf-8 -*-
"""12 批并行回填 runner（低重试）。"""
import os, sys
sys.path.insert(0, "/opt/balanced-portfolio")
os.environ.setdefault("BP_MAX_RETRIES", "1")
from bp_ingest.config import load_config, setup_logging
from bp_ingest import ingest
batch = sys.argv[1]
with open("/tmp/vb12_%s.txt" % batch, encoding="utf-8") as f:
    symbols = [line.strip() for line in f if line.strip()]
app = load_config()
setup_logging()
print("batch", batch, "symbols", len(symbols), flush=True)
try:
    results = ingest.run(app, symbols=symbols, refresh_clean=False)
    ok = sum(1 for r in results if r.status in ("ok", "stale"))
    print("batch", batch, "done ok", ok, "of", len(results), flush=True)
except Exception as exc:
    print("batch", batch, "failed:", type(exc).__name__, exc, flush=True)
