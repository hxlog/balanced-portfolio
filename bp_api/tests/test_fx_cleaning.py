"""清洗期 CNY 折算单测(DDL 43 / W6)。

覆盖:
  * 外币 close == 原 close × 当日 fx_rate; OHLC 同时折算; volume 不折算
  * fx_rate 列: CNY 资产恒 1, 外币资产记当日汇率
  * 无汇率日不产出行(不被插值填掉), 且该日旧行被删除
  * 先折算再插值: 插值日 close 是折算价插值, 其 fx_rate 留空(不外推汇率)
  * 汇率依赖整体缺失 / 币种无新浪报价 / 汇率尾部停更 → MissingFxRate 终止(不产出部分行)
  * 加密/DXY/COMEX 黄金(crypto_yfinance 等)不折算
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd
import pytest
from unittest.mock import MagicMock

from bp_api.quant import cleaning
from bp_api.quant.cleaning import MissingFxRate, clean_one


# ---------------------------------------------------------------------
# 夹具: 内存 conn(按 SQL 关键字分派) + 极简交易日历
# ---------------------------------------------------------------------
class _FakeCursor:
    def __init__(self, conn: "_FakeConn"):
        self._conn = conn
        self.rowcount = 0
        self._result: list = []

    def execute(self, sql: str, params=None):
        sql_norm = " ".join(sql.split())
        self._conn.statements.append((sql_norm, params))
        self._result = self._conn._rows_for(sql_norm, params)
        if sql_norm.upper().startswith("DELETE"):
            self.rowcount = len(self._conn.deleted)
        return None

    def executemany(self, sql, params):
        self._conn.statements.append((" ".join(sql.split()), params))
        self._conn.upserted.extend(params)
        self.rowcount = len(params)

    def fetchall(self):
        return self._result

    def fetchone(self):
        return self._result[0] if self._result else None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    """按查询目标分派的最简连接桩: 只实现清洗用到的三类读 + 两类写。"""

    def __init__(self, raw: dict, fx: dict, currency: dict):
        self.raw = raw            # (symbol, source) -> list[(date, o, h, l, c, v)]
        self.fx = fx              # ('USDCNY', 'fx_sina') -> list[(date, close)]
        self.currency = currency  # (symbol, source) -> 'CNY' | 'USD' | ...
        self.upserted: list[dict] = []
        self.deleted: list = []
        self.statements: list = []
        self.committed = 0

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.committed += 1

    def rollback(self):
        pass

    def _rows_for(self, sql: str, params):
        if "FROM bp_index_quote_daily" in sql:
            return list(self.raw.get(tuple(params), []))
        if "fill_flag = 'real'" in sql:  # _load_fx_panel
            pair, src, start, end = params[0], params[1], params[2], params[3]
            return [
                r for r in self.fx.get((pair, src), []) if start <= r[0] <= end
            ]
        if "FROM bp_index_config" in sql:
            cur = self.currency.get(tuple(params))
            return [(cur,)] if cur else []
        if sql.upper().startswith("DELETE"):
            self.deleted = list(params[2])
            return []
        return []


class _Cal:
    """只含指定交易日的极简日历(避开真实日历的网络加载)。"""

    def __init__(self, days: list[date]):
        self._days = days

    def trading_days_between(self, start: date, end: date) -> list[date]:
        return [d for d in self._days if start <= d <= end]


def _cal_for(days: list[date]) -> _Cal:
    """周一到周五算交易日(测试数据本身只在工作日)。"""
    out, d = [], min(days)
    while d <= max(days):
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return _Cal(out)


def _daily(days: list[date], base: float) -> list[tuple]:
    """构造原始行情行(date, open, high, low, close, volume); close 逐日 +1。"""
    return [
        (d, base + i, base + i + 0.5, base + i - 0.5, base + i, 1000 + i)
        for i, d in enumerate(days)
    ]


def _fx_rows(days: list[date], rate: float, skip: set[date] | None = None) -> list[tuple]:
    skip = skip or set()
    return [(d, rate) for d in days if d not in skip]


D1, D2, D3, D4 = (date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4), date(2026, 3, 5))


def test_foreign_asset_close_is_converted_and_fx_rate_recorded():
    """外币资产: close == 原 close × 当日汇率, OHLC 同折, volume 不动。"""
    conn = _FakeConn(
        raw={("DAX", "global_index_em"): _daily([D1, D2], 100.0)},
        fx={("USDCNY", "fx_sina"): _fx_rows([D1, D2], 7.0)},
        currency={("DAX", "global_index_em"): "USD"},
    )
    n = clean_one(conn, "DAX", "global_index_em", _cal_for([D1, D2]))

    assert n == 2
    assert [r["trade_date"] for r in conn.upserted] == [D1, D2]
    for i, r in enumerate(conn.upserted):
        assert r["fx_rate"] == pytest.approx(7.0)
        assert r["close"] == pytest.approx((100.0 + i) * 7.0)
        assert r["open"] == pytest.approx((100.0 + i) * 7.0)   # 原 open == close
        assert r["high"] == pytest.approx((100.5 + i) * 7.0)
        assert r["low"] == pytest.approx((99.5 + i) * 7.0)
        assert r["volume"] == 1000 + i  # 成交量不折算
    # 汇率不变时折算后收益仍等于原币收益
    assert conn.upserted[1]["ret"] == pytest.approx(1.0 / 100.0)


def test_cny_asset_fx_rate_is_one_and_price_untouched():
    conn = _FakeConn(
        raw={("000300", "cn_index_em"): _daily([D1, D2], 3000.0)},
        fx={},
        currency={("000300", "cn_index_em"): "CNY"},
    )
    n = clean_one(conn, "000300", "cn_index_em", _cal_for([D1, D2]))

    assert n == 2
    for i, r in enumerate(conn.upserted):
        assert r["fx_rate"] == 1.0
        assert r["close"] == pytest.approx(3000.0 + i)
    # CNY 资产不读汇率表
    assert not any("fill_flag = 'real'" in s[0] for s in conn.statements)


def test_missing_fx_day_produces_no_row_and_deletes_stale_row():
    """无汇率日不处理: 不产出行(不被插值填掉), 且删除该日残留的旧行。"""
    conn = _FakeConn(
        raw={("DAX", "global_index_em"): _daily([D1, D2, D3], 100.0)},
        fx={("USDCNY", "fx_sina"): _fx_rows([D1, D2, D3], 7.0, skip={D2})},
        currency={("DAX", "global_index_em"): "USD"},
    )
    n = clean_one(conn, "DAX", "global_index_em", _cal_for([D1, D2, D3]))

    assert n == 2
    assert [r["trade_date"] for r in conn.upserted] == [D1, D3]
    assert all(r["fx_rate"] == pytest.approx(7.0) for r in conn.upserted)
    assert conn.deleted == [D2]  # 该日残行被清掉


def test_convert_before_interpolate_leaves_interp_fx_rate_null():
    """先折算再插值: 插值发生在折算后的价序上; 该日无真实汇率 → fx_rate 留空(不外推汇率)。"""
    conn = _FakeConn(
        raw={("DAX", "global_index_em"): _daily([D1, D4], 100.0)},  # D2/D3 源缺 → 插值
        fx={("USDCNY", "fx_sina"): [(D1, 7.0), (D4, 7.3)]},
        currency={("DAX", "global_index_em"): "USD"},
    )
    n = clean_one(conn, "DAX", "global_index_em", _cal_for([D1, D2, D3, D4]))

    assert n == 4
    by_day = {r["trade_date"]: r for r in conn.upserted}
    assert by_day[D2]["fill_flag"] == "interp" and by_day[D3]["fill_flag"] == "interp"
    # 折算价 D1=100×7.0=700, D4=101×7.3=737.3 → D2 落在 1/3 处
    assert by_day[D2]["close"] == pytest.approx(700.0 + (737.3 - 700.0) / 3)
    assert by_day[D2]["fx_rate"] is None   # 汇率不外推
    assert by_day[D3]["fx_rate"] is None
    assert by_day[D1]["fx_rate"] == pytest.approx(7.0)
    assert by_day[D4]["fx_rate"] == pytest.approx(7.3)
    # close 与 fx_rate 同源(真实日): close == 原币价 × 该日汇率
    assert by_day[D4]["close"] == pytest.approx(101.0 * 7.3)


def test_currency_without_usable_fx_pair_raises_instead_of_silently_skipping():
    """币种无可用新浪人民币报价(VND: 报价精度不足): 终止清洗, 不做美元三角合成, 不动旧行。"""
    conn = _FakeConn(
        raw={("越南胡志明", "global_index_em"): _daily([D1, D2], 1200.0)},
        fx={("USDCNY", "fx_sina"): _fx_rows([D1, D2], 7.0)},
        currency={("越南胡志明", "global_index_em"): "VND"},
    )
    with pytest.raises(MissingFxRate, match="VND"):
        clean_one(conn, "越南胡志明", "global_index_em", _cal_for([D1, D2]))
    assert conn.upserted == []
    assert conn.deleted == []


def test_each_pool_currency_has_a_direct_fx_pair():
    """资产池出现过的外币币种都已在 _CURRENCY_PAIR 里映射到可直接取数的 {币种}CNY。"""
    from bp_api.quant.cleaning import _CURRENCY_PAIR

    # 与 bp_index_config.currency 的实测分布一致(见 DDL 41/45)
    pool_currencies = {"USD", "HKD", "JPY", "EUR", "GBP", "AUD", "KRW", "INR", "RUB", "BRL"}
    assert pool_currencies <= set(_CURRENCY_PAIR)
    assert all(pair.endswith("CNY") for pair in _CURRENCY_PAIR.values())


def test_missing_fx_series_raises_without_deleting():
    """汇率依赖尚未入库: 终止该资产(不产出、不删除), 等 ingest 拉到汇率后重洗。"""
    conn = _FakeConn(
        raw={("HSI", "hk_index_em"): _daily([D1, D2], 24000.0)},
        fx={},  # HKDCNY 还没拉过
        currency={("HSI", "hk_index_em"): "HKD"},
    )
    with pytest.raises(MissingFxRate, match="HKDCNY"):
        clean_one(conn, "HSI", "hk_index_em", _cal_for([D1, D2]))
    assert conn.upserted == []
    assert conn.deleted == []


def test_stale_fx_tail_raises_to_avoid_silent_truncation():
    """汇率尾部停更(超过容忍窗): 拒绝产出被截断的清洗序列, 保留上一轮完整结果。"""
    d_long = D1 + timedelta(days=10)
    conn = _FakeConn(
        raw={("HSI", "hk_index_em"): _daily([D1, D2, d_long], 24000.0)},
        fx={("HKDCNY", "fx_sina"): _fx_rows([D1, D2], 0.9)},  # 汇率只到 D2
        currency={("HSI", "hk_index_em"): "HKD"},
    )
    with pytest.raises(MissingFxRate, match="尾部"):
        clean_one(conn, "HSI", "hk_index_em", _cal_for([D1, D2, d_long]))
    assert conn.upserted == []
    assert conn.deleted == []


def test_short_fx_tail_within_tolerance_is_allowed():
    """汇率落后 3 个自然日(长假差容忍窗内): 正常折算, 无汇率的日出不来行。"""
    conn = _FakeConn(
        raw={("HSI", "hk_index_em"): _daily([D1, D2, D3, D4], 24000.0)},
        fx={("HKDCNY", "fx_sina"): _fx_rows([D1, D2, D3], 0.9)},  # 汇率到 D3
        currency={("HSI", "hk_index_em"): "HKD"},
    )
    n = clean_one(conn, "HSI", "hk_index_em", _cal_for([D1, D2, D3, D4]))

    assert n == 3  # D1/D2/D3; D4 无汇率 → 不产出行
    assert [r["trade_date"] for r in conn.upserted] == [D1, D2, D3]
    assert conn.deleted == [D4]


def test_natural_calendar_usd_asset_not_converted():
    """加密(7×24 自然日路径)不折算, fx_rate 留 NULL — /crypto 看板按 USD 口径展示。"""
    conn = _FakeConn(
        raw={("BTC-USD", "crypto_yfinance"): _daily([D1, D2], 100000.0)},
        fx={},
        currency={("BTC-USD", "crypto_yfinance"): "USD"},
    )
    n = clean_one(conn, "BTC-USD", "crypto_yfinance", _cal_for([D1, D2]))

    assert n == 2
    assert [r["close"] for r in conn.upserted] == [100000.0, 100001.0]
    assert all(r["fx_rate"] is None for r in conn.upserted)


def test_usd_denominated_display_sources_are_never_converted():
    """dxy_em / gold_comex_em 保留原币口径(原生 USD 即展示口径)。"""
    conn = _FakeConn(
        raw={
            ("DX-Y.NYB", "dxy_em"): _daily([D1, D2], 99.0),
            ("GC=F", "gold_comex_em"): _daily([D1, D2], 3300.0),
        },
        fx={("USDCNY", "fx_sina"): _fx_rows([D1, D2], 7.0)},
        currency={("DX-Y.NYB", "dxy_em"): "USD", ("GC=F", "gold_comex_em"): "USD"},
    )
    assert clean_one(conn, "DX-Y.NYB", "dxy_em", _cal_for([D1, D2])) == 2
    assert clean_one(conn, "GC=F", "gold_comex_em", _cal_for([D1, D2])) == 2
    assert all(r["fx_rate"] is None for r in conn.upserted)
    assert [r["close"] for r in conn.upserted] == [99.0, 100.0, 3300.0, 3301.0]


def test_rebuild_cleans_fx_sources_first():
    """rebuild_clean 先把 fx_sina 标的重建完, 再洗依赖它的外币资产。"""
    order: list[tuple[str, str]] = []

    class _Conn:
        def commit(self):
            pass

        def rollback(self):
            pass

    orig_targets, orig_one = cleaning._list_targets, cleaning.clean_one
    cleaning._list_targets = lambda conn, symbols: [
        ("DAX", "global_index_em"), ("USDCNY", "fx_sina"), ("HSI", "hk_index_em"),
        ("HKDCNY", "fx_sina"),
    ]
    cleaning.clean_one = lambda conn, symbol, source, cal: order.append((symbol, source)) or 1
    try:
        cleaning.rebuild_clean(_Conn(), cal=_Cal([D1]))
    finally:
        cleaning._list_targets, cleaning.clean_one = orig_targets, orig_one

    assert [s for _, s in order] == ["fx_sina", "fx_sina", "global_index_em", "hk_index_em"]


def test_rebuild_purges_unconverted_rows_when_conversion_fails():
    """折算失败(MissingFxRate)时清掉无法证明已折算的旧行 —— 绝不静默以原币混入面板。"""
    purged: list[tuple[str, str]] = []

    class _Conn:
        def commit(self):
            pass

        def rollback(self):
            pass

    def _fail(conn, symbol, source, cal):
        raise MissingFxRate(f"{symbol}@{source}: 测试注入", total=True)

    orig = (cleaning._list_targets, cleaning.clean_one,
            cleaning._purge_unconverted_rows, cleaning.needs_conversion)
    cleaning._list_targets = lambda conn, symbols: [("越南胡志明", "global_index_em")]
    cleaning.clean_one = _fail
    cleaning.needs_conversion = lambda conn, symbol, source: True
    cleaning._purge_unconverted_rows = (
        lambda conn, symbol, source, total=False: purged.append((symbol, source, total)) or 7
    )
    try:
        cleaning.rebuild_clean(_Conn(), cal=_Cal([D1]))
    finally:
        (cleaning._list_targets, cleaning.clean_one, cleaning._purge_unconverted_rows,
         cleaning.needs_conversion) = orig

    # 币种根本无汇率标的(total=True) → 整表清理, 不给原币行留任何残存机会
    assert purged == [("越南胡志明", "global_index_em", True)]


def test_rebuild_partial_purge_keeps_interp_rows():
    """尾部护栏触发(total=False)只清 real 行的未折算项, 保留折算后插值出的行。

    折算发生在插值**之前**, interp 行由两侧已折算的 real 行插值而来, 已是 CNY 口径;
    且它们没有对应 raw 行可供验证 —— 一并删除会让面板出现本不该有的空洞。
    """
    purged: list[tuple[str, str, bool]] = []

    class _Conn:
        def commit(self):
            pass

        def rollback(self):
            pass

    def _fail(conn, symbol, source, cal):
        raise MissingFxRate("尾部停更")  # 默认 total=False

    orig = (cleaning._list_targets, cleaning.clean_one,
            cleaning._purge_unconverted_rows, cleaning.needs_conversion)
    cleaning._list_targets = lambda conn, symbols: [("HSI", "hk_index_em")]
    cleaning.clean_one = _fail
    cleaning.needs_conversion = lambda conn, symbol, source: True
    cleaning._purge_unconverted_rows = (
        lambda conn, symbol, source, total=False: purged.append((symbol, source, total)) or 3
    )
    try:
        cleaning.rebuild_clean(_Conn(), cal=_Cal([D1]))
    finally:
        (cleaning._list_targets, cleaning.clean_one, cleaning._purge_unconverted_rows,
         cleaning.needs_conversion) = orig

    assert purged == [("HSI", "hk_index_em", False)]


def test_rebuild_never_purges_display_only_usd_assets():
    """原生 USD 展示口径资产(BTC/DXY/GC)的 fx_rate=NULL 是设计, 绝不能被清理。"""
    purged: list = []

    class _Conn:
        def commit(self):
            pass

        def rollback(self):
            pass

    def _fail(conn, symbol, source, cal):
        raise MissingFxRate("测试注入")

    orig = (cleaning._list_targets, cleaning.clean_one, cleaning._purge_unconverted_rows)
    cleaning._list_targets = lambda conn, symbols: [("BTC-USD", "crypto_yfinance")]
    cleaning.clean_one = _fail
    cleaning._purge_unconverted_rows = (
        lambda conn, symbol, source, total=False: purged.append((symbol, source)) or 0
    )
    try:
        cleaning.rebuild_clean(_Conn(), cal=_Cal([D1]))
    finally:
        cleaning._list_targets, cleaning.clean_one, cleaning._purge_unconverted_rows = orig

    assert purged == []


def test_needs_conversion_matches_conversion_path():
    """needs_conversion 必须与 clean_one 的折算判据一致(用于决定能否清理旧行)。"""
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = ("HKD",)
    assert cleaning.needs_conversion(conn, "HSI", "hk_index_em") is True
    # 展示口径源永远不折算, 即便 currency 非 CNY
    assert cleaning.needs_conversion(conn, "BTC-USD", "crypto_yfinance") is False
    assert cleaning.needs_conversion(conn, "GC=F", "gold_comex_em") is False
    cur.fetchone.return_value = ("CNY",)
    assert cleaning.needs_conversion(conn, "000300", "cn_index_em") is False


def test_purge_requires_provable_conversion_ratio():
    """清理判据必须是「close/raw_close == fx_rate」等式, 而非仅 fx_rate IS NULL。

    否则 fx_rate 有值但 close 未折算的历史行(生产实测 9 个 HKD 指数共 ~16k 行)会留在面板里。
    同时限定 `fill_flag='real'`: 只有 real 行有 raw 行可对照, interp 行是折算后插值的结果。
    """
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.rowcount = 4
    n = cleaning._purge_unconverted_rows(conn, "HSI", "hk_index_em")
    assert n == 4
    sql, params = cur.execute.call_args[0]
    norm = " ".join(sql.split())
    assert "c.fill_flag = 'real'" in norm                # 只判定有 raw 可对照的行
    assert "NOT EXISTS" in norm                          # 保留 = 能证明已折算; 其余删除
    assert "c.close / q.close - c.fx_rate" in norm       # 可证明的等式
    assert "bp_index_quote_daily" in norm                # 需要 raw 价参与判定
    assert params == ("HSI", "hk_index_em")


def test_purge_total_mode_wipes_everything():
    """total=True(币种无汇率标的) → 整表删除, 不依赖任何等式。"""
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.rowcount = 73
    n = cleaning._purge_unconverted_rows(conn, "越南胡志明", "global_index_em", total=True)
    assert n == 73
    sql, params = cur.execute.call_args[0]
    norm = " ".join(sql.split())
    assert norm == "DELETE FROM bp_quote_clean WHERE symbol = %s AND source = %s"
    assert params == ("越南胡志明", "global_index_em")


def test_load_fx_panel_ignores_interp_rows():
    """汇率取数只认 real 行: 插值价不是可成交价, 与回测取价口径一致。"""
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [(D1, 7.0)]
    out = cleaning._load_fx_panel(conn, "USDCNY", D1, D4)
    assert out == {D1: 7.0}
    sql = cur.execute.call_args[0][0]
    assert "fill_flag = 'real'" in " ".join(sql.split())


def test_fx_sina_symbol_parsing():
    from bp_ingest.sources import fx_sina_symbol

    assert fx_sina_symbol("USDCNY") == "fx_susdcny"
    assert fx_sina_symbol("hkdCny") == "fx_shkdcny"
    assert fx_sina_symbol("JPYCNY") == "fx_sjpycny"
    assert fx_sina_symbol("BTC-USD") is None
    assert fx_sina_symbol("EUR") is None
    assert fx_sina_symbol("USDJPY") is None


# ---------------------------------------------------------------------
# 真实 PostgreSQL 行为回归(BP_TEST_DSN 未设置时跳过; 见 deploy/OPS.md 的 scratch-DB 流程)
# ---------------------------------------------------------------------
_real_db = pytest.mark.skipif(
    not os.environ.get("BP_TEST_DSN"),
    reason="real-DB behaviour test; set BP_TEST_DSN=postgresql://user:pass@host/db to run",
)

_SYM, _SRC = "__T_fx__", "__t_fx__"


@_real_db
def test_purge_deletes_corrupted_rows_and_keeps_interp_real_db():
    """生产实证过的脏行形状必须被清掉, 且不能误伤折算后的插值行。

    背景: 部署版清洗代码的 `_UPSERT_SQL` 不含 fx_rate, ON CONFLICT 时只把 close 改回
    原币价而保留 fx_rate → 落成 `close/raw_close = 1.0 ≠ fx_rate` 的自相矛盾行(实测
    9 个 HKD 指数 + 印度 SENSEX 共 18,509 行)。同时 interp 行由两侧**已折算**的 real 行
    插值而来(已是 CNY), 且没有 raw 行可对照 —— 用同一条 NOT EXISTS 判定会把它们一并
    删掉(实测会误删 1,402 行)。本测试把这两种行同时放进真实库, 断言前者被删、后者留存。
    """
    import psycopg

    from bp_api.quant.cleaning import _purge_unconverted_rows

    d1, d2, d3 = date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4)
    with psycopg.connect(os.environ["BP_TEST_DSN"], autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM bp_quote_clean WHERE symbol=%s AND source=%s", (_SYM, _SRC)
            )
            cur.execute(
                "DELETE FROM bp_index_quote_daily WHERE symbol=%s AND source=%s",
                (_SYM, _SRC),
            )
            # 原始行: 三天的原币收盘 100 / 101 / 102
            cur.executemany(
                "INSERT INTO bp_index_quote_daily (trade_date, symbol, source, close) "
                "VALUES (%s,%s,%s,%s)",
                [(d, _SYM, _SRC, c) for d, c in ((d1, 100), (d2, 101), (d3, 102))],
            )
            # d1 已正确折算(close=100×0.855=85.5) → 必须保留
            # d2 fx_rate 有值但 close 未折算(仍 101) → 必须删除
            # d3 interp 行(无对应 raw 行可对照, 但由 d1/d3 折算价插值而出) → 必须保留
            cur.executemany(
                "INSERT INTO bp_quote_clean "
                "(trade_date, symbol, source, close, fill_flag, fx_rate) VALUES (%s,%s,%s,%s,%s,%s)",
                [
                    (d1, _SYM, _SRC, 85.5, "real", 0.855),
                    (d2, _SYM, _SRC, 101.0, "real", 0.855),
                ],
            )
            cur.execute(
                "INSERT INTO bp_quote_clean "
                "(trade_date, symbol, source, close, fill_flag, fx_rate) VALUES (%s,%s,%s,%s,%s,%s)",
                (d3, _SYM, _SRC, 86.5, "interp", None),
            )
        conn.commit()
        try:
            n = _purge_unconverted_rows(conn, _SYM, _SRC)
            conn.commit()
            assert n == 1  # 只删 d2
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT trade_date, fill_flag FROM bp_quote_clean "
                    "WHERE symbol=%s AND source=%s ORDER BY trade_date",
                    (_SYM, _SRC),
                )
                assert cur.fetchall() == [(d1, "real"), (d3, "interp")]
        finally:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM bp_quote_clean WHERE symbol=%s AND source=%s", (_SYM, _SRC)
                )
                cur.execute(
                    "DELETE FROM bp_index_quote_daily WHERE symbol=%s AND source=%s",
                    (_SYM, _SRC),
                )
            conn.commit()


@_real_db
def test_purge_total_mode_clears_all_rows_real_db():
    """total=True(币种无汇率标的)整表清空, 不给原币行留残存机会。"""
    import psycopg

    from bp_api.quant.cleaning import _purge_unconverted_rows

    with psycopg.connect(os.environ["BP_TEST_DSN"], autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM bp_quote_clean WHERE symbol=%s AND source=%s", (_SYM, _SRC)
            )
            cur.executemany(
                "INSERT INTO bp_quote_clean "
                "(trade_date, symbol, source, close, fill_flag, fx_rate) VALUES (%s,%s,%s,%s,%s,%s)",
                [
                    (date(2026, 3, 2), _SYM, _SRC, 100.0, "real", None),
                    (date(2026, 3, 3), _SYM, _SRC, 101.0, "interp", None),
                ],
            )
        conn.commit()
        try:
            assert _purge_unconverted_rows(conn, _SYM, _SRC, total=True) == 2
            conn.commit()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM bp_quote_clean WHERE symbol=%s AND source=%s",
                    (_SYM, _SRC),
                )
                assert cur.fetchone()[0] == 0
        finally:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM bp_quote_clean WHERE symbol=%s AND source=%s", (_SYM, _SRC)
                )
            conn.commit()
