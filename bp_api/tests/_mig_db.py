"""bp_mig_test 集成测试连接助手（P1-4）。

安全约束（code review P1-4）：

- **不硬编码生产 host/IP**，**不从仓库 `.env` 读取生产口令**；
- 只有显式设置环境变量才会连接测试库，否则 `pytest.skip`，保证 CI（无 DB）全绿：
  - `BP_MIG_TEST_DSN`：完整 DSN，例如
    `host=127.0.0.1 port=5432 dbname=bp_mig_test user=postgres password=...`；
  - 或 `BP_MIG_TEST=1` + `PGHOST` + `PGPASSWORD`（可选 `PGPORT`/`PGUSER`/`PGDATABASE`，
    缺省 dbname=bp_mig_test，user=postgres）。
- 目标库名必须像测试库（包含 `test` 或 `mig`），否则 skip，避免误连生产/共享库。

测试自身仍必须遵守「只删除/回滚自己创建的数据」：优先在单事务内 seed + 断言 +
`rollback()`，不要 `commit()` 后再做无 WHERE 的整表 DELETE。
"""
from __future__ import annotations

import os

import pytest

_TRUTHY = {"1", "true", "yes", "on"}


def mig_test_enabled() -> bool:
    """是否显式启用了 bp_mig_test 集成测试。"""
    if (os.environ.get("BP_MIG_TEST_DSN") or "").strip():
        return True
    return (os.environ.get("BP_MIG_TEST") or "").strip().lower() in _TRUTHY


def _looks_like_test_db(dbname: str) -> bool:
    name = (dbname or "").strip().lower()
    return "test" in name or "mig" in name


def mig_test_dsn() -> str:
    """解析 DSN；未显式启用 / 缺变量 / 目标不是测试库时 pytest.skip。"""
    if not mig_test_enabled():
        pytest.skip(
            "未显式设置 BP_MIG_TEST_DSN 或 BP_MIG_TEST=1（+PGHOST/PGPASSWORD），"
            "跳过 bp_mig_test 集成测试"
        )
    import psycopg

    raw = (os.environ.get("BP_MIG_TEST_DSN") or "").strip()
    if raw:
        dsn_text = raw
    else:
        missing = [name for name in ("PGHOST", "PGPASSWORD") if not os.environ.get(name)]
        if missing:
            pytest.skip(
                f"BP_MIG_TEST=1 但缺少显式环境变量 {', '.join(missing)}，"
                "跳过 bp_mig_test 集成测试"
            )
        kwargs: dict[str, str] = {
            "host": os.environ["PGHOST"],
            "password": os.environ["PGPASSWORD"],
            "dbname": os.environ.get("PGDATABASE") or "bp_mig_test",
            "user": os.environ.get("PGUSER") or "postgres",
        }
        port = os.environ.get("PGPORT")
        if port:
            kwargs["port"] = port
        dsn_text = psycopg.conninfo.make_conninfo(**kwargs)

    info = psycopg.conninfo.conninfo_to_dict(dsn_text)
    dbname = str(info.get("dbname") or "")
    if not _looks_like_test_db(dbname):
        pytest.skip(
            f"dbname={dbname!r} 不像测试库（需包含 test/mig），"
            "跳过以免误连生产/共享库"
        )
    return dsn_text


def connect_mig_test(**kwargs):
    """连接显式配置的 bp_mig_test；未启用/不可达时 pytest.skip。

    默认 `autocommit=False`：测试应在单事务内 seed + 断言并 `rollback()`。
    """
    import psycopg

    dsn_text = mig_test_dsn()
    kwargs.setdefault("connect_timeout", 8)
    kwargs.setdefault("autocommit", False)
    try:
        return psycopg.connect(dsn_text, **kwargs)
    except psycopg.Error as exc:  # pragma: no cover - 环境不可达时走 skip
        pytest.skip(f"bp_mig_test 不可达: {exc}")
