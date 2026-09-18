"""行情清洗: 按 A股交易日历对齐 + 线性插值 + 外币资产 CNY 折算, 构建物化表 bp_quote_clean。

规则:
  1. 以 A股交易日历为基准, 把每个 (symbol, source) 的原始序列 reindex 到
     其[首个真实值, 最后真实值]区间内的 A股交易日 → 剔除所有 A股非交易日的行。
  2. 内部缺口(两侧均有真实值)用线性插值填充, fill_flag=interp。
  3. 前导/尾部不外推(区间端点本身即真实值, 故区间内不会出现无锚点缺口)。
     "某资产相对其他资产停更" 的尾部缺口在回测构面板时检测并报错(见 backtest)。
  4. 基于清洗后 close 重算日简单收益 ret。
  5. **外币折算(2026-09)**: 非 CNY 资产先按日折算出人民币 OHLC, 再在折算价上做插值
     (见下方 _convert_to_cny); CNY 资产 fx_rate=1 且价格原样。

提供 rebuild_clean() 供 bp_ingest 增量刷新或独立全量构建调用。
"""

from __future__ import annotations

import logging
from datetime import date as _date
from typing import Optional

import pandas as pd
import psycopg

from bp_ingest.calendar import TradingCalendar

logger = logging.getLogger(__name__)


_UPSERT_SQL = """
INSERT INTO bp_quote_clean
    (trade_date, symbol, source, close, open, high, low, volume, ret, fx_rate, fill_flag)
VALUES
    (%(trade_date)s, %(symbol)s, %(source)s, %(close)s, %(open)s, %(high)s,
     %(low)s, %(volume)s, %(ret)s, %(fx_rate)s, %(fill_flag)s)
ON CONFLICT (symbol, source, trade_date) DO UPDATE SET
    close     = EXCLUDED.close,
    open      = EXCLUDED.open,
    high      = EXCLUDED.high,
    low       = EXCLUDED.low,
    volume    = EXCLUDED.volume,
    ret       = EXCLUDED.ret,
    fx_rate   = EXCLUDED.fx_rate,
    fill_flag = EXCLUDED.fill_flag,
    updated_at = now()
"""

# ---------------------------------------------------------------------
# 外币 → CNY 折算
#
# 口径决策(2026-09, 与用户确认):
#   - 汇率**只有新浪一个口径**(bp_data_source.fx_sina)。实测新浪「人民币汇率」与中行牌价
#     是两套口径(USD 日变动相关 0.149, ±2 日移位检验排除日期错位), 不可聚合/不可互换。
#     资产池出现过的外币币种均已实测可直取(见 _CURRENCY_PAIR)。
#   - **先折算再插值**: 折算因子按日精确取值(无 ffill/不外推), 与插值无关; 先折算使插值
#     发生在同一币种的序列上。若先插值再折算, 插值日的净值会混入当日汇率 → 引入汇率噪声。
#   - **无汇率日不处理**: 该日不产出清洗行(在插值后显式置 NaN, 否则 interpolate 会把它
#     当成普通缺口填掉), 并删除上一轮可能残留的该日旧行; 前导空白/尾部缺口由既有机制接管。
#   - **尾部护栏**: 汇率整体落后资产价格超过 _FX_TAIL_TOL_DAYS 自然日 → 抛 MissingFxRate
#     中止该资产本轮清洗, 保留上一轮完整结果(避免净值静默截断且无人发现)。
#   - **OHLC 同时乘汇率**: 收益率/协方差/回撤必须与 close 同口径; 只折 close 会让
#     open/high/low 与 close 币种不一致(前端 K 线/振幅类展示失真)。
#   - **volume/amount 不折算**: volume 是股数/手数(无币种), amount 本就不入清洗表。
#   - 交叉汇率: 优先用新浪**直接报价**的 {币种}CNY(实测 EUR/GBP/AUD/KRW/INR/RUB/BRL 均可直取),
#     直取比美元三角合成少一层误差。仅当某币种新浪无直接报价时才需三角合成 —— 目前
#     资产池里只有 VND 属于此类(且新浪报价精度 4 位小数下恒为 0.0000, 不可用), 故仍抛
#     MissingFxRate; 静默跳过会让组合面板里的外币资产悄悄以原币混入。
# ---------------------------------------------------------------------

