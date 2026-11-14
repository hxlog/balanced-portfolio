"""valuation_ingest 编排测试（真实 bp_mig_test + fake fetch，不联网）。

覆盖：主数据/日频/序列/分位落库、幂等、单指数失败隔离、as_of 覆盖、
周频解析与 ERP 同日计算、空抓取与整体抓取异常。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import psycopg
import pytest

from bp_ingest.valuation_ingest import run_valuation_ingest

TEST_PREFIX = "T3ING"
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


def _detail_row(
    code: str,
    name: str,
    *,
    pe: str = "23.27",
    pb: str = "2.02",
    dividend: str = "3.68%",
    bond10: str = "1.6123",
    etf_fund: str | None = "SH560080,SZ159647",
    update_date: str = "20261114",
    pe_bar: str = "20211119,30|20211126,31|20211203,32",
    pb_bar: str = "20211119,3|20211126,3.1|20211203,3.2",
    did_his: str = "20211119,2|20211126,2.1|20211203,2.2",
) -> dict:
    return {
        "code": f"ZI{code}",
        "indexName": name,
        "indexType": "宽基",
        "peRatio": pe,
        "pbRatio": pb,
        "dividendRate": dividend,
        "bond10": bond10,
        "peLevel": "较低",
        "pbLevel": "中等",
        "dividendLevel": "较高",
        "roe": "8.63",
        "updateDate": update_date,
        "peBar": pe_bar,
        "pbBar": pb_bar,
        "didHis": did_his,
        "etfFund": etf_fund,
        "stockList": "SH600000,Test Bank,10.0%",
        "isPb": "1",
    }


_BOND10_ROWS = [
    {"tradeDt": "20211119", "bAnalyield": "2.5"},
    {"tradeDt": "20211126", "bAnalyield": "2.6"},
    {"tradeDt": "20211203", "bAnalyield": "2.7"},
    {"tradeDt": "20261114", "bAnalyield": "1.6123"},
]

_DESCRIPTIONS = [
    {
        "code": "{TEST-GUID-1}",
        "sInfoWindCode": "T3ING1.CSI",
        "sInfoIndexBaseper": "20041231",
        "sInfoIndexBasept": "1000",
        "sInfoPublisher": "测试编制方",
        "sInfoIncomeMethod": "价格指数",
        "weightTypeName": "市值加权",
    }
]


def _fake_fetch(details: list[dict], descriptions: list[dict] | None = None):
    def _fetch() -> dict:
        return {
            "index_universe": [],
            "index_detail": details,
            "index_description": descriptions or [],
            "index_valuation_meta": [],
            "index_performance": [],
            "bond10_history": _BOND10_ROWS,
            "tracker_funds": [],
        }

    return _fetch


def _count(conn: psycopg.Connection, table: str, code: str | None = None) -> int:
    sql = f"SELECT count(*) FROM {table}"
    params: tuple = ()
    if code is not None:
        if code.endswith("%"):
            sql += " WHERE index_code LIKE %s"
        else:
            sql += " WHERE index_code=%s"
        params = (code,)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return int(cur.fetchone()[0])


# ---------------------------------------------------------------------
# 1. 两指数全链路落库（行数 + 字段口径）
# ---------------------------------------------------------------------
def test_ingest_writes_master_daily_series_and_percentiles(conn):
    details = [
        _detail_row("T3ING1", "Test Index One"),
        _detail_row("T3ING2", "Test Index Two", pe="15.5", pb="1.5"),
    ]
    summary = run_valuation_ingest(
        conn, as_of=date(2026, 11, 14), fetch=_fake_fetch(details, _DESCRIPTIONS)
    )

    assert summary["as_of"] == date(2026, 11, 14)
    assert summary["indices"] == 2
    assert summary["valuation_rows"] == 2
    assert summary["series_rows"] == 32
    assert summary["percentile_rows"] == 24
    assert summary["errors"] == []
    assert isinstance(summary["duration_ms"], int) and summary["duration_ms"] >= 0

    prefix = f"{TEST_PREFIX}%"
    assert _count(conn, "bp_index_master", prefix) == 2
    assert _count(conn, "bp_index_valuation_daily", prefix) == 2
    assert _count(conn, "bp_index_valuation_series", prefix) == 32
    assert _count(conn, "bp_index_percentile", prefix) == 24

    with conn.cursor() as cur:
        cur.execute(
            "SELECT pe_ttm, pb, dividend_yield_ttm, bond10y, erp, pe_basis, div_basis, "
            "       level_pe, level_pb, level_dividend, is_primary, calc_src, raw "
            "FROM bp_index_valuation_daily WHERE index_code=%s AND trade_date=%s",
            ("T3ING1", date(2026, 11, 14)),
        )
        (
            pe,
            pb,
            dividend,
            bond10y,
            erp,
            pe_basis,
            div_basis,
            level_pe,
            level_pb,
            level_dividend,
            is_primary,
            calc_src,
            raw,
        ) = cur.fetchone()
    assert float(pe) == pytest.approx(23.27)
    assert float(pb) == pytest.approx(2.02)
    assert float(dividend) == pytest.approx(3.68)
    assert float(bond10y) == pytest.approx(1.6123)
    assert float(erp) == pytest.approx(2.0677, abs=1e-6)
    assert pe_basis == "vendor_default"
    assert div_basis == "ttm"
    assert (level_pe, level_pb, level_dividend) == ("低估", "中性", "高估")
    assert is_primary is True
    assert calc_src == "pingan_index"
    assert raw["etf_fund"] == ["SH560080", "SZ159647"]
    assert raw["stock_list"][0]["stock_code"] == "600000"
    assert raw["update_date"] == "2026-11-14"

    with conn.cursor() as cur:
        cur.execute(
            "SELECT sample_size, pct FROM bp_index_percentile "
            "WHERE index_code=%s AND as_of_date=%s AND metric='pe_ttm' AND window_key='5y'",
            ("T3ING1", date(2026, 11, 14)),
        )
        sample_size, pct = cur.fetchone()
    assert sample_size == 4  # 3 个周频点 + 当日日频点
    assert pct is None  # 样本 < 120，不得伪造分位


# ---------------------------------------------------------------------
# 2. 重复跑幂等（行数、captured_at 不变）
# ---------------------------------------------------------------------
def test_ingest_is_idempotent(conn):
    details = [
        _detail_row("T3ING1", "Test Index One"),
        _detail_row("T3ING2", "Test Index Two"),
    ]
    first = run_valuation_ingest(
        conn, as_of=date(2026, 11, 14), fetch=_fake_fetch(details)
    )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT captured_at FROM bp_index_valuation_daily "
            "WHERE index_code='T3ING1' AND trade_date=%s",
            (date(2026, 11, 14),),
        )
        captured_first = cur.fetchone()[0]

    second = run_valuation_ingest(
        conn, as_of=date(2026, 11, 14), fetch=_fake_fetch(details)
    )
    for key in ("indices", "valuation_rows", "series_rows", "percentile_rows"):
        assert second[key] == first[key]
    assert second["errors"] == []
    prefix = f"{TEST_PREFIX}%"
    assert _count(conn, "bp_index_master", prefix) == 2
    assert _count(conn, "bp_index_valuation_daily", prefix) == 2
    assert _count(conn, "bp_index_valuation_series", prefix) == first["series_rows"]
    assert _count(conn, "bp_index_percentile", prefix) == first["percentile_rows"]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT captured_at FROM bp_index_valuation_daily "
            "WHERE index_code='T3ING1' AND trade_date=%s",
            (date(2026, 11, 14),),
        )
        assert cur.fetchone()[0] == captured_first

    # 编排层不得 commit：调用方 rollback 后应全部消失。
    conn.rollback()
    assert _count(conn, "bp_index_master", f"{TEST_PREFIX}%") == 0
    assert _count(conn, "bp_index_valuation_daily", f"{TEST_PREFIX}%") == 0


# ---------------------------------------------------------------------
# 3. 单指数失败隔离
# ---------------------------------------------------------------------
def test_ingest_isolates_single_index_failure(conn):
    details = [
        _detail_row("T3ING1", "Good One"),
        # 未知字母前缀现在归入 GLOBAL（不再丢弃），因此用「缺名称」的行验证失败隔离。
        {"code": "SH600000", "indexName": "", "updateDate": "20261114"},
        _detail_row("T3ING2", "Good Two"),
    ]
    summary = run_valuation_ingest(
        conn, as_of=date(2026, 11, 14), fetch=_fake_fetch(details)
    )

    assert summary["indices"] == 2
    assert summary["valuation_rows"] == 2
    assert len(summary["errors"]) == 1
    assert summary["errors"][0].startswith("600000")
    assert _count(conn, "bp_index_master", f"{TEST_PREFIX}%") == 2
    assert _count(conn, "bp_index_master", "600000") == 0
    assert _count(conn, "bp_index_valuation_daily", "BADCODE") == 0
    assert _count(conn, "bp_index_valuation_daily", "T3ING1") == 1
    assert _count(conn, "bp_index_valuation_daily", "T3ING2") == 1


# ---------------------------------------------------------------------
# 4. as_of 覆盖写入口径
# ---------------------------------------------------------------------
def test_ingest_as_of_override_controls_trade_date(conn):
    as_of = date(2026, 1, 5)
    summary = run_valuation_ingest(
        conn,
        as_of=as_of,
        fetch=_fake_fetch([_detail_row("T3ING1", "Test Index One")]),
    )
    assert summary["as_of"] == as_of
    with conn.cursor() as cur:
        cur.execute(
            "SELECT trade_date FROM bp_index_valuation_daily WHERE index_code='T3ING1'"
        )
        assert [r[0] for r in cur.fetchall()] == [as_of]
        cur.execute(
            "SELECT distinct as_of_date FROM bp_index_percentile WHERE index_code='T3ING1'"
        )
        assert [r[0] for r in cur.fetchall()] == [as_of]
        cur.execute(
            "SELECT count(*) FROM bp_index_valuation_series "
            "WHERE index_code='T3ING1' AND trade_date > %s",
            (as_of,),
        )
        assert cur.fetchone()[0] == 0  # 未来序列不得写入


# ---------------------------------------------------------------------
# 5. 周频解析、ERP 同日、等级映射
# ---------------------------------------------------------------------
def test_ingest_parses_weekly_series_and_same_day_erp(conn):
    run_valuation_ingest(
        conn,
        as_of=date(2026, 11, 14),
        fetch=_fake_fetch(
            [
                _detail_row(
                    "T3ING1",
                    "Test Index One",
                    # 负 PE 是脏点：与日频 CHECK 同口径，不得写入序列
                    pe_bar="20211119,30|20211126,31|20211203,32|20211210,-5",
                )
            ]
        ),
    )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT trade_date, value, is_weekly FROM bp_index_valuation_series "
            "WHERE index_code='T3ING1' AND metric='pe_ttm' ORDER BY trade_date"
        )
        pe_rows = [(d, float(v), w) for d, v, w in cur.fetchall()]
        assert pe_rows == [
            (date(2021, 11, 19), 30.0, True),
            (date(2021, 11, 26), 31.0, True),
            (date(2021, 12, 3), 32.0, True),
            (date(2026, 11, 14), 23.27, False),
        ]

        cur.execute(
            "SELECT value, is_weekly FROM bp_index_valuation_series "
            "WHERE index_code='T3ING1' AND metric='erp' ORDER BY trade_date"
        )
        erp_rows = [(float(v), w) for v, w in cur.fetchall()]
        assert erp_rows == [
            (-0.5, True),  # 2.0 - 2.5
            (-0.5, True),  # 2.1 - 2.6
            (-0.5, True),  # 2.2 - 2.7
            (2.0677, False),  # 3.68 - 1.6123
        ]


# ---------------------------------------------------------------------
# 6. 主数据批量失败时降级为逐指数隔离
# ---------------------------------------------------------------------
def test_ingest_master_batch_failure_falls_back_to_per_index(conn, monkeypatch):
    import bp_ingest.valuation_ingest as ingest

    real_upsert = ingest.upsert_index_master
    calls = {"count": 0}

    def flaky_upsert(connection, rows):
        calls["count"] += 1
        if calls["count"] == 1 and len(rows) > 1:
            raise RuntimeError("batch boom")
        return real_upsert(connection, rows)

    monkeypatch.setattr(ingest, "upsert_index_master", flaky_upsert)
    summary = run_valuation_ingest(
        conn,
        as_of=date(2026, 11, 14),
        fetch=_fake_fetch(
            [
                _detail_row("T3ING1", "Test Index One"),
                _detail_row("T3ING2", "Test Index Two"),
            ]
        ),
    )

    assert summary["indices"] == 2
    assert any("master batch" in error for error in summary["errors"])
    prefix = f"{TEST_PREFIX}%"
    assert _count(conn, "bp_index_master", prefix) == 2
    assert _count(conn, "bp_index_valuation_daily", prefix) == 2


# ---------------------------------------------------------------------
# 7. 空抓取 / 整体抓取异常
# ---------------------------------------------------------------------
def test_ingest_empty_and_fetch_failure(conn):
    empty = run_valuation_ingest(
        conn, as_of=date(2026, 11, 14), fetch=_fake_fetch([])
    )
    assert empty["indices"] == 0
    assert empty["valuation_rows"] == 0
    assert empty["series_rows"] == 0
    assert empty["percentile_rows"] == 0
    assert empty["errors"] == []
    assert isinstance(empty["duration_ms"], int)
    assert _count(conn, "bp_index_master", f"{TEST_PREFIX}%") == 0

    def _boom() -> dict:
        raise RuntimeError("network down")

    failed = run_valuation_ingest(
        conn, as_of=date(2026, 11, 14), fetch=_boom
    )
    assert failed["indices"] == 0
    assert failed["valuation_rows"] == 0
    assert len(failed["errors"]) == 1
    assert "network down" in failed["errors"][0]
    assert _count(conn, "bp_index_master", f"{TEST_PREFIX}%") == 0
