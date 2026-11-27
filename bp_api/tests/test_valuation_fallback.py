"""中证官网 fallback（000985 等平安未覆盖指数）测试。

覆盖：
- indicator.xls / perf.xls 解析（列名容错、NaN/负数过滤）；
- _build_csindex_rows：PE/股息/同日 ERP，PB 缺失必须写 NULL 且 raw 标记 pb_available=False；
- fetch_csindex_fallback 的抓取编排（mock HTTP，不联网）；
- _run_csindex_fallback 落库集成（真实 bp_mig_test，需 ddl/80；不可达 skip）。
"""

from __future__ import annotations

import io
from datetime import date, timedelta

import pandas as pd
import pytest

from bp_ingest import valuation_ingest as ingest


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------


def _xlsx_bytes(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False)
    return buffer.getvalue()


def _indicator_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "日期Date": ["20261126", "20261125", "20261124"],
            "指数代码Index Code": ["985", "985", "985"],
            "指数中文全称Chinese Name(Full)": ["中证全指指数"] * 3,
            "指数中文简称Index Chinese Name": ["中证全指"] * 3,
            "市盈率1（总股本）P/E1": [16.65, 16.64, None],
            "市盈率2（计算用股本）P/E2": [18.31, -1.0, 18.83],
            "股息率1（总股本）D/P1": [2.38, 2.38, 2.32],
            "股息率2（计算用股本）D/P2": [2.06, 2.06, None],
        }
    )


def _perf_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "日期Date": ["2021-08-27", "2021-08-26"],
            "指数代码Index Code": ["985", "985"],
            "指数中文全称Index Chinese Name(Full)": ["中证全指指数"] * 2,
            "指数中文简称Index Chinese Name": ["中证全指"] * 2,
            "开盘Open": [5719.1854, 5813.2341],
            "最高High": [5773.8428, 5813.2341],
            "最低Low": [5712.6946, 5730.1863],
            "收盘Close": [5757.1462, 5733.4157],
            "涨跌幅(%)Change(%)": [0.41, -1.43],
            "成交量（股）Volume(share)": [8.68e10, 9.16e10],
            "成交金额（元）Turnover": [1.22e12, 1.24e12],
        }
    )


def test_parse_csindex_indicator():
    rows = ingest._parse_csindex_indicator(_xlsx_bytes(_indicator_frame()))
    assert [row["trade_date"] for row in rows] == [
        date(2026, 11, 24),
        date(2026, 11, 25),
        date(2026, 11, 26),
    ]
    latest = rows[-1]
    assert latest["pe_static"] == pytest.approx(16.65)
    assert latest["pe_ttm"] == pytest.approx(18.31)
    assert latest["dividend_yield_lyr"] == pytest.approx(2.38)
    assert latest["dividend_yield_ttm"] == pytest.approx(2.06)
    # 负 PE 视为脏点 -> None（与日频 CHECK 同口径）
    assert rows[1]["pe_ttm"] is None


def test_parse_csindex_perf_xls():
    name, rows = ingest._parse_csindex_perf_xls(_xlsx_bytes(_perf_frame()))
    assert name == "中证全指"
    assert len(rows) == 2
    row = rows[0]["row"]
    assert row.trade_date == date(2021, 8, 26)
    assert row.close == pytest.approx(5733.4157)
    assert row.source == "csindex_perf"
    assert row.adjust == "bfq"


# ---------------------------------------------------------------------------
# 估值行构造（PB 缺失不得造数）
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self):
        self._rows: list[tuple] = []
        self._params: tuple = ()

    def execute(self, sql, params=None):
        self._params = tuple(params or ())
        self._rows = []

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, bond_rows=None):
        self.bond_rows = bond_rows or {}
        self.sql_log: list[str] = []

    def cursor(self):
        conn = self

        class _Cursor(_FakeCursor):
            def execute(self, sql, params=None):
                conn.sql_log.append(sql)
                self._params = tuple(params or ())
                self._rows = []
                if "bp_macro_series" in sql:
                    days = params[0] if params else []
                    self._rows = [
                        (day, conn.bond_rows[day])
                        for day in days
                        if day in conn.bond_rows
                    ]

        return _Cursor()