# 资产币种 → 新浪人民币汇率标的({币种}CNY@fx_sina)。
# 覆盖资产池里出现过的全部外币币种; 新增币种前先用 `_fetch_fx_sina` 实测该对是否可直取。
_CURRENCY_PAIR: dict[str, str] = {
    "USD": "USDCNY",
    "HKD": "HKDCNY",
    "JPY": "JPYCNY",
    "EUR": "EURCNY",
    "GBP": "GBPCNY",
    "AUD": "AUDCNY",
    "KRW": "KRWCNY",
    "INR": "INRCNY",
    "RUB": "RUBCNY",
    "BRL": "BRLCNY",
}

# 不参与折算的 source: close 的原生计价单位**就是** /crypto 看板的展示口径(BTC/DXY/GC),
# 折算会静默改掉该看板与相关性口径 → 这些行 fx_rate 恒为 NULL 是**设计**。
# 注意: 它们在 /builder 里仍是可选资产(is_selectable=TRUE); 若加入组合, 就是把一条原币
# 序列混进 CNY 折算面板。要彻底杜绝需在 list_assets 排除这三个 source 或前端置灰。
_NEVER_CONVERT_SOURCES = frozenset({"crypto_yfinance", "dxy_em", "gold_comex_em"})

FX_SOURCE = "fx_sina"


