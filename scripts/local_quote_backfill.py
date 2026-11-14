"""本机全量行情回填 → 写生产库（服务器只保留增量）。

用法（Windows 本机）:
    .venv\\Scripts\\python.exe scripts\\local_quote_backfill.py

为什么在本机跑：521 只估值指数的首次全量拉取是一次性重任务，
在 3.6GB 的云服务器上并发会打满内存/IO（曾导致整机不可用），
因此全量回填放在本机，只把结果 upsert 进远程库；服务器只跑日常增量。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 本机直连（不走本机代理），写远程库
for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(key, None)
os.environ.setdefault("PGHOST", "81.71.158.239")
os.environ.setdefault("BP_REQUEST_INTERVAL", "0.25")
os.environ.setdefault("BP_REQUEST_JITTER", "0.35")
os.environ.setdefault("BP_MAX_RETRIES", "2")

from bp_ingest import ingest  # noqa: E402
from bp_ingest.config import load_config, setup_logging  # noqa: E402
from bp_ingest.db import connect  # noqa: E402

CHUNK = 40


def main() -> int:
    setup_logging()
    app = load_config()
    print("target db:", app.db.host, flush=True)
    with connect(app.db) as conn, conn.cursor() as cur:
        cur.execute(
            "select symbol from bp_index_config"
            " where is_deleted = 0 and category = %s and index_code is not null",
            ("index",),
        )
        all_syms = sorted({row[0] for row in cur.fetchall()})
        cur.execute(
            "select distinct symbol from bp_index_quote_daily where adjust = %s",
            ("bfq",),
        )
        have = {row[0] for row in cur.fetchall()}
    missing = [symbol for symbol in all_syms if symbol not in have]
    print("index configs:", len(all_syms), "have quotes:", len(have), "missing:", len(missing), flush=True)

    started = time.time()
    for index in range(0, len(missing), CHUNK):
        batch = missing[index : index + CHUNK]
        try:
            results = ingest.run(app, symbols=batch, refresh_clean=False)
            ok = sum(1 for item in results if item.status in ("ok", "stale"))
            print(
                "progress %d/%d ok=%d elapsed=%.0fs"
                % (min(index + CHUNK, len(missing)), len(missing), ok, time.time() - started),
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 - 单批失败继续
            print("batch failed:", type(exc).__name__, exc, flush=True)

    print("fetch done, rebuilding clean for %d symbols" % len(all_syms), flush=True)
    from bp_api.quant.cleaning import rebuild_clean

    with connect(app.db) as conn:
        conn.autocommit = False
        rows = rebuild_clean(conn, symbols=all_syms)
    print("clean rows:", rows, "total elapsed=%.0fs" % (time.time() - started), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
