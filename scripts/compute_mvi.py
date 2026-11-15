# -*- coding: utf-8 -*-
"""每日计算市场估值指数 MVI + 风险分，写入 bp_market_valuation_index。

模型（研究 v1 定稿，见 docs/index-valuation/21-mvi-research-report.md）：
  cheap = 0.1686*PE分位(反向) + 0.1927*PB分位(反向) + 0.2853*股息率分位
        + 0.2347*ERP分位 + 0.1188*ROE分位
  MVI   = 100 - cheap   （0=极度低估，100=极度高估）
  风险分 = 0.55*60日波动率分位 + 0.45*回撤分位（0=安全，100=危险）
"""
from __future__ import annotations

import json
import sys
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, "/opt/balanced-portfolio")
sys.path.insert(0, "/opt/balanced-portfolio/bp_ingest")
sys.stdout.reconfigure(encoding="utf-8")

from bp_api.repositories_valuation import upsert_market_valuation_index
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


def rolling_percentile(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    def pct_rank(values: np.ndarray) -> float:
        return float((values <= values[-1]).sum()) / len(values) * 100.0
    return series.rolling(window, min_periods=min_periods).apply(pct_rank, raw=True)


def load_panel(conn) -> pd.DataFrame:
    factor_frames: dict[str, list[pd.Series]] = {f: [] for f in FACTORS}
    for code in PROXIES:
        query = """
            SELECT trade_date, metric, value FROM bp_index_valuation_series
            WHERE index_code = %s AND trade_date >= DATE '2015-01-01'
              AND metric IN ('pe_ttm', 'pb', 'dividend_yield_ttm', 'erp')
        """
        df = pd.read_sql(query, conn, params=(code,))
        if df.empty:
            continue
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        wide = df.pivot_table(index="trade_date", columns="metric", values="value", aggfunc="last").sort_index()
        wide = wide.apply(pd.to_numeric, errors="coerce")
        if "pe_ttm" not in wide or "pb" not in wide:
            continue
        wide = wide[wide["pe_ttm"].notna() & wide["pb"].notna()]
        wide["roe_ttm"] = wide["pb"] / wide["pe_ttm"] * 100.0
        for factor, col, invert in [
            ("cheap_pe", "pe_ttm", True), ("cheap_pb", "pb", True),
            ("div_pct", "dividend_yield_ttm", False), ("erp_pct", "erp", False),
            ("roe_pct", "roe_ttm", False),
        ]:
            pct = rolling_percentile(wide[col].astype(float), ROLL_WEEKS, MIN_WEEKS)
            if invert:
                pct = 100.0 - pct
            factor_frames[factor].append(pct.rename("p"))
    combined = {}
    for factor, frames in factor_frames.items():
        if frames:
            combined[factor] = pd.concat(frames, axis=1).mean(axis=1, skipna=True)
    panel = pd.DataFrame(combined).sort_index()
    return panel.dropna(subset=["cheap_pe", "cheap_pb"]).dropna()


def load_risk_series(conn) -> pd.DataFrame:
    """沪深300 波动率/回撤分位（日频）。"""
    df = pd.read_sql(
        "SELECT trade_date, close FROM bp_index_quote_daily "
        "WHERE symbol = '000300' AND adjust = 'bfq' ORDER BY trade_date",
        conn,
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.drop_duplicates(subset=["trade_date"], keep="last").set_index("trade_date").sort_index()
    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    returns = close.pct_change()
    vol = returns.rolling(60, min_periods=40).std() * np.sqrt(252) * 100
    vol_pct = rolling_percentile(vol, 1260, 252).rename("vol_pct")
    drawdown = close / close.rolling(252, min_periods=120).max() - 1.0
    dd_pct = rolling_percentile(-drawdown, 1260, 252).rename("dd_pct")
    risk = pd.concat([vol_pct, dd_pct], axis=1).dropna()
    risk["risk_score"] = 0.55 * risk["vol_pct"] + 0.45 * risk["dd_pct"]
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


def main() -> int:
    cfg = load_config()
    with connect(cfg.db) as conn:
        panel = load_panel(conn)
        risk = load_risk_series(conn)
    risk_aligned = risk.reindex(panel.index, method="ffill")
    rows = []
    for as_of, factor_row in panel.iterrows():
        cheap = float(sum(WEIGHTS[f] * float(factor_row[f]) for f in FACTORS))
        mvi = 100.0 - cheap
        risk_row = risk_aligned.loc[as_of] if as_of in risk_aligned.index else None
        risk_score = float(risk_row["risk_score"]) if risk_row is not None and pd.notna(risk_row["risk_score"]) else None
        rows.append({
            "as_of": as_of.date(),
            "mvi": round(mvi, 2),
            "cheap_score": round(cheap, 2),
            "risk_score": None if risk_score is None else round(risk_score, 2),
            "zone": zone_of(mvi),
            "factors": json.dumps({LABELS[f]: round(float(factor_row[f]), 2) for f in FACTORS}, ensure_ascii=False),
            "weights": json.dumps({LABELS[f]: WEIGHTS[f] for f in FACTORS}, ensure_ascii=False),
            "contributions": json.dumps({LABELS[f]: round(WEIGHTS[f] * float(factor_row[f]), 2) for f in FACTORS}, ensure_ascii=False),
            "risk_factors": json.dumps(
                {
                    "波动率分位": None if risk_row is None else round(float(risk_row["vol_pct"]), 2),
                    "回撤分位": None if risk_row is None else round(float(risk_row["dd_pct"]), 2),
                },
                ensure_ascii=False,
            ) if risk_row is not None else None,
        })
    with connect(cfg.db) as conn:
        conn.autocommit = False
        upsert_market_valuation_index(conn, rows)
        conn.commit()
    latest = rows[-1] if rows else None
    print("rows:", len(rows), "latest:", json.dumps(latest, ensure_ascii=False, default=str)[:400] if latest else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
