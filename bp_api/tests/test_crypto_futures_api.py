"""加密合约看板 API 的离线单测（打桩 DB，不连库）。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bp_api import cache, crypto_futures


class _Cursor:
    def __init__(self, rows_by_sql):
        self._rows_by_sql = rows_by_sql
        self._rows: list = []
        self.description = []
        self._sql = ""

    def execute(self, sql, params=None):
        self._sql = " ".join(sql.split())
        self._rows = []
        for marker, rows in self._rows_by_sql.items():
            if marker in self._sql:
                self._rows = rows
                break
        if self._rows:
            self.description = [type("D", (), {"name": name}) for name in self._rows[0].keys()]
        return None

    def fetchall(self):
        if not self._rows:
            return []
        columns = list(self._rows[0].keys())
        return [tuple(r[c] for c in columns) for r in self._rows]

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conn:
    def __init__(self, rows_by_sql):
        self._rows_by_sql = rows_by_sql

    def cursor(self):
        return _Cursor(self._rows_by_sql)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(cache, "get_json", lambda key: None)
    monkeypatch.setattr(cache, "set_json", lambda *a, **k: None)
    app = FastAPI()
    crypto_futures.register_routes(app)
    return TestClient(app)


def _patch_conn(monkeypatch, rows_by_sql):
    monkeypatch.setattr(crypto_futures.db, "get_conn", lambda: _Conn(rows_by_sql))


def _snapshot(code="BTCUSDT", mark=66000.0, oi=6.4e9, ls=3.07, taker=0.79, basis=-0.02):
    return {
        "contract_code": code,
        "base_asset": code.replace("USDT", ""),
        "oi_notional_rank": 1,
        "captured_at": datetime(2026, 11, 14, 13, 25, tzinfo=timezone.utc),
        "mark_price": mark,
        "index_price": mark * 1.0002,
        "oi_contracts": 97000.0,
        "oi_notional": oi,
        "long_short_ratio": ls,
        "taker_buy_sell_ratio": taker,
        "basis_pct": basis,
    }


def test_contracts_returns_envelope_and_percentiles(client, monkeypatch):
    rows = [_snapshot()]
    pcts = [
        {
            "contract_code": "BTCUSDT",
            "metric": "long_short_ratio",
            "window_days": 30,
            "pct": 88.5,
            "sample_size": 12,
            "as_of": datetime(2026, 11, 14, tzinfo=timezone.utc).date(),
        }
    ]
    _patch_conn(monkeypatch, {"SELECT * FROM (": rows, "FROM bp_crypto_futures_percentile": pcts})

    resp = client.get("/api/crypto/futures/contracts")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"][0]["contract_code"] == "BTCUSDT"
    assert body["data"][0]["percentiles"]["long_short_ratio:30"]["pct"] == 88.5
    assert body["meta"]["rows"] == 1


def test_contracts_rejects_invalid_limit(client):
    assert client.get("/api/crypto/futures/contracts?limit=0").status_code == 422
    assert client.get("/api/crypto/futures/contracts?limit=61").status_code == 422


def test_summary_computes_weighted_ratio_and_median(client, monkeypatch):
    rows = [
        _snapshot("BTCUSDT", oi=6.0e9, ls=3.0, taker=0.5),
        _snapshot("ETHUSDT", oi=2.0e9, ls=4.0, taker=1.5),
    ]
    rows[1]["oi_notional_rank"] = 2
    _patch_conn(monkeypatch, {"SELECT * FROM (": rows})

    resp = client.get("/api/crypto/futures/summary")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["contracts"] == 2
    assert data["total_oi_notional"] == pytest.approx(8.0e9)
    assert data["weighted_long_short_ratio"] == pytest.approx((6.0e9 * 3.0 + 2.0e9 * 4.0) / 8.0e9)
    assert data["median_taker_buy_sell_ratio"] == pytest.approx(1.0)


def test_series_404_unknown_contract(client, monkeypatch):
    _patch_conn(monkeypatch, {"SELECT 1 FROM bp_crypto_contract": []})

    resp = client.get("/api/crypto/futures/NOPEUSDT/series")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "contract_not_found"


def test_series_returns_rows(client, monkeypatch):
    known = [{"?column?": 1}]
    series = [
        {
            "captured_at": datetime(2026, 11, 14, 13, 25, tzinfo=timezone.utc),
            "mark_price": 66000.0,
            "oi_notional": 6.4e9,
            "long_short_ratio": 3.0,
            "taker_buy_sell_ratio": 0.8,
            "basis_pct": -0.02,
        }
    ]
    _patch_conn(monkeypatch, {"SELECT 1 FROM bp_crypto_contract": known, "FROM bp_crypto_futures_snapshot_5m": series})

    resp = client.get("/api/crypto/futures/BTCUSDT/series?hours=6")

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["rows"] == 1
    assert body["data"][0]["mark_price"] == 66000.0


def test_series_rejects_bad_hours(client):
    assert client.get("/api/crypto/futures/BTCUSDT/series?hours=0").status_code == 422
    assert client.get("/api/crypto/futures/BTCUSDT/series?hours=9999").status_code == 422
