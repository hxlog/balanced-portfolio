"""repositories_valuation 集成测试（真实 bp_mig_test）。

连接：81.71.158.239:5432/bp_mig_test，密码取 `.env` 的 PGPASSWORD（去除尾部空白）。
不可达时整文件 skip；测试数据统一用 ``T3REPO%`` 前缀并在前后清理，避免污染
同一测试库上的其他并行任务。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import psycopg
import pytest

from bp_api import repositories_valuation as repo

TEST_PREFIX = "T3REPO"
TEST_DB = {
    "host": "81.71.158.239",
    "port": 5432,
    "dbname": "bp_mig_test",
    "user": "postgres",
}


def _password() -> str:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        pytest.skip(".env 不存在，跳过 bp_mig_test 集成测试")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("PGPASSWORD="):
            return line.split("=", 1)[1].strip()
    pytest.skip("PGPASSWORD 不在 .env 中，跳过 bp_mig_test 集成测试")


def _connect() -> psycopg.Connection:
    try:
        return psycopg.connect(
            **TEST_DB,
            password=_password(),
            connect_timeout=8,
            autocommit=False,
        )
    except psycopg.Error as exc:  # pragma: no cover - 环境不可达时走 skip
        pytest.skip(f"bp_mig_test 不可达: {exc}")


def _purge(conn: psycopg.Connection) -> None:
    """删除本文件创建的全部测试数据（master 级联 daily/series/percentile）。"""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM bp_index_master WHERE index_code LIKE %s",
            (f"{TEST_PREFIX}%",),
        )
    conn.commit()


@pytest.fixture(scope="module")
def conn():
    connection = _connect()
    yield connection
    connection.rollback()
    connection.close()


@pytest.fixture(autouse=True)
def _clean(conn):
    conn.rollback()
    _purge(conn)
    yield
    conn.rollback()
    _purge(conn)


def _master_row(code: str, **overrides) -> dict:
    row = {
        "index_code": code,
        "market": "CSI",
        "wind_code": f"{code}.CSI",
        "name": f"Name {code}",
        "short_name": None,
        "index_type": "宽基",
        "publisher": "测试编制方",
        "base_date": date(2004, 12, 31),
        "base_point": 1000.0,
        "income_method": "价格指数",
        "weight_method": "市值加权",
        "intro": "测试指数",
        "is_active": True,
        "is_tracked": True,
    }
    row.update(overrides)
    return row


def _daily_row(code: str, trade_date: date, **overrides) -> dict:
    row = {
        "index_code": code,
        "trade_date": trade_date,
        "calc_src": "pingan_index",
        "pe_ttm": 20.0,
        "pb": 2.0,
        "dividend_yield_ttm": 3.0,
        "bond10y": 1.5,
        "erp": 1.5,
        "pe_basis": "vendor_default",
        "div_basis": "ttm",
        "level_pe": "中性",
        "is_primary": True,
        "raw": {"etf_fund": ["SH000001"]},
    }
    row.update(overrides)
    return row


def _pct_row(code: str, as_of: date, metric: str, pct: float, **overrides) -> dict:
    row = {
        "index_code": code,
        "as_of_date": as_of,
        "metric": metric,
        "window_key": "5y",
        "calc_src": "pingan_index",
        "pct": pct,
        "mean": 20.0,
        "sd": 2.0,
        "p20": 15.0,
        "p50": 20.0,
        "p80": 25.0,
        "min_value": 10.0,
        "max_value": 30.0,
        "sample_size": 300,
    }
    row.update(overrides)
    return row


class _CountingConn:
    """只暴露 cursor 的代理，用来断言 get_index_list 只发一条 SQL（无 N+1）。"""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn
        self.cursor_calls = 0

    def cursor(self, *args, **kwargs):
        self.cursor_calls += 1
        return self._conn.cursor(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _mock_conn():
    cur = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=cur)
    ctx.__exit__ = MagicMock(return_value=False)
    conn = MagicMock()
    conn.cursor.return_value = ctx
    return conn, cur


# ---------------------------------------------------------------------
# 1. upsert_index_master 幂等
# ---------------------------------------------------------------------
def test_upsert_index_master_is_idempotent(conn):
    code = f"{TEST_PREFIX}M1"
    assert repo.upsert_index_master(conn, [_master_row(code)]) == 1
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name, first_seen_at, updated_at FROM bp_index_master WHERE index_code=%s",
            (code,),
        )
        first_name, first_seen, first_updated = cur.fetchone()
    assert first_name == f"Name {code}"

    assert repo.upsert_index_master(
        conn, [_master_row(code, name="Renamed", publisher="新编制方")]
    ) == 1
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*), max(name), max(publisher), min(first_seen_at), min(updated_at) "
            "FROM bp_index_master WHERE index_code=%s",
            (code,),
        )
        count, name, publisher, seen_again, updated_again = cur.fetchone()
    assert count == 1
    assert name == "Renamed"
    assert publisher == "新编制方"
    assert seen_again == first_seen  # first_seen_at 不重写
    assert updated_again >= first_updated


# ---------------------------------------------------------------------
# 2. upsert_valuation_daily 幂等 + raw JSON 清洗
# ---------------------------------------------------------------------
def test_upsert_valuation_daily_is_idempotent_and_cleans_json(conn):
    code = f"{TEST_PREFIX}D1"
    repo.upsert_index_master(conn, [_master_row(code)])
    trade_date = date(2026, 11, 14)
    row = _daily_row(
        code,
        trade_date,
        pe_ttm=23.27,
        raw={
            "etf_fund": ["SH560080"],
            "nested": {"bad": float("nan")},
            "update_date": date(2026, 11, 14),
        },
    )
    assert repo.upsert_valuation_daily(conn, [row]) == 1
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pe_ttm, raw, captured_at FROM bp_index_valuation_daily "
            "WHERE index_code=%s AND trade_date=%s AND calc_src=%s",
            (code, trade_date, "pingan_index"),
        )
        pe_first, raw_first, captured_first = cur.fetchone()
    assert float(pe_first) == pytest.approx(23.27)
    assert raw_first["etf_fund"] == ["SH560080"]
    assert raw_first["nested"]["bad"] is None
    assert raw_first["update_date"] == "2026-11-14"

    row["pe_ttm"] = 25.5
    assert repo.upsert_valuation_daily(conn, [row]) == 1
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*), max(pe_ttm), min(captured_at) FROM bp_index_valuation_daily "
            "WHERE index_code=%s AND trade_date=%s AND calc_src=%s",
            (code, trade_date, "pingan_index"),
        )
        count, pe_second, captured_second = cur.fetchone()
    assert count == 1
    assert float(pe_second) == pytest.approx(25.5)
    assert captured_second == captured_first  # PiT：captured_at 不重写


# ---------------------------------------------------------------------
# 3. series / percentile upsert 幂等
# ---------------------------------------------------------------------
def test_upsert_series_and_percentiles_are_idempotent(conn):
    code = f"{TEST_PREFIX}S1"
    repo.upsert_index_master(conn, [_master_row(code)])
    series = [
        {
            "index_code": code,
            "trade_date": date(2021, 11, 19) + i * (date(2021, 12, 3) - date(2021, 11, 19)),
            "metric": "pe_ttm",
            "calc_src": "pingan_index",
            "value": 30.0 + i,
            "is_weekly": True,
        }
        for i in range(3)
    ]
    percentiles = [
        _pct_row(code, date(2026, 11, 14), "pe_ttm", 12.5),
        _pct_row(code, date(2026, 11, 14), "pb", 30.0),
    ]
    assert repo.upsert_valuation_series(conn, series) == 3
    assert repo.upsert_percentiles(conn, percentiles) == 2
    assert repo.upsert_valuation_series(conn, series) == 3
    assert repo.upsert_percentiles(conn, percentiles) == 2
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM bp_index_valuation_series WHERE index_code=%s", (code,)
        )
        assert cur.fetchone()[0] == 3
        cur.execute(
            "SELECT count(*) FROM bp_index_percentile WHERE index_code=%s", (code,)
        )
        assert cur.fetchone()[0] == 2


# ---------------------------------------------------------------------
# 4. fetch_series 过滤 / 排序 / Decimal→float
# ---------------------------------------------------------------------
def test_fetch_series_filters_and_orders(conn):
    code = f"{TEST_PREFIX}F1"
    repo.upsert_index_master(conn, [_master_row(code)])
    rows = [
        {"index_code": code, "trade_date": date(2021, 1, 1), "metric": "pe_ttm",
         "calc_src": "pingan_index", "value": 10.0, "is_weekly": True},
        {"index_code": code, "trade_date": date(2022, 1, 1), "metric": "pe_ttm",
         "calc_src": "pingan_index", "value": 20.0, "is_weekly": True},
        {"index_code": code, "trade_date": date(2023, 1, 1), "metric": "pe_ttm",
         "calc_src": "pingan_index", "value": 30.0, "is_weekly": True},
        {"index_code": code, "trade_date": date(2022, 1, 1), "metric": "pb",
         "calc_src": "pingan_index", "value": 2.0, "is_weekly": True},
        {"index_code": code, "trade_date": date(2022, 1, 1), "metric": "pe_ttm",
         "calc_src": "csindex_value", "value": 99.0, "is_weekly": False},
    ]
    repo.upsert_valuation_series(conn, rows)

    bounded = repo.fetch_series(
        conn, code, "pe_ttm", "pingan_index", date(2022, 1, 1), date(2023, 1, 1)
    )
    assert bounded == [(date(2022, 1, 1), 20.0), (date(2023, 1, 1), 30.0)]
    assert all(isinstance(value, float) for _, value in bounded)

    everything = repo.fetch_series(conn, code, "pe_ttm", "pingan_index", None, None)
    assert [d for d, _ in everything] == [
        date(2021, 1, 1),
        date(2022, 1, 1),
        date(2023, 1, 1),
    ]
    assert repo.fetch_series(conn, code, "pb", "pingan_index", None, None) == [
        (date(2022, 1, 1), 2.0)
    ]


# ---------------------------------------------------------------------
# 5. get_index_list 过滤 / 分页 / 单条 SQL
# ---------------------------------------------------------------------
def test_get_index_list_filters_paginates_and_uses_single_sql(conn):
    code1, code2, code3 = (
        f"{TEST_PREFIX}L1",
        f"{TEST_PREFIX}L2",
        f"{TEST_PREFIX}L3",
    )
    repo.upsert_index_master(conn, [
        _master_row(code1, name="Alpha Bank", index_type="行业"),
        _master_row(code2, name="Beta Tech", index_type="主题"),
        _master_row(code3, name="Gamma Broad", index_type="宽基"),
    ])
    repo.upsert_valuation_daily(conn, [
        _daily_row(code1, date(2026, 11, 14), pe_ttm=12.0, raw={"etf_fund": ["SH1"]}),
        _daily_row(code2, date(2026, 11, 14), pe_ttm=22.0, raw={"etf_fund": []}),
    ])
    repo.upsert_percentiles(conn, [
        _pct_row(code1, date(2026, 11, 14), "pe_ttm", 12.5),
        _pct_row(code1, date(2026, 11, 14), "pb", 30.0),
        _pct_row(code2, date(2026, 11, 14), "pe_ttm", 80.0),
        _pct_row(code2, date(2026, 11, 14), "pb", 70.0),
    ])

    counting = _CountingConn(conn)
    rows, total = repo.get_index_list(
        counting,
        query=TEST_PREFIX,
        index_type=None,
        only_with_etf=False,
        only_with_valuation=True,
        limit=10,
        offset=0,
    )
    assert counting.cursor_calls == 1  # 单条 SQL，无 N+1
    assert total == 2
    assert [r["index_code"] for r in rows] == [code1, code2]  # 默认按 index_code 排序
    assert rows[0]["has_valuation"] is True
    assert rows[0]["has_etf"] is True
    assert rows[1]["has_etf"] is False
    assert rows[0]["pe_percentile"] == pytest.approx(12.5)
    assert rows[0]["pb_percentile"] == pytest.approx(30.0)
    assert isinstance(rows[0]["pe_ttm"], float)

    filtered, filtered_total = repo.get_index_list(
        conn,
        query="Alpha",
        index_type=None,
        only_with_etf=False,
        only_with_valuation=False,
        limit=10,
        offset=0,
    )
    assert filtered_total == 1
    assert filtered[0]["index_code"] == code1

    typed, typed_total = repo.get_index_list(
        conn,
        query=TEST_PREFIX,
        index_type="主题",
        only_with_etf=False,
        only_with_valuation=False,
        limit=10,
        offset=0,
    )
    assert typed_total == 1
    assert typed[0]["index_code"] == code2

    etf_rows, etf_total = repo.get_index_list(
        conn,
        query=TEST_PREFIX,
        index_type=None,
        only_with_etf=True,
        only_with_valuation=False,
        limit=10,
        offset=0,
    )
    assert etf_total == 1
    assert etf_rows[0]["index_code"] == code1

    page, page_total = repo.get_index_list(
        conn,
        query=TEST_PREFIX,
        index_type=None,
        only_with_etf=False,
        only_with_valuation=True,
        limit=1,
        offset=1,
    )
    assert page_total == 2
    assert [r["index_code"] for r in page] == [code2]


# ---------------------------------------------------------------------
# 6. get_index_detail 404 / 组合返回
# ---------------------------------------------------------------------
def test_get_index_detail_returns_none_or_composed_detail(conn):
    assert repo.get_index_detail(conn, f"{TEST_PREFIX}MISSING") is None

    code = f"{TEST_PREFIX}DT1"
    repo.upsert_index_master(conn, [
        _master_row(code, name="Detail Index", publisher="Detail Publisher")
    ])
    repo.upsert_valuation_daily(conn, [
        _daily_row(
            code,
            date(2026, 11, 14),
            pe_ttm=23.27,
            pb=2.02,
            dividend_yield_ttm=3.68,
            bond10y=1.6123,
            erp=2.0677,
            roe_ttm=8.63,
            level_pe="低估",
            raw={
                "etf_fund": ["SH560080", "SZ159647"],
                "stock_list": [
                    {"stock_code": "000538", "name": "云南白药", "weight": 10.76}
                ],
            },
        )
    ])
    stats = [
        _pct_row(code, date(2026, 11, 14), metric, pct)
        for metric, pct in (
            ("pe_ttm", 12.5),
            ("pb", 30.0),
            ("dividend_yield_ttm", 40.0),
            ("erp", 55.0),
        )
    ]
    stats.append(_pct_row(code, date(2026, 11, 14), "pe_ttm", 15.0, window_key="10y"))
    repo.upsert_percentiles(conn, stats)

    detail = repo.get_index_detail(conn, code)
    assert detail is not None
    assert detail["name"] == "Detail Index"
    assert detail["publisher"] == "Detail Publisher"
    assert detail["pe_ttm"] == pytest.approx(23.27)
    assert detail["pb"] == pytest.approx(2.02)
    assert isinstance(detail["pe_ttm"], float)
    assert detail["tracker_etf_codes"] == ["SH560080", "SZ159647"]
    assert detail["constituents"][0]["stock_code"] == "000538"
    by_key = {
        (row["metric"], row["window_key"]): row for row in detail["percentiles"]
    }
    assert by_key[("pe_ttm", "5y")]["pct"] == pytest.approx(12.5)
    assert by_key[("pe_ttm", "10y")]["pct"] == pytest.approx(15.0)
    assert by_key[("erp", "5y")]["pct"] == pytest.approx(55.0)


# ---------------------------------------------------------------------
# 7. get_index_history 窗口 / 数据源选择
# ---------------------------------------------------------------------
def test_get_index_history_applies_window_and_source(conn):
    code = f"{TEST_PREFIX}H1"
    repo.upsert_index_master(conn, [_master_row(code)])
    repo.upsert_valuation_daily(conn, [_daily_row(code, date(2026, 11, 14))])
    repo.upsert_valuation_series(conn, [
        {"index_code": code, "trade_date": date(2019, 1, 1), "metric": "pe_ttm",
         "calc_src": "pingan_index", "value": 10.0, "is_weekly": True},
        {"index_code": code, "trade_date": date(2021, 6, 1), "metric": "pe_ttm",
         "calc_src": "pingan_index", "value": 20.0, "is_weekly": True},
        {"index_code": code, "trade_date": date(2023, 6, 1), "metric": "pe_ttm",
         "calc_src": "pingan_index", "value": 30.0, "is_weekly": False},
        {"index_code": code, "trade_date": date(2026, 6, 1), "metric": "pe_ttm",
         "calc_src": "pingan_index", "value": 40.0, "is_weekly": False},
        {"index_code": code, "trade_date": date(2026, 6, 1), "metric": "pe_ttm",
         "calc_src": "csindex_value", "value": 99.0, "is_weekly": False},
    ])

    five_years = repo.get_index_history(conn, code, "pe_ttm", "5y")
    assert [row["value"] for row in five_years] == [20.0, 30.0, 40.0]
    assert all(isinstance(row["value"], float) for row in five_years)
    assert five_years[0]["trade_date"] == date(2021, 6, 1)
    assert five_years[0]["is_weekly"] is True

    ten_years = repo.get_index_history(conn, code, "pe_ttm", "10y")
    assert [row["value"] for row in ten_years] == [10.0, 20.0, 30.0, 40.0]
    assert repo.get_index_history(conn, code, "pe_ttm", "all") == ten_years
    assert repo.get_index_history(conn, code, "pb", "5y") == []

    with pytest.raises(ValueError):
        repo.get_index_history(conn, code, "pe_ttm", "2y")


# ---------------------------------------------------------------------
# 8. get_market_overview 空表 + Decimal→float（bp_mig_test 无 54 号表，用 mock）
# ---------------------------------------------------------------------
def test_get_market_overview_empty_table_and_decimal_conversion():
    conn, cur = _mock_conn()
    cur.description = [
        SimpleNamespace(name=name)
        for name in (
            "board",
            "trade_date",
            "pe_median",
            "pe_equal",
            "pb_median",
            "pb_equal",
            "pct_pe",
            "pct_pb",
            "sample_size",
            "calc_src",
            "history_days",
        )
    ]
    cur.fetchall.return_value = []
    assert repo.get_market_overview(conn, None) == []

    cur.fetchall.return_value = [
        (
            "all",
            date(2026, 11, 13),
            Decimal("20.1234"),
            Decimal("22.2000"),
            Decimal("2.1000"),
            Decimal("2.3000"),
            Decimal("55.5000"),
            Decimal("44.4000"),
            5123,
            "self",
            88,
        )
    ]
    rows = repo.get_market_overview(conn, date(2026, 11, 13))
    assert len(rows) == 1
    assert rows[0]["board"] == "all"
    assert rows[0]["pe_median"] == pytest.approx(20.1234)
    assert isinstance(rows[0]["pe_median"], float)
    assert rows[0]["pct_pe"] == pytest.approx(55.5)
    assert rows[0]["sample_size"] == 5123
    assert rows[0]["history_days"] == 88
