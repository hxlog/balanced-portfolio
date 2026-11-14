# -*- coding: utf-8 -*-
"""按编号应用单个迁移（幂等，显式事务 + statement_timeout）。

用法：
    python scripts/apply_migration.py ddl/51_quote_adjust_dimension.sql
    python scripts/apply_migration.py ddl/52_index_valuation_domain.sql --db postgres
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys
import time

import psycopg

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_env() -> dict:
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Z0-9_]+)=(.*)$", line)
        if m:
            env[m.group(1)] = m.group(2).strip().strip('"')
    return env


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("--db", default="postgres")
    parser.add_argument("--host", default="81.71.158.239")
    parser.add_argument("--timeout-ms", type=int, default=600_000)
    args = parser.parse_args()

    env = load_env()
    sql = (ROOT / args.file).read_text(encoding="utf-8")
    started = time.perf_counter()
    with psycopg.connect(
        host=args.host,
        port=int(env.get("PGPORT", "5432")),
        dbname=args.db,
        user=env.get("PGUSER", "postgres"),
        password=env.get("PGPASSWORD", ""),
        connect_timeout=15,
        autocommit=False,
    ) as conn, conn.cursor() as cur:
        cur.execute("select set_config('statement_timeout', %s, true)", (str(args.timeout_ms),))
        cur.execute(sql, prepare=False)
        conn.commit()
    print(f"[ok] {args.file} applied in {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
