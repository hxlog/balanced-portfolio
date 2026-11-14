# -*- coding: utf-8 -*-
"""按批回填行情（读 /tmp/vbatch_N.txt，避免 shell 引号问题）。"""
import sys
sys.path.insert(0, "/opt/balanced-portfolio")
from bp_ingest.config import load_config, setup_logging
from bp_ingest import ingest

batch = sys.argv[1]
with open("/tmp/vbatch_%s.txt" % batch, encoding="utf-8") as f:
    symbols = [line.strip() for line in f if line.strip()]
app = load_config()
setup_logging()
print("batch", batch, "symbols", len(symbols), flush=True)
results = ingest.run(app, symbols=symbols, refresh_clean=False)
ok = sum(1 for r in results if r.status in ("ok", "stale"))
print("batch", batch, "done ok", ok, "of", len(results), flush=True)