def _load_currency(conn: psycopg.Connection, symbol: str, source: str) -> str:
    """读取资产计价币种; 缺配置行(如测试夹具)视为 CNY。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT currency FROM bp_index_config WHERE symbol = %s AND source = %s",
            (symbol, source),
        )
        row = cur.fetchone()
    return (row[0] or "CNY") if row else "CNY"


class MissingFxRate(RuntimeError):
    """汇率缺失或未覆盖到资产尾部 — 中止该资产本轮清洗, 不产出部分行。

    无汇率日**不处理**(不 ffill/不外推), 但「整个尾部都缺汇率」与「中间偶发缺一日」
    后果不同: 前者会让面板静默截断到汇率最后一天(净值图少一截而无人发现), 故直接
    中止清洗。rebuild_clean 会捕获它并: (1) 保留已折算的历史行, (2) 清掉未折算的旧行
    (fx_rate IS NULL), (3) 打 ERROR 日志。该资产的 last_clean_date 随之落后于
    last_raw_date → 管理端「刷新状态」可见为滞后, 运维据此补汇率。

    `total` 标记清理力度: 币种无汇率标的 / 汇率标的完全没有清洗数据时为 True ——
    该资产**根本不可能**产出 CNY 口径, 其全部清洗行都必须是原币口径, 应整表删除;
    尾部护栏触发时为 False —— 只是折算输入停更, 停止守卫之前的行仍是合法折算结果。
    """

    def __init__(self, message: str, *, total: bool = False) -> None:
        super().__init__(message)
        self.total = total


# 尾部容忍窗口: 汇率比资产价格最多可落后几个自然日仍视为正常(港股/A 股休假差,
# 实测 HKDCNY 比 A 股交易日历最多落后 1 个交易日; 4 天窗口足以吸收长假差)。
_FX_TAIL_TOL_DAYS = 4


def _load_fx_panel(
    conn: psycopg.Connection, pair: str, start: _date, end: _date
) -> dict[_date, float]:
    """读取汇率标的({pair}@fx_sina)在 [start, end] 的**真实**收盘汇率。

    fill_flag='interp' 的行剔除(与回测取价口径一致: 插值价不是可成交价); 缺失的日期
    不在返回值中, 由调用方按「无汇率日不处理」跳过。
    """
    sql = (
        "SELECT trade_date, close FROM bp_quote_clean "
        "WHERE symbol = %s AND source = %s AND fill_flag = 'real'"
    )
    params: list = [pair, FX_SOURCE]
    if start is not None and end is not None:
        sql += " AND trade_date BETWEEN %s AND %s"
        params.extend([start, end])
    sql += " ORDER BY trade_date"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return {r[0]: float(r[1]) for r in rows if r[1] is not None}


def _convert_to_cny(panel: pd.DataFrame, fx: dict) -> pd.DataFrame:
    """把外币 OHLC 按日折算为 CNY(缺失汇率日乘 NaN)。

    缺汇率的日子不在此处「处理」: 它在 clean_one 里被显式置 NaN 而落空, 见模块头口径决策。
    这里只保证「有汇率的日一定按该日真实汇率折算」, 绝不用 ffill/插值汇率凑数。
    """
    rate = _fx_rate_by_day(panel, fx)
    out = panel.copy()
    for col in ("open", "high", "low", "close"):
        out[col] = out[col] * rate
    return out


def _fx_rate_by_day(panel: pd.DataFrame, fx: dict) -> pd.Series:
    """每个交易日的折算汇率; 无汇率日为 NaN(该日后续不产出清洗行)。"""
    return pd.Series(
        {d: fx.get(d) for d in panel.index}, index=panel.index, dtype="float64"
    )


def _to_fx(value) -> Optional[float]:
    """折算汇率落库值(NaN → None; NUMERIC 列不接受 NaN)。"""
    return None if value is None or pd.isna(value) else float(value)


def _fx_column_value(value, convert: bool, currency: str) -> Optional[float]:
    """fx_rate 列语义: CNY 资产=1; 折算资产=当日汇率; 原生 USD 展示口径资产=NULL。"""
    if convert:
        return _to_fx(value)
    return 1.0 if currency == "CNY" else None



def _load_raw(conn: psycopg.Connection, symbol: str, source: str) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT trade_date, open, high, low, close, volume
            FROM bp_index_quote_daily
            WHERE symbol = %s AND source = %s
            ORDER BY trade_date
            """,
            (symbol, source),
        )
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(
        rows, columns=["trade_date", "open", "high", "low", "close", "volume"]
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    return df.set_index("trade_date").sort_index()


def _list_targets(
    conn: psycopg.Connection, symbols: Optional[list[str]]
) -> list[tuple[str, str]]:
    sql = "SELECT DISTINCT symbol, source FROM bp_index_quote_daily"
    params: list = []
    if symbols:
        sql += " WHERE symbol = ANY(%s)"
        params.append(symbols)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [(r[0], r[1]) for r in cur.fetchall()]


def _clean_natural(
    raw: pd.DataFrame, symbol: str, source: str, conn: psycopg.Connection
) -> int:
    """自然日清洗: 不按交易日历对齐, 保留所有原始日期。

    用于加密/外汇/商品等 7×24 交易资产 (yfinance source)。
    直接写入 bp_quote_clean，fill_flag 全部为 'real'。
    这些资产原生以 USD 计价且 /crypto 看板按 USD 展示(见 _NEVER_CONVERT_SOURCES),
    不做 CNY 折算 → fx_rate 留 NULL(除 CNY 计价源外)。
    """
    currency = _load_currency(conn, symbol, source)
    fx_rate = 1.0 if currency == "CNY" else None
    payload = []
    idx = raw.index
    close = raw["close"]
    ret = close.pct_change()
    for d in idx:
        c = close.loc[d]
        if pd.isna(c):
            continue
        r = ret.loc[d]
        v = raw["volume"].loc[d]
        payload.append(
            {
                "trade_date": d,
                "symbol": symbol,
                "source": source,
                "close": float(c),
                "open": None if pd.isna(raw["open"].loc[d]) else float(raw["open"].loc[d]),
                "high": None if pd.isna(raw["high"].loc[d]) else float(raw["high"].loc[d]),
                "low": None if pd.isna(raw["low"].loc[d]) else float(raw["low"].loc[d]),
                "volume": None if pd.isna(v) else int(v),
                "ret": None if pd.isna(r) else float(r),
                "fx_rate": fx_rate,
                "fill_flag": "real",
            }
        )
    if not payload:
        return 0
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_SQL, payload)
    return len(payload)


