"""L3 桥接测试：ETL 资产清洗路由、目标清单并集、状态统计路由。"""
from __future__ import annotations

from bp_api.quant import cleaning
from bp_api import repositories


class FakeCursor:
    def __init__(self, conn: "FakeConn") -> None:
        self.conn = conn

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: object = None) -> None:
        self.conn.queries.append((sql, params))
        self.conn._rows = self.conn.results.pop(0) if self.conn.results else []

    def fetchall(self) -> list:
        return self.conn._rows

    def fetchone(self) -> object:
        return self.conn._rows[0] if self.conn._rows else None


class FakeConn:
    def __init__(self, results: list | None = None) -> None:
        self.results = list(results or [])
        self.queries: list[tuple[str, object]] = []
        self._rows: list = []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)


def test_load_raw_routes_etl_sources_to_v3_tables() -> None:
    conn = FakeConn([[("2026-11-23", 1, 2, 0.5, 1.5, 100)]])
    df = cleaning._load_raw(conn, "600036", "etl_a_stock", "hfq")
    assert not df.empty
    sql, params = conn.queries[0]
    assert "FROM bp_stock_quote_daily" in sql
    assert params == ("600036", "hfq")
    conn2 = FakeConn([[]])
    cleaning._load_raw(conn2, "510300", "etl_etf", "hfq")
    sql2, params2 = conn2.queries[0]
    assert "FROM bp_etf_quote_daily" in sql2 and "etf_code" in sql2
    assert params2 == ("510300", "hfq")


def test_load_raw_keeps_legacy_table_for_old_sources() -> None:
    conn = FakeConn([[]])
    cleaning._load_raw(conn, "000300", "cn_index_em", "bfq")
    sql, params = conn.queries[0]
    assert "bp_index_quote_daily" in sql
    assert params == ("000300", "cn_index_em", "bfq")


def test_list_targets_union_includes_managed_assets(monkeypatch) -> None:
    monkeypatch.setenv("BP_ETL_L3", "on")
    conn = FakeConn([
        [("600036", "etl_a_stock", "hfq")],
        [("000300", "cn_index_em", "bfq")],
    ])
    targets = cleaning._list_targets(conn, ["600036", "000300"])
    assert ("600036", "etl_a_stock", "hfq") in targets
    assert ("000300", "cn_index_em", "bfq") in targets
    assert "managed_by = 'bp_etl'" in conn.queries[0][0]


def test_raw_scan_sql_routes_by_source() -> None:
    sql, extra = repositories._raw_scan_sql("etl_hk_stock", with_count=True)
    assert "bp_stock_quote_daily" in sql and "adjust='hfq'" in sql
    assert extra == ()
    sql2, _extra2 = repositories._raw_scan_sql("etl_etf", with_count=False)
    assert "bp_etf_quote_daily" in sql2 and "etf_code" in sql2
    sql3, extra3 = repositories._raw_scan_sql("cn_index_em", with_count=True)
    assert "bp_index_quote_daily" in sql3 and extra3 == ("cn_index_em",)


def test_seed_script_kind_map() -> None:
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "seed_etl_assets.py"
    spec = importlib.util.spec_from_file_location("seed_etl_assets", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    assert set(module.KIND_SQL) == {"a_stock", "hk_stock", "etf"}
    assert module.KIND_SQL["hk_stock"][2] == "HKD"