def test_build_csindex_rows_keeps_pb_null():
    indicator = [
        {
            "trade_date": date(2026, 11, 26),
            "pe_static": 16.65,
            "pe_ttm": 18.31,
            "dividend_yield_lyr": 2.38,
            "dividend_yield_ttm": 2.06,
        }
    ]
    conn = _FakeConn({date(2026, 11, 26): 1.6})
    daily, series, latest = ingest._build_csindex_rows(conn, "000985", indicator, None)
    assert latest == date(2026, 11, 26)
    assert len(daily) == 1
    row = daily[0]
    assert row["calc_src"] == "csindex_value"
    assert row["is_primary"] is True
    assert row["pe_ttm"] == pytest.approx(18.31)
    assert row["pe_static"] == pytest.approx(16.65)
    # 中证官网估值文件没有 PB：必须留 NULL，不得用别的口径冒充
    assert row["pb"] is None
    assert row["raw"]["pb_available"] is False
    # ERP = 股息率(ttm) - 同日 10Y；1.6 是伪造的同日 bond10y
    assert row["erp"] == pytest.approx(2.06 - 1.6)
    metrics = {item["metric"] for item in series}
    assert metrics == {"pe_ttm", "pe_static", "dividend_yield_ttm", "dividend_yield_lyr", "erp"}
    assert "pb" not in metrics


def test_build_csindex_rows_filters_future_dates():
    indicator = [
        {"trade_date": date(2026, 11, 26), "pe_ttm": 18.31, "dividend_yield_ttm": 2.06},
        {"trade_date": date(2026, 11, 27), "pe_ttm": 18.40, "dividend_yield_ttm": 2.05},
    ]
    conn = _FakeConn()
    daily, _series, latest = ingest._build_csindex_rows(
        conn, "000985", indicator, date(2026, 11, 26)
    )
    assert latest == date(2026, 11, 26)
    assert all(row["trade_date"] <= date(2026, 11, 26) for row in daily)


# ---------------------------------------------------------------------------
# 抓取编排（mock HTTP）
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, *, content: bytes = b"", payload: dict | None = None):
        self.content = content
        self._payload = payload or {}
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_fetch_csindex_fallback_wiring(monkeypatch):
    from bp_ingest.db import QuoteRow

    calls: list[str] = []

    def fake_get(url, params=None, timeout=25.0):
        calls.append(url)
        if "indicator" in url:
            return _FakeResponse(content=_xlsx_bytes(_indicator_frame()))
        raise AssertionError(f"unexpected csindex call: {url}")

    tencent_quotes = [
        {
            "row": QuoteRow(
                trade_date=date(2026, 11, 26) + timedelta(days=offset),
                symbol="000985",
                source=ingest.CALC_SRC_CN_INDEX_TX,
                category="index",
                name=None,
                open=None,
                high=None,
                low=None,
                close=5000.0 + offset,
                volume=None,
                amount=None,
                turnover_rate=None,
                pct_change=None,
                adjust="bfq",
            ),
            "name": None,
        }
        for offset in range(2)
    ]
    monkeypatch.setattr(ingest, "_csindex_get", fake_get)
    monkeypatch.setattr(
        ingest, "_fetch_tencent_quotes", lambda code, start, end: tencent_quotes
    )
    payload = ingest.fetch_csindex_fallback("000985", full_history=True)

    assert payload["errors"] == []
    assert any("indicator" in url for url in calls)
    assert len(payload["indicator"]) == 3
    quote_dates = {item["row"].trade_date for item in payload["quotes"]}
    assert quote_dates == {date(2026, 11, 26), date(2026, 11, 27)}
    assert {item["row"].source for item in payload["quotes"]} == {"cn_index_tx"}


def test_fetch_csindex_fallback_degrades_to_csindex_json(monkeypatch):
    def fake_get(url, params=None, timeout=25.0):
        if "indicator" in url:
            return _FakeResponse(content=_xlsx_bytes(_indicator_frame()))
        return _FakeResponse(
            payload={
                "data": [
                    {
                        "tradeDate": "20170103",
                        "indexNameCn": "中证全指",
                        "open": 4000.0,
                        "high": 4010.0,
                        "low": 3990.0,
                        "close": 4005.0,
                        "changePct": 0.1,
                        "tradingVol": 100,
                        "tradingValue": 200.0,
                    }
                ]
            }
        )

    def boom(code, start, end):
        raise RuntimeError("tencent blocked")

    monkeypatch.setattr(ingest, "_csindex_get", fake_get)
    monkeypatch.setattr(ingest, "_fetch_tencent_quotes", boom)
    payload = ingest.fetch_csindex_fallback("000985", full_history=True)

    assert len(payload["indicator"]) == 3
    quote_dates = {item["row"].trade_date for item in payload["quotes"]}
    assert date(2017, 1, 3) in quote_dates  # 腾讯不可用 -> 中证官网 JSON 降级
    assert payload["name"] == "中证全指"


