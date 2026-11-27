"""P0-T5: /api/valuation 路由契约测试。

覆盖契约 docs/index-valuation/15-p0-contracts.md 第 4 节:
- overview / indices / detail / history 正常路径与响应信封;
- 未知代码 404 `{"detail": "index_not_found"}`;
- limit > 500、offset < 0 参数校验 422;
- Redis 缓存命中时不再回源 repositories(monkeypatch 打桩)。

repositories_valuation 由并行 ingest-agent 交付, 本文件把它整体打桩为
MagicMock, 不依赖真实 PostgreSQL。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bp_api import valuation


@contextmanager
def _fake_conn():
    """只读路由只需要一个可进入/退出的连接占位。"""
    yield MagicMock()


@pytest.fixture
def client(monkeypatch):
    """独立 FastAPI app + 内存版 Redis, 不触碰 bp_api.main 的全局 app。"""
    store: dict[str, object] = {}

    def fake_get_json(key: str):
        value = store.get(key)
        # 模拟 Redis 的 JSON 往返, 避免测试直接共享可变对象
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
    """把 repositories_valuation 换成按契约返回值的 mock。"""
    repo = MagicMock()
    for name, value in return_values.items():
        getattr(repo, name).return_value = value
    # detail 端点会额外查成分股与跟踪基金；默认返回空列表，避免 mock 未配置时抛错。
    if "get_index_constituents" not in return_values:
        repo.get_index_constituents.return_value = []
    if "get_index_tracker_funds" not in return_values:
        repo.get_index_tracker_funds.return_value = []
    if "get_index_risk_stats" not in return_values:
        repo.get_index_risk_stats.return_value = {}
    # 需求 7/8 新增的详情字段（HSI 双轴图 + 跟踪基金数据截止/更新时间）
    if "get_index_price_series" not in return_values:
        repo.get_index_price_series.return_value = []
    if "get_index_tracker_funds_meta" not in return_values:
        repo.get_index_tracker_funds_meta.return_value = {}
    monkeypatch.setattr(valuation, "repositories_valuation", repo)
    return repo


def test_overview_returns_four_boards_with_envelope(client, monkeypatch):
    test_client, _ = client
    cards = [
        {"board": "all", "label": "全市场", "pe": 20.1, "pb": 2.0,
         "pe_percentile": 0.5, "pb_percentile": 0.4, "as_of": "2026-11-13"},
        {"board": "main", "label": "主板", "pe": 18.2, "pb": 1.8,
         "pe_percentile": 0.4, "pb_percentile": 0.3, "as_of": "2026-11-13"},
        {"board": "chinext", "label": "创业板", "pe": 35.0, "pb": 3.1,
         "pe_percentile": 0.6, "pb_percentile": 0.5, "as_of": "2026-11-13"},
        {"board": "star", "label": "科创板", "pe": 45.0, "pb": 4.0,
         "pe_percentile": None, "pb_percentile": None, "as_of": "2026-11-13"},
    ]
    repo = _install_repo(monkeypatch, get_market_overview=cards)

    resp = test_client.get("/api/valuation/overview")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == cards
    assert body["meta"]["rows"] == 4
    assert body["meta"]["as_of"] == "2026-11-13"
    assert body["meta"]["cached"] is False
    repo.get_market_overview.assert_called_once()
    assert isinstance(repo.get_market_overview.call_args.args[1], date)


def test_indices_returns_rows_total_and_passes_filters(client, monkeypatch):
    test_client, _ = client
    rows = [{
        "index_code": "000300", "name": "沪深300", "category": "宽基",
        "trade_date": "2026-11-13", "pe_ttm": 20.47,
    }]
    repo = _install_repo(monkeypatch, get_index_list=(rows, 37))

    resp = test_client.get(
        "/api/valuation/indices",
        params={
            "q": "300", "type": "宽基", "with_etf": "true",
            "with_val": "true", "limit": 20, "offset": 5,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == rows
    assert body["meta"]["rows"] == 1
    assert body["meta"]["total"] == 37
    assert body["meta"]["limit"] == 20
    assert body["meta"]["offset"] == 5
    assert body["meta"]["as_of"] == "2026-11-13"
    assert body["meta"]["cached"] is False
    assert repo.get_index_list.call_args.kwargs == {
        "query": "300",
        "index_type": "宽基",
        "industry": None,
        "window": "5y",
        "metric": "pe_ttm",
        "only_with_etf": True,
        "only_with_valuation": True,
        "limit": 20,
        "offset": 5,
    }


def test_detail_returns_detail_payload(client, monkeypatch):
    test_client, _ = client
    detail = {
        "index_code": "000300",
        "name": "沪深300",
        "trade_date": "2026-11-13",
        "pe_stats": {"metric": "pe_ttm", "window_key": "5y", "pct": 0.1577},
        "tracker_etf_codes": ["510300"],
    }
    repo = _install_repo(monkeypatch, get_index_detail=detail)

    resp = test_client.get("/api/valuation/000300")

    assert resp.status_code == 200
    body = resp.json()
    # detail 端点会追加成分股与跟踪基金（无数据时为空列表）
    expected = {
        **detail,
        "constituents": [],
        "tracker_funds": [],
        "risk": {},
        "price_series": [],
        "tracker_funds_meta": {},
    }
    assert body["data"] == expected
    assert body["meta"]["rows"] == 1
    assert body["meta"]["as_of"] == "2026-11-13"
    assert body["meta"]["cached"] is False
    repo.get_index_detail.assert_called_once()
    assert repo.get_index_detail.call_args.args[1] == "000300"


def test_history_returns_series_and_window_stats(client, monkeypatch):
    test_client, _ = client
    series = [
        {"trade_date": "2026-11-12", "value": 20.0},
        {"trade_date": "2026-11-13", "value": 20.5},
    ]
    detail = {
        "index_code": "000300",
        "trade_date": "2026-11-13",
        "pe_stats": {
            "metric": "pe_ttm", "window_key": "5y",
            "pct": 0.1577, "mean": 22.0, "sd": 3.0,
        },
    }
    repo = _install_repo(
        monkeypatch, get_index_detail=detail, get_index_history=series
    )

    resp = test_client.get(
        "/api/valuation/000300/history",
        params={"metric": "pe_ttm", "window": "5y"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["series"] == series
    assert body["data"]["stats"] == detail["pe_stats"]
    assert body["meta"]["rows"] == 2
    assert body["meta"]["metric"] == "pe_ttm"
    assert body["meta"]["window"] == "5y"
    assert body["meta"]["as_of"] == "2026-11-13"
    repo.get_index_history.assert_called_once()
    assert repo.get_index_history.call_args.args[1:] == ("000300", "pe_ttm", "5y")


def test_unknown_index_returns_404_index_not_found(client, monkeypatch):
    test_client, _ = client
    _install_repo(monkeypatch, get_index_detail=None)

    resp = test_client.get("/api/valuation/999999")

    assert resp.status_code == 404
    assert resp.json() == {"detail": "index_not_found"}


def test_limit_above_cap_returns_422_without_querying_repo(client, monkeypatch):
    test_client, _ = client
    repo = _install_repo(monkeypatch, get_index_list=([], 0))

    resp = test_client.get("/api/valuation/indices", params={"limit": 1001})

    assert resp.status_code == 422
    repo.get_index_list.assert_not_called()


def test_negative_offset_returns_422_without_querying_repo(client, monkeypatch):
    test_client, _ = client
    repo = _install_repo(monkeypatch, get_index_list=([], 0))

    resp = test_client.get("/api/valuation/indices", params={"offset": -1})

    assert resp.status_code == 422
    repo.get_index_list.assert_not_called()


def test_second_request_hits_cache_and_skips_repository(client, monkeypatch):
    test_client, store = client
    cards = [{"board": "all", "label": "全市场", "as_of": "2026-11-13"}]
    repo = _install_repo(monkeypatch, get_market_overview=cards)

    first = test_client.get("/api/valuation/overview")
    second = test_client.get("/api/valuation/overview")

    assert first.status_code == second.status_code == 200
    assert first.json()["meta"]["cached"] is False
    assert second.json()["meta"]["cached"] is True
    assert second.json()["data"] == cards
    assert repo.get_market_overview.call_count == 1
    # 缓存键必须带 api:valuation: 前缀
    assert store and all(key.startswith("api:valuation:") for key in store)
