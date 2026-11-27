"""MVI 计算修复的回归测试（需求 6）。

覆盖：
- rolling_percentile 的 NaN 语义：当期 NaN 不得落成 0 分位，窗口内 NaN 不参与计数；
- to_weekly 按 A 股交易日历重采样：非交易日（周日）点映射到该周最后交易日，
  输出不含周末/非交易日，且交易日点优先于映射点；
- build_factor_panel：缺因子的周直接剔除（不补 0），不产生 NaN 分位；
- compute_mvi_rows 勾稽：MVI = 100 - cheap_score、风险分 = 0.55 波动分位 + 0.45 回撤分位；
- 构造「周末缺失 + 因子缺口」序列：断言无 NaN 引起的 0 分位跳变，且日变 < 5 占比 > 99%；
- bp_mig_test 集成：从库读取 -> 周频锚点均为交易日 + 勾稽（不可达自动 skip）。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.compute_mvi import (
    FACTORS,
    ROLL_WEEKS,
    WEIGHTS,
    align_weekly_risk,
    build_factor_panel,
    compute_mvi_rows,
    compute_risk_series,
    rolling_percentile,
    to_weekly,
    zone_of,
)


def _trading_days(start: str = "2021-01-04", end: str = "2026-12-31") -> pd.DatetimeIndex:
    return pd.bdate_range(start, end)


def _synthetic_frames(
    codes: list[str],
    weeks: int = 180,
    *,
    drift: float = 0.0005,
    noise: float = 0.01,
    seed: int = 7,
    weekend_only: bool = True,
) -> dict[str, pd.DataFrame]:
    """构造 5 只宽基的估值序列：周频 bar 落在周日（复刻平安 didHis/peBar 口径）。"""
    rng = np.random.default_rng(seed)
    fridays = pd.date_range("2022-01-07", periods=weeks, freq="W-FRI")
    frames: dict[str, pd.DataFrame] = {}
    for index, code in enumerate(codes):
        pe = 20.0 + index * 3 + np.cumsum(rng.normal(drift, noise, weeks))
        dates = fridays + pd.Timedelta(days=2) if weekend_only else fridays
        frame = pd.DataFrame(
            {
                "pe_ttm": pe,
                "pb": pe / 10.0,
                "dividend_yield_ttm": 3.0 + np.cumsum(rng.normal(0, 0.002, weeks)),
                "erp": 1.5 + np.cumsum(rng.normal(0, 0.002, weeks)),
            },
            index=pd.DatetimeIndex(dates),
        )
        frames[code] = frame
    return frames


def test_rolling_percentile_nan_current_is_nan_not_zero():
    series = pd.Series(
        [10.0, 11.0, 12.0, np.nan, 9.0],
        index=pd.bdate_range("2024-01-01", periods=5),
    )
    pct = rolling_percentile(series, window=5, min_periods=1)
    # 当期 NaN 必须是 NaN（旧实现会算成 0 分位）
    assert np.isnan(pct.iloc[3])
    assert not np.isnan(pct.iloc[4])
    # 有效样本 [10,11,12,9]，9 最小 -> 25 分位（旧实现 NaN 当期会输出 0）
    assert pct.iloc[4] == pytest.approx(25.0)


def test_rolling_percentile_skips_nan_in_window_and_respects_min_periods():
    series = pd.Series(
        [1.0, np.nan, 3.0, 4.0], index=pd.bdate_range("2024-01-01", periods=4)
    )
    pct = rolling_percentile(series, window=4, min_periods=2)
    assert np.isnan(pct.iloc[0])  # 有效样本 1 < 2，不伪造分位
    assert np.isnan(pct.iloc[1])
    # 第 3 个点：有效样本 [1,3]，1 与 3 中 3 最大 -> 100
    assert pct.iloc[2] == pytest.approx(100.0)
    # 第 4 个点：有效样本 [1,3,4]，4 最大 -> 100
    assert pct.iloc[3] == pytest.approx(100.0)


def test_to_weekly_maps_non_trading_day_to_last_trading_day():
    trading_days = _trading_days("2024-01-01", "2024-01-31")
    friday = pd.Timestamp("2024-01-05")
    sunday = pd.Timestamp("2024-01-07")
    next_sunday = pd.Timestamp("2024-01-14")  # 该周只有周日 bar（复刻平安周频口径）
    series = pd.Series(
        [100.0, 101.0, 102.0],
        index=pd.DatetimeIndex([friday, sunday, next_sunday]),
    )
    weekly = to_weekly(series, trading_days)
    # 同周交易日点优先（周五 100 而不是周日 101）；只有周日 bar 的周映射到 1/12
    assert list(weekly.index) == [friday, pd.Timestamp("2024-01-12")]
    assert weekly.iloc[0] == pytest.approx(100.0)
    assert weekly.iloc[1] == pytest.approx(102.0)
    assert all(day in trading_days for day in weekly.index)
    assert all(day.dayofweek < 5 for day in weekly.index)


def test_to_weekly_prefers_trading_day_value_over_weekend_bar():
    trading_days = _trading_days("2024-01-01", "2024-01-31")
    friday = pd.Timestamp("2024-01-05")
    sunday = pd.Timestamp("2024-01-07")
    series = pd.Series([7.0, 9.0], index=pd.DatetimeIndex([friday, sunday]))
    weekly = to_weekly(series, trading_days)
    assert len(weekly) == 1
    assert weekly.iloc[0] == pytest.approx(7.0)


def test_build_factor_panel_drops_incomplete_weeks_without_zero_percentile():
    trading_days = _trading_days("2021-01-01", "2026-12-31")
    codes = [f"00000{i}" for i in range(1, 6)]
    frames = _synthetic_frames(codes)
    # 人为制造缺口：某只指数最后 20 周的股息率缺失（旧实现会算成 0 分位）
    for frame in frames.values():
        frame.loc[frame.index[-20:], "dividend_yield_ttm"] = np.nan
    panel = build_factor_panel(frames, trading_days)
    assert not panel.empty
    assert not panel.isna().any().any()
    assert all(day.weekday() < 5 for day in panel.index)
    # 缺因子的周必须被整行剔除，而不是以 0 分位参与 MVI
    assert len(panel) <= len(frames[codes[0]]) - 20


def test_compute_mvi_rows_reconciliation():
    index = pd.DatetimeIndex(["2026-11-13", "2026-11-20", "2026-11-27"])
    panel = pd.DataFrame(
        {
            "cheap_pe": [60.0, 65.0, 70.0],
            "cheap_pb": [50.0, 50.0, 50.0],
            "div_pct": [40.0, 45.0, 50.0],
            "erp_pct": [30.0, 30.0, 30.0],
            "roe_pct": [80.0, 80.0, 80.0],
        },
        index=index,
    )
    risk = pd.DataFrame(
        {
            "vol_pct": [40.0, 50.0, 60.0],
            "dd_pct": [20.0, 10.0, 0.0],
        },
        index=index,
    )
    risk["risk_score"] = 0.55 * risk["vol_pct"] + 0.45 * risk["dd_pct"]
    rows = compute_mvi_rows(panel, risk)
    assert len(rows) == 3
    for row in rows:
        assert row["mvi"] + row["cheap_score"] == pytest.approx(100.0, abs=0.011)
        expected_cheap = sum(
            WEIGHTS[factor] * panel.loc[pd.Timestamp(row["as_of"]), factor]
            for factor in FACTORS
        )
        assert row["cheap_score"] == pytest.approx(expected_cheap, abs=0.011)
        assert row["zone"] == zone_of(row["mvi"])
        risk_row = risk.loc[pd.Timestamp(row["as_of"])]
        assert row["risk_score"] == pytest.approx(
            0.55 * risk_row["vol_pct"] + 0.45 * risk_row["dd_pct"], abs=0.011
        )
    assert rows[-1]["mvi"] < rows[0]["mvi"]  # 因子分位走高（更便宜）-> MVI 走低


def test_weekend_missing_sequence_has_no_nan_zero_jump():
    """构造含周末缺失的序列：MVI 不得因 NaN 变 0 分位跳变，日变 <5 占比 >99%。"""
    trading_days = _trading_days("2021-01-01", "2026-12-31")
    codes = [f"00000{i}" for i in range(1, 6)]
    frames = _synthetic_frames(codes, weeks=200)
    # 复刻真实脏数据：周日周频 bar 只有 pe/pb，股息率/ERP 缺失；
    # 同周周五的日频点才带股息/ERP（真实库里每个交易日 ingest 都会写当日点）。
    for code, frame in frames.items():
        fridays = pd.DatetimeIndex([day - pd.Timedelta(days=2) for day in frame.index])
        daily = pd.DataFrame(
            {
                "pe_ttm": frame["pe_ttm"].to_numpy(),
                "pb": frame["pb"].to_numpy(),
                "dividend_yield_ttm": 3.0 + np.linspace(0, 0.2, len(fridays)),
                "erp": 1.5 + np.linspace(0, 0.1, len(fridays)),
            },
            index=fridays,
        )
        frame.loc[:, "dividend_yield_ttm"] = np.nan
        frame.loc[:, "erp"] = np.nan
        frames[code] = pd.concat([frame, daily]).sort_index()
    panel = build_factor_panel(frames, trading_days)
    assert not panel.empty
    assert not panel.isna().any().any()
    assert all(day.weekday() < 5 for day in panel.index)

    rows = compute_mvi_rows(panel, pd.DataFrame())
    mvi = pd.Series(
        [row["mvi"] for row in rows],
        index=pd.to_datetime([row["as_of"] for row in rows]),
    )
    changes = mvi.diff().dropna().abs()
    assert (changes < 5).mean() > 0.99
    # 旧实现会在「周日行」把缺失因子算成 0 分位，导致 MVI 约 +38 的假跳变
    assert changes.max() < 10



# ---------------------------------------------------------------------------
# DB 集成（显式环境变量启用；未设置时 skip）
#
# P1-4：不硬编码 host、不从 .env 读生产口令；只有显式设置
# BP_MIG_TEST_DSN（或 BP_MIG_TEST=1 + PGHOST/PGPASSWORD）才会连接。
# 所有 seed/写入都在**单事务内**完成并 rollback：不删除/清空共享表数据（尤其不再
# 无 WHERE 清空 bp_market_valuation_index，也不删除 bp_trading_calendar 共享行）。
# ---------------------------------------------------------------------------

from bp_api.tests._mig_db import connect_mig_test

PREFIX = "T80MVI"


def _insert_master(conn, codes: list[str]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO bp_index_master (index_code, market, name, is_active, is_tracked)"
            " SELECT unnest(%s::text[]), 'CSI', unnest(%s::text[]), TRUE, TRUE"
            " ON CONFLICT (index_code) DO NOTHING",
            (codes, codes),
        )


def _insert_calendar(conn) -> None:
    """补齐测试窗口的工作日（共享行 ON CONFLICT 不覆盖；rollback 只回滚新插入行）。"""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO bp_trading_calendar (market, cal_date, is_trading)"
            " SELECT 'CN', d::date, TRUE FROM generate_series("
            " DATE '2021-01-04', DATE '2026-12-31', INTERVAL '1 day') d"
            " WHERE extract(isodow FROM d) <= 5"
            " ON CONFLICT (market, cal_date) DO NOTHING"
        )


def _build_quotes(
    symbol: str,
    start: pd.Timestamp,
    count: int,
    *,
    name: str = "沪深300",
):
    from bp_ingest.db import QuoteRow

    quotes = []
    for offset in range(count):
        day = start - pd.Timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        quotes.append(
            QuoteRow(
                trade_date=day.date(),
                symbol=symbol,
                source="cn_index_em",
                category="index",
                name=name,
                open=None,
                high=None,
                low=None,
                close=4000.0 + offset * 0.5,
                volume=None,
                amount=None,
                turnover_rate=None,
                pct_change=None,
                adjust="bfq",
            )
        )
    return quotes


def test_db_roundtrip_weekly_calendar_and_reconciliation():
    from bp_ingest.db import upsert_quotes
    from scripts.compute_mvi import (
        load_factor_series,
        load_panel,
        load_risk_prices,
        load_trading_days,
    )

    conn = connect_mig_test()
    codes = [f"{PREFIX}{i}" for i in range(1, 6)]
    risk_symbol = PREFIX + "300"
    try:
        _insert_master(conn, codes)
        _insert_calendar(conn)
        frames = _synthetic_frames(codes)
        with conn.cursor() as cur:
            for code, frame in frames.items():
                for trade_date, row in frame.iterrows():
                    for metric in ("pe_ttm", "pb", "dividend_yield_ttm", "erp"):
                        cur.execute(
                            "INSERT INTO bp_index_valuation_series"
                            " (index_code, trade_date, metric, calc_src, value, is_weekly)"
                            " VALUES (%s, %s, %s, 'pingan_index', %s, TRUE)"
                            " ON CONFLICT (index_code, trade_date, metric, calc_src)"
                            " DO UPDATE SET value = EXCLUDED.value",
                            (code, trade_date.date(), metric, float(row[metric])),
                        )
        upsert_quotes(conn, _build_quotes(risk_symbol, pd.Timestamp("2026-11-27"), 400))

        # 不 commit：同一连接内验证，finally rollback（不污染共享测试库）
        trading_days = load_trading_days(conn)
        assert len(trading_days) > 500
        raw = load_factor_series(conn, codes)
        assert len(raw) == 5
        panel = load_panel(conn, codes)
        assert not panel.empty
        assert all(day.weekday() < 5 for day in panel.index)
        risk = compute_risk_series(load_risk_prices(conn, risk_symbol))
        assert not risk.empty
        risk_weekly = align_weekly_risk(risk, panel.index)
        rows = compute_mvi_rows(panel, risk_weekly)
        assert len(rows) == len(panel)
        for row in rows:
            assert row["mvi"] + row["cheap_score"] == pytest.approx(100.0, abs=0.011)
    finally:
        # 只回滚，不做任何 DELETE（所有写入都是本测试事务内的临时数据）
        conn.rollback()
        conn.close()


def test_main_full_recompute_writes_weekly_rows(monkeypatch):
    """端到端：main() 全量重算 -> 只写周频（交易日）行 + 勾稽正确。

    全程复用测试连接的同一事务（monkeypatch connect），结束后 rollback：
    main 内部的 replace（DELETE+INSERT bp_market_valuation_index）不会落到共享库。
    """
    from contextlib import contextmanager
    from types import SimpleNamespace

    import numpy as np

    from bp_ingest.db import upsert_quotes
    from bp_api import repositories_valuation as repo
    from scripts import compute_mvi

    conn = connect_mig_test()
    codes = [f"{PREFIX}{i}" for i in range(1, 6)]
    risk_symbol = PREFIX + "300"
    try:
        week_count = 254  # 覆盖到 2026-11，保证风险分（约 2 年历史）有值
        sundays = pd.date_range("2022-01-02", periods=week_count, freq="W-SUN")
        _insert_master(conn, codes)
        _insert_calendar(conn)
        series_rows = []
        for index, code in enumerate(codes):
            pe = np.linspace(15.0 + index, 25.0 + index, week_count)
            pb = pe / 10.0
            for position, day in enumerate(sundays):
                for metric, value in (
                    ("pe_ttm", pe[position]),
                    ("pb", pb[position]),
                    ("dividend_yield_ttm", 2.5 + 0.001 * position),
                    ("erp", 1.4 + 0.001 * position),
                ):
                    series_rows.append(
                        {
                            "index_code": code,
                            "trade_date": day.date(),
                            "metric": metric,
                            "calc_src": "pingan_index",
                            "value": float(value),
                            "is_weekly": True,
                        }
                    )
        repo.upsert_valuation_series(conn, series_rows)
        upsert_quotes(
            conn,
            _build_quotes(risk_symbol, pd.Timestamp("2026-11-27"), 750, name="Test Risk"),
        )

        @contextmanager
        def fake_connect(db):
            # main() 的读写都用同一个测试连接（同一事务）；退出不 commit
            yield conn

        monkeypatch.setattr(compute_mvi, "connect", fake_connect)
        monkeypatch.setattr(
            compute_mvi, "load_config", lambda: SimpleNamespace(db=object())
        )
        exit_code = compute_mvi.main(proxies=codes, risk_symbol=risk_symbol)
        assert exit_code == 0

        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*), min(as_of), max(as_of) FROM bp_market_valuation_index"
            )
            count, first_date, last_date = cur.fetchone()
            assert count > 100
            assert first_date is not None
            assert last_date == sundays[-1].date() - pd.Timedelta(days=2)
            cur.execute(
                "SELECT count(*) FROM bp_market_valuation_index"
                " WHERE extract(isodow FROM as_of) > 5"
            )
            assert int(cur.fetchone()[0]) == 0  # 绝无周末/非交易日点
            cur.execute(
                "SELECT count(*) FROM bp_market_valuation_index"
                " WHERE abs(mvi + cheap_score - 100) > 0.011"
            )
            assert int(cur.fetchone()[0]) == 0
            cur.execute(
                "SELECT count(*) FROM bp_market_valuation_index"
                " WHERE risk_score IS NOT NULL AND risk_factors IS NOT NULL"
            )
            assert int(cur.fetchone()[0]) > 0
    finally:
        # 只回滚，不做整表 DELETE：共享库里的真实 MVI 历史不受影响
        conn.rollback()
        conn.close()


# ---------------------------------------------------------------------------
# 空数据 / min 行数安全（P1-5；纯 mock，不连库）
# ---------------------------------------------------------------------------
def test_main_empty_rows_refuses_to_replace_history(monkeypatch):
    """rows 为空时必须报错退出且**不调用 replace**（不清空历史）。"""
    import pandas as pd

    from scripts import compute_mvi

    calls: list = []
    connections: list = []
    monkeypatch.setattr(compute_mvi, "load_panel", lambda conn, proxies=None: pd.DataFrame())
    monkeypatch.setattr(
        compute_mvi, "load_risk_series", lambda conn, symbol=None: pd.DataFrame()
    )
    monkeypatch.setattr(
        compute_mvi, "replace_market_valuation_index",
        lambda conn, rows: calls.append(("replace", rows)) or len(rows),
    )

    @contextmanager
    def fake_connect(db):
        connections.append(db)
        yield object()

    monkeypatch.setattr(compute_mvi, "load_config", lambda: SimpleNamespace(db=object()))
    monkeypatch.setattr(compute_mvi, "connect", fake_connect)
    exit_code = compute_mvi.main()
    assert exit_code != 0
    assert calls == [], "空 rows 不得 replace/清空历史"
    assert len(connections) == 1, "空 rows 只允许建读连接，不得进入写库阶段"


def test_main_rejects_too_few_rows_before_replace(monkeypatch):
    """新数据低于 min 行数时：直接失败退出，不 replace、不 DELETE。"""
    import pandas as pd
    from types import SimpleNamespace

    from scripts import compute_mvi

    calls: list = []
    monkeypatch.setattr(compute_mvi, "load_panel", lambda conn, proxies=None: pd.DataFrame({"x": [1.0]}))
    monkeypatch.setattr(
        compute_mvi, "load_risk_series", lambda conn, symbol=None: pd.DataFrame()
    )
    monkeypatch.setattr(
        compute_mvi, "compute_mvi_rows",
        lambda panel, risk_weekly: [{"as_of": date(2026, 1, 2), "mvi": 50.0}],
    )
    monkeypatch.setattr(compute_mvi, "min_expected_rows", lambda: 52)
    monkeypatch.setattr(
        compute_mvi, "replace_market_valuation_index",
        lambda conn, rows: calls.append(("replace", rows)) or len(rows),
    )

    connections: list = []

    @contextmanager
    def fake_connect(db):
        connections.append(db)
        yield object()

    monkeypatch.setattr(compute_mvi, "load_config", lambda: SimpleNamespace(db=object()))
    monkeypatch.setattr(compute_mvi, "connect", fake_connect)
    exit_code = compute_mvi.main()
    assert exit_code != 0
    assert calls == []
    assert len(connections) == 1, "rows 不足时只允许建读连接，不得进入写库阶段"
