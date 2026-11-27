"""全局数据新鲜度：应到日期/状态判定/写入/API（纯 mock，不连库）。"""
from __future__ import annotations

import datetime as dt
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bp_api import freshness

CN = dt.timezone(dt.timedelta(hours=8))
DAYS = [dt.date(2026, 11, 25), dt.date(2026, 11, 26), dt.date(2026, 11, 27)]


# ---------------------------------------------------------------------------
# 纯计算
# ---------------------------------------------------------------------------
def test_expected_trade_date_respects_each_dataset_cutoff() -> None:
    stock = freshness._SPEC_BY_KEY["a_stock"]
    fund = freshness._SPEC_BY_KEY["fund_nav"]
    valuation = freshness._SPEC_BY_KEY["index_valuation"]
    # 11-27 14:00：A 股未过 15:10 -> 应到 11-26；估值 21:00 同理
    early = dt.datetime(2026, 11, 27, 14, 0, tzinfo=CN)
    assert freshness.expected_trade_date(stock, early, DAYS) == dt.date(2026, 11, 26)
    assert freshness.expected_trade_date(fund, early, DAYS) == dt.date(2026, 11, 26)
    assert freshness.expected_trade_date(valuation, early, DAYS) == dt.date(2026, 11, 26)
    # 11-27 16:00：A 股已确认，估值仍未到 21:00
    mid = dt.datetime(2026, 11, 27, 16, 0, tzinfo=CN)
    assert freshness.expected_trade_date(stock, mid, DAYS) == dt.date(2026, 11, 27)
    assert freshness.expected_trade_date(valuation, mid, DAYS) == dt.date(2026, 11, 26)
    # 周末：最近交易日 11-27 恒为应到
    weekend = dt.datetime(2026, 11, 29, 10, 0, tzinfo=CN)
    assert freshness.expected_trade_date(stock, weekend, DAYS) == dt.date(2026, 11, 27)


def test_classify_status_levels() -> None:
    ok = freshness.classify_status(dt.date(2026, 11, 27), dt.date(2026, 11, 27), DAYS)
    assert ok["status"] == "ok" and ok["is_stale"] is False
    lag = freshness.classify_status(dt.date(2026, 11, 26), dt.date(2026, 11, 27), DAYS)
    assert lag["status"] == "lagging" and lag["lag_trading_days"] == 1
    stale = freshness.classify_status(dt.date(2026, 11, 25), dt.date(2026, 11, 27), DAYS)
    assert stale["status"] == "stale" and stale["lag_trading_days"] == 2
    missing = freshness.classify_status(None, dt.date(2026, 11, 27), DAYS)
    assert missing["status"] == "missing" and missing["is_stale"] is True
    unavailable = freshness.classify_status(
        dt.date(2026, 11, 14), dt.date(2026, 11, 27), DAYS,
        stored_status="unavailable", stored_note="源全挂",
    )
    assert unavailable["status"] == "unavailable"
    assert unavailable["note"] == "源全挂"
    assert unavailable["is_stale"] is True


# ---------------------------------------------------------------------------
# build_payload
# ---------------------------------------------------------------------------
def _patch_payload_sources(monkeypatch: pytest.MonkeyPatch, stored: dict, derived: dict) -> None:
    monkeypatch.setattr(freshness, "_load_trading_days", lambda conn, now: list(DAYS))
    monkeypatch.setattr(freshness, "load_stored_rows", lambda conn: stored)
    monkeypatch.setattr(freshness, "derive_as_of", lambda conn: derived)


def test_build_payload_min_as_of_and_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = {
        "a_stock": {"as_of": dt.date(2026, 11, 27), "status": "ok", "note": None,
                    "source": "bp_etl", "updated_at": dt.datetime(2026, 11, 27, 15, 30, tzinfo=CN)},
        "etf": {"as_of": dt.date(2026, 11, 26), "status": "ok", "note": None,
                "source": "bp_etl", "updated_at": None},
    }
    _patch_payload_sources(monkeypatch, stored, {})
    now = dt.datetime(2026, 11, 27, 22, 0, tzinfo=CN)
    payload = freshness.build_payload(SimpleNamespace(), now=now)
    assert [item["dataset"] for item in payload["data"]] == list(freshness.DATASET_KEYS)
    assert len(payload["data"]) == 8
    by_key = {item["dataset"]: item for item in payload["data"]}
    assert by_key["a_stock"]["as_of"] == "2026-11-27"
    assert by_key["a_stock"]["status"] == "ok"
    assert by_key["a_stock"]["lag_days"] == 0
    assert by_key["etf"]["status"] == "lagging"
    assert by_key["etf"]["lag_days"] == 1  # 前端契约：自然日差
    # 全库最小 as_of 是 11-26（etf），其它 6 类无数据不参与 min
    assert payload["meta"]["latest_complete_date"] == "2026-11-26"
    assert payload["meta"]["all_complete"] is False
    assert "fund_nav" in payload["meta"]["missing"]
    assert payload["error"] is None