# ---------------------------------------------------------------------------
# fallback 行情按 as_of 截断（P2；纯 mock）
# ---------------------------------------------------------------------------
class _CountCursor:
    def execute(self, sql: str, params: object = None) -> None:
        pass

    def fetchone(self):
        return (0,)

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _CountConn:
    def cursor(self) -> _CountCursor:
        return _CountCursor()


def test_fallback_quotes_truncated_by_as_of(monkeypatch: pytest.MonkeyPatch) -> None:
    """as_of 之后的 fallback 行情不得写入 bp_index_quote_daily（不回写未来）。"""
    from bp_ingest.db import QuoteRow

    code = "T80TRUNC"
    monkeypatch.setattr(ingest, "FALLBACK_INDEX_CODES", (code,))
    monkeypatch.setattr(
        ingest,
        "CSINDEX_MASTER_META",
        {
            code: {
                "index_code": code,
                "market": "CSI",
                "name": "测试截断指数",
                "is_active": True,
                "is_tracked": True,
            }
        },
    )
    captured: list = []
    from bp_ingest import db as ingest_db

    monkeypatch.setattr(ingest, "upsert_index_master", lambda conn, rows: len(rows))
    monkeypatch.setattr(
        ingest_db, "upsert_quotes", lambda conn, rows: captured.extend(rows) or len(rows)
    )
    monkeypatch.setattr(ingest, "upsert_valuation_daily", lambda conn, rows: 0)
    monkeypatch.setattr(ingest, "upsert_valuation_series", lambda conn, rows: 0)
    monkeypatch.setattr(ingest, "upsert_percentiles", lambda conn, rows: 0)
    monkeypatch.setattr(ingest, "_build_csindex_rows", lambda *a, **kw: ([], [], None))
    monkeypatch.setattr(ingest, "_refresh_quote_health", lambda *a, **kw: None)

    as_of = date(2026, 11, 25)

    def fake_fetch(target, full_history):
        rows = []
        for offset in range(3):  # 11-25 / 11-26 / 11-27
            rows.append(
                {
                    "row": QuoteRow(
                        trade_date=as_of + timedelta(days=offset),
                        symbol=code,
                        source="csindex_perf",
                        category="index",
                        name="测试截断指数",
                        open=None,
                        high=None,
                        low=None,
                        close=5000.0 + offset,
                        volume=None,
                        amount=None,
                        turnover_rate=None,
                        pct_change=None,
                        adjust="bfq",
                    ),
                    "name": "测试截断指数",
                }
            )
        return {"indicator": [], "quotes": rows, "name": "测试截断指数", "errors": []}

    errors: list[str] = []
    summary = ingest._run_csindex_fallback(
        _CountConn(), set(), as_of, errors, fetch=fake_fetch
    )
    assert errors == []
    assert summary["quote_rows"] == 1
    assert [row.trade_date for row in captured] == [as_of]



# ---------------------------------------------------------------------------
# 落库集成（显式启用 bp_mig_test；未设置时 skip）
#
# P1-4：不硬编码 host、不读 .env；只有显式 BP_MIG_TEST_DSN / BP_MIG_TEST=1 才连接。
# fallback 用**本测试专属代码**（不再使用共享的 000985 真实指数），所有写入在单事务
# 内完成并 rollback——不删除/覆盖任何非本测试创建的数据。
# ---------------------------------------------------------------------------

from bp_api.tests._mig_db import connect_mig_test

FALLBACK_TEST_CODE = "T80FBL1"


def _fallback_meta() -> dict:
    return {
        "index_code": FALLBACK_TEST_CODE,
        "market": "CSI",
        "wind_code": None,
        "name": "测试 fallback 指数",
        "short_name": "测试 fallback",
        "index_type": "宽基",
        "publisher": "测试",
        "base_date": date(2004, 12, 31),
        "base_point": 1000.0,
        "income_method": "价格指数",
        "weight_method": "调整市值加权",
        "intro": "集成测试专用 fallback 指数",
        "is_active": True,
        "is_tracked": True,
    }


