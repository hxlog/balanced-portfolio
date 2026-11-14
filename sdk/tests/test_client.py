"""bpdata SDK 单元测试。

全部用例离线运行：通过 monkeypatch 替换 ``bpdata.client._http_get``，
不发起任何真实网络请求。
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

SDK_DIR = Path(__file__).resolve().parents[1]
if str(SDK_DIR) not in sys.path:
    sys.path.insert(0, str(SDK_DIR))

import bpdata.client as client_mod  # noqa: E402
from bpdata import BpApiError, BpAuthError, BpRateLimitError, Client  # noqa: E402

BASE = "https://xushilu.com"


# ---------------------------------------------------------------------------
# 测试替身
# ---------------------------------------------------------------------------
def _envelope(data: Any, meta: dict[str, Any] | None = None) -> bytes:
    return json.dumps(
        {"data": data, "meta": meta or {}, "error": None}, ensure_ascii=False
    ).encode("utf-8")


def _error_envelope(
    code: str, message: str, meta: dict[str, Any] | None = None
) -> bytes:
    return json.dumps(
        {"data": None, "meta": meta or {}, "error": {"code": code, "message": message}},
        ensure_ascii=False,
    ).encode("utf-8")


def _resp(
    status: int = 200,
    body: bytes = b"",
    headers: dict[str, str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(status=status, headers=headers or {}, body=body)


class _Transport:
    """按顺序返回预置响应，并记录每次调用参数。"""

    def __init__(self, *responses: Any) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        url: str,
        params: dict[str, str],
        headers: dict[str, str],
        timeout: float,
    ) -> SimpleNamespace:
        self.calls.append(
            {
                "url": url,
                "params": dict(params),
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        if not self._responses:
            raise AssertionError(f"unexpected extra HTTP call #{len(self.calls)}")
        return self._responses.pop(0)


@pytest.fixture
def sleep_spy(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(client_mod.time, "sleep", slept.append)
    return slept


# ---------------------------------------------------------------------------
# 成功 / 参数拼接
# ---------------------------------------------------------------------------
def test_daily_success_parses_envelope_and_builds_query(
    monkeypatch: pytest.MonkeyPatch, sleep_spy: list[float]
) -> None:
    rows = [{"code": "000300", "date": "2024-01-02", "close": 3430.5}]
    transport = _Transport(
        _resp(
            200,
            _envelope(
                rows, {"rows": 1, "as_of": "2024-01-02", "truncated": False}
            ),
        )
    )
    monkeypatch.setattr(client_mod, "_http_get", transport)

    client = Client("bp_live_test")
    result = client.daily(
        ["000300", "600036"], start=dt.date(2024, 1, 1), end="2024-12-31"
    )

    assert result == rows
    call = transport.calls[0]
    assert call["url"] == f"{BASE}/api/v1/market/daily"
    assert call["params"] == {
        "codes": "000300,600036",
        "start": "2024-01-01",
        "end": "2024-12-31",
        "adjust": "hfq",
    }
    assert call["headers"]["Authorization"] == "Bearer bp_live_test"
    assert call["headers"]["Accept"] == "application/json"
    assert call["timeout"] == 30
    assert client.last_meta == {
        "rows": 1,
        "as_of": "2024-01-02",
        "truncated": False,
    }
    assert sleep_spy == []


def test_base_url_trailing_slash_and_custom_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _Transport(_resp(200, _envelope({"index_code": "930641"})))
    monkeypatch.setattr(client_mod, "_http_get", transport)

    client = Client("tok", base_url="https://example.test/", timeout=5)
    detail = client.detail("930641")

    assert detail == {"index_code": "930641"}
    assert transport.calls[0]["url"] == "https://example.test/api/v1/index/detail"
    assert transport.calls[0]["timeout"] == 5


def test_comma_separated_codes_are_passed_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _Transport(_resp(200, _envelope([])))
    monkeypatch.setattr(client_mod, "_http_get", transport)

    Client("tok").daily("000300,600036", adjust="qfq")

    assert transport.calls[0]["params"] == {
        "codes": "000300,600036",
        "adjust": "qfq",
    }


def test_valuation_joins_fields_and_omits_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [{"code": "000300", "date": "2024-01-02", "pe_ttm": 12.3}]
    transport = _Transport(_resp(200, _envelope(rows)))
    monkeypatch.setattr(client_mod, "_http_get", transport)

    result = Client("tok").valuation(
        "000300", start="2024-01-01", fields=["pe_ttm", "pb"]
    )

    assert result == rows
    assert transport.calls[0]["url"] == f"{BASE}/api/v1/index/valuation"
    assert transport.calls[0]["params"] == {
        "codes": "000300",
        "start": "2024-01-01",
        "fields": "pe_ttm,pb",
    }


def test_percentile_joins_metrics_and_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _Transport(_resp(200, _envelope([])))
    monkeypatch.setattr(client_mod, "_http_get", transport)

    Client("tok").percentile(
        ("000300", "930641"),
        metrics=("pe_ttm", "pb"),
        windows="5y,10y",
    )

    assert transport.calls[0]["url"] == f"{BASE}/api/v1/index/percentile"
    assert transport.calls[0]["params"] == {
        "codes": "000300,930641",
        "metrics": "pe_ttm,pb",
        "windows": "5y,10y",
    }


def test_detail_returns_dict_and_strips_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = {"index_code": "930641", "name": "中证白酒"}
    transport = _Transport(_resp(200, _envelope(data)))
    monkeypatch.setattr(client_mod, "_http_get", transport)

    result = Client("tok").detail(" 930641 ")

    assert result == data
    assert transport.calls[0]["url"] == f"{BASE}/api/v1/index/detail"
    assert transport.calls[0]["params"] == {"code": "930641"}


def test_bond_yield_omits_empty_params(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _Transport(_resp(200, _envelope([])))
    monkeypatch.setattr(client_mod, "_http_get", transport)

    Client("tok").bond_yield(start="2024-01-01")

    assert transport.calls[0]["url"] == f"{BASE}/api/v1/market/bond-yield"
    assert transport.calls[0]["params"] == {"start": "2024-01-01"}


def test_sdk_never_requests_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _Transport(
        _resp(200, _envelope([])),
        _resp(200, _envelope([])),
        _resp(200, _envelope([])),
        _resp(200, _envelope({})),
        _resp(200, _envelope([])),
    )
    monkeypatch.setattr(client_mod, "_http_get", transport)

    client = Client("tok")
    client.daily("000300")
    client.valuation("000300")
    client.percentile("000300")
    client.detail("930641")
    client.bond_yield()

    assert len(transport.calls) == 5
    assert all("format" not in call["params"] for call in transport.calls)
    assert all(
        call["headers"]["Accept"] == "application/json" for call in transport.calls
    )


# ---------------------------------------------------------------------------
# 鉴权 / 错误
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors_are_not_retried(
    monkeypatch: pytest.MonkeyPatch,
    sleep_spy: list[float],
    status: int,
) -> None:
    code = "unauthorized" if status == 401 else "forbidden"
    transport = _Transport(_resp(status, _error_envelope(code, "鉴权失败")))
    monkeypatch.setattr(client_mod, "_http_get", transport)

    with pytest.raises(BpAuthError) as excinfo:
        Client("tok").daily("000300")

    assert excinfo.value.status == status
    assert excinfo.value.code == code
    assert excinfo.value.message == "鉴权失败"
    assert len(transport.calls) == 1
    assert sleep_spy == []


def test_422_envelope_error_raises_bp_api_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = json.dumps(
        {
            "data": None,
            "meta": {"details": []},
            "error": {"code": "validation_error", "message": "参数校验失败"},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    transport = _Transport(_resp(422, body))
    monkeypatch.setattr(client_mod, "_http_get", transport)

    with pytest.raises(BpApiError) as excinfo:
        Client("tok").bond_yield()

    assert excinfo.value.status == 422
    assert excinfo.value.code == "validation_error"
    assert excinfo.value.message == "参数校验失败"
    assert len(transport.calls) == 1


def test_404_unknown_code_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _Transport(
        _resp(404, _error_envelope("unknown_code", "以下指数代码不存在: 999999"))
    )
    monkeypatch.setattr(client_mod, "_http_get", transport)

    with pytest.raises(BpApiError) as excinfo:
        Client("tok").valuation("999999")

    assert excinfo.value.status == 404
    assert excinfo.value.code == "unknown_code"
    assert len(transport.calls) == 1


def test_non_json_error_body_still_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch, sleep_spy: list[float]
) -> None:
    transport = _Transport(
        *[_resp(502, b"<html>bad gateway</html>") for _ in range(4)]
    )
    monkeypatch.setattr(client_mod, "_http_get", transport)

    with pytest.raises(BpApiError) as excinfo:
        Client("tok").daily("000300")

    assert excinfo.value.status == 502
    assert excinfo.value.code == "server_error"
    assert len(transport.calls) == 4
    assert sleep_spy == [1.0, 2.0, 4.0]


# ---------------------------------------------------------------------------
# 重试
# ---------------------------------------------------------------------------
def test_429_honors_retry_after_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, sleep_spy: list[float]
) -> None:
    transport = _Transport(
        _resp(429, b"", {"Retry-After": "0.25"}),
        _resp(200, _envelope([{"date": "2024-01-02", "value": 2.1}])),
    )
    monkeypatch.setattr(client_mod, "_http_get", transport)

    result = Client("tok").bond_yield()

    assert result == [{"date": "2024-01-02", "value": 2.1}]
    assert len(transport.calls) == 2
    assert sleep_spy == [0.25]


def test_429_exhausts_three_retries_and_raises_rate_limit(
    monkeypatch: pytest.MonkeyPatch, sleep_spy: list[float]
) -> None:
    transport = _Transport(*[_resp(429, b"") for _ in range(4)])
    monkeypatch.setattr(client_mod, "_http_get", transport)

    with pytest.raises(BpRateLimitError) as excinfo:
        Client("tok").percentile("000300")

    assert excinfo.value.status == 429
    assert excinfo.value.retry_after is None
    assert len(transport.calls) == 4
    assert sleep_spy == [1.0, 2.0, 4.0]


def test_5xx_retries_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, sleep_spy: list[float]
) -> None:
    transport = _Transport(
        _resp(503, b"upstream unavailable"),
        _resp(200, _envelope([{"code": "000300"}])),
    )
    monkeypatch.setattr(client_mod, "_http_get", transport)

    result = Client("tok").daily("000300")

    assert result == [{"code": "000300"}]
    assert len(transport.calls) == 2
    assert sleep_spy == [1.0]


def test_5xx_exhausts_retries_and_raises_api_error(
    monkeypatch: pytest.MonkeyPatch, sleep_spy: list[float]
) -> None:
    transport = _Transport(*[_resp(500, b"boom") for _ in range(4)])
    monkeypatch.setattr(client_mod, "_http_get", transport)

    with pytest.raises(BpApiError) as excinfo:
        Client("tok").daily("000300")

    assert excinfo.value.status == 500
    assert excinfo.value.code == "server_error"
    assert len(transport.calls) == 4
    assert sleep_spy == [1.0, 2.0, 4.0]


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------
def test_invalid_adjust_fails_before_http(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _Transport()
    monkeypatch.setattr(client_mod, "_http_get", transport)

    with pytest.raises(ValueError, match="adjust"):
        Client("tok").daily("000300", adjust="bad")

    assert transport.calls == []


def test_empty_token_is_rejected() -> None:
    with pytest.raises(ValueError, match="token"):
        Client("   ")


# ---------------------------------------------------------------------------
# DataFrame 辅助方法
# ---------------------------------------------------------------------------
def test_daily_frame_without_pandas_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "pandas", None)
    transport = _Transport()
    monkeypatch.setattr(client_mod, "_http_get", transport)

    with pytest.raises(ImportError, match="pandas"):
        Client("tok").daily_frame("000300")

    assert transport.calls == []


def test_frames_build_dataframes_with_stub_pandas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDataFrame:
        def __init__(self, rows: list[dict[str, Any]]) -> None:
            self.rows = rows

    monkeypatch.setitem(
        sys.modules, "pandas", SimpleNamespace(DataFrame=FakeDataFrame)
    )
    transport = _Transport(
        _resp(200, _envelope([{"code": "000300", "date": "2024-01-02"}])),
        _resp(
            200,
            _envelope(
                [{"code": "000300", "date": "2024-01-02", "pe_ttm": 12.3}]
            ),
        ),
    )
    monkeypatch.setattr(client_mod, "_http_get", transport)

    client = Client("tok")
    daily_df = client.daily_frame("000300")
    valuation_df = client.valuation_frame("000300")

    assert isinstance(daily_df, FakeDataFrame)
    assert daily_df.rows == [{"code": "000300", "date": "2024-01-02"}]
    assert isinstance(valuation_df, FakeDataFrame)
    assert valuation_df.rows == [
        {"code": "000300", "date": "2024-01-02", "pe_ttm": 12.3}
    ]


# ---------------------------------------------------------------------------
# 无 requests 时的 urllib 兜底
# ---------------------------------------------------------------------------
def test_http_get_uses_requests_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200
        headers = {"X-Test": "1"}
        content = b'{"ok": true}'

    def fake_get(
        url: str,
        params: dict[str, str],
        headers: dict[str, str],
        timeout: float,
    ) -> FakeResponse:
        captured.update(
            {"url": url, "params": params, "headers": headers, "timeout": timeout}
        )
        return FakeResponse()

    monkeypatch.setattr(client_mod, "_requests", SimpleNamespace(get=fake_get))

    response = client_mod._http_get(
        "https://x.test/api", {"a": "b"}, {"Authorization": "Bearer t"}, 12
    )

    assert response.status == 200
    assert response.headers["X-Test"] == "1"
    assert response.body == b'{"ok": true}'
    assert captured == {
        "url": "https://x.test/api",
        "params": {"a": "b"},
        "headers": {"Authorization": "Bearer t"},
        "timeout": 12,
    }


def test_http_get_falls_back_to_urllib(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_mod, "_requests", None)
    captured: dict[str, Any] = {}

    class FakeHTTPResponse:
        status = 200
        headers = {"Content-Type": "application/json"}

        def read(self) -> bytes:
            return b'{"data": []}'

        def __enter__(self) -> FakeHTTPResponse:
            return self

        def __exit__(self, *args: Any) -> bool:
            return False

    def fake_urlopen(request: Any, timeout: float) -> FakeHTTPResponse:
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return FakeHTTPResponse()

    monkeypatch.setattr(client_mod, "urlopen", fake_urlopen)

    response = client_mod._http_get(
        "https://x.test/api", {"codes": "000300"}, {"Authorization": "Bearer t"}, 9
    )

    assert response.status == 200
    assert response.body == b'{"data": []}'
    assert "codes=000300" in captured["url"]
    assert captured["timeout"] == 9
