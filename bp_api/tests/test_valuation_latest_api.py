"""新估值快速接口契约测试（需求 2/3/6，mock repositories，不依赖真实 PG）。

覆盖：
- GET /api/v1/valuation/indices：读快照 -> 一次性返回 4 指标当前值/分位/涨跌，缓存命中；
- GET /api/v1/market/mvi：latest + 周频 history 信封；
- GET /api/v1/market/mvi/overlay：4 指数白名单、缺价格时 200 + missing + reason、正常序列；
- GET /api/valuation/{code} 详情追加 price_series / tracker_funds_meta（不影响旧字段）。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bp_api import valuation


@contextmanager
def _fake_conn():
    yield MagicMock()


@pytest.fixture
def client(monkeypatch):
    store: dict[str, object] = {}

    def fake_get_json(key: str):
        value = store.get(key)
        return json.loads(json.dumps(value, default=str)) if value is not None else None

    def fake_set_json(key: str, value, ttl_seconds: int = 300) -> None:
        store[key] = json.loads(json.dumps(value, default=str))

    monkeypatch.setattr(valuation.cache, "get_json", fake_get_json)
    monkeypatch.setattr(valuation.cache, "set_json", fake_set_json)
    monkeypatch.setattr(valuation.db, "get_conn", _fake_conn)

    app = FastAPI()
    valuation.register_routes(app)
    return TestClient(app), store


def _install_repo(monkeypatch, **return_values) -> MagicMock:
    repo = MagicMock()
    for name, value in return_values.items():
        getattr(repo, name).return_value = value
    defaults = {
        "get_index_constituents": [],
        "get_index_tracker_funds": [],
        "get_index_risk_stats": {},
        "get_index_price_series": [],
        "get_index_tracker_funds_meta": {},
    }
    for name, value in defaults.items():
        if name not in return_values:
            getattr(repo, name).return_value = value
    monkeypatch.setattr(valuation, "repositories_valuation", repo)
    return repo


def _snapshot_row(**overrides) -> dict:
    row = {
        "index_code": "000300",
        "name": "沪深300",
        "index_type": "宽基",
        "industry": None,
        "publisher": "中证指数有限公司",
        "market": "SH",
        "trade_date": date(2026, 11, 27),
        "calc_src": "pingan_index",
        "is_primary": True,
        "pe_ttm": 13.4,
        "pe_percentile": 42.0,
        "pb": 1.38,
        "pb_percentile": 38.0,
        "dividend_yield_ttm": 3.2,
        "dividend_percentile": 61.0,
        "erp": 5.1,
        "erp_percentile": 55.0,
        "roe_ttm": 10.2,
        "fund_aum": 1.0e11,
        "fund_count": 23,
        "quote_status": "ok",
        "quote_lag_days": 0,
        "close_price": 4010.5,
        "change_pct": 0.42,
        "change_52w_pct": 12.3,
        "position_52w_pct": 74.5,
        "coverage_start": date(2021, 11, 19),
        "updated_at": datetime(2026, 11, 27, 21, 10, 0),
        "has_valuation": True,
        "window": "5y",
    }
    row.update(overrides)
    return row


def test_v1_indices_returns_all_metrics_and_meta(client, monkeypatch):
    test_client, store = client
    rows = [_snapshot_row(), _snapshot_row(index_code="000985", name="中证全指", pe_percentile=None)]
    repo = _install_repo(monkeypatch, get_valuation_latest_list=rows)

    resp = test_client.get("/api/v1/valuation/indices", params={"window": "5y"})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 2
    first = body["data"][0]
    for key in (
        "index_code", "name", "pe_ttm", "pe_percentile", "pb", "pb_percentile",
        "dividend_yield_ttm", "dividend_percentile", "erp", "erp_percentile",
        "roe_ttm", "close_price", "change_pct", "change_52w_pct", "position_52w_pct",
        "fund_aum", "fund_count", "quote_status", "quote_lag_days",
        "trade_date", "updated_at", "coverage_start",
    ):
        assert key in first, key
    assert body["meta"]["rows"] == 2
    assert body["meta"]["total"] == 2
    assert body["meta"]["window"] == "5y"
    assert body["meta"]["as_of"] == "2026-11-27"
    assert body["meta"]["cached"] is False
    # 4 指标一次返回
    assert first["pe_ttm"] == pytest.approx(13.4)
    assert first["erp_percentile"] == pytest.approx(55.0)
    repo.get_valuation_latest_list.assert_called_once()
    assert repo.get_valuation_latest_list.call_args.kwargs == {"window": "5y"}
    assert store and all(key.startswith("api:valuation:") for key in store)


def test_v1_indices_cache_hit_and_pagination(client, monkeypatch):
    test_client, _ = client
    rows = [_snapshot_row(index_code=f"00000{i}") for i in range(5)]
    repo = _install_repo(monkeypatch, get_valuation_latest_list=rows)

    first = test_client.get("/api/v1/valuation/indices")
    second = test_client.get("/api/v1/valuation/indices")
    paged = test_client.get("/api/v1/valuation/indices", params={"limit": 2, "offset": 1})

    assert first.json()["meta"]["cached"] is False
    assert second.json()["meta"]["cached"] is True
    assert second.json()["meta"]["total"] == 5
    assert len(second.json()["data"]) == 5
    assert repo.get_valuation_latest_list.call_count == 2  # 分页参数不同 -> 新缓存键
    page_body = paged.json()
    assert [row["index_code"] for row in page_body["data"]] == ["000001", "000002"]
    assert page_body["meta"]["total"] == 5
    assert page_body["meta"]["rows"] == 2


def test_v1_market_mvi_returns_latest_and_history(client, monkeypatch):
    test_client, _ = client
    latest = {
        "as_of": "2026-11-27",
        "mvi": 31.38,
        "cheap_score": 68.62,
        "risk_score": 66.92,
        "zone": "低估",
        "factors": {"PE 分位（反向）": 69.81},
        "weights": {"PE 分位（反向）": 0.1686},
        "contributions": {"PE 分位（反向）": 11.77},
        "risk_factors": {"波动率分位": 54.92, "回撤分位": 81.59},
    }
    history = [
        {"as_of": "2026-11-20", "mvi": 35.42, "risk": 56.88},
        {"as_of": "2026-11-27", "mvi": 31.38, "risk": 66.92},
    ]
    _install_repo(
        monkeypatch,
        get_market_valuation_index_range={
            "latest": latest,
            "history": history,
            "range": "5y",
            "start": date(2021, 11, 27),
        },
    )

    resp = test_client.get("/api/v1/market/mvi", params={"range": "5y"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["latest"]["mvi"] == pytest.approx(31.38)
    assert body["data"]["latest"]["zone"] == "低估"
    assert body["data"]["history"] == history
    assert body["meta"]["rows"] == 2
    assert body["meta"]["range"] == "5y"


def test_v1_mvi_overlay_rejects_unsupported_index(client, monkeypatch):
    test_client, _ = client
    repo = _install_repo(monkeypatch, get_market_mvi_overlay={})

    resp = test_client.get("/api/v1/market/mvi/overlay", params={"index": "999999"})

    assert resp.status_code == 404
    assert resp.json() == {"detail": "index_not_supported"}
    repo.get_market_mvi_overlay.assert_not_called()


def test_v1_mvi_overlay_missing_price_data_is_explicit_not_fabricated(client, monkeypatch):
    test_client, _ = client
    payload = {
        "index_code": "000985",
        "name": "中证全指",
        "series": [],
        "mvi": [{"as_of": "2026-11-27", "mvi": 31.38, "risk": 66.92}],
        "range": "5y",
        "coverage_start": None,
        "coverage_end": None,
        "mvi_start": "2026-11-27",
        "mvi_end": "2026-11-27",
        "missing": True,
        "reason": "no_price_data_for_overlay",
    }
    repo = _install_repo(monkeypatch, get_market_mvi_overlay=payload)

    resp = test_client.get("/api/v1/market/mvi/overlay", params={"index": "000985"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["series"] == []
    assert body["data"]["mvi"][0]["mvi"] == pytest.approx(31.38)
    assert body["meta"]["missing"] is True
    assert body["meta"]["reason"] == "no_price_data_for_overlay"
    repo.get_market_mvi_overlay.assert_called_once()
    assert repo.get_market_mvi_overlay.call_args.args[1] == "000985"
    # 回归：仓储函数参数名是 range_key（曾误写成 range= 导致 TypeError/500）。
    assert repo.get_market_mvi_overlay.call_args.kwargs == {"range_key": "5y"}


def test_v1_mvi_overlay_calls_repository_with_matching_signature(client, monkeypatch):
    """回归：路由必须用 range_key= 调用仓储；MagicMock 会吞掉错误参数名，
    这里用真实签名的函数兜底，参数名不一致时会 TypeError -> 500。"""
    test_client, _ = client
    payload = {
        "index_code": "000300",
        "name": "沪深300",
        "series": [{"trade_date": date(2026, 11, 27), "close": 4010.5}],
        "mvi": [],
        "range": "5y",
        "missing": False,
        "reason": None,
    }
    calls: list[tuple[str, str]] = []

    def fake_overlay(conn, index_code, range_key="5y"):
        calls.append((index_code, range_key))
        return payload

    repo = _install_repo(monkeypatch)
    repo.get_market_mvi_overlay = fake_overlay  # type: ignore[assignment]

    resp = test_client.get("/api/v1/market/mvi/overlay", params={"index": "000300", "range": "3y"})

    assert resp.status_code == 200
    assert calls == [("000300", "3y")]


def test_v1_mvi_overlay_returns_index_price_series(client, monkeypatch):
    test_client, _ = client
    payload = {
        "index_code": "000300",
        "name": "沪深300",
        "series": [
            {"trade_date": date(2026, 11, 26), "close": 4000.0},
            {"trade_date": date(2026, 11, 27), "close": 4010.5},
        ],
        "mvi": [{"as_of": "2026-11-27", "mvi": 31.38, "risk": 66.92}],
        "range": "5y",
        "coverage_start": date(2017, 1, 3),
        "coverage_end": date(2026, 11, 27),
        "mvi_start": "2026-11-27",
        "mvi_end": "2026-11-27",
        "missing": False,
        "reason": None,
    }
    _install_repo(monkeypatch, get_market_mvi_overlay=payload)

    resp = test_client.get("/api/v1/market/mvi/overlay", params={"index": "000300"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["index_code"] == "000300"
    assert body["data"]["name"] == "沪深300"
    assert body["data"]["series"][-1]["close"] == pytest.approx(4010.5)
    assert body["meta"]["source"] == "bp_index_quote_daily"
    assert body["meta"]["missing"] is False


def test_detail_appends_price_series_and_tracker_meta(client, monkeypatch):
    test_client, _ = client
    detail = {
        "index_code": "HSI",
        "name": "恒生指数",
        "trade_date": date(2026, 11, 27),
        "tracker_etf_codes": ["513660"],
    }
    price_series = [{"trade_date": date(2026, 11, 27), "close": 24586.32}]
    tracker_meta = {
        "data_as_of": date(2026, 11, 23),
        "updated_at": datetime(2026, 11, 27, 21, 10, 0),
        "risk_updated_at": datetime(2026, 11, 27, 21, 10, 0),
        "fund_count": 23,
    }
    _install_repo(
        monkeypatch,
        get_index_detail=detail,
        get_index_price_series=price_series,
        get_index_tracker_funds_meta=tracker_meta,
    )

    resp = test_client.get("/api/valuation/HSI")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["price_series"] == [
        {"trade_date": "2026-11-27", "close": 24586.32}
    ]
    assert body["tracker_funds_meta"]["fund_count"] == 23
    assert body["tracker_funds_meta"]["data_as_of"] == "2026-11-23"
    # 旧字段保持
    assert body["tracker_funds"] == []
    assert body["constituents"] == []
    assert body["risk"] == {}

def test_v1_history_alias_matches_legacy_payload(client, monkeypatch):
    test_client, _ = client
    series = [
        {"trade_date": date(2026, 11, 26), "value": 13.3, "is_weekly": False},
        {"trade_date": date(2026, 11, 27), "value": 13.4, "is_weekly": False},
    ]
    detail = {
        "index_code": "000300",
        "trade_date": date(2026, 11, 27),
        "pe_stats": {"metric": "pe_ttm", "window_key": "5y", "pct": 42.0},
    }
    repo = _install_repo(monkeypatch, get_index_detail=detail, get_index_history=series)

    resp = test_client.get(
        "/api/v1/valuation/000300/history",
        params={"metric": "pe_ttm", "window": "5y"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["series"] == [
        {"trade_date": "2026-11-26", "value": 13.3, "is_weekly": False},
        {"trade_date": "2026-11-27", "value": 13.4, "is_weekly": False},
    ]
    assert body["data"]["stats"] == detail["pe_stats"]
    assert body["meta"]["rows"] == 2
    repo.get_index_history.assert_called_once()

def test_v1_mvi_overlay_no_price_no_mvi_does_not_fabricate_today(client, monkeypatch):
    """P2：无价格且无 MVI 时 meta.as_of 必须为 None，不得用 date.today() 造新鲜度。"""
    test_client, _ = client
    payload = {
        "index_code": "000985",
        "name": "中证全指",
        "series": [],
        "mvi": [],
        "range": "5y",
        "coverage_start": None,
        "coverage_end": None,
        "mvi_start": None,
        "mvi_end": None,
        "missing": True,
        "reason": "no_price_data_for_overlay",
    }
    _install_repo(monkeypatch, get_market_mvi_overlay=payload)

    resp = test_client.get("/api/v1/market/mvi/overlay", params={"index": "000985"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["as_of"] is None
    assert body["meta"]["missing"] is True
    assert body["data"]["series"] == []
