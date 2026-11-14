# -*- coding: utf-8 -*-
"""迁移测试脚手架：在临时库上验证 schema.sql + ddl/NN_*.sql 的正确性与幂等性。

用法：
    python scripts/test_migrations.py            # 重建临时库并全量验证
    python scripts/test_migrations.py --keep     # 保留临时库

安全：只操作 bp_mig_test 临时库；不触碰生产库任何数据。
"""
import argparse
import pathlib
import re
import sys

import psycopg

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEST_DB = "bp_mig_test"


def load_env() -> dict:
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
        if m:
            env[m.group(1)] = m.group(2).strip().strip('"')
    return env


def connect(env: dict, db: str, autocommit: bool = True):
    return psycopg.connect(
        host="81.71.158.239",
        port=5432,
        user=env.get("PGUSER", "postgres"),
        password=env.get("PGPASSWORD", ""),
        dbname=db,
        connect_timeout=15,
        autocommit=autocommit,
    )


def recreate_db(env: dict) -> None:
    with connect(env, "postgres") as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s", (TEST_DB,))
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        cur.execute(f"CREATE DATABASE {TEST_DB}")


def apply_sql(cur, path: pathlib.Path, label: str) -> None:
    sql = path.read_text(encoding="utf-8")
    cur.execute(sql, prepare=False)
    print(f"  [ok] {label}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    env = load_env()

    print("== 重建临时库 ==")
    recreate_db(env)

    with connect(env, TEST_DB) as conn, conn.cursor() as cur:
        print("== 基线 ==")
        apply_sql(cur, ROOT / "ddl" / "schema.sql", "schema.sql")

        migrations = sorted((ROOT / "ddl").glob("5[0-9]_*.sql"))
        if not migrations:
            print("  (无 5x 迁移)")
        for mig in migrations:
            print(f"== {mig.name} (x3 幂等) ==")
            for i in (1, 2, 3):
                try:
                    apply_sql(cur, mig, f"第 {i} 次")
                except Exception as exc:  # noqa: BLE001
                    print(f"  [FAIL] {mig.name} 第 {i} 次: {type(exc).__name__}: {str(exc)[:300]}")
                    return 1

        cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
        print(f"== 完成：public 表 {cur.fetchone()[0]} 张 ==")

    if not args.keep:
        with connect(env, "postgres") as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s", (TEST_DB,))
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        print("临时库已清理")
    return 0


if __name__ == "__main__":
    sys.exit(main())