def _delete_clean_rows(
    conn: psycopg.Connection, symbol: str, source: str, dates: list
) -> int:
    """删除指定日期的清洗行(无汇率日不处理时, 清掉上一轮可能残留的脏行)。"""
    if not dates:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM bp_quote_clean "
            "WHERE symbol = %s AND source = %s AND trade_date = ANY(%s)",
            (symbol, source, dates),
        )
        return cur.rowcount or 0


def _purge_unconverted_rows(
    conn: psycopg.Connection, symbol: str, source: str, total: bool = False
) -> int:
    """删除该资产**无法证明已折算**的清洗行。**仅对「必须折算」的资产调用。**

    中止折算(MissingFxRate)时调用。`fx_rate IS NULL` 不足以判定 —— 生产库里存在
    「fx_rate 有值但 close 未折算」的历史行(2026-09-18 审计发现 9 个 HKD 指数共 16k 行),
    只看 NULL 会把这批行留在面板里, 让原币价格与 CNY 资产混比, 正是本改造要消除的口径错误。
    故 real 行用**可证明的等式**判定: 必须存在对应 raw 行且 `close / raw_close == fx_rate`
    (容差 1e-3, 吸收 NUMERIC(20,6) 落库舍入)。

    `total=True` 用于**该资产根本不可能折算**的情形(币种无汇率标的 / 汇率标的无任何清洗
    数据): 此时**全部**清洗行按定义都是原币口径, 一律删除 —— 这类资产没有可保留的历史。
    `total=False`(尾部护栏触发)保留不动的行: 中途日期的 interp 行没有对应 raw 行可供验证,
    但折算发生在插值**之前**, 其值由两侧已折算的 real 行线性插值而来, 已是 CNY 口径。

    调用前必须确认该资产确实需要折算 —— 对原生 USD 展示口径资产(crypto/dxy/comex,
    其 fx_rate 恒为 NULL 是**设计**而非缺陷)调用本函数会删掉全部行。调用方见 rebuild_clean。
    """
    with conn.cursor() as cur:
        if total:
            cur.execute(
                "DELETE FROM bp_quote_clean WHERE symbol = %s AND source = %s",
                (symbol, source),
            )
        else:
            cur.execute(
                """
                DELETE FROM bp_quote_clean c
                WHERE c.symbol = %s AND c.source = %s
                  AND c.fill_flag = 'real'
                  AND NOT EXISTS (
                        SELECT 1 FROM bp_index_quote_daily q
                         WHERE q.symbol = c.symbol AND q.source = c.source
                           AND q.trade_date = c.trade_date
                           AND q.close IS NOT NULL AND q.close <> 0
                           AND c.fx_rate IS NOT NULL
                           AND abs(c.close / q.close - c.fx_rate) <= 0.001
                      )
                """,
                (symbol, source),
            )
        return cur.rowcount or 0


def needs_conversion(conn: psycopg.Connection, symbol: str, source: str) -> bool:
    """该资产是否必须折算为 CNY(决定能否对它清理未折算旧行)。"""
    if source in _NEVER_CONVERT_SOURCES:
        return False
    return _load_currency(conn, symbol, source) != "CNY"


