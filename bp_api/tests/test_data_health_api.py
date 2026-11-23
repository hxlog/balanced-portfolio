"""管理端数据健康 API 测试（T12，TestClient + 打桩，不连库）。"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from bp_api import data_health


class FakeCursor:
    def __init__(self, owner: "FakeConn") -> None:
        self.owner = owner

    def execute(self, sql: str, params: object = None) -> None:
        self.owner.statements.append((sql, params))

    def fetchall(self):
        item = self.owner.results.pop(0) if self.owner.results else []
        if item and isinstance(item, tuple):
            return [item]
        return item

    def fetchone(self):
        item = self.owner.results.pop(0) if self.owner.results else None
        if isinstance(item, list):
            return item[0] if item else None
        return item

    @property
    def description(self):
        return [SimpleNamespace(name=name) for name in self.owner.columns]

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


class FakeConn:
    def __init__(self, results: list, columns: list[str] | None = None) -> None:
        self.results = list(results)
        self.columns = list(columns or [])
        self.statements: list[tuple[str, object]] = []

    def cursor(self):
        return FakeCursor(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


def _user_dep(_authorization: str = Header(default="")) -> object:
    return SimpleNamespace(is_super_admin=True, is_admin=True, user_id=1)


def _client(monkeypatch: pytest.MonkeyPatch, conn: FakeConn | None = None, *, auth_ok: bool = True) -> TestClient:
    if auth_ok:
        monkeypatch.setattr(data_health.auth, "require_super_admin", _user_dep)
    if conn is not None:
        @contextmanager
        def _provide_conn():
            yield conn

        monkeypatch.setattr(data_health.db, "get_conn", _provide_conn)
    app = FastAPI()
    data_health.register_routes(app)
    return TestClient(app)


TODAY = date(2026, 11, 23)


def test_overview_requires_super_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch, auth_ok=False)
    response = client.get("/api/admin/data-health/overview")
    assert response.status_code == 401


def test_overview_ready_and_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn([
        [(TODAY,)],  # latest trading day
        [("a_stock", TODAY, 1, None), ("etf", date(2026, 11, 20), 2, None)],  # states
        [("a_stock", 3)],  # backlog
        [("a_stock", 1, TODAY, 1, "catching_up", 0.99, None)],  # last runs
        [(5200, 2700)],  # stock covered (A/HK)
        [(1380,)],  # etf covered
        [(25000,)],  # fund covered
        [(5227,)],  # a total
        [(2811,)],  # hk total
        [(1392,)],  # etf total
        [(28101,)],  # fund total
    ])
    client = _client(monkeypatch, conn)
    response = client.get("/api/admin/data-health/overview")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["latest_trading_date"] == "2026-11-23"
    by_name = {item["dataset"]: item for item in payload["datasets"]}
    assert by_name["a_stock"]["ready"] is True
    assert by_name["a_stock"]["backlog"] == 3
    assert by_name["etf"]["ready"] is False
    assert by_name["a_stock"]["coverage"] == {"covered": 5200, "total": 5227}
    assert by_name["fund_nav"]["coverage"] == {"covered": 25000, "total": 28101}


def test_runs_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn([[(7, "a_stock", TODAY, 1, "ok", 0.995, 1.0, 100, 0, None, None)]],
                    columns=["run_id", "dataset", "trade_date", "wave", "status",
                             "target_coverage", "achieved_coverage", "rows_written",
                             "errors", "started_at", "finished_at"])
    client = _client(monkeypatch, conn)
    response = client.get("/api/admin/data-health/runs?dataset=a_stock&limit=5")
    assert response.status_code == 200
    rows = response.json()["data"]
    assert rows[0]["run_id"] == 7 and rows[0]["trade_date"] == "2026-11-23"
    sql, params = conn.statements[0]
    assert "WHERE dataset = %s" in sql and params == ["a_stock", 5]


def test_sources_and_issues_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn([[]], columns=["stat_date"])
    client = _client(monkeypatch, conn)
    assert client.get("/api/admin/data-health/sources?days=3").status_code == 200
    conn2 = FakeConn([[]], columns=["issue_id"])
    client2 = _client(monkeypatch, conn2)
    assert client2.get("/api/admin/data-health/issues?limit=5").status_code == 200


def test_replay_accepts_and_runs_background_task(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(data_health, "_run_replay", lambda *args: calls.append(args))
    conn = FakeConn([])
    client = _client(monkeypatch, conn)
    response = client.post("/api/admin/data-health/replay", json={"dataset": "a_stock", "adjust": "hfq"})
    assert response.status_code == 200
    assert response.json()["data"]["accepted"] is True
    assert calls and calls[0][0] == "a_stock"


def test_replay_rejects_unknown_dataset(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch, FakeConn([]))
    response = client.post("/api/admin/data-health/replay", json={"dataset": "nope"})
    assert response.status_code == 200
    assert response.json()["error"]["code"] == "invalid_dataset"