def _patch_fallback_code(monkeypatch: pytest.MonkeyPatch, code: str = FALLBACK_TEST_CODE) -> None:
    """把 fallback 目标换成测试专属代码，避免读写共享的 000985。"""
    monkeypatch.setattr(ingest, "FALLBACK_INDEX_CODES", (code,))
    monkeypatch.setattr(ingest, "CSINDEX_MASTER_META", {code: _fallback_meta()})


def _fallback_quotes(code: str, start: date, count: int) -> list[dict]:
    from bp_ingest.db import QuoteRow

    return [
        {
            "row": QuoteRow(
                trade_date=start + timedelta(days=offset),
                symbol=code,
                source="csindex_perf",
                category="index",
                name="测试 fallback 指数",
                open=None,
                high=None,
                low=None,
                close=5000.0 + offset,
                volume=None,
                amount=None,
                turnover_rate=None,
                pct_change=None,
                adjust="bfq",
            ),
            "name": "测试 fallback 指数",
        }
        for offset in range(count)
    ]


def _fallback_indicator(start: date, count: int) -> list[dict]:
    return [
        {
            "trade_date": start + timedelta(days=offset),
            "pe_static": 16.0 + offset,
            "pe_ttm": 18.0 + offset,
            "dividend_yield_lyr": 2.3,
            "dividend_yield_ttm": 2.0,
        }
        for offset in range(count)
    ]


def test_run_csindex_fallback_writes_valuation_and_quotes(monkeypatch):
    conn = connect_mig_test()
    code = FALLBACK_TEST_CODE
    _patch_fallback_code(monkeypatch, code)
    try:
        as_of = date(2026, 11, 27)
        quote_rows = _fallback_quotes(code, date(2026, 11, 25), 3)
        indicator = _fallback_indicator(date(2026, 11, 25), 3)

        def fake_fetch(target, full_history):
            assert target == code
            return {"indicator": indicator, "quotes": quote_rows, "name": "测试 fallback 指数", "errors": []}

        errors: list[str] = []
        summary = ingest._run_csindex_fallback(
            conn, set(), as_of, errors, fetch=fake_fetch
        )

        # 不 commit：断言后 rollback，所有数据只存在于本测试事务
        assert errors == []
        assert summary["valuation_rows"] == 3
        assert summary["series_rows"] >= 12
        assert summary["quote_rows"] == 3
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pe_ttm, pb, calc_src, is_primary, raw"
                " FROM bp_index_valuation_daily WHERE index_code = %s"
                " ORDER BY trade_date",
                (code,),
            )
            daily = cur.fetchall()
            assert len(daily) == 3
            assert float(daily[-1][0]) == pytest.approx(20.0)
            assert daily[-1][1] is None  # PB 不可得
            assert daily[-1][2] == "csindex_value"
            assert daily[-1][3] is True
            assert daily[-1][4]["pb_available"] is False
            cur.execute(
                "SELECT count(*) FROM bp_index_quote_daily"
                " WHERE symbol = %s AND source = 'csindex_perf'",
                (code,),
            )
            assert int(cur.fetchone()[0]) == 3
            cur.execute(
                "SELECT status FROM bp_index_quote_health WHERE symbol = %s", (code,)
            )
            assert cur.fetchone()[0] == "ok"
            cur.execute(
                "SELECT count(*) FROM bp_index_percentile WHERE index_code = %s", (code,)
            )
            assert int(cur.fetchone()[0]) > 0
    finally:
        conn.rollback()
        conn.close()


def test_run_csindex_fallback_quotes_truncated_by_as_of(monkeypatch):
    """P2：fallback 行情按 as_of 截断，as_of 之后的行情不得写入。"""
    conn = connect_mig_test()
    code = FALLBACK_TEST_CODE
    _patch_fallback_code(monkeypatch, code)
    try:
        as_of = date(2026, 11, 25)
        quote_rows = _fallback_quotes(code, date(2026, 11, 25), 3)  # 25/26/27
        def fake_fetch(target, full_history):
            assert target == code
            return {"indicator": [], "quotes": quote_rows, "name": "", "errors": []}

        errors: list[str] = []
        summary = ingest._run_csindex_fallback(
            conn, set(), as_of, errors, fetch=fake_fetch
        )
        assert errors == []
        assert summary["quote_rows"] == 1
        with conn.cursor() as cur:
            cur.execute(
                "SELECT trade_date FROM bp_index_quote_daily"
                " WHERE symbol = %s AND source = 'csindex_perf' ORDER BY trade_date",
                (code,),
            )
            assert [row[0] for row in cur.fetchall()] == [as_of]
    finally:
        conn.rollback()
        conn.close()


