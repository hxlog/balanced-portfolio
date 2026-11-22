"""对外行情 API 扩展测试：quote_store / market/last / history / fx / fund-navy。

与 test_public_api.py 同风格：TestClient + monkeypatch，不连数据库。
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from bp_api import market_extra, market_last, quote_store

ALL_SCOPES = ["quotes", "valuation", "percentile", "crypto", "portfolio"]


class _Cursor:
    def __init__(self, owner: "FakeConn") -> None:
        self.owner = owner

    def execute(self, sql, params=None) -> None:
        self.owner.statements.append((sql, params))

    def fetchall(self):
        return self.owner.results.pop(0) if self.owner.results else []

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


class FakeConn:
    """按顺序返回预置结果集的假连接（每条 SQL 一次 fetch）。"""

    def __init__(self, *results) -> None:
        self.results = list(results)
        self.statements: list[tuple[str, object]] = []

    def cursor(self):
        return _Cursor(self)

    def rollback(self) -> None:
        pass


def _token_dep(scope):
    def dependency(
        authorization: str = Header(default=""),
        x_api_key: str = Header(default=""),
    ) -> dict:
        raw = ""
        if authorization.lower().startswith("bearer "):
            raw = authorization.split(" ", 1)[1].strip()
        elif x_api_key:
            raw = x_api_key.strip()
        if not raw:
            raise HTTPException(401, "缺少 API Token")
        scopes = list(ALL_SCOPES)
        if scope is not None and scope not in scopes:
            raise HTTPException(403, f"缺少 {scope} scope")
        return {"token_id": "t", "name": "pytest", "scopes": scopes}

    return dependency


def _make_client(monkeypatch, module) -> TestClient:
    monkeypatch.setattr(module.auth, "require_api_token", _token_dep)
    app = FastAPI()
    module.register_routes(app)
    return TestClient(app)


# ---------------------------------------------------------------------
# quote_store 代码规范化
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("601318", ("601318", "SH", None)),
        ("601318.SH", ("601318", "SH", None)),
        ("sh601318", ("601318", "SH", None)),
        ("02020", ("02020", "HK", None)),
        ("02020.HK", ("02020", "HK", None)),
        ("HK02020", ("02020", "HK", None)),
        ("159915", ("159915", "SZ", None)),
        ("IDX:000300", ("000300", "SZ", "index")),
        ("ETF:159915", ("159915", "SZ", "etf")),
        ("STK:600000", ("600000", "SH", "stock")),
    ],
)
def test_normalize_code(raw, expected):
    assert quote_store.normalize_code(raw) == expected


@pytest.mark.parametrize("raw", ["", "ABC", "123", "0003000", "USDCNY", "xx601318"])
def test_normalize_code_rejects(raw):
    assert quote_store.normalize_code(raw) is None


def test_resolve_codes_priority_and_forced():
    """stock > etf > index；显式 IDX: 前缀可强制指数。"""
    conn = FakeConn(
        [("601318", "中国平安", "SH"), ("02020", "安踏体育", "HK")],   # stock_master
        [("159915", "创业板ETF", "SZ")],                                # etf_master
        [("000300", "沪深300", "SH"), ("000001", "上证指数", "SH")],    # index_master
        ["601318"],                                                     # stock present
        ["159915"],                                                     # etf present
        ["000300", "000001"],                                           # index present
    )
    resolved, invalid = quote_store.resolve_codes(
        conn, ["601318", "02020", "159915", "000300", "IDX:000001"], "bfq"
    )
    assert invalid == []
    assert resolved["601318"]["kind"] == "stock"
    assert resolved["601318"]["currency"] == "CNY"
    assert resolved["02020"]["market"] == "HK"
    assert resolved["02020"]["currency"] == "HKD"
    assert resolved["159915"]["kind"] == "etf"
    assert resolved["000300"]["kind"] == "index"
    assert resolved["IDX:000001"]["kind"] == "index"


def test_resolve_codes_invalid():
    conn = FakeConn([], [], [], set(), set(), set())
    resolved, invalid = quote_store.resolve_codes(conn, ["999999", "ABC"], "bfq")
    assert resolved == {}
    assert invalid == ["ABC", "999999"]


# ---------------------------------------------------------------------
# market/last
# ---------------------------------------------------------------------
@pytest.fixture
def last_client(monkeypatch):
    return _make_client(monkeypatch, market_last)


def test_market_last_requires_token(monkeypatch):
    monkeypatch.setattr(market_last.auth, "require_api_token", _token_dep)
    app = FastAPI()
    market_last.register_routes(app)
    client = TestClient(app)
    resp = client.get("/api/v1/market/last", params={"codes": "601318"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_market_last_missing_codes(last_client):
    resp = last_client.get(
        "/api/v1/market/last", headers={"Authorization": "Bearer x"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "missing_parameter"


def test_market_last_success(monkeypatch, last_client):
    info = {
        "code": "601318",
        "kind": "stock",
        "market": "SH",
        "currency": "CNY",
        "name": "中国平安",
        "canonical": "601318.SH",
    }
    monkeypatch.setattr(
        quote_store, "resolve_codes", lambda conn, codes, adjust="bfq": ({"601318": info}, [])
    )
    monkeypatch.setattr(
        quote_store,
        "latest_rows",
        lambda conn, resolved, adjust="bfq": {
            "601318": {
                "date": date(2026, 11, 20),
                "close": 55.46,
                "prev_close": 54.66,
                "source": "tencent_qt",
                "adjust": "bfq",
            }
        },
    )
    monkeypatch.setattr(quote_store, "latest_trade_date", lambda conn: date(2026, 11, 20))
    monkeypatch.setattr(market_last.db, "get_conn", lambda: _fake_conn())

    resp = last_client.get(
        "/api/v1/market/last",
        params={"codes": "601318"},
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 200
    body = resp.json()
    row = body["data"][0]
    assert row["code"] == "601318.SH"
    assert row["close"] == 55.46
    assert row["date"] == "2026-11-20"
    assert row["status"] == "ok"
    assert row["currency"] == "CNY"
    assert body["meta"]["as_of"] == "2026-11-20"
    assert body["meta"]["latest_trade_date"] == "2026-11-20"
    assert body["meta"]["price_basis"] == "last_confirmed_close"
    assert body["error"] is None


def test_market_last_unknown_code_returns_null_row(monkeypatch, last_client):
    info = {
        "code": "02714",
        "kind": "stock",
        "market": "HK",
        "currency": "HKD",
        "name": "牧原股份",
        "canonical": "02714.HK",
    }
    monkeypatch.setattr(
        quote_store, "resolve_codes", lambda conn, codes, adjust="bfq": ({"02714": info}, [])
    )
    monkeypatch.setattr(quote_store, "latest_rows", lambda conn, resolved, adjust="bfq": {})
    monkeypatch.setattr(quote_store, "latest_trade_date", lambda conn: None)
    monkeypatch.setattr(market_last.db, "get_conn", lambda: _fake_conn())

    resp = last_client.get(
        "/api/v1/market/last",
        params={"codes": "02714"},
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 200
    row = resp.json()["data"][0]
    assert row["close"] is None and row["status"] == "unknown"
    assert resp.json()["meta"]["unknown"] == ["02714.HK"]


def test_market_last_csv_has_bom(monkeypatch, last_client):
    info = {"code": "601318", "kind": "stock", "market": "SH", "currency": "CNY", "name": "中国平安", "canonical": "601318.SH"}
    monkeypatch.setattr(quote_store, "resolve_codes", lambda conn, codes, adjust="bfq": ({"601318": info}, []))
    monkeypatch.setattr(
        quote_store,
        "latest_rows",
        lambda conn, resolved, adjust="bfq": {"601318": {"date": date(2026, 11, 20), "close": 55.46, "prev_close": 54.66, "source": "s", "adjust": "bfq"}},
    )
    monkeypatch.setattr(quote_store, "latest_trade_date", lambda conn: date(2026, 11, 20))
    monkeypatch.setattr(market_last.db, "get_conn", lambda: _fake_conn())
    resp = last_client.get(
        "/api/v1/market/last",
        params={"codes": "601318", "format": "csv"},
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 200
    assert resp.content.startswith(b"\xef\xbb\xbf")
    assert b"601318.SH" in resp.content


@contextmanager
def _fake_conn():
    yield MagicMock()


# ---------------------------------------------------------------------
# 汇率
# ---------------------------------------------------------------------
def test_parse_pairs_variants():
    assert market_extra._parse_pairs("USD/CNY, hkd-cny, USDCNY, USD/SGD") == [
        ("USD", "CNY"),
        ("HKD", "CNY"),
        ("USD", "SGD"),
    ]


@pytest.mark.parametrize("bad", ["", "USD", "US", "USDC", "USD/CNY,X", "USD/USD"])
def test_parse_pairs_rejects(bad):
    with pytest.raises(market_extra.ApiError):
        market_extra._parse_pairs(bad)


def test_fetch_fx_latest_cross_rates():
    d1, d2 = date(2026, 11, 19), date(2026, 11, 20)
    rows = [
        ("HKDCNY", d1, 0.90),
        ("HKDCNY", d2, 0.91),
        ("SGDCNY", d1, 5.00),
        ("SGDCNY", d2, 5.05),
        ("USDCNY", d1, 7.00),
        ("USDCNY", d2, 7.10),
    ]
    conn = FakeConn(rows)
    result, missing, as_of = market_extra._fetch_fx(
        conn,
        [("USD", "CNY"), ("USD", "HKD"), ("USD", "SGD"), ("HKD", "CNY")],
        start=None,
        end=None,
        latest=True,
    )
    assert missing == []
    assert as_of == "2026-11-20"
    by_pair = {row["pair"]: row for row in result}
    assert by_pair["USD/CNY"]["price"] == pytest.approx(7.10)
    assert by_pair["USD/HKD"]["price"] == pytest.approx(7.10 / 0.91)
    assert by_pair["USD/SGD"]["price"] == pytest.approx(7.10 / 5.05)
    assert by_pair["HKD/CNY"]["price"] == pytest.approx(0.91)
    assert all(row["date"] == d2 for row in result)


def test_fetch_fx_missing_leg_is_reported():
    conn = FakeConn([("USDCNY", date(2026, 11, 20), 7.1)])
    result, missing, as_of = market_extra._fetch_fx(
        conn, [("USD", "SGD")], start=None, end=None, latest=True
    )
    assert result == []
    assert missing == ["SGDCNY"]
    assert as_of is None


def test_fx_endpoint_envelope(monkeypatch):
    client = _make_client(monkeypatch, market_extra)
    d2 = date(2026, 11, 20)
    monkeypatch.setattr(market_extra.db, "get_conn", lambda: _fake_conn())
    monkeypatch.setattr(
        market_extra,
        "_fetch_fx",
        lambda conn, pairs, start, end, latest: (
            [
                {
                    "pair": "USD/CNY",
                    "base": "USD",
                    "quote": "CNY",
                    "date": d2,
                    "price": 7.1,
                    "source": "fx_sina",
                }
            ],
            [],
            "2026-11-20",
        ),
    )
    resp = client.get(
        "/api/v1/market/fx",
        params={"pairs": "USD/CNY"},
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"][0]["price"] == 7.1
    assert body["meta"]["mode"] == "latest"
    assert body["meta"]["as_of"] == "2026-11-20"


# ---------------------------------------------------------------------
# 基金净值
# ---------------------------------------------------------------------
def test_fetch_fund_nav_latest():
    conn = FakeConn(
        [("000001", "华夏成长")],
        [("000001", date(2026, 11, 20), 1.23, 3.45, "em_pingzhongdata")],
    )
    rows, unknown, truncated = market_extra._fetch_fund_nav(
        conn, ["000001", "999999"], start=None, end=None, latest=True, limit=100
    )
    assert truncated is False
    assert unknown == ["999999"]
    assert rows == [
        {
            "code": "000001",
            "name": "华夏成长",
            "date": date(2026, 11, 20),
            "nav": 1.23,
            "acc_nav": 3.45,
            "source": "em_pingzhongdata",
        }
    ]


# ---------------------------------------------------------------------
# 历史日线
# ---------------------------------------------------------------------
def test_history_endpoint(monkeypatch):
    client = _make_client(monkeypatch, market_extra)
    monkeypatch.setattr(market_extra.db, "get_conn", lambda: _fake_conn())
    monkeypatch.setattr(
        quote_store,
        "resolve_codes",
        lambda conn, codes, adjust="bfq": (
            {
                "601318": {
                    "code": "601318",
                    "kind": "stock",
                    "market": "SH",
                    "currency": "CNY",
                    "name": "中国平安",
                    "canonical": "601318.SH",
                }
            },
            [],
        ),
    )
    monkeypatch.setattr(
        quote_store,
        "history_rows",
        lambda conn, resolved, adjust="bfq", start=None, end=None, limit=50000: (
            [
                {
                    "code": "601318.SH",
                    "kind": "stock",
                    "market": "SH",
                    "currency": "CNY",
                    "date": date(2026, 11, 20),
                    "open": 54.0,
                    "high": 55.9,
                    "low": 53.9,
                    "close": 55.46,
                    "volume": 1,
                    "amount": 2.0,
                    "pct_change": 1.46,
                    "source": "tencent_qt",
                    "adjust": "bfq",
                }
            ],
            False,
        ),
    )
    resp = client.get(
        "/api/v1/market/history",
        params={"codes": "601318", "start": "2026-11-01", "end": "2026-11-20"},
        headers={"Authorization": "Bearer x"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"][0]["close"] == 55.46
    assert body["meta"]["adjust"] == "bfq"
    assert body["meta"]["truncated"] is False

