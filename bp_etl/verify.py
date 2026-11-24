"""重建/日常校验：覆盖、锚定一致性、hfq/bfq 比率漂移。

只读；输出可直接写入 docs/data/etl-verification.json。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable, Sequence

from bp_etl.registry import REGISTRY, DatasetSpec


def ratio_drift_stats(ratios: Sequence[float | None], *, max_change: float = 0.005) -> dict[str, Any]:
    """给定按日期排序的 hfq/bfq 比率序列，统计非除权日漂移比例。"""
    valid = [float(value) for value in ratios if value is not None and float(value) > 0]
    changes = 0
    big = 0
    for previous, current in zip(valid, valid[1:]):
        changes += 1
        if abs(current / previous - 1.0) > max_change:
            big += 1
    return {
        "points": len(valid),
        "transitions": changes,
        "drift_count": big,
        "drift_ratio": round(big / changes, 6) if changes else 0.0,
        "ok": (big / changes <= 0.01) if changes else True,
    }


def _dataset_summary(conn: Any, spec: DatasetSpec) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for adjust in (spec.adjust_modes or ("bfq",)):
        sql = (
            f"SELECT count(*), count(DISTINCT {spec.key_column}), min(trade_date), max(trade_date)"
            f" FROM {spec.table} WHERE adjust = %s"
        )
        with conn.cursor() as cur:
            cur.execute(sql, (adjust,))
            rows, symbols, first, last = cur.fetchone()
        out.append(
            {
                "dataset": spec.name,
                "adjust": adjust,
                "rows": int(rows),
                "symbols": int(symbols),
                "first_date": str(first) if first else None,
                "last_date": str(last) if last else None,
            }
        )
    return out


def _market_filter(spec: DatasetSpec) -> str:
    """同一张 stock 表按 symbol 长度区分 A 股(6)/港股(5)，避免抽样串市场。"""
    if spec.table == "bp_stock_quote_daily":
        return " AND length(symbol)=6" if spec.name == "a_stock" else " AND length(symbol)=5"
    return ""


def sample_ratio_drift(
    conn: Any, spec: DatasetSpec, *, sample: int = 100, days: int = 60, seed: int = 42
) -> dict[str, Any]:
    """抽样检查 hfq/bfq 比率常数性（除权日变化属正常，比例阈值 1%）。"""
    if spec.value_kind != "bar" or "hfq" not in spec.adjust_modes:
        return {"skipped": True}
    since = date.today() - timedelta(days=days)
    sql = (
        f"SELECT {spec.key_column} FROM {spec.table} WHERE adjust='hfq'"
        f"{_market_filter(spec)} GROUP BY 1 ORDER BY 1 LIMIT %s"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (sample * 3,))
        codes = [row[0] for row in cur.fetchall()][:sample]
    totals = {"points": 0, "transitions": 0, "drift_count": 0}
    for code in codes:
        pair_sql = (
            f"SELECT trade_date, max(CASE WHEN adjust='bfq' THEN close END) AS bfq,"
            f" max(CASE WHEN adjust='hfq' THEN close END) AS hfq"
            f" FROM {spec.table} WHERE {spec.key_column} = %s AND trade_date >= %s"
            f"{_market_filter(spec)}"
            " GROUP BY trade_date ORDER BY trade_date"
        )
        with conn.cursor() as cur:
            cur.execute(pair_sql, (code, since))
            ratios = [
                (row[2] / row[1]) if row[1] and row[2] and row[1] > 0 else None
                for row in cur.fetchall()
            ]
        stats = ratio_drift_stats(ratios)
        totals["points"] += stats["points"]
        totals["transitions"] += stats["transitions"]
        totals["drift_count"] += stats["drift_count"]
    totals["drift_ratio"] = (
        round(totals["drift_count"] / totals["transitions"], 6) if totals["transitions"] else 0.0
    )
    totals["ok"] = totals["drift_ratio"] <= 0.01
    totals["sampled_symbols"] = len(codes)
    return totals


def verify_rebuild(config: Any, *, datasets: Iterable[str] = ("a_stock", "hk_stock", "etf"), sample: int = 100) -> dict[str, Any]:
    from bp_ingest.db import connect

    payload: dict[str, Any] = {"generated_at": None, "datasets": []}
    from datetime import datetime, timezone, timedelta

    payload["generated_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
    with connect(config.db) as conn:
        for name in datasets:
            spec = REGISTRY[name]
            payload["datasets"].extend(_dataset_summary(conn, spec))
            drift = sample_ratio_drift(conn, spec, sample=sample)
            payload.setdefault("ratio_drift", {})[name] = drift
    return payload