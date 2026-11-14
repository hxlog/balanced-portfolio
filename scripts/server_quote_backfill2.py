# -*- coding: utf-8 -*-
"""服务器端指数行情回填 v2：优先级排序 + 快速跳过无效代码 + 单进程限速。"""
import os, re, sys, time
sys.path.insert(0, "/opt/balanced-portfolio")
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("BP_REQUEST_INTERVAL", "0.6")
os.environ.setdefault("BP_REQUEST_JITTER", "0.6")
os.environ.setdefault("BP_MAX_RETRIES", "1")
from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import connect
from bp_ingest import ingest

# 这些是平安口径里的供应商私有代码（富时/新交所/郑商所等），东财无对应 K 线，
# 反复重试只会阻塞整批，直接跳过（页面上它们只有估值没有行情）。
SKIP_PATTERNS = [
    r"^\d+L$", r"^FI", r"^SG", r"^DC", r"^CZ", r"^CICS", r"^INESC", r"^XI\d",
]
SKIP_RE = re.compile("|".join(SKIP_PATTERNS))

def priority(symbol: str) -> int:
    if re.match(r"^(000|399|930|H30|H11|H12|CN)", symbol):
        return 0
    if re.match(r"^[A-Z]{2,}$", symbol):
        return 2
    return 1

setup_logging()
app = load_config()
with connect(app.db) as conn, conn.cursor() as cur:
    cur.execute("select symbol from bp_index_config where is_deleted = 0 and category = %s and index_code is not null", ("index",))
    all_syms = sorted({row[0] for row in cur.fetchall()})
    cur.execute("select distinct symbol from bp_index_quote_daily where adjust = %s", ("bfq",))
    have = {row[0] for row in cur.fetchall()}
missing = [s for s in all_syms if s not in have]
usable = [s for s in missing if not SKIP_RE.search(s)]
skipped = len(missing) - len(usable)
usable.sort(key=lambda s: (priority(s), s))
print("missing", len(missing), "usable", len(usable), "skip", skipped, flush=True)
started = time.time()
ok_total = 0
for idx, symbol in enumerate(usable):
    try:
        results = ingest.run(app, symbols=[symbol], refresh_clean=False)
        ok = sum(1 for r in results if r.status in ("ok", "stale"))
        ok_total += ok
    except Exception as exc:  # noqa: BLE001
        ok = 0
    if (idx + 1) % 10 == 0 or idx + 1 == len(usable):
        print("progress %d/%d ok_total=%d elapsed=%.0fs last=%s" % (
            idx + 1, len(usable), ok_total, time.time() - started, symbol), flush=True)
print("done ok_total", ok_total, "elapsed %.0fs" % (time.time() - started), flush=True)
