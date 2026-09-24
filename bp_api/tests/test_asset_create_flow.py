"""新增资产(probe 结论分类 / 保存门禁 / 顺序调整权限)的单元测试。

覆盖三件事:
1. `classify_probe_error` 把「接口可达但本次被反爬/限频挡住」与「真实错误」分开 ——
   这是「暂时取不到全量日行情也要能保存」这条路的地基。
2. `asset_probe_ok` 门禁: unreachable 放行, invalid 与从未 probe 拦截。
3. `reorder_portfolios` 的权限口径: 示例组合的全局顺序只有管理员能改, 且
   payload 里缺失的 demo 也必须被编号, 否则新旧顺序会交错。
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
import requests

from bp_ingest import sources as src


# ---------------------------------------------------------------------
# classify_probe_error: unreachable vs invalid
# ---------------------------------------------------------------------
def test_unreachable_source_error_is_retryable():
    """整条降级链都拿不到数据 → unreachable(可重试, 允许保存)。"""
    exc = src.UnreachableSourceError("源 etf_em 及降级链均无法拉取 510300")
    assert src.classify_probe_error(exc) == "unreachable"


def test_unknown_source_is_invalid():
    """未知数据源(KeyError) 是配置错误, 必须拦截 —— 重试一万次也不会变。"""
    assert src.classify_probe_error(KeyError("未知 source: nope")) == "invalid"


def test_symbol_not_found_is_invalid():
    """全链正常应答却一致为空 = 代码不存在; 放行它会落一个永远没数据的死标的。"""
    assert src.classify_probe_error(src.SymbolNotFoundError("无 999999 的数据")) == "invalid"


@pytest.mark.parametrize(
    "exc",
    [
        requests.exceptions.ConnectionError("被反爬掐断"),
        requests.exceptions.Timeout("超时"),
        requests.exceptions.SSLError("握手失败"),
        ConnectionResetError("连接重置"),
    ],
)
def test_connection_class_errors_are_unreachable(exc):
    assert src.classify_probe_error(exc) == "unreachable"


def test_http_429_and_5xx_are_retryable_but_4xx_is_invalid():
    """429(限频) 与 5xx(上游抽风) 可重试; 404 之类的 4xx 说明代码写错了。"""

    def _http_error(status: int) -> requests.exceptions.HTTPError:
        resp = requests.Response()
        resp.status_code = status
        return requests.exceptions.HTTPError(response=resp)

    assert src.classify_probe_error(_http_error(429)) == "unreachable"
    assert src.classify_probe_error(_http_error(500)) == "unreachable"
    assert src.classify_probe_error(_http_error(404)) == "invalid"
    assert src.classify_probe_error(_http_error(400)) == "invalid"


def test_yf_rate_limit_is_unreachable():
    """Yahoo 429 抛自家 YFRateLimitError(非 requests 系), 必须同样归入可重试。"""
    try:
        from yfinance.exceptions import YFRateLimitError  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pytest.skip("未安装 yfinance")
    # YFRateLimitError 的 __init__ 不接受位置参数, 只能无参构造。
    assert src.classify_probe_error(YFRateLimitError()) == "unreachable"


def test_unknown_exception_defaults_to_invalid():
    """未知异常保守判 invalid: 宁可让用户看到错误, 也不放行一个可能写错的代码。"""
    assert src.classify_probe_error(ValueError("something odd")) == "invalid"


def test_fetch_all_sources_failed_raises_unreachable_subclass():
    """fetch_with_fallback 全链失败必须抛 UnreachableSourceError(RuntimeError 子类),
    保持既有 except RuntimeError 的调用方不破。"""
    assert issubclass(src.UnreachableSourceError, RuntimeError)


# ---------------------------------------------------------------------
# asset_probe_ok: 保存门禁放行条件
# ---------------------------------------------------------------------
@contextmanager
def _mock_conn(row):
    cur = MagicMock()
    cur.fetchone.return_value = row
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    yield conn, cur


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        # (last_probe_kind, legacy_verdict)
        (("ok", ""), True),
        (("unreachable", ""), True),      # 本次新增: 接口可达但被限频 → 允许保存
        (("invalid", ""), False),         # 代码写错 → 拦截
        (("", "ok"), True),               # 49 号迁移前的旧行, 成功 probe 过
        (("", ""), False),                # 从未 probe 成功
    ],
)
def test_asset_probe_ok_gate(row, expected):
    from bp_api.repositories import asset_probe_ok

    with _mock_conn(row) as (conn, _):
        assert asset_probe_ok(conn, "510300", "etf_em") is expected


def test_asset_probe_ok_no_status_row_blocks():
    from bp_api.repositories import asset_probe_ok

    with _mock_conn(None) as (conn, _):
        assert asset_probe_ok(conn, "510300", "etf_em") is False


# ---------------------------------------------------------------------
# reorder_portfolios: 权限与全局顺序完整性
# ---------------------------------------------------------------------
def _reorder_conn(portfolio_rows, extra_demo_ids=None):
    """构造 reorder 用的假连接: 第一次 SELECT 返回 portfolio_rows(三元组),
    管理员分支的第二次 SELECT(未列出的 demo)返回 extra_demo_ids。"""
    cur = MagicMock()
    cur.fetchall.side_effect = [
        [(pid, is_demo, owner) for pid, is_demo, owner in portfolio_rows],
        [(pid,) for pid in (extra_demo_ids or [])],
    ]
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cur


def test_reorder_non_admin_cannot_touch_demo_globally():
    """非管理员排 demo: 不写 bp_portfolio.display_order, 也不写个人表 —— 计入 skipped。"""
    from bp_api.repositories import reorder_portfolios

    conn, cur = _reorder_conn([(1, True, None), (7, False, 42)])
    out = reorder_portfolios(conn, user_id=42, ordered_ids=[1, 7], is_admin=False)

    assert out["demo_applied"] == []
    assert out["own_applied"] == [7]
    assert out["skipped"] == [1]
    sqls = " ".join(" ".join(c[0][0].split()) for c in cur.execute.call_args_list)
    assert "UPDATE bp_portfolio SET display_order" not in sqls


def test_reorder_non_admin_skips_other_users_portfolios():
    """别人的非 demo 组合既不可排也不报错 —— skipped 里如实回报, 不泄露存在性。"""
    from bp_api.repositories import reorder_portfolios

    conn, cur = _reorder_conn([(7, False, 42), (9, False, 99)])
    out = reorder_portfolios(conn, user_id=42, ordered_ids=[9, 7], is_admin=False)

    assert out["own_applied"] == [7]
    assert out["skipped"] == [9]
    inserts = [c for c in cur.execute.call_args_list if "bp_user_portfolio_order" in c[0][0]]
    assert len(inserts) == 1


def test_reorder_admin_writes_global_demo_order_and_appends_missing():
    """管理员排 demo: 写全局 display_order, 且 payload 未列出的 demo 也要续编到末尾。

    旧实现只对 payload 里出现的 demo 从 0 编号, 未出现的保留旧值 → 新旧编号交错。
    """
    from bp_api.repositories import reorder_portfolios

    conn, cur = _reorder_conn([(3, True, None), (1, True, None)], extra_demo_ids=[5])
    out = reorder_portfolios(conn, user_id=1, ordered_ids=[3, 1], is_admin=True)

    assert out["demo_applied"] == [3, 1, 5]
    updates = [
        c[0][1] for c in cur.execute.call_args_list
        if "UPDATE bp_portfolio SET display_order" in c[0][0]
    ]
    assert updates == [(0, 3), (1, 1), (2, 5)]


def test_reorder_admin_keeps_own_non_demo_in_user_scope():
    """管理员自己的非 demo 组合仍走个人顺序表(不因 is_admin 而写成全局)。"""
    from bp_api.repositories import reorder_portfolios

    conn, cur = _reorder_conn([(3, True, None), (8, False, 1)], extra_demo_ids=[])
    out = reorder_portfolios(conn, user_id=1, ordered_ids=[3, 8], is_admin=True)

    assert out["demo_applied"] == [3]
    assert out["own_applied"] == [8]
    assert out["skipped"] == []


def test_filter_demo_ids_empty_input_short_circuits():
    """空入参不查库 —— 所有调用都发生在登录后的热路径上。"""
    from bp_api.repositories import filter_demo_ids

    conn = MagicMock()
    assert filter_demo_ids(conn, []) == []
    conn.cursor.assert_not_called()


# ---------------------------------------------------------------------
# probe 端点: 结论分类写库 + 422 结构化 detail
# ---------------------------------------------------------------------
@contextmanager
def _probe_conn():
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=MagicMock())
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    yield conn


def _run_probe_with_fetch(fake_fetch):
    """驱动 probe_admin_asset, 返回 (捕获的 HTTPException 或 None, refresh 调用参数)。"""
    from unittest.mock import patch

    from fastapi import HTTPException

    from bp_api import main

    calls: list[dict] = []

    def _fake_refresh(conn, symbol, source, **kwargs):
        calls.append(kwargs)

    err = None
    with patch.object(main.db, "get_conn", _probe_conn), \
         patch.object(main.repo, "refresh_asset_status", _fake_refresh), \
         patch("bp_ingest.sources.fetch_with_fallback", fake_fetch):
        try:
            main.probe_admin_asset("etf_em", "510300", None)
        except HTTPException as e:  # noqa: PERF203
            err = e
    return err, calls


def test_probe_writes_ok_kind_on_success():
    """读到数据时落 last_probe_kind='ok' —— 保存门禁据此放行。"""
    from bp_api.tests.test_repositories import _probe_df

    err, calls = _run_probe_with_fetch(lambda *a, **k: _probe_df())
    assert err is None
    assert calls[-1]["probe_kind"] == "ok"


def test_probe_reports_unreachable_with_can_save_anyway():
    """反爬掐断 → 422 携带 {probe_kind: unreachable, can_save_anyway: true}, 前端据此给出口。"""
    def _boom(*a, **k):
        raise src.UnreachableSourceError("源 etf_em 及降级链均无法拉取 510300")

    err, calls = _run_probe_with_fetch(_boom)
    assert err is not None and err.status_code == 422
    assert err.detail["probe_kind"] == "unreachable"
    assert err.detail["can_save_anyway"] is True
    assert calls[-1]["probe_kind"] == "unreachable"


def test_probe_reports_invalid_without_escape_hatch():
    """未知数据源 → 422 且 can_save_anyway=false; 不给「仍要保存」出口。"""
    def _boom(*a, **k):
        raise KeyError("未知 source: nope")

    err, calls = _run_probe_with_fetch(_boom)
    assert err is not None and err.status_code == 422
    assert err.detail["probe_kind"] == "invalid"
    assert err.detail["can_save_anyway"] is False


def test_probe_empty_frame_is_invalid_not_unreachable():
    """代码不存在时部分源返回空表而不抛错 —— 必须归 invalid, 否则会落库一个死标的。"""
    import pandas as pd

    err, calls = _run_probe_with_fetch(lambda *a, **k: pd.DataFrame())
    assert err is not None and err.status_code == 422
    assert err.detail["probe_kind"] == "invalid"
    assert calls[-1]["probe_kind"] == "invalid"