def clean_one(
    conn: psycopg.Connection, symbol: str, source: str, cal: TradingCalendar
) -> int:
    """清洗单个 (symbol, source) 并写入 bp_quote_clean。返回写入行数。

    外币资产(currency 非 CNY)在**插入窗口前**折算: 按日乘真实汇率, 再在折算价上做
    线性插值; 无汇率日不产出清洗行(见模块头口径决策), 并清掉该日可能残留的旧行。
    """
    raw = _load_raw(conn, symbol, source)
    if raw.empty:
        return 0

    # 加密/外汇/商品(yfinance) 7×24 交易，不按 A 股交易日历对齐，直接透传全量原始数据
    if source == "crypto_yfinance":
        return _clean_natural(raw, symbol, source, conn)

    first, last = raw.index.min(), raw.index.max()

    # ---- 外币折算: 把原始 OHLC 换成 CNY 口径, 再进入 A 股日历对齐 + 插值 ----
    currency = _load_currency(conn, symbol, source)
    convert = currency != "CNY" and source not in _NEVER_CONVERT_SOURCES
    fx_by_day: dict | None = None  # 逐日折算汇率(写入 fx_rate 列); None = CNY 资产(恒 1)
    if convert:
        pair = _CURRENCY_PAIR.get(currency)
        if pair is None:
            raise MissingFxRate(
                f"{symbol}@{source}: 币种 {currency} 无新浪人民币汇率标的; "
                f"需先补 {currency}CNY@fx_sina 数据源并实测新浪是否有该对报价",
                total=True,
            )
        fx = _load_fx_panel(conn, pair, first, last)
        if not fx:
            raise MissingFxRate(
                f"{symbol}@{source}: 汇率标的 {pair}@{FX_SOURCE} 无清洗数据, "
                f"先运行 `python -m bp_ingest run --symbols {pair}`",
                total=True,
            )
        # 尾部护栏: 汇率必须覆盖资产价格尾部, 否则面板会被静默截断到汇率最后一天。
        last_real = raw["close"].last_valid_index()
        fx_last = max(fx)
        if last_real is not None and (last_real - fx_last).days > _FX_TAIL_TOL_DAYS:
            raise MissingFxRate(
                f"{symbol}@{source}: 汇率 {pair}@{FX_SOURCE} 尾部仅到 {fx_last}, "
                f"资产价格到 {last_real}(差 {(last_real - fx_last).days} 天) — "
                f"折算输入停更, 拒绝产出截断的清洗序列"
            )
        panel_src = _convert_to_cny(raw, fx)
        fx_by_day = fx  # 逐日真实汇率(按 raw 帧取, 缺失日不在其中)
    else:
        panel_src = raw

    a_days = cal.trading_days_between(first, last)
    if not a_days:
        return 0

    idx = pd.Index(a_days, name="trade_date")
    panel = panel_src.reindex(idx)

    # 折算汇率对齐到 A 股日历。缺汇率的判定必须基于**原始**帧: 折算后的 close 在缺汇率日
    # 也是 NaN, 无法与「源本身缺价」区分, 会让 interpolate 把「无汇率日」当成普通缺口填掉
    # (与「无汇率日不处理」的口径矛盾)。故先按原始 close 定位, 再在插值后重新置 NaN。
    raw_panel = raw.reindex(idx)
    fx_aligned = _fx_rate_by_day(raw_panel, fx_by_day or {})
    fx_blocked = fx_aligned.isna() & raw_panel["close"].notna()
    missing_days = [d for d in idx if bool(fx_blocked.loc[d])]

    real_mask = panel["close"].notna()
    # 线性插值: 仅内部缺口(limit_area="inside" 不外推; 端点为真实值故区间内必有锚点)
    close = panel["close"].interpolate(method="linear", limit_area="inside")
    open_ = panel["open"].interpolate(method="linear", limit_area="inside")
    high = panel["high"].interpolate(method="linear", limit_area="inside")
    low = panel["low"].interpolate(method="linear", limit_area="inside")
    if fx_by_day is not None and missing_days:
        for frame in (close, open_, high, low):
            frame.loc[missing_days] = float("nan")
        # 清理上一轮可能残留的该日旧行(本轮不产出 → 必须删除, 否则脏行永久留存)
        _delete_clean_rows(conn, symbol, source, missing_days)
        logger.info(
            "折算 %s@%s: %d 日无 %s 汇率, 不产出清洗行(区间 %s ~ %s)",
            symbol, source, len(missing_days), _CURRENCY_PAIR.get(currency, currency),
            min(missing_days), max(missing_days),
        )
    volume = panel["volume"]  # 插值日成交量留空(NaN)

    ret = close.pct_change()

    payload = []
    for d in idx:
        c = close.loc[d]
        if pd.isna(c):
            continue
        v = volume.loc[d]
        r = ret.loc[d]
        payload.append(
            {
                "trade_date": d,
                "symbol": symbol,
                "source": source,
                "close": float(c),
                "open": None if pd.isna(open_.loc[d]) else float(open_.loc[d]),
                "high": None if pd.isna(high.loc[d]) else float(high.loc[d]),
                "low": None if pd.isna(low.loc[d]) else float(low.loc[d]),
                "volume": None if pd.isna(v) else int(v),
                "ret": None if pd.isna(r) else float(r),
                # CNY 资产恒 1; 外币资产记当日折算汇率(无汇率日不产出行);
                # 原生 USD 展示口径资产(BTC/DXY/GC)不折算 → NULL
                "fx_rate": _fx_column_value(fx_aligned.loc[d], convert, currency),
                "fill_flag": "real" if bool(real_mask.loc[d]) else "interp",
            }
        )

    if not payload:
        return 0
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_SQL, payload)

    interp_n = sum(1 for p in payload if p["fill_flag"] == "interp")
    if interp_n:
        logger.info("清洗 %s@%s: %d 行(插值 %d)", symbol, source, len(payload), interp_n)
    return len(payload)


