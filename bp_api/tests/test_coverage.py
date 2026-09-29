"""成分行情覆盖判定单测 —— 「未覆盖」口径必须与回测引擎准入条件逐字一致。

核心不变式: compute_coverage 算出的 effective_start 与 run_backtest 的
effective_start 必须相等。两处若漂移, UI 就会报出引擎并不认可的风险(或漏报真实风险)。
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from bp_api.quant.backtest import run_backtest
from bp_api.quant.coverage import compute_coverage, effective_min_window, union_calendar


def _panel(n_days: int, late_start: dict[str, int] | None = None, start="2020-01-01"):
    """构造价格面板: 全体共享同一日历, 某些列从指定下标起才有真实收盘(此前 NaN)。"""
    dates = [d.date() for d in pd.bdate_range(start, periods=n_days)]
    late_start = late_start or {}
    cols = ["EARLY1@s", "EARLY2@s"] + list(late_start.keys())
    data = {}
    for i, c in enumerate(cols):
        vals = np.linspace(100.0, 120.0 + i, n_days)
        s = pd.Series(vals, index=dates)
        if c in late_start:
            s.iloc[: late_start[c]] = np.nan
        data[c] = s
    return pd.DataFrame(data), dates


def test_all_covered_when_full_history():
    prices, dates = _panel(200)
    cov = compute_coverage(prices, lookback=250, min_window=60)
    assert cov["effective_start"] == dates[61]
    assert all(a["covered_at_start"] for a in cov["assets"])
    for a in cov["assets"]:
        assert a["first_date"] == dates[0]
        assert a["last_date"] == dates[-1]
        # 全员从第一天有数据 → 首个参与日就是组合建仓日
        assert a["first_covered_date"] == cov["effective_start"]


def test_late_lister_is_the_only_uncovered():
    # lookback=60=min_window: 窗口 [k-60, k-1] 必须整段都有真实收盘。
    # LATE 从 index=120 才有数据 → 需 k-60 >= 120 → k >= 180 才首次准入。
    prices, dates = _panel(200, late_start={"LATE@s": 120})
    cov = compute_coverage(prices, lookback=60, min_window=60)

    assert cov["effective_start"] == dates[61]
    by_key = {a["key"]: a for a in cov["assets"]}

    assert by_key["EARLY1@s"]["covered_at_start"] is True
    late = by_key["LATE@s"]
    assert late["covered_at_start"] is False
    assert late["first_covered_date"] == dates[180]
    assert late["first_date"] == dates[120]
    assert late["first_date"] < late["first_covered_date"]


def test_has_data_but_not_enough_min_window():
    """有数据、但攒不够 min_window 个交易日 —— 引擎同样不给权重, 必须判为未覆盖。

    这正是「用 first_clean_date > effective_start 近似」会漏掉的一类:
    该标的 first_date 确实晚于 effective_start, 但即使等到它有数据,
    也要再攒满 min_window 才准入。
    """
    # 只在最后 30 天有数据: 永远攒不够 60 个交易日
    prices, dates = _panel(200, late_start={"LATE@s": 170})
    cov = compute_coverage(prices, lookback=250, min_window=60)
    by_key = {a["key"]: a for a in cov["assets"]}
    assert by_key["LATE@s"]["covered_at_start"] is False
    assert by_key["LATE@s"]["first_covered_date"] is None  # 全区间都没拿到过权重


def test_one_day_short_of_min_window_still_uncovered():
    """差一个交易日不足 min_window → 仍不算覆盖(边界不能 off-by-one)。

    LATE 从 index=n-60 起有数据, 到末日共 60 个交易日, 而 lookback=200 的窗口
    [k-199, k-1] 要求整段都有数据 —— 前半段永远缺 → 从未准入。
    """
    n = 200
    prices, dates = _panel(n, late_start={"LATE@s": n - 60})
    cov = compute_coverage(prices, lookback=200, min_window=60)
    late = {a["key"]: a for a in cov["assets"]}["LATE@s"]
    assert late["covered_at_start"] is False
    assert late["first_covered_date"] is None


def test_boundary_exactly_at_min_window_is_covered():
    """恰好攒满 min_window 个交易日 → 应当准入(与上一条互为边界)。

    lookback=60 时窗口是 [k-60, k-1](长度 60)。LATE 从 index=139 起有数据,
    末个可建仓日 k=199 的窗口 [139, 198] 才对 LATE 满员 → 首次准入 = 末日。
    """
    n = 200
    prices, dates = _panel(n, late_start={"LATE@s": n - 61})
    cov = compute_coverage(prices, lookback=60, min_window=60)
    late = {a["key"]: a for a in cov["assets"]}["LATE@s"]
    assert late["first_covered_date"] == dates[n - 1]


def test_no_lookahead_tampering_future_does_not_move_past_verdicts():
    """无未来函数: 篡改某日之后的价格, 不得改变该日之前的判定。"""
    prices, dates = _panel(200, late_start={"LATE@s": 120})
    base = compute_coverage(prices, lookback=250, min_window=60)

    tampered = prices.copy()
    cut = dates[150]
    tampered.loc[tampered.index > cut, :] *= 3.0  # 大幅篡改未来
    after = compute_coverage(tampered, lookback=250, min_window=60)

    assert after["effective_start"] == base["effective_start"]
    b = {a["key"]: a for a in base["assets"]}
    a2 = {a["key"]: a for a in after["assets"]}
    for k in b:
        assert a2[k]["first_covered_date"] == b[k]["first_covered_date"]
        assert a2[k]["covered_at_start"] == b[k]["covered_at_start"]


def test_effective_start_matches_engine():
    """compute_coverage 的 effective_start 必须与 run_backtest 逐字相等。"""
    dates = [d.date() for d in pd.bdate_range("2020-01-01", periods=150)]
    rng = np.random.default_rng(7)
    cols = ["EARLY1@s", "EARLY2@s", "LATE@s"]
    data = {}
    for i, c in enumerate(cols):
        rets = rng.normal(0.0003, 0.01, len(dates))
        s = pd.Series(100 * np.exp(np.cumsum(rets)), index=dates)
        if c == "LATE@s":
            s.iloc[:100] = np.nan
        data[c] = s
    prices = pd.DataFrame(data)
    bench = pd.Series(
        100 * np.exp(np.cumsum(rng.normal(0.0002, 0.012, len(dates)))), index=dates
    )

    res = run_backtest(
        prices=prices, benchmark=bench, quadrant_assets=None,
        method="all_risk_parity", ratio="sharpe", lookback=250, min_window=60,
        rebalance_band=0.05, risk_free=0.0, trading_days=244,
    )
    cov = compute_coverage(prices, lookback=250, min_window=60)

    assert cov["effective_start"] == res.effective_start
    # 引擎里 LATE 在 effective_start 那天权重为 0(未被覆盖)
    late = {a["key"]: a for a in cov["assets"]}["LATE@s"]
    assert late["covered_at_start"] is False


def test_effective_min_window_clamps():
    assert effective_min_window(60, 55) == 55   # min_window > lookback → 收紧
    assert effective_min_window(1, 156) == 2    # 下限 2
    assert effective_min_window(60, 156) == 60


def test_empty_and_too_short_panels_degrade_without_raising():
    empty = pd.DataFrame()
    out = compute_coverage(empty, lookback=156, min_window=60)
    assert out == {"effective_start": None, "assets": []}

    # 历史不足 min_window+2: 引擎会 raise, 这里降级返回而不是炸
    prices, _ = _panel(30)
    out2 = compute_coverage(prices, lookback=250, min_window=60)
    assert out2["effective_start"] is None
    assert all(a["covered_at_start"] is False for a in out2["assets"])
    assert all(a["first_covered_date"] is None for a in out2["assets"])


def test_union_calendar_merges_disjoint_dates():
    a = pd.Series([1.0, 2.0], index=[date(2020, 1, 2), date(2020, 1, 6)])
    b = pd.Series([1.0, 2.0], index=[date(2020, 1, 3), date(2020, 1, 7)])
    cal = union_calendar(pd.DataFrame({"a@s": a, "b@s": b}))
    assert cal == [date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6), date(2020, 1, 7)]


# ---------------------------------------------------------------------------
# preview_coverage: 变更对话框的覆盖预览(DB 读取层, 用 mock 连接验证分支逻辑)
# ---------------------------------------------------------------------------
def _stub_settings(min_window: int = 60):
    """ApiSettings 的轻量替身 —— preview_coverage 只读 settings.min_window。"""
    from types import SimpleNamespace
    return SimpleNamespace(min_window=min_window)


def _mock_conn():
    from unittest.mock import MagicMock
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cur


def _series_loader(series_by_key: dict):
    """替身 _load_series: 按 (symbol, source) 返回预设序列(缺省空序列 = 无清洗数据)。"""
    def _load(conn, symbol, source):
        return series_by_key.get(f"{symbol}@{source}", pd.Series(dtype="float64"))
    return _load


def test_preview_coverage_includes_assets_without_data(monkeypatch):
    """尚无清洗行情的资产(新加标的的典型状态)必须以 first_date=None 出现在结果里。

    这是 preview 端点存在的理由: load_price_panel 对这类资产会 raise, 但 UI 恰恰最需要
    在「刚加了一个还没数据的标的」时给出提示, 不能 500、也不能把该行悄悄丢掉。
    """
    from bp_api import repositories as repo

    dates = [d.date() for d in pd.bdate_range("2020-01-01", periods=200)]
    full = pd.Series(np.linspace(100, 120, 200), index=dates)
    monkeypatch.setattr(repo, "_load_series", _series_loader({
        "000300@cn_index_em": full,
        "HSI@hk_index_em": pd.Series(dtype="float64"),   # 无行情
    }))

    conn, _ = _mock_conn()
    rows = repo.preview_coverage(
        conn,
        [("000300", "cn_index_em"), ("HSI", "hk_index_em")],
        dates[61], 250, _stub_settings(),
    )

    assert [r["symbol"] for r in rows] == ["000300", "HSI"]  # 保持入参顺序
    by = {r["symbol"]: r for r in rows}
    assert by["000300"]["covered_at_start"] is True
    assert by["HSI"]["first_date"] is None and by["HSI"]["last_date"] is None
    assert by["HSI"]["first_covered_date"] is None
    assert by["HSI"]["covered_at_start"] is False


def test_preview_coverage_dedups_and_keeps_input_order(monkeypatch):
    """同一资产在多个象限重复出现(入参未去重) → 结果里只出现一次。"""
    from bp_api import repositories as repo

    dates = [d.date() for d in pd.bdate_range("2020-01-01", periods=200)]
    monkeypatch.setattr(repo, "_load_series", _series_loader({
        "000300@cn_index_em": pd.Series(np.linspace(100, 120, 200), index=dates),
        "HSI@hk_index_em": pd.Series(np.linspace(100, 90, 200), index=dates),
    }))

    conn, _ = _mock_conn()
    rows = repo.preview_coverage(
        conn,
        [("HSI", "hk_index_em"), ("000300", "cn_index_em"), ("HSI", "hk_index_em")],
        dates[61], 250, _stub_settings(),
    )
    assert [r["symbol"] for r in rows] == ["HSI", "000300"]


def test_preview_coverage_read_failure_degrades_to_no_data(monkeypatch):
    """单个资产的读取异常不得让整次预览失败(降级为「无数据」行)。"""
    from bp_api import repositories as repo

    dates = [d.date() for d in pd.bdate_range("2020-01-01", periods=200)]
    good = pd.Series(np.linspace(100, 120, 200), index=dates)

    def _load(conn, symbol, source):
        if symbol == "BOOM":
            raise RuntimeError("模拟读取失败")
        return good

    monkeypatch.setattr(repo, "_load_series", _load)
    conn, _ = _mock_conn()
    rows = repo.preview_coverage(
        conn, [("000300", "cn_index_em"), ("BOOM", "x")], dates[61], 250, _stub_settings()
    )
    by = {r["symbol"]: r for r in rows}
    assert by["000300"]["covered_at_start"] is True
    assert by["BOOM"]["first_date"] is None


def test_preview_coverage_empty_pairs():
    from bp_api import repositories as repo

    conn, _ = _mock_conn()
    assert repo.preview_coverage(conn, [], None, 156, _stub_settings()) == []
