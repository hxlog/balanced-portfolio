# -*- coding: utf-8 -*-
"""迁移测试脚手架：在临时库上验证 schema.sql + ddl/NN_*.sql 的正确性与幂等性。

用法（安全约束 P1-4）：
    # 显式环境变量（二选一）：
    #   1) BP_MIG_TEST_DSN="host=... dbname=bp_mig_test user=... password=..."
    #   2) BP_MIG_TEST=1 PGHOST=... PGPASSWORD=... [PGPORT/PGUSER/PGDATABASE]
    BP_MIG_TEST=1 PGHOST=127.0.0.1 PGPASSWORD=*** python scripts/test_migrations.py
    python scripts/test_migrations.py --keep     # 保留临时库

安全：
- **不硬编码 host、不从仓库 .env 读取生产口令**：只读显式环境变量；
- 目标库名必须像测试库（包含 test/mig），否则拒绝执行；可用
  BP_MIG_TEST_DBNAME 指定专用临时库名（默认 bp_mig_test）；
- 只操作该临时库；不触碰生产库任何数据。
"""
import argparse
import os
import pathlib
import sys

import psycopg

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_TEST_DB = "bp_mig_test"
_TRUTHY = {"1", "true", "yes", "on"}


def _conninfo() -> dict:
    """从显式环境变量解析连接参数；未启用/缺变量时给出可操作错误。"""
    raw = (os.environ.get("BP_MIG_TEST_DSN") or "").strip()
    if raw:
        return dict(psycopg.conninfo.conninfo_to_dict(raw))
    if (os.environ.get("BP_MIG_TEST") or "").strip().lower() not in _TRUTHY:
        raise SystemExit(
            "未启用迁移测试：请显式设置 BP_MIG_TEST_DSN，或 BP_MIG_TEST=1 + "
            "PGHOST/PGPASSWORD（不从 .env 读取口令、不硬编码 host）"
        )
    missing = [name for name in ("PGHOST", "PGPASSWORD") if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"BP_MIG_TEST=1 但缺少显式环境变量: {', '.join(missing)}")
    info = {
        "host": os.environ["PGHOST"],
        "password": os.environ["PGPASSWORD"],
        "user": os.environ.get("PGUSER") or "postgres",
    }
    if os.environ.get("PGPORT"):
        info["port"] = os.environ["PGPORT"]
    return info


def _test_dbname(info: dict) -> str:
    name = (
        os.environ.get("BP_MIG_TEST_DBNAME")
        or info.get("dbname")
        or DEFAULT_TEST_DB
    )
    name = str(name).strip()
    if not ("test" in name.lower() or "mig" in name.lower()):
        raise SystemExit(f"拒绝操作 dbname={name!r}：目标库名必须包含 test/mig（防误连生产库）")
    return name


def connect(dbname: str | None = None, autocommit: bool = True):
    info = _conninfo()
    target = dbname or _test_dbname(info)
    if dbname is not None and not ("test" in dbname.lower() or "mig" in dbname.lower()):
        # 维护库（postgres）仅用于 DROP/CREATE 测试库，允许
        target = dbname
    info["dbname"] = target
    return psycopg.connect(
        **{key: value for key, value in info.items() if value},
        connect_timeout=15,
        autocommit=autocommit,
    )


def recreate_db() -> None:
    test_db = _test_dbname(_conninfo())
    with connect("postgres") as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s",
            (test_db,),
        )
        cur.execute(f'DROP DATABASE IF EXISTS "{test_db}"')
        cur.execute(f'CREATE DATABASE "{test_db}"')


def apply_sql(cur, path: pathlib.Path, label: str) -> None:
    sql = path.read_text(encoding="utf-8")
    cur.execute(sql, prepare=False)
    print(f"  [ok] {label}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--from", dest="from_num", type=int, default=51,
                        help="从该编号迁移起验证（默认 51；只验证新迁移可传 75）")
    args = parser.parse_args()
    test_db = _test_dbname(_conninfo())

    print(f"== 重建临时库 {test_db} ==")
    recreate_db()

    with connect(test_db) as conn, conn.cursor() as cur:
        print("== 基线 ==")
        apply_sql(cur, ROOT / "ddl" / "schema.sql", "schema.sql")

        migrations = sorted(
            p for p in (ROOT / "ddl").glob("[5-9][0-9]_*.sql")
            if int(p.name.split("_", 1)[0]) >= args.from_num
        )
        if not migrations:
            print("  (无可验证迁移)")
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
        with connect("postgres") as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s",
                (test_db,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{test_db}"')
        print("临时库已清理")
    return 0


if __name__ == "__main__":
    sys.exit(main())