def rebuild_clean(
    conn: psycopg.Connection,
    symbols: Optional[list[str]] = None,
    cal: Optional[TradingCalendar] = None,
) -> int:
    """重建 bp_quote_clean。symbols 为空则处理全部标的。返回总写入行数。

    处理顺序: **汇率源(fx_sina)优先**。外币资产的折算读的是清洗表里汇率标的的
    close, 同一批内若汇率还没洗出来, 折算会因缺输入而整体跳过(打 WARNING)。

    `MissingFxRate` 单独兜底: 折算失败的外币资产必须清掉**无法证明已折算**的旧行,
    否则上一轮以原币写入的行会静默留在面板里与 CNY 资产混比 —— 正是本改造要消除的口径错误。
    清理力度由 `exc.total` 决定(见 MissingFxRate 文档): 币种/汇率标的不存在 → 整表删除,
    尾部停更 → 只删 real 行中折算等式不成立的那些。
    """
    if cal is None:
        cal = TradingCalendar()
        cal.load()
    targets = _list_targets(conn, symbols)
    targets.sort(key=lambda t: 0 if t[1] == FX_SOURCE else 1)
    total = 0
    for symbol, source in targets:
        try:
            total += clean_one(conn, symbol, source, cal)
            conn.commit()
        except MissingFxRate as exc:
            # 仅对「必须折算」的资产清理: 原生 USD 展示口径资产(BTC/DXY/GC)的 fx_rate 恒为
            # NULL 是设计而非缺陷, 对它们跑清理会删光全部行。
            conn.rollback()
            n_purged = 0
            try:
                if needs_conversion(conn, symbol, source):
                    n_purged = _purge_unconverted_rows(
                        conn, symbol, source, total=exc.total
                    )
                    conn.commit()
            except Exception:  # noqa: BLE001
                conn.rollback()
            logger.error(
                "清洗中止 %s@%s(折算依赖缺失): %s%s",
                symbol, source, exc,
                f"; 已清理{'全部' if exc.total else '未折算'}旧行 {n_purged} 行"
                if n_purged else "",
            )
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            logger.error("清洗失败 %s@%s: %s", symbol, source, exc)
    logger.info("清洗完成: 标的=%d 写入行=%d", len(targets), total)
    return total
