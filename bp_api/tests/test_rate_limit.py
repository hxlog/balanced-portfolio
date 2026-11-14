"""对外 API 限流与请求审计的单元测试。"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from bp_api import rate_limit


@pytest.fixture(autouse=True)
def _clean():
    rate_limit.reset()
    yield
    rate_limit.reset()


def test_limit_defaults_to_60(monkeypatch):
    monkeypatch.delenv("BP_API_RATE_LIMIT_RPM", raising=False)
    assert rate_limit.limit_per_minute() == 60


def test_limit_reads_env(monkeypatch):
    monkeypatch.setenv("BP_API_RATE_LIMIT_RPM", "3")
    assert rate_limit.limit_per_minute() == 3


def test_invalid_env_falls_back(monkeypatch):
    monkeypatch.setenv("BP_API_RATE_LIMIT_RPM", "abc")
    assert rate_limit.limit_per_minute() == 60


def test_check_allows_up_to_limit(monkeypatch):
    monkeypatch.setenv("BP_API_RATE_LIMIT_RPM", "3")
    for _ in range(3):
        rate_limit.check("token-a")


def test_check_raises_429_over_limit(monkeypatch):
    monkeypatch.setenv("BP_API_RATE_LIMIT_RPM", "2")
    rate_limit.check("token-b")
    rate_limit.check("token-b")
    with pytest.raises(HTTPException) as exc:
        rate_limit.check("token-b")
    assert exc.value.status_code == 429
    assert exc.value.headers and "Retry-After" in exc.value.headers
    assert exc.value.detail["code"] == "rate_limited"
    assert exc.value.detail["limit_per_minute"] == 2


def test_windows_are_per_token(monkeypatch):
    monkeypatch.setenv("BP_API_RATE_LIMIT_RPM", "1")
    rate_limit.check("t1")
    rate_limit.check("t2")  # 不同 token 互不影响
    with pytest.raises(HTTPException):
        rate_limit.check("t1")


def test_reset_clears_window(monkeypatch):
    monkeypatch.setenv("BP_API_RATE_LIMIT_RPM", "1")
    rate_limit.check("t3")
    with pytest.raises(HTTPException):
        rate_limit.check("t3")
    rate_limit.reset()
    rate_limit.check("t3")