def test_build_payload_derived_as_of_when_writer_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """写方未接入时用源表 MAX 兜底：不应整块 missing。"""
    _patch_payload_sources(
        monkeypatch, {},
        {"a_stock": dt.date(2026, 11, 27), "cffex": dt.date(2026, 11, 27),
         "index_valuation": dt.date(2026, 11, 27), "mvi": dt.date(2026, 11, 27)},
    )
    payload = freshness.build_payload(
        SimpleNamespace(), now=dt.datetime(2026, 11, 27, 23, 55, tzinfo=CN)
    )
    by_key = {item["dataset"]: item for item in payload["data"]}
    assert by_key["a_stock"]["as_of"] == "2026-11-27"
    assert by_key["a_stock"]["status"] == "ok"
    assert "a_stock" not in payload["meta"]["missing"]


def test_build_payload_extra_unavailable_market_valuation(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = {
        "market_valuation": {
            "label": "全市场估值快照", "as_of": dt.date(2026, 11, 14),
            "status": "unavailable", "note": "sina:empty; em:IP封禁", "updated_at": None,
        }
    }
    _patch_payload_sources(monkeypatch, stored, {"market_valuation": dt.date(2026, 11, 14)})
    payload = freshness.build_payload(
        SimpleNamespace(), now=dt.datetime(2026, 11, 27, 22, 0, tzinfo=CN)
    )
    # 8 类契约不变，扩展类别只出现在 meta.extra（前端可据此显示不可用）
    assert len(payload["data"]) == 8
    assert payload["meta"]["extra"]["market_valuation"]["status"] == "unavailable"
    assert "sina:empty" in payload["meta"]["extra"]["market_valuation"]["note"]


def test_build_payload_extra_market_valuation_stale_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    """市场估值快照停更时 meta.extra 必须给出 stale + note（UI 明确不可用信号）。"""
    _patch_payload_sources(monkeypatch, {}, {"market_valuation": dt.date(2026, 11, 14)})
    payload = freshness.build_payload(
        SimpleNamespace(), now=dt.datetime(2026, 11, 27, 22, 0, tzinfo=CN)
    )
    extra = payload["meta"]["extra"]["market_valuation"]
    assert extra["as_of"] == "2026-11-14"
    assert extra["status"] == "stale"
    assert extra["is_stale"] is True
    assert "落后" in extra["note"]


# ---------------------------------------------------------------------------
# 缓存
# ---------------------------------------------------------------------------
def test_load_payload_cached_60s(monkeypatch: pytest.MonkeyPatch) -> None:
    freshness._CACHE.clear()
    calls: list[int] = []

    def fake_build(conn, *, now=None, cached=False):
        calls.append(1)
        return {"data": [], "meta": {"cached": cached}, "error": None}

    monkeypatch.setattr(freshness, "build_payload", fake_build)
    first = freshness.load_payload_cached(SimpleNamespace())
    second = freshness.load_payload_cached(SimpleNamespace())
    assert len(calls) == 1
    assert first["meta"]["cached"] is False
    assert second["meta"]["cached"] is True
    # 过期后重新构建
    stored_at, payload = freshness._CACHE["freshness"]
    freshness._CACHE["freshness"] = (stored_at - freshness.CACHE_TTL_SECONDS - 1, payload)
    third = freshness.load_payload_cached(SimpleNamespace())
    assert len(calls) == 2 and third["meta"]["cached"] is False
    freshness._CACHE.clear()


# ---------------------------------------------------------------------------
# record_freshness
# ---------------------------------------------------------------------------
class FakeCursor:
    def __init__(self, conn: "FakeConn") -> None:
        self.conn = conn

    def execute(self, sql: str, params: object = None) -> None:
        self.conn.statements.append((sql, params))

    def fetchone(self):
        return self.conn.fetchone_queue.pop(0) if self.conn.fetchone_queue else None

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class FakeConn:
    def __init__(self, *, table: bool = True, as_of: dt.date | None = None) -> None:
        self.statements: list[tuple[str, object]] = []
        self.fetchone_queue: list = []
        if table:
            self.fetchone_queue.append(("bp_data_freshness",))
            self.fetchone_queue.append((as_of,))
        self.committed = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self) -> None:
        self.committed += 1


