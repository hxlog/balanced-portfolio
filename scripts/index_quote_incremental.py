# -*- coding: utf-8 -*-
"""每日收盘后：521 只估值指数行情增量（单进程、限速、不重建清洗表）。

为什么要单独脚本：这些指数的日常更新只需 upsert 原始行情；
页面展示的收盘/涨跌/7日/52周 直接读 bp_index_quote_daily（指数点位本就是原币口径，
不需要清洗表的 CNY 折算），因此日常无需跑耗时的 rebuild_clean。
"""
import os
import sys
import time

sys.path.insert(0, "/opt/balanced-portfolio")
os.environ.setdefault("BP_REQUEST_INTERVAL", "0.25")
os.environ.setdefault("BP_REQUEST_JITTER", "0.35")
os.environ.setdefault("BP_MAX_RETRIES", "2")

from bp_ingest import ingest
from bp_ingest.config import load_config, setup_logging
from bp_ingest.db import connect

CHUNK = 60


def main() -> int:
    setup_logging()
    app = load_config()
    with connect(app.db) as conn, conn.cursor() as cur:
        cur.execute(
            "select symbol from bp_index_config"
            " where is_deleted = 0 and category = %s and index_code is not null"
            " order by symbol",
            ("index",),
        )
        symbols = [row[0] for row in cur.fetchall()]
    print("index symbols:", len(symbols), flush=True)
    started = time.time()
    for index in range(0, len(symbols), CHUNK):
        batch = symbols[index : index + CHUNK]
        try:
            results = ingest.run(app, symbols=batch, refresh_clean=False)
            ok = sum(1 for r in results if r.status in ("ok", "stale"))
        except Exception as exc:  # noqa: BLE001
            ok = -1
            print("batch failed:", type(exc).__name__, exc, flush=True)
        print(
            "progress %d/%d ok=%d elapsed=%.0fs"
            % (min(index + CHUNK, len(symbols)), len(symbols), ok, time.time() - started),
            flush=True,
        )
        time.sleep(1)
    print("incremental done in %.0fs" % (time.time() - started), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
