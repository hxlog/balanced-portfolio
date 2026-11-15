"""P5 加密合约看板 — 完全离线单元测试（无网络 / 无真实 DB）。

覆盖:
  - 合约筛选: USDT 永续、按 quoteVolume 倒序取前 30、缺失 ticker 跳过
  - 快照解析: premiumIndex / openInterest / 多空比 / taker 比 / OI 历史
  - 缺失值: 不补 0（落库 NULL），缺 markPrice 跳过整条合约
  - 分位: 30/90/180 天窗口，复用 quant/valuation.percentile 的中点 rank 口径
  - 代理: BP_BINANCE_PROXY_URL 存在时走 ``?path=``，未配置时直连 Binance
  - 容错: 单合约 / 单端点失败不中断整轮

运行: python -m pytest bp_api/tests/test_crypto_futures.py -q
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from bp_ingest import crypto_futures as cf

UTC = timezone.utc


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------

def _conn(rows: list[tuple] | None = None) -> tuple[MagicMock, MagicMock]:
    """伪造 psycopg 连接 / cursor（只关心 SQL 与参数，不连库）。"""
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = rows or []
    return conn, cur


def _symbol(
    symbol: str,
    *,
    base_asset: str = "BTC",
    quote_asset: str = "USDT",
    contract_type: str = "PERPETUAL",
    status: str = "TRADING",
    onboard_ms: int = 1_596_000_000_000,
) -> dict:
    return {
        "symbol": symbol,
        "baseAsset": base_asset,
        "quoteAsset": quote_asset,
        "contractType": contract_type,
        "status": status,
        "onboardDate": onboard_ms,
    }


def _ticker(symbol: str, quote_volume: float) -> dict:
    return {"symbol": symbol, "quoteVolume": str(quote_volume)}


# ---------------------------------------------------------------------------
# 合约筛选: 前 30 个 USDT 永续
# ---------------------------------------------------------------------------

def test_select_top_contracts_sorts_by_quote_volume_and_limits_30():
    symbols = [_symbol(f"COIN{i}USDT", base_asset=f"COIN{i}") for i in range(35)]
    tickers = [_ticker(f"COIN{i}USDT", 1000 - i) for i in range(35)]

    selected = cf._select_top_contracts({"symbols": symbols}, tickers)

    assert len(selected) == 30
    assert [c["contract_code"] for c in selected] == [
        f"COIN{i}USDT" for i in range(30)
    ]
    assert [c["oi_notional_rank"] for c in selected] == list(range(1, 31))
    assert selected[0]["base_asset"] == "COIN0"
    assert selected[0]["quote_asset"] == "USDT"
    assert selected[0]["is_active"] is True


def test_select_top_contracts_excludes_non_usdt_non_perpetual_and_inactive():
    symbols = [
        _symbol("BTCUSDT", base_asset="BTC"),
        _symbol("ETHUSDT", base_asset="ETH", status="SETTLING"),
        _symbol("BTCUSDC", base_asset="BTC", quote_asset="USDC"),
        _symbol("XRPUSDT", base_asset="XRP", contract_type="CURRENT_QUARTER"),
    ]
    tickers = [_ticker(s["symbol"], 9999) for s in symbols]

    selected = cf._select_top_contracts({"symbols": symbols}, tickers)

    assert [c["contract_code"] for c in selected] == ["BTCUSDT"]


def test_select_top_contracts_skips_missing_or_invalid_ticker_volume():
    symbols = [
        _symbol("AAAUSDT", base_asset="AAA"),
        _symbol("BBBUSDT", base_asset="BBB"),
        _symbol("CCCUSDT", base_asset="CCC"),
        _symbol("DDDUSDT", base_asset="DDD"),
    ]
    tickers = [
        _ticker("AAAUSDT", 10),
        # BBBUSDT 缺失 ticker
        _ticker("CCCUSDT", 0),
        {"symbol": "DDDUSDT", "quoteVolume": "not-a-number"},
    ]

    selected = cf._select_top_contracts({"symbols": symbols}, tickers)

    assert [c["contract_code"] for c in selected] == ["AAAUSDT"]


def test_select_top_contracts_parses_onboard_date_as_utc():
    ms = 1_596_000_000_000
    symbols = [_symbol("BTCUSDT", onboard_ms=ms)]
    tickers = [_ticker("BTCUSDT", 1)]

    selected = cf._select_top_contracts({"symbols": symbols}, tickers)

    assert selected[0]["listed_at"] == datetime.fromtimestamp(ms / 1000, tz=UTC)


def test_select_top_contracts_handles_empty_or_malformed_payloads():
    assert cf._select_top_contracts({}, []) == []
    assert cf._select_top_contracts({"symbols": None}, None) == []


def test_fetch_contracts_calls_both_endpoints_and_upserts(monkeypatch):
    exchange_info = {
        "symbols": [
            _symbol("BTCUSDT", base_asset="BTC"),
            _symbol("ETHUSDT", base_asset="ETH"),
        ]
    }
    tickers = [_ticker("BTCUSDT", 500), _ticker("ETHUSDT", 900)]
    calls: list[tuple[str, dict]] = []

    def fake_get(path: str, params: dict | None = None, **_kw):
        calls.append((path, params or {}))
        if path == "/fapi/v1/exchangeInfo":
            return exchange_info
        if path == "/fapi/v1/ticker/24hr":
            return tickers
        raise AssertionError(path)

    monkeypatch.setattr(cf, "_get_json", fake_get)
    conn, cur = _conn()

    contracts = cf.fetch_contracts(conn)

    assert [c["contract_code"] for c in contracts] == ["ETHUSDT", "BTCUSDT"]
    assert [c[0] for c in calls] == [
        "/fapi/v1/exchangeInfo",
        "/fapi/v1/ticker/24hr",
    ]
    sql, payload = cur.executemany.call_args.args
    assert "ON CONFLICT (contract_code)" in sql
    assert len(payload) == 2


# ---------------------------------------------------------------------------
# 快照解析
# ---------------------------------------------------------------------------

def test_parse_snapshot_maps_all_fields():
    premium = {
        "symbol": "BTCUSDT",
        "markPrice": "100.5",
        "indexPrice": "100.0",
        "lastFundingRate": "0.0001",
    }
    open_interest = {"symbol": "BTCUSDT", "openInterest": "1000"}
    long_short = [
        {"symbol": "BTCUSDT", "longShortRatio": "1.10", "timestamp": 1},
        {"symbol": "BTCUSDT", "longShortRatio": "1.50", "timestamp": 2},
    ]
    taker = [
        {"buySellRatio": "0.90", "timestamp": 1},
        {"buySellRatio": "0.80", "timestamp": 2},
    ]
    oi_hist = [
        {"sumOpenInterest": "990", "sumOpenInterestValue": "99500", "timestamp": 1},
        {"sumOpenInterest": "1000", "sumOpenInterestValue": "100500", "timestamp": 2},
    ]

    row = cf._parse_snapshot(
        "BTCUSDT", premium, open_interest, long_short, taker, oi_hist
    )

    assert row is not None
    assert row["contract_code"] == "BTCUSDT"
    assert row["mark_price"] == pytest.approx(100.5)
    assert row["index_price"] == pytest.approx(100.0)
    assert row["oi_contracts"] == pytest.approx(1000.0)
    # 名义 OI 用 当前 OI × markPrice（USDT 本位永续）
    assert row["oi_notional"] == pytest.approx(100_500.0)
    assert row["long_short_ratio"] == pytest.approx(1.50)  # 取数组最后一个
    assert row["taker_buy_sell_ratio"] == pytest.approx(0.80)
    assert row["basis_pct"] == pytest.approx(0.5)


def test_parse_snapshot_missing_optional_fields_is_none_not_zero():
    """多空比 / taker 比 / OI 缺失时写 NULL，绝不补 0。"""
    row = cf._parse_snapshot(
        "BTCUSDT",
        {"markPrice": "100", "indexPrice": "100"},
        {},
        None,
        None,
        None,
    )

    assert row is not None
    assert row["oi_contracts"] is None
    assert row["oi_notional"] is None
    assert row["long_short_ratio"] is None
    assert row["taker_buy_sell_ratio"] is None
    assert row["basis_pct"] == pytest.approx(0.0)


def test_parse_snapshot_falls_back_to_oi_history():
    row = cf._parse_snapshot(
        "BTCUSDT",
        {"markPrice": "2", "indexPrice": "1"},
        {},  # openInterest 缺失
        None,
        None,
        [{"sumOpenInterest": "50", "sumOpenInterestValue": "100"}],
    )

    assert row is not None
    assert row["oi_contracts"] == pytest.approx(50.0)
    assert row["oi_notional"] == pytest.approx(100.0)  # 50 × 2


def test_parse_snapshot_missing_mark_price_skips_contract():
    assert cf._parse_snapshot("BTCUSDT", {}, {"openInterest": "1"}, None, None, None) is None
    assert cf._parse_snapshot("BTCUSDT", None, None, None, None, None) is None


def test_parse_snapshot_handles_zero_index_price_without_division_error():
    row = cf._parse_snapshot(
        "BTCUSDT",
        {"markPrice": "100", "indexPrice": "0"},
        None,
        None,
        None,
        None,
    )
    assert row is not None
    assert row["basis_pct"] is None


def test_parse_snapshot_rejects_nan_and_non_finite_numbers():
    row = cf._parse_snapshot(
        "BTCUSDT",
        {"markPrice": "NaN", "indexPrice": "100"},
        None,
        None,
        None,
        None,
    )
    assert row is None


# ---------------------------------------------------------------------------
# 5 分钟桶
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "ts,expected",
    [
        (datetime(2026, 11, 14, 12, 0, 0, tzinfo=UTC), datetime(2026, 11, 14, 12, 0, tzinfo=UTC)),
        (datetime(2026, 11, 14, 12, 4, 59, tzinfo=UTC), datetime(2026, 11, 14, 12, 0, tzinfo=UTC)),
        (datetime(2026, 11, 14, 12, 5, 0, tzinfo=UTC), datetime(2026, 11, 14, 12, 5, tzinfo=UTC)),
        (datetime(2026, 11, 14, 12, 7, 31, tzinfo=UTC), datetime(2026, 11, 14, 12, 5, tzinfo=UTC)),
    ],
)
def test_floor_to_5m(ts, expected):
    assert cf._floor_to_5m(ts) == expected


def test_floor_to_5m_requires_aware_datetime():
    with pytest.raises(ValueError):
        cf._floor_to_5m(datetime(2026, 11, 14, 12, 0))


# ---------------------------------------------------------------------------
# 代理 URL 拼接
# ---------------------------------------------------------------------------

def test_allowed_paths_match_worker_proxy_whitelist():
    assert cf.ALLOWED_PATHS == {
        cf.EXCHANGE_INFO,
        cf.TICKER_24H,
        cf.PREMIUM_INDEX,
        cf.OPEN_INTEREST,
        cf.GLOBAL_LONG_SHORT,
        cf.TAKER_LONG_SHORT,
        cf.OI_HIST,
        cf.KLINE,
        cf.FUNDING_RATE,
        cf.TOP_ACCOUNT,
        cf.TOP_POSITION,
    }


def test_build_request_url_rejects_non_whitelisted_path(monkeypatch):
    monkeypatch.delenv("BP_BINANCE_PROXY_URL", raising=False)
    with pytest.raises(ValueError, match="unsupported Binance path"):
        cf.build_request_url("/fapi/v1/account")


def test_build_request_url_uses_proxy_path_param(monkeypatch):
    monkeypatch.setenv("BP_BINANCE_PROXY_URL", "https://bp-proxy.example.workers.dev/")

    url = cf.build_request_url(
        "/fapi/v1/openInterest", {"symbol": "BTCUSDT"}
    )

    assert url == (
        "https://bp-proxy.example.workers.dev/"
        "?path=/fapi/v1/openInterest&symbol=BTCUSDT"
    )


def test_build_request_url_direct_when_proxy_not_configured(monkeypatch):
    monkeypatch.delenv("BP_BINANCE_PROXY_URL", raising=False)

    url = cf.build_request_url(
        "/futures/data/openInterestHist",
        {"symbol": "BTCUSDT", "period": "5m", "limit": 500},
    )

    assert url == (
        "https://fapi.binance.com/futures/data/openInterestHist"
        "?symbol=BTCUSDT&period=5m&limit=500"
    )


def test_get_json_calls_installed_session_and_proxy_url(monkeypatch):
    monkeypatch.setenv("BP_BINANCE_PROXY_URL", "https://proxy.test")
    installed: list[bool] = []
    monkeypatch.setattr(cf, "install_hardened_session", lambda: installed.append(True))
    response = MagicMock(status_code=200)
    response.json.return_value = {"ok": True}
    session = MagicMock()
    session.get = MagicMock(return_value=response)
    monkeypatch.setattr(cf, "_session", lambda: session)

    payload = cf._get_json("/fapi/v1/premiumIndex", {"symbol": "BTCUSDT"})

    assert payload == {"ok": True}
    assert installed == [True]
    assert session.get.call_args.args[0] == (
        "https://proxy.test/?path=/fapi/v1/premiumIndex&symbol=BTCUSDT"
    )

def test_get_json_raises_on_http_error(monkeypatch):
    monkeypatch.delenv("BP_BINANCE_PROXY_URL", raising=False)
    monkeypatch.setattr(cf, "install_hardened_session", lambda: None)
    response = MagicMock(status_code=451)
    response.raise_for_status.side_effect = RuntimeError("451 Client Error")
    session = MagicMock()
    session.get = MagicMock(return_value=response)
    monkeypatch.setattr(cf, "_session", lambda: session)
    monkeypatch.setattr(cf.time, "sleep", lambda _s: None)

    with pytest.raises(RuntimeError, match="451"):
        cf._get_json("/fapi/v1/premiumIndex", retries=1)

# ---------------------------------------------------------------------------
# fetch_snapshot_5m: 并发、写库、异常隔离
# ---------------------------------------------------------------------------

def _snapshot_payload(path: str, symbol: str):
    if path == "/fapi/v1/premiumIndex":
        return {"symbol": symbol, "markPrice": "100", "indexPrice": "99"}
    if path == "/fapi/v1/openInterest":
        return {"symbol": symbol, "openInterest": "10"}
    if path == "/futures/data/globalLongShortAccountRatio":
        return [{"symbol": symbol, "longShortRatio": "1.2"}]
    if path == "/futures/data/takerlongshortRatio":
        return [{"buySellRatio": "0.9"}]
    if path == "/futures/data/openInterestHist":
        return [{"sumOpenInterest": "10", "sumOpenInterestValue": "1000"}]
    raise AssertionError(path)


def test_fetch_snapshot_5m_parses_and_upserts(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_get(path: str, params: dict | None = None, **_kw):
        params = params or {}
        calls.append((path, params))
        return _snapshot_payload(path, params["symbol"])

    monkeypatch.setattr(cf, "_get_json", fake_get)
    conn, cur = _conn()
    contracts = [{"contract_code": "BTCUSDT"}, {"contract_code": "ETHUSDT"}]
    captured = datetime(2026, 11, 14, 12, 7, 31, tzinfo=UTC)

    rows = cf.fetch_snapshot_5m(contracts, conn, captured_at=captured)

    assert [r["contract_code"] for r in rows] == ["BTCUSDT", "ETHUSDT"]
    assert all(r["captured_at"] == datetime(2026, 11, 14, 12, 5, tzinfo=UTC) for r in rows)
    assert all(r["oi_notional"] == pytest.approx(1000.0) for r in rows)
    assert len(calls) == 14  # 2 合约 × 7 端点
    assert {p for p, _ in calls} == {
        "/fapi/v1/premiumIndex",
        "/fapi/v1/openInterest",
        "/futures/data/globalLongShortAccountRatio",
        "/futures/data/takerlongshortRatio",
        "/futures/data/openInterestHist",
        "/futures/data/topLongShortAccountRatio",
        "/futures/data/topLongShortPositionRatio",
    }
    sql, payload = cur.executemany.call_args.args
    assert "ON CONFLICT (contract_code, captured_at)" in sql
    assert len(payload) == 2


def test_fetch_snapshot_5m_isolates_contract_failure(monkeypatch):
    def fake_get(path: str, params: dict | None = None, **_kw):
        symbol = (params or {})["symbol"]
        if symbol == "ETHUSDT":
            raise RuntimeError("upstream timeout")
        return _snapshot_payload(path, symbol)

    monkeypatch.setattr(cf, "_get_json", fake_get)
    contracts = [
        {"contract_code": "BTCUSDT"},
        {"contract_code": "ETHUSDT"},
        {"contract_code": "SOLUSDT"},
    ]

    rows = cf.fetch_snapshot_5m(contracts, conn=None)

    assert [r["contract_code"] for r in rows] == ["BTCUSDT", "SOLUSDT"]


def test_fetch_snapshot_5m_keeps_row_when_optional_endpoint_fails(monkeypatch):
    def fake_get(path: str, params: dict | None = None, **_kw):
        symbol = (params or {})["symbol"]
        if path == "/futures/data/takerlongshortRatio":
            raise RuntimeError("taker endpoint down")
        return _snapshot_payload(path, symbol)

    monkeypatch.setattr(cf, "_get_json", fake_get)

    rows = cf.fetch_snapshot_5m([{"contract_code": "BTCUSDT"}], conn=None)

    assert len(rows) == 1
    assert rows[0]["taker_buy_sell_ratio"] is None  # 缺失即 NULL，不补 0
    assert rows[0]["mark_price"] == pytest.approx(100.0)


def test_fetch_snapshot_5m_empty_contracts_makes_no_requests(monkeypatch):
    get = MagicMock()
    monkeypatch.setattr(cf, "_get_json", get)

    assert cf.fetch_snapshot_5m([], conn=None) == []
    get.assert_not_called()


# ---------------------------------------------------------------------------
# 分位计算
# ---------------------------------------------------------------------------

def _daily_rows(
    contract: str,
    end: date,
    days: int,
    metric: str,
    values: dict[int, float | None],
) -> list[tuple]:
    """构造 compute_percentiles 的 SQL 返回行。

    行顺序: (contract_code, trade_date, mark_price, oi_notional,
             long_short_ratio, taker_buy_sell_ratio, basis_pct)
    """
    metric_index = {
        "mark_price": 2,
        "oi_notional": 3,
        "long_short_ratio": 4,
        "taker_buy_sell_ratio": 5,
        "basis_pct": 6,
    }
    rows: list[tuple] = []
    for i in range(days):
        d = end - timedelta(days=days - 1 - i)
        row = [contract, d, None, None, None, None, None]
        row[metric_index[metric]] = values.get(i)
        rows.append(tuple(row))
    return rows


def test_compute_percentiles_30_90_180_windows_use_midrank():
    end = date(2026, 11, 14)
    values = {i: float(i + 1) for i in range(200)}
    rows = _daily_rows("BTCUSDT", end, 200, "mark_price", values)
    conn, cur = _conn(rows)

    stats = cf.compute_percentiles(conn)

    assert stats["rows"] == 3
    assert stats["contracts"] == 1
    by_window = {p[2]: p for p in cur.executemany.call_args.args[1]}
    assert by_window[30][0] == "BTCUSDT"
    assert by_window[30][1] == "mark_price"
    assert by_window[30][3] == end
    # 30 日窗口: 171..200, 当前 200 → (29 + 0.5) / 30 * 100
    assert by_window[30][4] == pytest.approx(98.3333333333)
    assert by_window[30][5] == 30
    # 90 日: 111..200 → (89 + 0.5) / 90 * 100
    assert by_window[90][4] == pytest.approx(99.4444444444)
    assert by_window[90][5] == 90
    # 180 日: 21..200 → (179 + 0.5) / 180 * 100
    assert by_window[180][4] == pytest.approx(99.7222222222)
    assert by_window[180][5] == 180
    assert "ON CONFLICT (contract_code, metric, window_days, as_of)" in cur.executemany.call_args.args[0]


def test_compute_percentiles_excludes_nulls_from_sample_size():
    end = date(2026, 11, 14)
    # 24 天里 3 天为 NULL、21 天为有效值 1..21（满足 30 天窗口的 20 样本门槛），当前值 = 21
    raw = [
        float(i + 1) for i in range(21)
    ]
    null_slots = {5, 12, 18}
    values: dict[int, float | None] = {}
    valid_index = 0
    for offset in range(24):
        if offset in null_slots:
            values[offset] = None
        else:
            values[offset] = raw[valid_index]
            valid_index += 1
    rows = _daily_rows("BTCUSDT", end, 24, "mark_price", values)
    conn, cur = _conn(rows)

    cf.compute_percentiles(conn)

    by_window = {p[2]: p for p in cur.executemany.call_args.args[1]}
    # 有效样本 21 个、当前值最大 → (20 + 0.5) / 21 * 100
    assert by_window[30][5] == 21
    assert by_window[30][4] == pytest.approx(97.6190476190, rel=1e-6)


def test_compute_percentiles_multiple_metrics_and_contracts():
    end = date(2026, 11, 14)
    rows = (
        _daily_rows("BTCUSDT", end, 40, "mark_price", {i: float(i + 1) for i in range(40)})
        + _daily_rows("BTCUSDT", end, 40, "oi_notional", {i: float(100 - i) for i in range(40)})
        + _daily_rows("ETHUSDT", end, 40, "basis_pct", {i: 0.01 * i for i in range(40)})
    )
    conn, cur = _conn(rows)

    stats = cf.compute_percentiles(conn)

    assert stats["contracts"] == 2
    # 40 个样本只满足 30 天窗口门槛（90d=60 / 180d=120），因此 3 组 metric × 1 窗口
    assert stats["rows"] == 3
    payload = cur.executemany.call_args.args[1]
    assert {p[0] for p in payload} == {"BTCUSDT", "ETHUSDT"}
    assert {p[1] for p in payload} == {"mark_price", "oi_notional", "basis_pct"}


def test_compute_percentiles_skips_all_null_metric_and_empty_input():
    end = date(2026, 11, 14)
    rows = _daily_rows("BTCUSDT", end, 40, "mark_price", {i: None for i in range(40)})
    conn, cur = _conn(rows)

    stats = cf.compute_percentiles(conn)

    assert stats["rows"] == 0
    cur.executemany.assert_not_called()

    conn2, _ = _conn([])
    assert cf.compute_percentiles(conn2)["rows"] == 0


def test_compute_percentiles_uses_each_contract_latest_date():
    rows = (
        _daily_rows(
            "BTCUSDT", date(2026, 11, 14), 35,
            "mark_price", {i: float(i + 1) for i in range(35)},
        )
        + _daily_rows(
            "ETHUSDT", date(2026, 11, 10), 35,
            "mark_price", {i: float(i + 1) for i in range(35)},
        )
    )
    conn, cur = _conn(rows)

    cf.compute_percentiles(conn)

    payload = cur.executemany.call_args.args[1]
    as_of_by_contract = {p[0]: p[3] for p in payload if p[2] == 30}
    assert as_of_by_contract == {
        "BTCUSDT": date(2026, 11, 14),
        "ETHUSDT": date(2026, 11, 10),
    }