def test_record_freshness_never_regresses_as_of() -> None:
    conn = FakeConn(table=True, as_of=dt.date(2026, 11, 27))
    assert freshness.record_freshness(conn, "a_stock", dt.date(2026, 11, 26), source="bp_etl") is True
    insert = [item for item in conn.statements if "INSERT INTO bp_data_freshness" in item[0]]
    assert insert, "应执行 upsert"
    params = insert[-1][1]
    # as_of 只前进：旧值 11-27 不被 11-26 覆盖
    assert params[2] == dt.date(2026, 11, 27)


def test_record_freshness_allows_explicit_unavailable_without_date() -> None:
    conn = FakeConn(table=True, as_of=dt.date(2026, 11, 14))
    assert freshness.record_freshness(
        conn, "market_valuation", None, status="unavailable", note="源不可用"
    ) is True
    insert = [item for item in conn.statements if "INSERT INTO bp_data_freshness" in item[0]]
    params = insert[-1][1]
    assert params[2] == dt.date(2026, 11, 14)  # 保留最后成功日期
    assert params[4] == "unavailable"


def test_record_freshness_graceful_when_table_missing() -> None:
    conn = FakeConn(table=False, as_of=None)
    assert freshness.record_freshness(conn, "a_stock", dt.date(2026, 11, 27)) is False
    assert not [item for item in conn.statements if "INSERT INTO bp_data_freshness" in item[0]]


class _FailingCursor(FakeCursor):
    def execute(self, sql: str, params: object = None) -> None:
        self.conn.statements.append((sql, params))
        if "INSERT INTO bp_data_freshness" in sql:
            raise RuntimeError("db write failed")


class _FailingConn(FakeConn):
    def __init__(self) -> None:
        super().__init__(table=True, as_of=None)
        self.fetchone_queue = [("bp_data_freshness",), (None,)]

    def cursor(self):
        return _FailingCursor(self)


def test_record_freshness_rolls_back_savepoint_on_write_failure() -> None:
    conn = _FailingConn()
    assert freshness.record_freshness(conn, "a_stock", dt.date(2026, 11, 27)) is False
    sqls = [sql for sql, _ in conn.statements]
    assert any("SAVEPOINT bp_data_freshness_write" in sql for sql in sqls)
    assert any("ROLLBACK TO SAVEPOINT bp_data_freshness_write" in sql for sql in sqls)


def test_sync_derived_freshness(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        freshness, "derive_as_of",
        lambda conn: {"index_valuation": dt.date(2026, 11, 27), "mvi": dt.date(2026, 11, 27)},
    )
    recorded: list = []
    monkeypatch.setattr(
        freshness, "record_freshness",
        lambda conn, dataset, as_of, **kw: recorded.append((dataset, as_of)) or True,
    )
    result = freshness.sync_derived_freshness(SimpleNamespace(), ("index_valuation", "mvi"))
    assert result == {"index_valuation": True, "mvi": True}
    assert ("index_valuation", dt.date(2026, 11, 27)) in recorded


# ---------------------------------------------------------------------------
# API（匿名可读）
# ---------------------------------------------------------------------------
def test_data_freshness_endpoint_anonymous(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "data": [{"dataset": key, "as_of": "2026-11-27"} for key in freshness.DATASET_KEYS],
        "meta": {"latest_complete_date": "2026-11-27", "all_complete": True,
                 "missing": [], "cached": False},
        "error": None,
    }
    monkeypatch.setattr(freshness, "load_payload_cached", lambda conn: payload)

    @contextmanager
    def fake_conn():
        yield SimpleNamespace()

    monkeypatch.setattr(freshness.db, "get_conn", fake_conn)
    app = FastAPI()
    freshness.register_routes(app)
    client = TestClient(app)
    response = client.get("/api/v1/market/data-freshness")
    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    assert len(body["data"]) == 8
    assert body["meta"]["latest_complete_date"] == "2026-11-27"

