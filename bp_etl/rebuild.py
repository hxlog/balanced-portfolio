"""历史单锚重建（D4）：A 股 hfq = 库内 bfq 历史 × 新浪 hfq 因子；港股/ETF 源收敛 + 近端补缺。

原则：
- 同一 (dataset, adjust) 只保留一个锚定源的绝对基准；重建后删除其它源的该口径行（防跨源跳变）。
- bfq 是不复权原始价，跨源数值一致，保留历史来源（quote_store 按优先级去重），不做删除。
- 断点友好：按 symbol 处理，已完整的 symbol 跳过（--force 才重算）。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable, Sequence

from bp_etl import adapters, writer
from bp_etl.adapters.base import Bar
from bp_etl.channels import ChannelManager
from bp_etl.config import EtlConfig
from bp_etl.datasets._common import fetch_parallel, missing_symbols
from bp_etl.registry import REGISTRY, DatasetSpec

logger = logging.getLogger(__name__)

A_STOCK = REGISTRY["a_stock"]
HK_STOCK = REGISTRY["hk_stock"]
ETF = REGISTRY["etf"]

BFQ_SOURCE_PRIORITY = (
    "CASE source WHEN 'tencent_qt' THEN 0 WHEN 'tencent_kline' THEN 1"
    " WHEN 'sina_kline' THEN 2 ELSE 3 END"
)


@dataclass
class RebuildReport:
    dataset: str
    adjust: str
    symbols: int = 0
    written: int = 0
    failed: int = 0
    skipped: int = 0
    deleted_legacy: int = 0
    elapsed_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "adjust": self.adjust,
            "symbols": self.symbols,
            "written": self.written,
            "failed": self.failed,
            "skipped": self.skipped,
            "deleted_legacy": self.deleted_legacy,
            "elapsed_s": round(self.elapsed_s, 1),
        }


def default_conn_factory(config: EtlConfig) -> Callable[[], Any]:
    from bp_ingest.db import connect

    return lambda: connect(config.db)


def read_bfq_history(
    conn: Any, spec: DatasetSpec, symbol: str, since: date
) -> list[Bar]:
    """读取该标的 bfq 历史（多源按优先级去重，日期唯一）。"""
    sql = (
        f"SELECT DISTINCT ON (trade_date) trade_date, open, high, low, close, volume, amount"
        f" FROM {spec.table}"
        f" WHERE {spec.key_column} = %s AND adjust = 'bfq' AND trade_date >= %s"
        f" ORDER BY trade_date, {BFQ_SOURCE_PRIORITY}"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (symbol, since))
        rows = cur.fetchall()
    return [
        Bar(
            symbol=symbol, trade_date=row[0],
            open=_f(row[1]), high=_f(row[2]), low=_f(row[3]), close=float(row[4]),
            volume=int(row[5]) if row[5] is not None else None,
            amount=_f(row[6]), source="rebuild_bfq", adjust="bfq",
        )
        for row in rows
        if row[4] is not None
    ]


def _f(value: Any) -> float | None:
    return None if value is None else float(value)


def delete_other_sources(
    conn: Any, spec: DatasetSpec, adjust: str, anchor_source: str, *, symbols: Sequence[str] | None = None
) -> int:
    """删除某口径下非锚定源的行（防跨源绝对基准跳变）。"""
    sql = f"DELETE FROM {spec.table} WHERE adjust = %s AND source <> %s"
    params: list = [adjust, anchor_source]
    if symbols:
        sql += f" AND {spec.key_column} = ANY(%s)"
        params.append(list(symbols))
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return int(cur.rowcount or 0)


def _existing_hfq_dates(conn: Any, spec: DatasetSpec, symbol: str, anchor: str) -> set[date]:
    sql = (
        f"SELECT trade_date FROM {spec.table}"
        f" WHERE {spec.key_column} = %s AND adjust = 'hfq' AND source = %s"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (symbol, anchor))
        return {row[0] for row in cur.fetchall()}


def rebuild_a_stock_hfq(
    conn: Any,
    channels: ChannelManager,
    *,
    since: date,
    limit: int | None = None,
    force: bool = False,
    mode: str = "delta",
) -> RebuildReport:
    spec = A_STOCK
    report = RebuildReport(dataset=spec.name, adjust="hfq")
    started = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT stock_code FROM bp_stock_master"
            " WHERE market IN ('SH','SZ','BJ') AND is_delisted = FALSE"
            " ORDER BY stock_code"
        )
        codes = [row[0] for row in cur.fetchall()]
    if limit:
        codes = codes[:limit]
    factor_channel = channels.get("sina_kline")
    for code in codes:
        bfq = read_bfq_history(conn, spec, code, since)
        if not bfq:
            report.skipped += 1
            continue
        anchor_dates = _existing_hfq_dates(conn, spec, code, "sina_kline")
        existing_hfq = max(anchor_dates) if anchor_dates else None
        if (
            not force
            and mode == "delta"
            and existing_hfq is not None
            and existing_hfq >= bfq[-1].trade_date
        ):
            # 数据已覆盖到最新：仍需删除可能的非锚源历史行（修复混源口径），保留计数
            report.deleted_legacy += delete_other_sources(
                conn, spec, "hfq", "sina_kline", symbols=[code]
            )
            conn.commit()
            report.skipped += 1
            continue
        if not force and mode == "delta":
            existing_dates = anchor_dates
        else:
            existing_dates = set()
        sina_symbol, _ = adapters.tencent.split_market(code)
        try:
            factors = adapters.sina.fetch_hfq_factor(factor_channel, sina_symbol)
            hfq_rows = adapters.sina.build_hfq_from_bfq(bfq, factors)
        except Exception as exc:  # noqa: BLE001 - 单只失败记录，可重跑
            logger.warning("A 股 hfq 重建失败 %s: %s", code, type(exc).__name__)
            report.failed += 1
            continue
        report.deleted_legacy += delete_other_sources(conn, spec, "hfq", "sina_kline", symbols=[code])
        if existing_dates:
            hfq_rows = [row for row in hfq_rows if row.trade_date not in existing_dates]
        report.written += writer.write_bars(conn, spec, hfq_rows)
        report.symbols += 1
        conn.commit()
        if report.symbols % 200 == 0:
            logger.info(
                "A股 hfq 重建进度: %d/%d symbols, 写入 %d 行, 删除旧源 %d 行, 失败 %d",
                report.symbols, len(codes), report.written, report.deleted_legacy, report.failed,
            )
    report.elapsed_s = time.perf_counter() - started
    return report


def _max_date(conn: Any, spec: DatasetSpec, symbol: str, adjust: str) -> date | None:
    sql = (
        f"SELECT max(trade_date) FROM {spec.table}"
        f" WHERE {spec.key_column} = %s AND adjust = %s"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (symbol, adjust))
        row = cur.fetchone()
    return row[0] if row and row[0] else None


def consolidate_sources(conn: Any, spec: DatasetSpec, adjust: str, anchor_source: str) -> RebuildReport:
    """收敛口径到锚定源（删除其它源历史行）。"""
    report = RebuildReport(dataset=spec.name, adjust=adjust)
    started = time.perf_counter()
    deleted = delete_other_sources(conn, spec, adjust, anchor_source)
    conn.commit()
    report.deleted_legacy = deleted
    report.elapsed_s = time.perf_counter() - started
    return report


def fill_recent_gaps(
    conn: Any,
    channels: ChannelManager,
    spec: DatasetSpec,
    adjust: str,
    *,
    target: date,
    days: int = 30,
    workers: int = 4,
) -> RebuildReport:
    """补近端缺口：锚定源最大日期 < target 的标的重拉近 N 天并 upsert。"""
    report = RebuildReport(dataset=spec.name, adjust=adjust)
    started = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(f"SELECT {spec.key_column} FROM {spec.table} GROUP BY 1")
        codes = [row[0] for row in cur.fetchall()]
    start = target - timedelta(days=days)

    def fetch_one(channel: Any, code: str) -> list[Bar]:
        market = "HK" if spec.name == "hk_stock" else "A"
        return adapters.tencent.fetch_kline(
            channel, code, adjust, start, target, market=market, count=days + 10
        )

    source = "tencent_hk_kline" if spec.name == "hk_stock" else "tencent_etf_kline"
    rows = fetch_parallel(codes, channels, source, fetch_one, workers=workers)
    report.written = writer.write_bars(conn, spec, rows)
    report.symbols = len({bar.symbol for bar in rows})
    conn.commit()
    report.elapsed_s = time.perf_counter() - started
    return report


def rebuild(
    config: EtlConfig,
    dataset: str,
    *,
    since: date = date(2020, 1, 1),
    limit: int | None = None,
    force: bool = False,
    mode: str = "delta",
) -> list[dict[str, Any]]:
    """执行重建（CLI 调用）；每类数据集独立连接，异常不影响其它数据集。"""
    channels = ChannelManager(config)
    conn_factory = default_conn_factory(config)
    reports: list[RebuildReport] = []
    if dataset in ("a_stock", "all"):
        with conn_factory() as conn:
            reports.append(
                rebuild_a_stock_hfq(conn, channels, since=since, limit=limit, force=force, mode=mode)
            )
    if dataset in ("hk_stock", "all"):
        with conn_factory() as conn:
            reports.append(consolidate_sources(conn, HK_STOCK, "hfq", "tencent_hk_kline"))
            reports.append(consolidate_sources(conn, HK_STOCK, "bfq", "sina_hk_kline"))
            reports.append(fill_recent_gaps(conn, channels, HK_STOCK, "hfq", target=_today(), days=30))
    if dataset in ("etf", "all"):
        with conn_factory() as conn:
            reports.append(consolidate_sources(conn, ETF, "hfq", "tencent_etf_kline"))
            reports.append(fill_recent_gaps(conn, channels, ETF, "hfq", target=_today(), days=30))
    return [report.to_dict() for report in reports]


def _today() -> date:
    from datetime import datetime, timezone, timedelta

    return datetime.now(timezone(timedelta(hours=8))).date()


def next_conn(conn: Any) -> Any:
    return conn