def test_run_valuation_ingest_wires_fallback_and_snapshot(monkeypatch):
    """端到端：fake 平安抓取 + fake 中证 fallback -> 落库 + 快照刷新（不联网）。

    全程单事务（写入后 rollback），不持久化改动共享测试库。
    """
    from bp_ingest.valuation_ingest import run_valuation_ingest

    conn = connect_mig_test()
    test_code = "T80ING1"
    fallback_code = FALLBACK_TEST_CODE
    _patch_fallback_code(monkeypatch, fallback_code)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.bp_index_valuation_latest')")
            if cur.fetchone()[0] is None:
                pytest.skip("ddl/80 未应用到 bp_mig_test（缺 bp_index_valuation_latest）")

        pingan_rows = [
            {
                "code": "ZIT80ING1",
                "indexName": "Test Ingest",
                "indexType": "宽基",
                "peRatio": "23.27",
                "pbRatio": "2.02",
                "dividendRate": "3.68%",
                "bond10": "1.6123",
                "updateDate": "20261127",
                "peBar": "20261113,22|20261120,23",
                "pbBar": "20261113,2.0|20261120,2.01",
                "didHis": "20261113,3.6|20261120,3.65",
                "etfFund": "",
                "stockList": "",
            }
        ]

        def fake_pingan():
            return {
                "index_universe": [],
                "index_detail": pingan_rows,
                "index_description": [],
                "index_valuation_meta": [],
                "index_performance": [],
                "bond10_history": [],
                "tracker_funds": [],
            }

        fake_quotes = _fallback_quotes(fallback_code, date(2026, 11, 26), 2)
        fake_indicator = _fallback_indicator(date(2026, 11, 26), 2)

        def fake_fallback(target, full_history):
            assert target == fallback_code
            return {
                "indicator": fake_indicator,
                "quotes": fake_quotes,
                "name": "测试 fallback 指数",
                "errors": [],
            }

        summary = run_valuation_ingest(
            conn,
            as_of=date(2026, 11, 27),
            fetch=fake_pingan,
            enable_fallback=True,
            fallback_fetch=fake_fallback,
        )

        # 不 commit：断言后 rollback，避免污染共享库的 latest 快照/估值表
        assert summary["errors"] == []
        assert summary["indices"] == 1
        assert summary["latest_rows"] is not None and summary["latest_rows"] >= 2
        assert summary["fallback"]["valuation_rows"] == 2
        with conn.cursor() as cur:
            cur.execute(
                "SELECT index_code, pe_ttm, calc_src FROM bp_index_valuation_latest"
                " WHERE index_code IN (%s, %s) ORDER BY index_code",
                (test_code, fallback_code),
            )
            rows = cur.fetchall()
        assert {row[0] for row in rows} == {test_code, fallback_code}
        fallback_row = next(row for row in rows if row[0] == fallback_code)
        assert fallback_row[1] == pytest.approx(19.0)  # 2026-11-27 的 pe_ttm
        assert fallback_row[2] == "csindex_value"
    finally:
        conn.rollback()
        conn.close()


class _CoverageCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        self.conn.sql_log.append(sql)

    def fetchone(self):
        return (self.conn.responses.pop(0),)

    def fetchall(self):
        value = self.conn.responses.pop(0)
        return [(item,) for item in value]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _CoverageConn:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sql_log: list[str] = []

    def cursor(self):
        return _CoverageCursor(self)


def test_valuation_gate_coverage_requires_fallback_index():
    """521/522 已达到 99%，但 fallback 指数无当日主口径行时门控必须仍判未完备。"""
    from bp_ingest.valuation_job import coverage

    conn = _CoverageConn([522, 521, ["000985"], 0])
    done, total, fallback_missing = coverage(conn, date(2026, 11, 27))
    assert (done, total) == (521, 522)
    assert fallback_missing is True
    assert any("000985" in sql or "is_tracked" in sql for sql in conn.sql_log)

    conn = _CoverageConn([522, 522, ["000985"], 1])
    done, total, fallback_missing = coverage(conn, date(2026, 11, 27))
    assert (done, total, fallback_missing) == (522, 522, False)