# ---------------------------------------------------------------------------
# 共享写事务隔离（P1-2）：派生查询失败只回滚 SAVEPOINT，绝不回滚主数据
# ---------------------------------------------------------------------------
class _TxCursor:
    """模拟 psycopg 事务语义：普通查询失败 -> 事务 aborted；SAVEPOINT 回滚可恢复。"""

    def __init__(self, conn: "_TxConn") -> None:
        self.conn = conn

    def execute(self, sql: str, params: object = None) -> None:
        self.conn.statements.append(sql)
        upper = " ".join(sql.upper().split())
        if upper.startswith("SAVEPOINT "):
            self.conn.savepoints.append(upper)
            return
        if upper.startswith("ROLLBACK TO SAVEPOINT "):
            self.conn.aborted = False  # 回滚保存点后事务恢复可用
            return
        if upper.startswith("RELEASE SAVEPOINT "):
            self.conn.savepoints = [s for s in self.conn.savepoints if s not in upper]
            return
        if self.conn.fail_all_queries:
            self.conn.aborted = True
            raise RuntimeError("derived query failed")

    def fetchone(self):
        return None

    def fetchall(self) -> list:
        return []

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _TxConn:
    """带事务状态的假连接：用于断言「不回滚主事务、主数据仍可提交」。"""

    def __init__(self, *, fail_all_queries: bool = True) -> None:
        self.fail_all_queries = fail_all_queries
        self.statements: list[str] = []
        self.savepoints: list[str] = []
        self.rollbacks = 0
        self.commits = 0
        self.aborted = False
        self.data: list[str] = []

    def cursor(self) -> _TxCursor:
        return _TxCursor(self)

    def rollback(self) -> None:
        # 若被调用说明主事务被误回滚（P1-2 回归）
        self.rollbacks += 1
        self.aborted = False

    def commit(self) -> None:
        assert not self.aborted, "主事务处于 aborted 时提交会静默丢数据"
        self.commits += 1


def test_derive_as_of_query_failure_only_rolls_back_savepoint() -> None:
    """派生查询异常：只用 SAVEPOINT 隔离，不调用 conn.rollback()（不毁主数据）。"""
    conn = _TxConn(fail_all_queries=True)
    derived = freshness.derive_as_of(conn)
    assert conn.rollbacks == 0, "derive_as_of 不得回滚整个事务"
    assert any("ROLLBACK TO SAVEPOINT" in sql for sql in conn.statements)
    assert all(value is None for value in derived.values())
    # 主事务仍可提交（未被拖入 aborted）
    conn.commit()
    assert conn.commits == 1
    assert conn.aborted is False


def test_sync_derived_freshness_failure_keeps_main_writes_committable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """估值/MVI 主数据已写入后 sync 失败：主数据仍在、仍可提交。"""
    conn = _TxConn(fail_all_queries=True)
    conn.data = ["index_valuation_rows", "mvi_rows"]  # 主链路已写入
    recorded: list = []
    monkeypatch.setattr(
        freshness, "record_freshness",
        lambda *args, **kwargs: recorded.append(args) or True,
    )
    result = freshness.sync_derived_freshness(conn, ("index_valuation", "mvi"))
    assert result == {"index_valuation": False, "mvi": False}
    assert recorded == []
    assert conn.rollbacks == 0, "sync_derived_freshness 异常绝不影响主链路事务"
    conn.commit()
    assert conn.commits == 1
    assert conn.data == ["index_valuation_rows", "mvi_rows"], "主数据必须仍可提交"
    assert conn.aborted is False


def test_scalar_or_none_uses_savepoint_on_error() -> None:
    conn = _TxConn(fail_all_queries=True)
    assert freshness._scalar_or_none(conn, "SELECT max(x) FROM missing") is None
    assert conn.rollbacks == 0
    assert any("ROLLBACK TO SAVEPOINT" in sql for sql in conn.statements)


