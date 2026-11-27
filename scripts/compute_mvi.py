# -*- coding: utf-8 -*-
"""计算市场估值指数 MVI + 风险分，全量写入 bp_market_valuation_index。

模型（研究 v1 定稿，见 docs/index-valuation/21-mvi-research-report.md）：
  cheap = 0.1686*PE分位(反向) + 0.1927*PB分位(反向) + 0.2853*股息率分位
        + 0.2347*ERP分位 + 0.1188*ROE分位
  MVI   = 100 - cheap   （0=极度低估，100=极度高估）
  风险分 = 0.55*60日波动率分位 + 0.45*252日回撤分位（0=安全，100=危险）

2026-11 修复（需求 6）：
  - 分位序列一律先按 A 股交易日历（bp_trading_calendar）重采样：非交易日点（平安
    周频 bar 的周日日期等）映射到该 ISO 周的最后一个交易日，绝不产生周末/非交易日
    的 MVI 点 —— 消除 2026-11-15 / 11-22 这类周日 NaN 点造成的假跳变；
  - rolling 窗口 = 104 周（约 2 年），不是 104 个混合日频/周频点；
  - NaN 处理：当前值为 NaN 时该期分位为 NaN（不落成 0 分位），窗口内 NaN 不参与
    计数；MVI 只在 5 个因子都有效的周生成，缺因子的周直接跳过（不补 0）；
  - 全量重算：先清空 bp_market_valuation_index 再写入周频序列（旧口径残留的每日点
    与周末点一并清除）。
  - **空数据安全（P1-5）**：rows 为空时直接报错退出，**绝不 replace/清空历史**；
    replace 前后都做 min 行数校验（默认 52，可用 BP_MVI_MIN_ROWS 覆盖），任何一项
    不达标都回滚写事务并返回非 0，避免源退化时把正确历史清成 0 行。

运行：
  python scripts/compute_mvi.py          # 全量重算
  python -m scripts.compute_mvi          # 同上
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, "/opt/balanced-portfolio")
sys.path.insert(0, "/opt/balanced-portfolio/bp_ingest")
sys.stdout.reconfigure(encoding="utf-8")

from bp_api.repositories_valuation import replace_market_valuation_index
from bp_ingest.config import load_config
from bp_ingest.db import connect

PROXIES = ["000016", "000300", "000510", "000905", "000852"]
FACTORS = ["cheap_pe", "cheap_pb", "div_pct", "erp_pct", "roe_pct"]
LABELS = {
    "cheap_pe": "PE 分位（反向）",
    "cheap_pb": "PB 分位（反向）",
    "div_pct": "股息率分位",
    "erp_pct": "风险溢价分位",
    "roe_pct": "ROE 分位",
}
WEIGHTS = {
    "cheap_pe": 0.1686,
    "cheap_pb": 0.1927,
    "div_pct": 0.2853,
    "erp_pct": 0.2347,
    "roe_pct": 0.1188,
}
ROLL_WEEKS = 104
MIN_WEEKS = 26
SERIES_START = date(2015, 1, 1)

# 风险分：沪深300 日频波动/回撤 -> 滚动分位
RISK_SYMBOL = "000300"
VOL_WINDOW = 60
VOL_MIN_PERIODS = 40
DRAWDOWN_WINDOW = 252
DRAWDOWN_MIN_PERIODS = 120
RISK_PCT_WINDOW = 1260
RISK_PCT_MIN_PERIODS = 252
VOL_WEIGHT = 0.55
DRAWDOWN_WEIGHT = 0.45

# 全量 replace 的安全下限：低于该行数视为源退化，拒绝清空历史（可用环境变量覆盖）。
MIN_MVI_ROWS_DEFAULT = 52
MIN_MVI_ROWS_ENV = "BP_MVI_MIN_ROWS"


# ---------------------------------------------------------------------------
# 纯函数（可离线单测）
# ---------------------------------------------------------------------------


def rolling_percentile(
    series: pd.Series, window: int, min_periods: int
) -> pd.Series:
    """滚动分位（0-100），NaN 安全。

    规则：当前值为 NaN -> 输出 NaN（绝不落成 0 分位）；窗口内 NaN 不参与计数；
    有效样本数 < min_periods -> 输出 NaN（不伪造分位）。
    """
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    for index in range(len(values)):
        current = values[index]
        if np.isnan(current):
            continue
        window_values = values[max(0, index - window + 1) : index + 1]
        valid = window_values[~np.isnan(window_values)]
        if len(valid) < min_periods:
            continue
        out[index] = float((valid <= current).sum()) / len(valid) * 100.0
    return pd.Series(out, index=series.index)


def to_weekly(series: pd.Series, trading_days: pd.DatetimeIndex) -> pd.Series:
    """按 A 股交易日历把任意日期序列重采样为周频。

    - 非交易日点（如平安周频 bar 的周日日期）映射到该 ISO 周的最后一个交易日；
    - 同一交易日同时有「交易日点」和「映射来的非交易日点」时，交易日点优先；
    - 每周只保留最后一个交易日的值（周频锚点 = 该周最后一个交易日）。
    """
    series = series.dropna().sort_index()
    if series.empty or len(trading_days) == 0:
        return series
    positions = trading_days.searchsorted(series.index, side="right") - 1
    valid = positions >= 0
    anchors = trading_days[positions[valid]]
    frame = pd.DataFrame(
        {"value": series.to_numpy()[valid], "orig": series.index[valid]},
        index=pd.DatetimeIndex(anchors),
    )
    # 「直接落在交易日」的点优先于「非交易日映射过来」的点（同一周同锚点时）
    frame["direct"] = frame["orig"].to_numpy() == frame.index.to_numpy()
    frame = frame.sort_values(["direct", "orig"])
    dedup = frame.groupby(level=0).last()["value"]
    iso = dedup.index.isocalendar()
    grouped = pd.DataFrame(
        {
            "value": dedup.to_numpy(),
            "year": iso.year.to_numpy(),
            "week": iso.week.to_numpy(),
        },
        index=dedup.index,
    )
    weekly = grouped.groupby(["year", "week"]).tail(1)
    return pd.Series(weekly["value"].to_numpy(), index=pd.DatetimeIndex(weekly.index))


def build_factor_panel(
    raw_by_code: dict[str, pd.DataFrame], trading_days: pd.DatetimeIndex
) -> pd.DataFrame:
    """5 宽基 x 5 因子 -> 全市场因子分位面板（周频、NaN 行剔除）。

    raw_by_code[code] 是列含 pe_ttm/pb/dividend_yield_ttm/erp 的日频 DataFrame；
    ROE 由 PB/PE*100 推导（与研究报告一致）。
    """
    frames: dict[str, list[pd.Series]] = {factor: [] for factor in FACTORS}
    for code in sorted(raw_by_code):
        wide = raw_by_code[code]
        if wide is None or wide.empty:
            continue
        if "pe_ttm" not in wide or "pb" not in wide:
            continue
        wide = wide.copy()
        wide["pe_ttm"] = pd.to_numeric(wide["pe_ttm"], errors="coerce")
        wide["pb"] = pd.to_numeric(wide["pb"], errors="coerce")
        wide = wide[wide["pe_ttm"].notna() & wide["pb"].notna()]
        if wide.empty:
            continue
        wide["roe_ttm"] = wide["pb"] / wide["pe_ttm"] * 100.0
        for factor, column, invert in (
            ("cheap_pe", "pe_ttm", True),
            ("cheap_pb", "pb", True),
            ("div_pct", "dividend_yield_ttm", False),
            ("erp_pct", "erp", False),
            ("roe_pct", "roe_ttm", False),
        ):
            if column not in wide:
                continue
            weekly = to_weekly(
                pd.to_numeric(wide[column], errors="coerce"), trading_days
            )
            pct = rolling_percentile(weekly, ROLL_WEEKS, MIN_WEEKS)
            if invert:
                pct = 100.0 - pct
            frames[factor].append(pct.rename(code))
    combined: dict[str, pd.Series] = {}
    for factor, parts in frames.items():
        if parts:
            combined[factor] = pd.concat(parts, axis=1).mean(axis=1, skipna=True)
    if not combined:
        return pd.DataFrame()
    panel = pd.DataFrame(combined).sort_index()
    # 只在 5 因子齐全的周生成 MVI：分母权重是固定的，缺因子不能按 0 处理
    return panel.dropna()


def compute_risk_series(close: pd.Series) -> pd.DataFrame:
    """由指数收盘算日频风险因子与风险分（波动率分位 55% + 回撤分位 45%）。"""
    close = pd.to_numeric(close, errors="coerce").dropna().sort_index()
    if close.empty:
        return pd.DataFrame()
    close = close[~close.index.duplicated(keep="last")]
    returns = close.pct_change()
    vol = returns.rolling(VOL_WINDOW, min_periods=VOL_MIN_PERIODS).std() * np.sqrt(252) * 100
    vol_pct = rolling_percentile(vol, RISK_PCT_WINDOW, RISK_PCT_MIN_PERIODS).rename(
        "vol_pct"
    )
    drawdown = close / close.rolling(DRAWDOWN_WINDOW, min_periods=DRAWDOWN_MIN_PERIODS).max() - 1.0
    dd_pct = rolling_percentile(-drawdown, RISK_PCT_WINDOW, RISK_PCT_MIN_PERIODS).rename(
        "dd_pct"
    )
    risk = pd.concat([vol_pct, dd_pct], axis=1)
    risk["risk_score"] = VOL_WEIGHT * risk["vol_pct"] + DRAWDOWN_WEIGHT * risk["dd_pct"]
    return risk


def zone_of(mvi: float) -> str:
    if mvi < 20:
        return "极度低估"
    if mvi < 40:
        return "低估"
    if mvi < 60:
        return "合理"
    if mvi < 80:
        return "高估"
    return "极度高估"


def compute_mvi_rows(panel: pd.DataFrame, risk_weekly: pd.DataFrame) -> list[dict]:
    """因子面板 + 周频风险 -> bp_market_valuation_index 行（幂等/确定性）。"""
    rows: list[dict] = []
    if panel is None or panel.empty:
        return rows
    for as_of, factor_row in panel.iterrows():
        factor_values = {factor: float(factor_row[factor]) for factor in FACTORS}
        cheap = float(sum(WEIGHTS[factor] * factor_values[factor] for factor in FACTORS))
        mvi = 100.0 - cheap
        risk_row = None
        if risk_weekly is not None and not risk_weekly.empty and as_of in risk_weekly.index:
            risk_row = risk_weekly.loc[as_of]
        risk_score = None
        vol_pct = None
        dd_pct = None
        if risk_row is not None:
            if pd.notna(risk_row.get("risk_score")):
                risk_score = float(risk_row["risk_score"])
            if pd.notna(risk_row.get("vol_pct")):
                vol_pct = float(risk_row["vol_pct"])
            if pd.notna(risk_row.get("dd_pct")):
                dd_pct = float(risk_row["dd_pct"])
        rows.append(
            {
                "as_of": as_of.date(),
                "mvi": round(mvi, 2),
                "cheap_score": round(cheap, 2),
                "risk_score": None if risk_score is None else round(risk_score, 2),
                "zone": zone_of(mvi),
                "factors": json.dumps(
                    {LABELS[f]: round(factor_values[f], 2) for f in FACTORS},
                    ensure_ascii=False,
                ),
                "weights": json.dumps(
                    {LABELS[f]: WEIGHTS[f] for f in FACTORS}, ensure_ascii=False
                ),
                "contributions": json.dumps(
                    {LABELS[f]: round(WEIGHTS[f] * factor_values[f], 2) for f in FACTORS},
                    ensure_ascii=False,
                ),
                "risk_factors": json.dumps(
                    {"波动率分位": None if vol_pct is None else round(vol_pct, 2),
                     "回撤分位": None if dd_pct is None else round(dd_pct, 2)},
                    ensure_ascii=False,
                ),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# 数据库读取（只读）
# ---------------------------------------------------------------------------


def load_trading_days(conn) -> pd.DatetimeIndex:
    df = pd.read_sql(
        "SELECT cal_date FROM bp_trading_calendar WHERE is_trading ORDER BY cal_date",
        conn,
    )
    if df.empty:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(pd.to_datetime(df["cal_date"]).sort_values().unique())


def load_factor_series(
    conn, proxies: list[str] | None = None
) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for code in proxies or PROXIES:
        df = pd.read_sql(
            """
            SELECT trade_date, metric, value FROM bp_index_valuation_series
            WHERE index_code = %s AND trade_date >= %s
              AND metric IN ('pe_ttm', 'pb', 'dividend_yield_ttm', 'erp')
            """,
            conn,
            params=(code, SERIES_START),
        )
        if df.empty:
            continue
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        wide = df.pivot_table(
            index="trade_date", columns="metric", values="value", aggfunc="last"
        ).sort_index()
        result[code] = wide.apply(pd.to_numeric, errors="coerce")
    return result


def load_risk_prices(conn, symbol: str = RISK_SYMBOL) -> pd.Series:
    df = pd.read_sql(
        """
        SELECT trade_date, close, updated_at FROM bp_index_quote_daily
        WHERE symbol = %s AND adjust = 'bfq' AND close IS NOT NULL
        ORDER BY trade_date, updated_at
        """,
        conn,
        params=(symbol,),
    )
    if df.empty:
        return pd.Series(dtype=float)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.drop_duplicates(subset=["trade_date"], keep="last").set_index("trade_date")
    return pd.to_numeric(df["close"], errors="coerce").dropna().sort_index()


def load_panel(conn, proxies: list[str] | None = None) -> pd.DataFrame:
    trading_days = load_trading_days(conn)
    raw = load_factor_series(conn, proxies)
    return build_factor_panel(raw, trading_days)


def load_risk_series(conn, symbol: str = RISK_SYMBOL) -> pd.DataFrame:
    return compute_risk_series(load_risk_prices(conn, symbol))


def align_weekly_risk(risk: pd.DataFrame, weekly_index: pd.Index) -> pd.DataFrame:
    """把日频风险因子对齐到周频锚点（最近一个交易日，前向填充）。"""
    if risk is None or risk.empty or len(weekly_index) == 0:
        return pd.DataFrame()
    return risk.reindex(weekly_index.sort_values(), method="ffill")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def min_expected_rows() -> int:
    """replace 安全下限（默认 52 周；BP_MVI_MIN_ROWS 显式覆盖，非法值回退默认）。"""
    raw = (os.getenv(MIN_MVI_ROWS_ENV) or "").strip()
    if not raw:
        return MIN_MVI_ROWS_DEFAULT
    try:
        value = int(raw)
    except ValueError:
        print(
            f"WARN: {MIN_MVI_ROWS_ENV}={raw!r} 非法（需正整数），使用默认 {MIN_MVI_ROWS_DEFAULT}",
            file=sys.stderr,
        )
        return MIN_MVI_ROWS_DEFAULT
    return value if value > 0 else MIN_MVI_ROWS_DEFAULT


def _stored_row_count(conn) -> int:
    """当前 bp_market_valuation_index 行数（replace 前后校验用）。"""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM bp_market_valuation_index")
        row = cur.fetchone()
    return int(row[0] or 0) if row else 0


def main(
    proxies: list[str] | None = None, risk_symbol: str = RISK_SYMBOL
) -> int:
    """全量重算 MVI（proxies/risk_symbol 仅测试注入用，CLI 走默认值）。

    安全约束（P1-5）：rows 为空 / 低于 min 行数时**直接失败退出，不写库、不 DELETE**；
    replace 后再核对表内行数，异常则回滚写事务。退出码：0=成功；2=新数据不足未写库；
    3=写入后校验失败已回滚。
    """
    cfg = load_config()
    with connect(cfg.db) as conn:
        panel = load_panel(conn, proxies)
        risk = load_risk_series(conn, risk_symbol)
    risk_weekly = align_weekly_risk(risk, panel.index)
    rows = compute_mvi_rows(panel, risk_weekly)

    min_rows = min_expected_rows()
    if not rows:
        print(
            "ERROR: MVI rows=0（估值序列为空/源退化），拒绝 replace 清空历史；"
            "未对 bp_market_valuation_index 执行任何写操作",
            file=sys.stderr,
        )
        return 2
    if len(rows) < min_rows:
        print(
            f"ERROR: MVI rows={len(rows)} < min_rows={min_rows}"
            f"（{MIN_MVI_ROWS_ENV} 可调），拒绝 replace 清空历史；未写库",
            file=sys.stderr,
        )
        return 2

    with connect(cfg.db) as conn:
        written = replace_market_valuation_index(conn, rows)
        stored = _stored_row_count(conn)
        if written < len(rows) or stored < min_rows or stored < len(rows):
            # 已执行 DELETE+INSERT 的事务整体回滚，保证历史数据不被半截数据覆盖。
            conn.rollback()
            print(
                f"ERROR: MVI replace 后校验失败 written={written} stored={stored}"
                f" expected={len(rows)} min_rows={min_rows}，已回滚写事务（历史保留）",
                file=sys.stderr,
            )
            return 3
        # 全局数据新鲜度（bp_api.freshness / ddl/79）：MVI 写入后同步；表缺失时静默跳过
        try:
            from bp_api.freshness import sync_derived_freshness

            sync_derived_freshness(conn, ("mvi",))
        except Exception:  # noqa: BLE001
            pass
    latest = rows[-1] if rows else None
    print(
        "rows:",
        written,
        "latest:",
        json.dumps(latest, ensure_ascii=False, default=str)[:400] if latest else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
