"""调度器取数范围与汇率依赖的回归测试(W6 / DDL 43-45)。

覆盖两个口径缺口 —— 它们都不会让任何断言变红, 只会让生产「悄悄少拉一类标的」:

1. **`fetch_active_configs(symbols=None)` 必须把 `fx_sina` 标的纳入。** 汇率标的是
   清洗期折算的**输入依赖**, 但 `is_selectable=FALSE` 使它们不进 /builder 可选池。
   若调度范围只看 `is_selectable = TRUE`, 汇率源就永远不会被增量拉取, 折算输入停更后
   所有外币资产会撞上 `_FX_TAIL_TOL_DAYS` 尾部护栏 → 组合净值静默停在上一个汇率日。
2. **`fetch_active_configs(symbols=[...])` 不得再加 is_selectable 过滤。** 管理员显式
   指定 symbol 时必须能拉到停用品种(手工补数场景), 否则单标的修复会被静默忽略。
3. **ingest 收尾的「清洗落后追赶」查询同样只看 is_selectable=TRUE。** 这是有意的:
   汇率源的清洗由折算时的按需读取驱动, 不靠追赶分支。此处固化该边界, 避免有人
   「顺手统一」两处谓词后让追赶分支去洗一堆展示口径标的。
"""

from __future__ import annotations

import re

from bp_ingest.db import fetch_active_configs


class _Cursor:
    def __init__(self, rows):
        self._rows = rows
        self.sql = ""
        self.params = None

    def execute(self, sql, params=None):
        self.sql = " ".join(sql.split())
        self.params = params

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conn:
    def __init__(self, rows=()):
        self.cur = _Cursor(list(rows))

    def cursor(self):
        return self.cur


def _row(symbol, source, selectable=None):  # noqa: ARG001 - selectable 只用于可读性
    return (1, symbol, source, "index", symbol, None, {})


def test_scheduler_scope_includes_fx_sources():
    """全量/调度取数必须包含 fx_sina, 否则折算输入停更。"""
    conn = _Conn([_row("USDCNY", "fx_sina"), _row("000300", "cn_index_em")])
    fetch_active_configs(conn, symbols=None)

    sql = conn.cur.sql
    assert "is_selectable = TRUE OR source = 'fx_sina'" in sql
    # symbols 为空时不得下发数组参数(全量走 WHERE 谓词, 不是 ANY(%s))
    assert conn.cur.params == []


def test_scheduler_scope_keeps_is_deleted_guard():
    """软删除永远是硬边界: 即便 source='fx_sina' 也不得复活。"""
    conn = _Conn([])
    fetch_active_configs(conn, symbols=None)
    assert "is_deleted = 0" in conn.cur.sql


def test_explicit_symbols_skip_selectable_filter():
    """管理员显式指定 symbol 时必须能拉停用品种, 不能被 is_selectable 二次过滤。"""
    conn = _Conn([_row("HSI", "hk_index_em")])
    out = fetch_active_configs(conn, symbols=["HSI"])

    sql = conn.cur.sql
    assert "symbol = ANY(%s)" in sql
    assert "is_selectable" not in sql          # 显式路径不看可选性
    assert conn.cur.params == [["HSI"]]
    assert [r.symbol for r in out] == ["HSI"]


def test_explicit_symbols_still_excludes_soft_deleted():
    conn = _Conn([])
    fetch_active_configs(conn, symbols=["HSI"])
    assert "is_deleted = 0" in conn.cur.sql


def test_config_rows_map_extra_params_default():
    """extra_params 为 NULL 时必须落成 {} 而非 None —— 下游到处 .get()。"""
    conn = _Conn([(7, "513500", "etf_em", "etf", "标普500ETF", None, None)])
    out = fetch_active_configs(conn, symbols=None)

    assert out[0].extra_params == {}
    assert out[0].config_id == 7
    assert out[0].has_data is False


def test_ingest_catchup_query_is_selectable_only():
    """追赶分支的谓词边界: 只看 is_selectable=TRUE(汇率源不靠它推进清洗)。"""
    src = (
        __import__("pathlib").Path(__file__).resolve().parents[2]
        / "bp_ingest" / "ingest.py"
    ).read_text(encoding="utf-8")
    # 取「清洗落后追赶」那段 SQL: 从 last_clean_date < last_raw_date 往前回溯到 SELECT
    idx = src.index("s.last_clean_date < s.last_raw_date")
    block = src[max(0, idx - 700): idx]
    assert "a.is_selectable = TRUE" in block
    assert "fx_sina" not in block          # 有意不把汇率源纳入追赶
    assert re.search(r"a\.is_deleted\s*=\s*0", block)