# ---------------------------------------------------------------------------
# 第二轮反馈：读侧 meta / completed_at(+08:00) / 状态取较严重者 / 覆盖不足
# ---------------------------------------------------------------------------
def test_build_item_exposes_meta_and_completed_at_in_cst(monkeypatch) -> None:
    stored = {
        "a_stock": {
            "as_of": dt.date(2026, 11, 27), "status": "ok", "note": None,
            "source": "bp_etl",
            "updated_at": dt.datetime(2026, 11, 27, 15, 30, tzinfo=dt.timezone.utc),
            "meta": {
                "coverage": 0.9975,
                "completed_at": "2026-11-27T07:30:00+00:00",
                "sources": ["tencent_qt", "sina_kline"],
            },
        }
    }
    _patch_payload_sources(monkeypatch, stored, {})
    monkeypatch.setattr(freshness, "_load_source_health", lambda conn: {})
    payload = freshness.build_payload(
        SimpleNamespace(), now=dt.datetime(2026, 11, 27, 22, 0, tzinfo=CN)
    )
    item = next(row for row in payload["data"] if row["dataset"] == "a_stock")
    assert item["meta"]["coverage"] == 0.9975
    assert item["meta"]["sources"] == ["tencent_qt", "sina_kline"]
    # meta.completed_at 优先，且统一 +08:00（UTC 07:30 -> CST 15:30）
    assert item["completed_at"] == "2026-11-27T15:30:00+08:00"
    assert item["source"] == "bp_etl"
    assert item["status"] == "ok"


def test_build_item_completed_at_falls_back_to_updated_at() -> None:
    spec = freshness._SPEC_BY_KEY["a_stock"]
    item = freshness._build_item(
        spec,
        {
            "as_of": dt.date(2026, 11, 27), "status": "ok",
            "updated_at": dt.datetime(2026, 11, 27, 15, 10, tzinfo=dt.timezone.utc),
            "meta": {},
        },
        None,
        dt.date(2026, 11, 27),
        list(DAYS),
    )
    assert item["completed_at"] == "2026-11-27T23:10:00+08:00"


def test_coverage_below_threshold_makes_stored_ok_lagging_with_note() -> None:
    spec = freshness._SPEC_BY_KEY["index_quotes"]
    item = freshness._build_item(
        spec,
        {
            "as_of": dt.date(2026, 11, 27), "status": "ok",
            "meta": {"covered": 284, "total": 481, "coverage": 0.59},
            "updated_at": dt.datetime(2026, 11, 27, 23, 0, tzinfo=CN),
        },
        None,
        dt.date(2026, 11, 27),
        list(DAYS),
    )
    # 写入方报 ok 但覆盖不足：读侧必须降级为 lagging，并给出覆盖 note
    assert item["status"] == "lagging"
    assert item["is_stale"] is True
    assert "284/481" in item["note"]
    assert item["coverage"]["ratio"] == pytest.approx(0.59)


def _coverage_item(dataset: str, ratio: float) -> dict:
    spec = freshness._SPEC_BY_KEY[dataset]
    return freshness._build_item(
        spec,
        {
            "as_of": dt.date(2026, 11, 27), "status": "ok",
            "meta": {"coverage": ratio},
            "updated_at": None,
        },
        None,
        dt.date(2026, 11, 27),
        list(DAYS),
    )


def test_coverage_threshold_is_per_dataset_not_blanket_99pct() -> None:
    """覆盖率阈值必须按数据集取 registry：ETF 96% / 基金 90% 追平应 ok。"""
    assert _coverage_item("fund_nav", 0.914)["status"] == "ok"
    assert _coverage_item("fund_nav", 0.90)["status"] == "ok"
    assert _coverage_item("etf", 0.96)["status"] == "ok"
    assert _coverage_item("etf", 0.959)["status"] == "lagging"
    assert _coverage_item("hk_stock", 0.966)["status"] == "lagging"
    assert _coverage_item("a_stock", 0.99)["status"] == "lagging"
    assert _coverage_item("a_stock", 0.995)["status"] == "ok"
    # 指数类别没有 registry 条目：保持 0.99
    assert _coverage_item("index_quotes", 0.9)["status"] == "lagging"
    assert _coverage_item("index_quotes", 0.99)["status"] == "ok"
    assert _coverage_item("index_valuation", 0.995)["status"] == "ok"
    # cffex/mvi 不以覆盖率判定（只按 as_of 时效）
    assert _coverage_item("cffex", 0.5)["status"] == "ok"
    assert _coverage_item("mvi", 0.5)["status"] == "ok"


