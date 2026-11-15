"""P2-B: 对外数据 API ``/api/v1`` 契约测试。

全部用例只依赖 FastAPI TestClient + monkeypatch 打桩, **不连数据库**:

- ``auth.require_api_token`` 用与 P2-A 相同的工厂语义打桩
  (``require_api_token(scope) -> dependency``)；
- 数据读取函数 ``public_api._fetch_*`` / ``_load_index_detail`` 直接返回合成数据；
- ``db.get_conn`` 替换为只可进入/退出的占位连接。

覆盖：401/403、参数校验、未知代码 404、统一信封、CSV(BOM + Accept 协商)、
五个端点的正常路径与字段选择。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from bp_api import public_api

ALL_SCOPES = ["quotes", "valuation", "percentile", "crypto", "portfolio"]
AUTH = {"Authorization": "Bearer test-token"}
REAL_TOKEN_ALL = "bp_live_" + "a" * 32
REAL_TOKEN_QUOTES = "bp_live_" + "b" * 32


@contextmanager
def _fake_conn():
    """只读查询函数已被打桩，连接本身只需可进入/退出。"""
    yield MagicMock()


@pytest.fixture
def client(monkeypatch):
    """独立 FastAPI app + 与 P2-A 对齐的 token 依赖工厂。"""

    def fake_require_api_token(scope: str | None = None):
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
            if raw == "bad":
                raise HTTPException(401, "Token 无效")
            if raw.startswith("scope:"):
                scopes = [item for item in raw[6:].split("+") if item]
            else:
                scopes = list(ALL_SCOPES)
            if scope is not None and scope not in scopes:
                raise HTTPException(403, f"缺少 {scope} scope")
            return {"token_id": "test-token-id", "name": "pytest", "scopes": scopes}

        return dependency

    monkeypatch.setattr(
        public_api.auth, "require_api_token", fake_require_api_token, raising=False
    )
    monkeypatch.setattr(public_api.db, "get_conn", _fake_conn)

    app = FastAPI()
    public_api.register_routes(app)
    return TestClient(app)


def _market_row(code: str = "000300") -> dict:
    return {
        "code": code,
        "source": "cn_index_em",
        "date": date(2024, 1, 2),
        "open": 3400.0,
        "high": 3450.0,
        "low": 3380.0,
        "close": 3430.5,
        "ret": 0.0123,
    }


# ---------------------------------------------------------------------
# 鉴权 / scope
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "path,params",
    [
        ("/api/v1/market/daily", {"codes": "000300"}),
        ("/api/v1/index/valuation", {"codes": "000300"}),
        ("/api/v1/index/percentile", {"codes": "000300"}),
        ("/api/v1/index/detail", {"code": "000300"}),
        ("/api/v1/market/bond-yield", {}),
    ],
)
def test_all_endpoints_require_token(client, path, params):
    resp = client.get(path, params=params)

    assert resp.status_code == 401
    body = resp.json()
    assert body["data"] is None
    assert body["error"]["code"] == "unauthorized"
    assert set(body) == {"data", "meta", "error"}


def test_invalid_token_returns_401_envelope(client):
    resp = client.get(
        "/api/v1/market/daily",
        params={"codes": "000300"},
        headers={"Authorization": "Bearer bad"},
    )

    assert resp.status_code == 401
    assert resp.json()["error"]["message"] == "Token 无效"


def test_missing_scope_returns_403_envelope(client):
    resp = client.get(
        "/api/v1/index/valuation",
        params={"codes": "000300"},
        headers={"Authorization": "Bearer scope:quotes"},
    )

    assert resp.status_code == 403
    body = resp.json()
    assert body["data"] is None
    assert body["error"]["code"] == "forbidden"
    assert body["error"]["required_scope"] == "valuation"


def test_direct_dependency_shape_is_supported(monkeypatch):
    """P2-A 若以「直接依赖」而非工厂形态合入，也必须兼容。"""

    def direct_dependency(authorization: str = Header(default="")):
        if not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "缺少 API Token")
        return SimpleNamespace(
            token_id="direct", name="direct", scopes=list(ALL_SCOPES)
        )

    monkeypatch.setattr(
        public_api.auth, "require_api_token", direct_dependency, raising=False
    )
    monkeypatch.setattr(public_api.db, "get_conn", _fake_conn)
    monkeypatch.setattr(
        public_api,
        "_fetch_market_daily",
        lambda conn, **kwargs: ([_market_row()], [], False),
    )

    app = FastAPI()
    public_api.register_routes(app)
    test_client = TestClient(app)

    resp = test_client.get(
        "/api/v1/market/daily", params={"codes": "000300"}, headers=AUTH
    )

    assert resp.status_code == 200
    assert resp.json()["error"] is None


def test_real_p2a_token_factory_integration(monkeypatch):
    """P2-A 已合入时，走真实 ``auth.require_api_token`` 工厂（仅打桩 verify_token）。"""
    if getattr(public_api.auth, "require_api_token", None) is None:
        pytest.skip("P2-A require_api_token 尚未合入")
    api_tokens_module = pytest.importorskip("bp_api.api_tokens")

    all_info = {
        "token_id": "real-all",
        "name": "integration-all",
        "scopes": list(ALL_SCOPES),
    }
    quotes_info = {
        "token_id": "real-quotes",
        "name": "integration-quotes",
        "scopes": ["quotes"],
    }
    monkeypatch.setattr(
        api_tokens_module,
        "verify_token",
        lambda conn, plain: {
            REAL_TOKEN_ALL: all_info,
            REAL_TOKEN_QUOTES: quotes_info,
        }.get(plain),
    )
    monkeypatch.setattr(public_api.db, "get_conn", _fake_conn)
    monkeypatch.setattr(
        public_api,
        "_fetch_market_daily",
        lambda conn, **kwargs: ([_market_row()], [], False),
    )

    app = FastAPI()
    public_api.register_routes(app)
    test_client = TestClient(app)

    ok = test_client.get(
        "/api/v1/market/daily",
        params={"codes": "000300"},
        headers={"Authorization": f"Bearer {REAL_TOKEN_ALL}"},
    )
    assert ok.status_code == 200
    assert ok.json()["error"] is None

    forbidden = test_client.get(
        "/api/v1/index/valuation",
        params={"codes": "000300"},
        headers={"X-API-Key": REAL_TOKEN_QUOTES},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["required_scope"] == "valuation"

    unauthorized = test_client.get(
        "/api/v1/market/daily",
        params={"codes": "000300"},
        headers={"Authorization": f"Bearer {REAL_TOKEN_ALL[:-1]}0"},
    )
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "unauthorized"


def test_x_api_key_header_is_accepted_by_factory_dependency(client, monkeypatch):
    monkeypatch.setattr(
        public_api,
        "_fetch_market_daily",
        lambda conn, **kwargs: ([_market_row()], [], False),
    )

    resp = client.get(
        "/api/v1/market/daily",
        params={"codes": "000300"},
        headers={"X-API-Key": "test-token"},
    )

    assert resp.status_code == 200


# ---------------------------------------------------------------------
# /market/daily 参数校验
# ---------------------------------------------------------------------
def test_market_daily_requires_codes(client):
    resp = client.get("/api/v1/market/daily", headers=AUTH)

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "missing_parameter"


def test_market_daily_rejects_more_than_50_codes(client):
    codes = ",".join(f"{i:06d}" for i in range(51))

    resp = client.get("/api/v1/market/daily", params={"codes": codes}, headers=AUTH)

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "too_many_codes"


def test_market_daily_rejects_unknown_adjust(client):
    resp = client.get(
        "/api/v1/market/daily",
        params={"codes": "000300", "adjust": "split"},
        headers=AUTH,
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_parameter"


@pytest.mark.parametrize("value", ["2024/01/01", "20240101", "not-a-date"])
def test_market_daily_rejects_non_iso_date(client, value):
    resp = client.get(
        "/api/v1/market/daily",
        params={"codes": "000300", "start": value},
        headers=AUTH,
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_date"


def test_market_daily_rejects_reversed_date_range(client):
    resp = client.get(
        "/api/v1/market/daily",
        params={"codes": "000300", "start": "2024-12-31", "end": "2024-01-01"},
        headers=AUTH,
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_range"


@pytest.mark.parametrize("limit", [0, -1, 50001])
def test_market_daily_rejects_limit_out_of_range(client, limit):
    resp = client.get(
        "/api/v1/market/daily",
        params={"codes": "000300", "limit": limit},
        headers=AUTH,
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_limit"


# ---------------------------------------------------------------------
# /market/daily 正常路径 + CSV
# ---------------------------------------------------------------------
def test_market_daily_returns_envelope_and_rows(client, monkeypatch):
    calls: list[dict] = []

    def fake_fetch(conn, *, codes, adjust, start, end, limit):
        calls.append(
            {
                "codes": codes,
                "adjust": adjust,
                "start": start,
                "end": end,
                "limit": limit,
            }
        )
        return [_market_row()], [], False

    monkeypatch.setattr(public_api, "_fetch_market_daily", fake_fetch)

    resp = client.get(
        "/api/v1/market/daily",
        params={
            "codes": "000300, 600036",
            "start": "2024-01-01",
            "end": "2024-12-31",
            "adjust": "hfq",
        },
        headers=AUTH,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"data", "meta", "error"}
    assert body["error"] is None
    row = body["data"][0]
    assert row["code"] == "000300"
    assert row["date"] == "2024-01-02"
    assert {"open", "high", "low", "close", "ret"} <= set(row)
    assert body["meta"]["rows"] == 1
    assert body["meta"]["adjust"] == "hfq"
    assert body["meta"]["truncated"] is False
    assert calls == [
        {
            "codes": ["000300", "600036"],
            "adjust": "hfq",
            "start": date(2024, 1, 1),
            "end": date(2024, 12, 31),
            "limit": 50000,
        }
    ]


def test_market_daily_unknown_code_returns_404(client, monkeypatch):
    monkeypatch.setattr(
        public_api,
        "_fetch_market_daily",
        lambda conn, **kwargs: ([], ["999999"], False),
    )

    resp = client.get(
        "/api/v1/market/daily", params={"codes": "999999"}, headers=AUTH
    )

    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "unknown_code"
    assert body["error"]["codes"] == ["999999"]


def test_market_daily_csv_via_format_has_bom_and_header(client, monkeypatch):
    monkeypatch.setattr(
        public_api,
        "_fetch_market_daily",
        lambda conn, **kwargs: ([_market_row()], [], False),
    )

    resp = client.get(
        "/api/v1/market/daily",
        params={"codes": "000300", "format": "csv"},
        headers=AUTH,
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert resp.content.startswith(b"\xef\xbb\xbf")
    text = resp.content.decode("utf-8-sig")
    header = text.splitlines()[0]
    assert header.split(",") == [
        "code",
        "source",
        "date",
        "open",
        "high",
        "low",
        "close",
        "ret",
    ]
    assert "000300" in text.splitlines()[1]


def test_market_daily_csv_via_accept_header(client, monkeypatch):
    monkeypatch.setattr(
        public_api,
        "_fetch_market_daily",
        lambda conn, **kwargs: ([_market_row()], [], False),
    )

    resp = client.get(
        "/api/v1/market/daily",
        params={"codes": "000300"},
        headers={**AUTH, "Accept": "text/csv"},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert resp.content.startswith(b"\xef\xbb\xbf")


def test_invalid_format_returns_400(client):
    resp = client.get(
        "/api/v1/market/daily",
        params={"codes": "000300", "format": "xml"},
        headers=AUTH,
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_parameter"


def test_fastapi_validation_error_is_wrapped_in_envelope(client):
    """非整数 limit 由 FastAPI 在进入端点前拦截，也必须返回统一信封。"""

    resp = client.get(
        "/api/v1/market/daily",
        params={"codes": "000300", "limit": "abc"},
        headers=AUTH,
    )

    assert resp.status_code == 422
    body = resp.json()
    assert set(body) == {"data", "meta", "error"}
    assert body["data"] is None
    assert body["error"]["code"] == "validation_error"


# ---------------------------------------------------------------------
# /index/valuation
# ---------------------------------------------------------------------
def test_index_valuation_filters_fields_and_returns_envelope(client, monkeypatch):
    calls: list[dict] = []

    def fake_fetch(conn, *, codes, fields, start, end, limit):
        calls.append({"codes": codes, "fields": fields, "limit": limit})
        return (
            [
                {
                    "code": "000300",
                    "date": date(2024, 1, 2),
                    "pb": 1.25,
                    "erp": 0.043,
                }
            ],
            [],
            False,
        )

    monkeypatch.setattr(public_api, "_fetch_index_valuation", fake_fetch)

    resp = client.get(
        "/api/v1/index/valuation",
        params={"codes": "000300", "fields": "pb,erp"},
        headers=AUTH,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == [
        {"code": "000300", "date": "2024-01-02", "pb": 1.25, "erp": 0.043}
    ]
    assert body["meta"]["fields"] == ["pb", "erp"]
    assert calls == [{"codes": ["000300"], "fields": ["pb", "erp"], "limit": 50000}]


def test_index_valuation_rejects_unknown_field(client):
    resp = client.get(
        "/api/v1/index/valuation",
        params={"codes": "000300", "fields": "pe_ttm,roe_ttm"},
        headers=AUTH,
    )

    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "invalid_parameter"
    assert body["error"]["invalid"] == ["roe_ttm"]


def test_index_valuation_unknown_code_returns_404(client, monkeypatch):
    monkeypatch.setattr(
        public_api,
        "_fetch_index_valuation",
        lambda conn, **kwargs: ([], ["000999"], False),
    )

    resp = client.get(
        "/api/v1/index/valuation", params={"codes": "000999"}, headers=AUTH
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "unknown_code"


# ---------------------------------------------------------------------
# /index/percentile
# ---------------------------------------------------------------------
def test_index_percentile_passes_defaults_and_returns_rows(client, monkeypatch):
    calls: list[dict] = []

    def fake_fetch(conn, *, codes, metrics, windows, limit):
        calls.append({"codes": codes, "metrics": metrics, "windows": windows})
        return (
            [
                {
                    "code": "000300",
                    "as_of": date(2026, 11, 13),
                    "metric": "pe_ttm",
                    "window": "5y",
                    "pct": 0.42,
                    "mean": 20.1,
                    "sd": 3.2,
                    "p20": 17.5,
                    "p50": 19.8,
                    "p80": 22.4,
                    "min_value": 12.0,
                    "max_value": 30.0,
                    "sample_size": 1215,
                }
            ],
            [],
            False,
        )

    monkeypatch.setattr(public_api, "_fetch_index_percentile", fake_fetch)

    resp = client.get(
        "/api/v1/index/percentile", params={"codes": "000300"}, headers=AUTH
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"][0]["pct"] == 0.42
    assert body["data"][0]["as_of"] == "2026-11-13"
    assert body["meta"]["metrics"] == ["pe_ttm"]
    assert body["meta"]["windows"] == ["5y"]
    assert calls == [
        {"codes": ["000300"], "metrics": ["pe_ttm"], "windows": ["5y"]}
    ]


@pytest.mark.parametrize(
    "params,invalid",
    [
        ({"metrics": "pe_ttm,roe_ttm"}, "roe_ttm"),
        ({"windows": "5y,2y"}, "2y"),
    ],
)
def test_index_percentile_rejects_invalid_metric_or_window(client, params, invalid):
    resp = client.get(
        "/api/v1/index/percentile",
        params={"codes": "000300", **params},
        headers=AUTH,
    )

    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "invalid_parameter"
    assert body["error"]["invalid"] == [invalid]


# ---------------------------------------------------------------------
# /index/detail
# ---------------------------------------------------------------------
def _patch_detail_repo(monkeypatch, detail):
    repo = MagicMock()
    repo.get_index_detail.return_value = detail
    repo.get_index_constituents.return_value = [
        {"stock_code": "600036", "name": "招商银行", "weight": 2.1}
    ]
    repo.get_index_tracker_funds.return_value = [
        {"fund_code": "512800", "name": "银行ETF", "aum": 1.2e10}
    ]
    monkeypatch.setattr(
        public_api.repositories_valuation, "get_index_detail", repo.get_index_detail
    )
    monkeypatch.setattr(
        public_api.repositories_valuation,
        "get_index_constituents",
        repo.get_index_constituents,
    )
    monkeypatch.setattr(
        public_api.repositories_valuation,
        "get_index_tracker_funds",
        repo.get_index_tracker_funds,
    )
    return repo


def test_index_detail_returns_profile_constituents_and_funds(client, monkeypatch):
    repo = _patch_detail_repo(
        monkeypatch,
        {"index_code": "930641", "name": "中证中药", "trade_date": date(2026, 11, 13)},
    )

    resp = client.get(
        "/api/v1/index/detail", params={"code": "930641"}, headers=AUTH
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["index_code"] == "930641"
    assert body["data"]["constituents"][0]["stock_code"] == "600036"
    assert body["data"]["tracker_funds"][0]["fund_code"] == "512800"
    assert body["meta"]["rows"] == 1
    assert body["meta"]["as_of"] == "2026-11-13"
    repo.get_index_detail.assert_called_once()
    repo.get_index_constituents.assert_called_once()
    repo.get_index_tracker_funds.assert_called_once()


def test_index_detail_unknown_returns_404(client, monkeypatch):
    _patch_detail_repo(monkeypatch, None)

    resp = client.get(
        "/api/v1/index/detail", params={"code": "999999"}, headers=AUTH
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "index_not_found"


def test_index_detail_requires_code(client):
    resp = client.get("/api/v1/index/detail", headers=AUTH)

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "missing_parameter"


# ---------------------------------------------------------------------
# /market/bond-yield
# ---------------------------------------------------------------------
def test_bond_yield_returns_envelope(client, monkeypatch):
    calls: list[dict] = []

    def fake_fetch(conn, *, start, end, limit):
        calls.append({"start": start, "end": end, "limit": limit})
        return (
            [
                {
                    "date": date(2024, 1, 2),
                    "value": 2.56,
                    "unit": "%",
                    "source": "bond_zh_us_rate",
                }
            ],
            False,
        )

    monkeypatch.setattr(public_api, "_fetch_bond_yield", fake_fetch)

    resp = client.get(
        "/api/v1/market/bond-yield",
        params={"start": "2024-01-01", "end": "2024-12-31"},
        headers=AUTH,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"][0]["value"] == 2.56
    assert body["meta"]["series_code"] == "cn_10y_yield"
    assert calls == [
        {"start": date(2024, 1, 1), "end": date(2024, 12, 31), "limit": 50000}
    ]


def test_bond_yield_rejects_invalid_date(client):
    resp = client.get(
        "/api/v1/market/bond-yield",
        params={"start": "2024-13-01"},
        headers=AUTH,
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_date"


# ---------------------------------------------------------------------
# 信封 / 截断
# ---------------------------------------------------------------------
def test_meta_reports_truncation(client, monkeypatch):
    monkeypatch.setattr(
        public_api,
        "_fetch_market_daily",
        lambda conn, **kwargs: ([_market_row()], [], True),
    )

    resp = client.get(
        "/api/v1/market/daily",
        params={"codes": "000300", "limit": 1},
        headers=AUTH,
    )

    assert resp.status_code == 200
    assert resp.json()["meta"]["truncated"] is True


def test_error_envelope_always_has_all_three_keys(client):
    resp = client.get(
        "/api/v1/index/valuation",
        params={"codes": "000300"},
        headers={"Authorization": "Bearer scope:none"},
    )

    body = resp.json()
    assert set(body) == {"data", "meta", "error"}
    assert body["data"] is None
    assert isinstance(body["meta"], dict)
    assert body["error"]["code"] == "forbidden"
