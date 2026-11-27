"""scripts/index_quotes_free.py：多源解析/降级链/时间口径/覆盖统计（纯 mock，不触网不连库）。"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "index_quotes_free", ROOT / "scripts" / "index_quotes_free.py"
)
iqf = importlib.util.module_from_spec(_SPEC)
sys.modules["index_quotes_free"] = iqf  # dataclass 需要 cls.__module__ 可在 sys.modules 找到
_SPEC.loader.exec_module(iqf)  # type: ignore[union-attr]

CN = timezone(timedelta(hours=8))
TARGET = date(2026, 11, 27)


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
def test_parse_tencent_kline_order_is_open_close_high_low() -> None:
    payload = {
        "data": {
            "sh000300": {
                "day": [
                    ["2026-11-26", "3918.020", "3900.550", "3922.290", "3877.820", "159947235.000"],
                    ["2026-11-27", "3909.080", "4063.060", "4067.010", "3883.800", "256763815.000"],
                ]
            }
        }
    }
    bars = iqf.parse_tencent_kline(payload, "sh000300")
    assert len(bars) == 2
    assert bars[-1]["trade_date"] == TARGET
    assert bars[-1]["open"] == pytest.approx(3909.08)
    assert bars[-1]["close"] == pytest.approx(4063.06)
    assert bars[-1]["high"] == pytest.approx(4067.01)
    assert bars[-1]["low"] == pytest.approx(3883.80)


def test_parse_tencent_ignores_missing_and_dirty_nodes() -> None:
    assert iqf.parse_tencent_kline({"data": {}}, "sh000300") == []
    payload = {"data": {"sh000300": {"day": [["bad-date", "1", "2", "1", "1", "1"],
                                             ["2026-11-27", "1", "0", "1", "1", "1"]]}}}
    assert iqf.parse_tencent_kline(payload, "sh000300") == []


def test_parse_sina_and_csindex_and_em() -> None:
    sina = iqf.parse_sina_kline([
        {"day": "2026-11-27", "open": "3909.077", "high": "4067.014",
         "low": "3883.797", "close": "4063.064", "volume": "25676381500"},
        "not-a-dict",
    ])
    assert len(sina) == 1 and sina[0]["close"] == pytest.approx(4063.064)

    csindex = iqf.parse_csindex_perf({"data": [{
        "tradeDate": "20261127", "open": 3909.08, "high": 4067.01,
        "low": 3883.8, "close": 4063.06, "tradingVol": 2.5e8, "tradingValue": 6143.37,
    }]})
    assert csindex[0]["trade_date"] == TARGET and csindex[0]["volume"] == 250000000

    em = iqf.parse_em_kline({"data": {"klines": [
        "2026-11-27,3909.08,4063.06,4067.01,3883.80,256763815,614337436130.30,4.70"
    ]}})
    assert em[0]["close"] == pytest.approx(4063.06)
    assert em[0]["amount"] == pytest.approx(614337436130.30)


def test_market_prefixes_and_em_secids() -> None:
    assert iqf.market_prefixes("000300", "SH") == ["sh000300"]
    assert iqf.market_prefixes("399006", "SZ") == ["sz399006"]
    assert iqf.market_prefixes("000985", "CSI") == ["sh000985"]
    # 中证系 930/931/932/H3/950 无腾讯/新浪等价代码
    assert iqf.market_prefixes("930641", "CSI") == []
    assert iqf.market_prefixes("H30007", "CSI") == []
    assert iqf.market_prefixes("950049", "CSI") == []
    assert iqf.em_secid_candidates("930641", "CSI") == ["2.930641"]
    assert iqf.em_secid_candidates("000985", "CSI") == ["1.000985", "2.000985"]
    assert iqf.em_secid_candidates("HSI", "HK") == ["100.HSI", "124.HSI", "116.HSI"]


# ---------------------------------------------------------------------------
# 时间口径
# ---------------------------------------------------------------------------
def test_close_confirm_filters_intraday_today() -> None:
    day = date(2026, 11, 27)
    assert iqf.is_close_confirmed(day, datetime(2026, 11, 27, 14, 0, tzinfo=CN)) is False
    assert iqf.is_close_confirmed(day, datetime(2026, 11, 27, 15, 20, tzinfo=CN)) is True
    assert iqf.is_close_confirmed(date(2026, 11, 26), datetime(2026, 11, 27, 9, 0, tzinfo=CN)) is True
    assert iqf.is_close_confirmed(date(2026, 11, 28), datetime(2026, 11, 27, 16, 0, tzinfo=CN)) is False


class _CalendarCursor:
    def __init__(self, conn: "_CalendarConn") -> None:
        self.conn = conn

    def execute(self, sql: str, params: object = None) -> None:
        self.conn.queries.append((sql, params))

    def fetchone(self):
        return self.conn.rows.pop(0) if self.conn.rows else None

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _CalendarConn:
    def __init__(self, rows: list) -> None:
        self.rows = list(rows)
        self.queries: list = []

    def cursor(self):
        return _CalendarCursor(self)


def test_resolve_target_date_rolls_back_before_close() -> None:
    conn = _CalendarConn([(TARGET,), (date(2026, 11, 26),)])
    resolved = iqf.resolve_target_date(conn, datetime(2026, 11, 27, 14, 0, tzinfo=CN))
    assert resolved == date(2026, 11, 26)
    conn2 = _CalendarConn([(TARGET,)])
    resolved2 = iqf.resolve_target_date(conn2, datetime(2026, 11, 27, 16, 0, tzinfo=CN))
    assert resolved2 == TARGET


# ---------------------------------------------------------------------------
# 核心 run：降级链 / 覆盖统计 / dry-run / 当日过滤
# ---------------------------------------------------------------------------
class _FakeFetcher:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result or []
        self.error = error
        self.calls: list = []

    def __call__(self, symbol: str, market: str, start: date, end: date):
        self.calls.append((symbol, market, start, end))
        if self.error is not None:
            raise self.error
        return list(self.result)


def _bar(day: date, close: float = 10.0) -> dict:
    return {"trade_date": day, "open": close - 1, "high": close + 1,
            "low": close - 2, "close": close, "volume": 100, "amount": None}


def _wire_run(monkeypatch: pytest.MonkeyPatch, universe, fetchers, writer):
    monkeypatch.setattr(
        iqf, "load_universe",
        lambda conn, symbols=None, include_hk=True, markets=None: list(universe),
    )
    monkeypatch.setattr(iqf, "load_registered_sources", lambda conn: set(fetchers))
    monkeypatch.setattr(iqf, "load_last_dates", lambda conn, adjust, **kw: {})
    monkeypatch.setattr(iqf, "previous_close", lambda conn, symbol, adjust, before: None)
    monkeypatch.setattr(iqf, "count_covered", lambda conn, symbols, trade_date, adjust: len(symbols))
    recorded: list = []
    monkeypatch.setattr(iqf, "_record_freshness", lambda target, payload: recorded.append((target, payload)))
    return recorded


def test_run_falls_back_through_sources_and_records_actual_source(monkeypatch: pytest.MonkeyPatch) -> None:
    universe = [iqf.IndexMeta("000300", "SH"), iqf.IndexMeta("930641", "CSI")]

    def tx(symbol, market, start, end):
        if market == "CSI":
            raise iqf.SourceError("no_tencent_prefix")  # 930+ 无腾讯等价代码
        raise RuntimeError("tx down")

    def sina(symbol, market, start, end):
        if market == "CSI":
            raise iqf.SourceError("no_sina_prefix")
        return [_bar(date(2026, 11, 26)), _bar(TARGET, 101.0)]

    def csindex(symbol, market, start, end):
        return [_bar(TARGET, 88.0)]

    def em(symbol, market, start, end):
        raise RuntimeError("em blocked")

    fetchers = {
        "cn_index_tx": tx,
        "cn_index_sina": sina,
        "csindex_perf": csindex,
        "cn_index_em": em,
    }
    writes: list = []
    recorded = _wire_run(monkeypatch, universe, fetchers, writes)

    def writer(conn, rows):
        writes.append(rows)
        return len(rows)

    result = iqf.run(target_date=TARGET, now=datetime(2026, 11, 27, 16, 0, tzinfo=CN),
            conn_factory=lambda: object(),
                     fetchers=fetchers, writer=writer, sleep_seconds=0)
    assert result["target_date"] == TARGET.isoformat()
    assert result["coverage"] == pytest.approx(1.0)
    assert result["covered"] == 2
    # 000300 腾讯失败后新浪成功；930641 腾讯/新浪均无前缀失败后中证官网成功
    assert result["by_source"] == {"cn_index_sina": 1, "csindex_perf": 1}
    flat = [row for batch in writes for row in batch]
    assert {(row.symbol, row.source, row.adjust) for row in flat} == {
        ("000300", "cn_index_sina", "bfq"),
        ("930641", "csindex_perf", "bfq"),
    }
    assert recorded and recorded[0][0] == TARGET


def test_run_missing_when_all_sources_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    universe = [iqf.IndexMeta("000300", "SH")]
    fetchers = {
        "cn_index_tx": _FakeFetcher(error=RuntimeError("tx down")),
        "cn_index_sina": _FakeFetcher([]),
        "csindex_perf": _FakeFetcher(error=RuntimeError("cs down")),
        "cn_index_em": _FakeFetcher(error=RuntimeError("em down")),
    }
    writes: list = []
    _wire_run(monkeypatch, universe, fetchers, writes)
    result = iqf.run(target_date=TARGET, now=datetime(2026, 11, 27, 16, 0, tzinfo=CN),
            conn_factory=lambda: object(),
                     fetchers=fetchers, writer=lambda conn, rows: writes.append(rows) or len(rows),
                     sleep_seconds=0)
    assert result["missing"] == ["000300"]
    assert writes == []
    assert result["by_source"] == {}


def test_run_filters_unconfirmed_future_rows_and_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    universe = [iqf.IndexMeta("000300", "SH")]
    fetchers = {
        "cn_index_tx": _FakeFetcher([_bar(date(2026, 11, 26)), _bar(TARGET), _bar(date(2026, 11, 30))]),
        "cn_index_sina": _FakeFetcher(error=RuntimeError("no need")),
        "csindex_perf": _FakeFetcher([]),
        "cn_index_em": _FakeFetcher([]),
    }
    writes: list = []
    _wire_run(monkeypatch, universe, fetchers, writes)
    result = iqf.run(target_date=TARGET, now=datetime(2026, 11, 27, 16, 0, tzinfo=CN),
            conn_factory=lambda: object(), fetchers=fetchers,
                     writer=lambda conn, rows: writes.append(rows) or len(rows),
                     dry_run=True, sleep_seconds=0)
    assert result["dry_run"] is True
    assert writes == [], "dry-run 不得写库"
    assert result["covered"] == 1
    assert result["db_covered"] == 1


def test_run_pct_change_uses_previous_close_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    universe = [iqf.IndexMeta("000300", "SH")]
    fetchers = {
        "cn_index_tx": _FakeFetcher([_bar(TARGET, 110.0)]),
        "cn_index_sina": _FakeFetcher([]),
        "csindex_perf": _FakeFetcher([]),
        "cn_index_em": _FakeFetcher([]),
    }
    _wire_run(monkeypatch, universe, fetchers, [])
    monkeypatch.setattr(iqf, "previous_close", lambda conn, symbol, adjust, before: 100.0)
    captured: list = []
    iqf.run(target_date=TARGET, now=datetime(2026, 11, 27, 16, 0, tzinfo=CN),
            conn_factory=lambda: object(), fetchers=fetchers,
            writer=lambda conn, rows: captured.append(rows) or len(rows), sleep_seconds=0)
    assert captured and captured[0][0].pct_change == pytest.approx(10.0)


def test_source_filter_restricts_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    universe = [iqf.IndexMeta("000300", "SH")]
    fetchers = {
        "cn_index_tx": _FakeFetcher(error=RuntimeError("tx down")),
        "cn_index_sina": _FakeFetcher([_bar(TARGET)]),
        "csindex_perf": _FakeFetcher([_bar(TARGET)]),
        "cn_index_em": _FakeFetcher([_bar(TARGET)]),
    }
    _wire_run(monkeypatch, universe, fetchers, [])
    result = iqf.run(target_date=TARGET, now=datetime(2026, 11, 27, 16, 0, tzinfo=CN),
            conn_factory=lambda: object(), fetchers=fetchers,
                     source_filter=["cn_index_sina"], writer=lambda conn, rows: len(rows),
                     sleep_seconds=0)
    assert result["by_source"] == {"cn_index_sina": 1}

def test_run_explicit_today_before_close_skips_without_writing(monkeypatch: pytest.MonkeyPatch) -> None:
    """P2：显式 --date=today 时若未过收盘确认，必须直接跳过（不写盘中快照）。"""
    _wire_run(monkeypatch, [], {}, [])
    writes: list = []
    called: list = []
    monkeypatch.setattr(iqf, "load_universe", lambda *a, **kw: called.append(1) or [])
    result = iqf.run(
        target_date=TARGET,
        now=datetime(2026, 11, 27, 14, 0, tzinfo=CN),
        conn_factory=lambda: object(),
        fetchers={},
        writer=lambda conn, rows: writes.append(rows) or len(rows),
    )
    assert result["status"] == "not_closed"
    assert result["reason"] == "before_close_confirm"
    assert writes == []
    assert called == [], "未收盘确认时不应进入抓取/写库流程"


def test_run_explicit_today_after_close_proceeds(monkeypatch: pytest.MonkeyPatch) -> None:
    fetchers = {"cn_index_tx": _FakeFetcher([_bar(TARGET)])}
    writes: list = []
    _wire_run(monkeypatch, [iqf.IndexMeta("000300", "SH")], fetchers, writes)
    result = iqf.run(
        target_date=TARGET,
        now=datetime(2026, 11, 27, 15, 20, tzinfo=CN),
        conn_factory=lambda: object(),
        fetchers=fetchers,
        writer=lambda conn, rows: writes.append(rows) or len(rows),
        sleep_seconds=0,
    )
    assert result["status"] == "ok"
    assert writes and writes[0][0].trade_date == TARGET


class _LastDateCursor:
    def __init__(self, conn: "_LastDateConn") -> None:
        self.conn = conn

    def execute(self, sql: str, params: object = None) -> None:
        self.conn.queries.append((sql, params))

    def fetchall(self) -> list:
        return [("000300", TARGET)]

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _LastDateConn:
    def __init__(self) -> None:
        self.queries: list = []

    def cursor(self) -> _LastDateCursor:
        return _LastDateCursor(self)


def test_load_last_dates_uses_date_window() -> None:
    """P2：max(trade_date) 查询必须带日期窗口，避免大表全量 GROUP BY。"""
    conn = _LastDateConn()
    dates = iqf.load_last_dates(conn, "bfq", reference=TARGET, window_days=30)
    assert dates == {"000300": TARGET}
    sql, params = conn.queries[-1]
    assert "trade_date >=" in sql
    assert params[0] == "bfq"
    assert params[1] == TARGET - timedelta(days=30)