def test_coverage_note_reports_dataset_threshold() -> None:
    fund = _coverage_item("fund_nav", 0.89)
    assert fund["status"] == "lagging"
    assert "90%" in fund["note"]
    etf = _coverage_item("etf", 0.90)
    assert etf["status"] == "lagging"
    assert "96%" in etf["note"]


def test_worst_status_and_meta_coverage() -> None:
    assert freshness.worst_status("ok", "lagging") == "lagging"
    assert freshness.worst_status("ok", None, "stale") == "stale"
    assert freshness.worst_status("unavailable", "error") == "error"
    assert freshness.worst_status("ok", "bogus") == "ok"
    cov = freshness.meta_coverage({"covered": 284, "universe": 481})
    assert cov == {"covered": 284, "total": 481, "ratio": pytest.approx(284 / 481)}


def test_build_payload_all_complete_requires_status_ok(monkeypatch) -> None:
    stored = {
        key: {"as_of": dt.date(2026, 11, 27), "status": "ok", "meta": {}}
        for key in freshness.DATASET_KEYS
    }
    # index_quotes 虽 as_of 追平，但覆盖率仅 59% -> status=lagging -> 不算齐套
    stored["index_quotes"] = {
        "as_of": dt.date(2026, 11, 27), "status": "ok",
        "meta": {"covered": 284, "total": 481, "coverage": 0.59},
    }
    _patch_payload_sources(monkeypatch, stored, {})
    monkeypatch.setattr(freshness, "_load_source_health", lambda conn: {})
    payload = freshness.build_payload(
        SimpleNamespace(), now=dt.datetime(2026, 11, 27, 23, 55, tzinfo=CN)
    )
    assert payload["meta"]["all_complete"] is False
    by_key = {item["dataset"]: item for item in payload["data"]}
    assert by_key["index_quotes"]["status"] == "lagging"
    # 覆盖率信息同时暴露在 meta.index_coverage
    assert payload["meta"]["index_coverage"]["covered"] == 284
    assert payload["meta"]["index_coverage"]["total"] == 481
    assert payload["meta"]["index_coverage"]["ratio"] == pytest.approx(0.59, abs=1e-4)


def test_build_payload_index_coverage_and_source_health(monkeypatch) -> None:
    stored = {
        key: {"as_of": dt.date(2026, 11, 27), "status": "ok", "meta": {}}
        for key in freshness.DATASET_KEYS
    }
    _patch_payload_sources(monkeypatch, stored, {})
    health = {
        "stat_date": "2026-11-27",
        "datasets": {"a_stock": {"attempts": 10, "ok": 9, "failed": 1,
                                 "banned_count": 0, "success_rate": 0.9, "sources": []}},
    }
    monkeypatch.setattr(freshness, "_load_source_health", lambda conn: health)
    monkeypatch.setattr(
        freshness, "_load_index_coverage",
        lambda conn, row, expected: {"covered": 400, "total": 481, "ratio": 0.8316,
                                     "as_of": "2026-11-27", "source": "bp_data_freshness.meta"},
    )
    payload = freshness.build_payload(
        SimpleNamespace(), now=dt.datetime(2026, 11, 27, 23, 55, tzinfo=CN)
    )
    assert payload["meta"]["source_health"] == health
    assert payload["meta"]["index_coverage"]["ratio"] == pytest.approx(0.8316)
    assert payload["meta"]["all_complete"] is True


def test_merge_freshness_meta_uses_savepoint() -> None:
    conn = FakeConn(table=True, as_of=None)
    assert freshness.merge_freshness_meta(conn, "index_valuation", {"note": "x"}) is True
    sqls = [sql for sql, _ in conn.statements]
    assert any("SAVEPOINT bp_data_freshness_meta" in sql for sql in sqls)
    update = [params for sql, params in conn.statements if "UPDATE bp_data_freshness" in sql]
    assert update and update[-1][1] == "index_valuation"

def test_stored_missing_ignored_when_derived_newer() -> None:
    """ddl/79 初始 status=missing 不得压在更新后的源表数据上（回归：全站 missing）。"""
    from datetime import date

    import bp_api.freshness as fr

    spec = next(s for s in fr.DATASETS if s.key == "a_stock")
    row = {"as_of": None, "status": "missing", "note": None, "meta": {}}
    item = fr._build_item(
        spec, row, date(2026, 11, 27), date(2026, 11, 27), [date(2026, 11, 27)]
    )
    assert item["as_of"] == "2026-11-27"
    assert item["status"] == "ok", item