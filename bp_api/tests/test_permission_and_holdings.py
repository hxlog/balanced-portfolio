"""资产编辑者权限(auth)与当天实际持仓(repositories)的单元测试。"""

from __future__ import annotations

from datetime import date

import pandas as pd

from bp_api import auth


def test_usercontext_has_can_manage_assets_default_false():
    ctx = auth.UserContext(1, "u@test.com", "user", False)
    assert ctx.can_manage_assets is False


def test_require_asset_editor_dependency_exists():
    assert callable(auth.require_asset_editor)


def test_actual_holdings_drift_computation():
    """漂移权重: 目标权重 × 逐日涨幅复利后归一, 日收益率/区间收益率正确。"""
    from bp_api.repositories import _build_actual_holdings

    # 两个持仓, 目标 0.5/0.5; A 三日累计 +21%, B 三日累计 -19%
    ret_rows = [
        ("A", "s", 0.1), ("B", "s", -0.1),
        ("A", "s", 0.1), ("B", "s", -0.1),
        ("A", "s", 0.0), ("B", "s", 0.0),
    ]

    class _Cur:
        def __init__(self, rows):
            self.rows = rows
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def execute(self, sql, params):
            return None
        def fetchall(self):
            return self.rows

    class _Conn:
        def cursor(self):
            return _Cur(ret_rows)

    name_map = {
        "A@s": {"symbol": "A", "source": "s", "display_name": "资产A"},
        "B@s": {"symbol": "B", "source": "s", "display_name": "资产B"},
    }
    quad_map = {"A@s": ["recession"], "B@s": ["overheat"]}
    out = _build_actual_holdings(
        _Conn(), {"A@s": 0.5, "B@s": 0.5}, name_map, quad_map,
        date(2026, 8, 1), date(2026, 8, 4),
    )
    assert out is not None
    by_key = {h["key"]: h for h in out["holdings"]}
    # A: (1+0.1)*(1+0.1)*(1+0)=1.21; B: (0.9)*(0.9)*(1)=0.81
    # 归一: A=1.21/(2.02), B=0.81/(2.02)
    assert by_key["A@s"]["weight"] == pytest_appx(1.21 / 2.02)
    assert by_key["B@s"]["weight"] == pytest_appx(0.81 / 2.02)
    assert abs(by_key["A@s"]["weight"] + by_key["B@s"]["weight"] - 1.0) < 1e-9
    # 最后一行的日收益 A=0, B=0
    assert by_key["A@s"]["day_return"] == 0.0
    assert by_key["A@s"]["period_return"] == pytest_appx(0.21)


def pytest_appx(v, eps=1e-6):
    import pytest as _pytest
    return _pytest.approx(v, rel=eps, abs=eps)