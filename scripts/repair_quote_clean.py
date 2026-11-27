#!/usr/bin/env python3
"""行情更新后的清洗/资产状态对账 + bp_etl_backlog 旧 universe 清理（P0-4）。

背景
----
1b. 指数/旧链行情恢复后，bp_quote_clean 没有跟着推进（2026-11-27 仍停在 11-26），
    组合 T-1 自动更新被旧 clean 卡死。本脚本按「raw 比 clean 新」增量找出受影响
    symbol，只对这些 symbol 调 rebuild_clean，再刷新 bp_asset_status（热路径
    with_count=False，不破坏 COUNT 分级不变式）。
2b. bp_etl_backlog 里残留旧 universe（9,600 只口径）的 symbol 行：11-25/26 两天
    合计 ~38k 条永远无法重放，run_backlog 每小时空转。本脚本按**当前 universe**
    对账删除这些行（datasets=legacy_index），并提供一次性日期清理与安全 SQL 输出。

安全约束
--------
* 默认 **dry-run**：只打印将要执行的动作与安全 SQL，不写库；确认后加 --apply。
* 生产库操作前请先备份 bp_etl_backlog / bp_quote_clean（脚本 --print-sql 会给出备份 SQL）。
* 不触碰 bp_etl_backlog 中 trade_date 晚于当前已确认交易日的行（未来日不存在）。

用法
----
    python scripts/repair_quote_clean.py                        # dry-run：列出待清洗 symbol / 待删 backlog
    python scripts/repair_quote_clean.py --apply                # 执行 增量 clean + 状态刷新 + backlog 旧 symbol 收敛
    python scripts/repair_quote_clean.py --symbols 000300 HSI   # 只对指定 symbol 重建 clean
    python scripts/repair_quote_clean.py --skip-backlog --apply # 只做 clean 对账
    python scripts/repair_quote_clean.py --purge-dates 2026-11-25 2026-11-26 --apply
    python scripts/repair_quote_clean.py --print-sql            # 输出可人工复核的安全 SQL
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from typing import Any, Iterable, Optional, Sequence

logger = logging.getLogger("repair_quote_clean")

# 直接执行 python scripts/repair_quote_clean.py 时 sys.path[0] 是 scripts/，
# 补上仓库根目录以便 import bp_ingest / bp_etl（cron 从任意 cwd 启动都能跑）。
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

#: 默认回看窗口（自然日）：只处理最近窗口内 raw 有推进的 symbol，避免全表扫描。
DEFAULT_SINCE_DAYS = 10
#: 交给 run_backlog 重放的旧日期上限（自然日），与 bp_etl 的 BP_ETL_BACKLOG_MAX_AGE_DAYS 对齐。
DEFAULT_PURGE_BEFORE_DAYS = 30


# ---------------------------------------------------------------------------
# 查询：raw 比 clean 新的 legacy symbol
# ---------------------------------------------------------------------------
STALE_SYMBOLS_SQL = """
SELECT q.symbol,
       max(q.trade_date) AS raw_max,
       max(k.trade_date) AS clean_max
FROM bp_index_quote_daily q
JOIN bp_index_config c
  ON c.symbol = q.symbol AND c.source = q.source
 AND c.is_deleted = 0 AND c.managed_by IS NULL
LEFT JOIN (
    SELECT symbol, max(trade_date) AS trade_date
    FROM bp_quote_clean
    WHERE trade_date >= %(since)s
    GROUP BY symbol
) k ON k.symbol = q.symbol
WHERE q.trade_date >= %(since)s
GROUP BY q.symbol
HAVING max(q.trade_date) > COALESCE(max(k.trade_date), DATE '1900-01-01')
ORDER BY q.symbol
LIMIT %(limit)s
""".strip()


def find_stale_symbols(
    conn: Any,
    *,
    since: date,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    """找出 raw 行情比 clean 新的 legacy 配置 symbol（按 raw 最大日期倒序）。"""
    with conn.cursor() as cur:
        cur.execute(STALE_SYMBOLS_SQL, {"since": since, "limit": limit})
        rows = cur.fetchall()
    return [
        {"symbol": row[0], "raw_max": row[1], "clean_max": row[2]}
        for row in rows
    ]


# ---------------------------------------------------------------------------
# backlog 对账：当前 universe
# ---------------------------------------------------------------------------
def current_legacy_universe(conn: Any) -> list[str]:
    """与 bp_etl LegacyIndexRunner.universe 同口径（managed_by IS NULL + 可选 selectable）。"""
    import os  # noqa: PLC0415

    scope = (os.getenv("BP_ETL_LEGACY_SCOPE") or "all").strip().lower()
    sql = (
        "SELECT DISTINCT symbol FROM bp_index_config"
        " WHERE is_deleted = 0 AND managed_by IS NULL"
    )
    if scope == "selectable":
        sql += " AND (is_selectable = TRUE OR source = 'fx_sina')"
    sql += " ORDER BY symbol"
    with conn.cursor() as cur:
        cur.execute(sql)
        return [row[0] for row in cur.fetchall()]


def backlog_snapshot(conn: Any, *, dataset: str = "legacy_index") -> dict[str, Any]:
    """backlog 概况（只读），用于 dry-run 与报告。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM bp_etl_backlog WHERE dataset = %s", (dataset,)
        )
        total = int(cur.fetchone()[0] or 0)
        cur.execute(
            "SELECT trade_date, count(*) FROM bp_etl_backlog"
            " WHERE dataset = %s GROUP BY trade_date ORDER BY trade_date",
            (dataset,),
        )
        by_date = [(row[0], int(row[1])) for row in cur.fetchall()]
    return {"total": total, "by_date": by_date}


def plan_backlog_reconcile(
    conn: Any,
    *,
    dataset: str = "legacy_index",
    purge_dates: Optional[Sequence[date]] = None,
    purge_before: Optional[date] = None,
) -> dict[str, Any]:
    """计算 backlog 对账计划（只读）：旧 universe symbol 行数 / 待删日期行数。"""
    universe = current_legacy_universe(conn)
    snapshot = backlog_snapshot(conn, dataset=dataset)
    stale_symbol_rows = 0
    if universe:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM bp_etl_backlog"
                " WHERE dataset = %s AND scope = 'symbol' AND NOT (symbol = ANY(%s))",
                (dataset, universe),
            )
            stale_symbol_rows = int(cur.fetchone()[0] or 0)
    purge_rows = 0
    if purge_dates:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM bp_etl_backlog"
                " WHERE dataset = %s AND trade_date = ANY(%s)",
                (dataset, list(purge_dates)),
            )
            purge_rows += int(cur.fetchone()[0] or 0)
    if purge_before is not None:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM bp_etl_backlog"
                " WHERE dataset = %s AND trade_date < %s",
                (dataset, purge_before),
            )
            purge_rows += int(cur.fetchone()[0] or 0)
    return {
        "universe": len(universe),
        "backlog": snapshot,
        "stale_symbol_rows": stale_symbol_rows,
        "purge_rows": purge_rows,
        "purge_dates": [day.isoformat() for day in (purge_dates or [])],
        "purge_before": purge_before.isoformat() if purge_before else None,
    }


def apply_backlog_reconcile(
    conn: Any,
    *,
    dataset: str = "legacy_index",
    purge_dates: Optional[Sequence[date]] = None,
    purge_before: Optional[date] = None,
) -> dict[str, int]:
    """执行 backlog 对账（需要 --apply）：按当前 universe 删旧 symbol 行 + 日期清理。"""
    from bp_etl.health import (  # noqa: PLC0415
        prune_backlog_symbols,
        purge_backlog_before,
        purge_backlog_dates,
    )

    universe = current_legacy_universe(conn)
    removed_symbols = 0
    removed_dates = 0
    removed_before = 0
    for adjust in ("bfq", "hfq"):
        if universe:
            removed_symbols += prune_backlog_symbols(conn, dataset, adjust, universe)
        if purge_dates:
            removed_dates += purge_backlog_dates(conn, dataset, adjust, list(purge_dates))
        if purge_before is not None:
            removed_before += purge_backlog_before(conn, dataset, adjust, purge_before)
    conn.commit()
    return {
        "removed_stale_symbol_rows": removed_symbols,
        "removed_purge_date_rows": removed_dates,
        "removed_purge_before_rows": removed_before,
    }


# ---------------------------------------------------------------------------
# clean 对账
# ---------------------------------------------------------------------------
def rebuild_clean_for(
    conn: Any,
    symbols: Sequence[str],
    *,
    refresh_status: bool = True,
) -> dict[str, Any]:
    """对受影响 symbol 增量 rebuild_clean + 刷新资产状态（热路径 with_count=False）。"""
    from bp_api.quant.cleaning import rebuild_clean  # noqa: PLC0415 - pandas 重
    from bp_etl.cleaning_hook import DbTradingCalendar  # noqa: PLC0415

    target = [str(item) for item in symbols if str(item)]
    if not target:
        return {"symbols": 0, "written": 0, "status_rows": 0}
    cal = DbTradingCalendar(conn)
    written = rebuild_clean(conn, symbols=target, cal=cal)  # type: ignore[arg-type]
    conn.commit()
    status_rows = 0
    if refresh_status:
        from bp_api.daily_update import refresh_all_asset_status  # noqa: PLC0415

        status_rows = refresh_all_asset_status(conn, with_count=False)
        conn.commit()
    logger.info(
        "clean 对账完成: symbols=%d written=%d status_rows=%s",
        len(target), written, status_rows,
    )
    return {"symbols": len(target), "written": written, "status_rows": status_rows}


# ---------------------------------------------------------------------------
# 安全 SQL（供 DBA 人工复核/备份；脚本不直接拼到生产）
# ---------------------------------------------------------------------------
def safe_sql(purge_dates: Optional[Sequence[date]] = None) -> str:
    """输出可人工复核的安全 SQL（备份 + 旧 universe 对账 + 指定日期清理）。"""
    dates_sql = ", ".join(f"DATE '{day.isoformat()}'" for day in (purge_dates or [])) or "NULL"
    return f"""-- ============================================================
-- repair_quote_clean.py --print-sql 生成；请先备份再人工执行
-- 生产执行前在维护窗口确认：SELECT count(*) 与 dry-run 输出一致
-- ============================================================
BEGIN;

-- 0) 备份（若同名表已存在先改名/删除）
CREATE TABLE IF NOT EXISTS bp_etl_backlog_bak_20261127 AS
    SELECT * FROM bp_etl_backlog;
CREATE TABLE IF NOT EXISTS bp_quote_clean_bak_20261127 AS
    SELECT * FROM bp_quote_clean WHERE trade_date >= current_date - INTERVAL '30 days';

-- 1) 旧 universe symbol 行收敛（当前 universe = legacy 配置且未删除；
--    生产若启用 BP_ETL_LEGACY_SCOPE=selectable，请追加
--    AND (is_selectable = TRUE OR source = 'fx_sina')）
DELETE FROM bp_etl_backlog b
WHERE b.dataset = 'legacy_index'
  AND b.scope = 'symbol'
  AND NOT (b.symbol = ANY (ARRAY(
      SELECT DISTINCT symbol FROM bp_index_config
      WHERE is_deleted = 0 AND managed_by IS NULL
  )));

-- 2) 一次性清理旧口径历史日期（11-25/26 的 9,434/9,496 条空转；确认后执行）
DELETE FROM bp_etl_backlog
WHERE dataset = 'legacy_index'
  AND trade_date IN ({dates_sql});

-- 3) 校验：backlog 应 < 1,000，且不再有 11-25/26 的旧 universe 条目
SELECT dataset, adjust, count(*), min(trade_date), max(trade_date)
FROM bp_etl_backlog GROUP BY dataset, adjust;

COMMIT;
"""


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def _parse_date(raw: str) -> date:
    return date.fromisoformat(raw.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repair_quote_clean.py",
        description="行情更新后的 clean/资产状态对账 + bp_etl_backlog 旧 universe 清理",
    )
    parser.add_argument("--symbols", nargs="+", default=None,
                        help="只对指定 symbol 增量重建 clean（默认自动找 raw>clean 的 legacy 标的）")
    parser.add_argument("--since-days", type=int, default=DEFAULT_SINCE_DAYS,
                        help=f"自动找受影响 symbol 的回看天数（默认 {DEFAULT_SINCE_DAYS}）")
    parser.add_argument("--date", dest="date", default=None,
                        help="对账参考日 YYYY-MM-DD（默认今天；仅用于日志）")
    parser.add_argument("--skip-clean", action="store_true", help="跳过 clean/资产状态对账")
    parser.add_argument("--skip-backlog", action="store_true", help="跳过 backlog 对账")
    parser.add_argument("--purge-dates", nargs="+", default=None,
                        help="一次性整批删除这些交易日的 backlog（如 2026-11-25 2026-11-26）")
    parser.add_argument("--purge-before", default=None,
                        help="删除早于该日期的 backlog（YYYY-MM-DD）")
    parser.add_argument("--dataset", default="legacy_index", help="backlog 对账的数据集（默认 legacy_index）")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不写库（默认即 dry-run）")
    parser.add_argument("--apply", action="store_true", help="真正执行写操作（clean 重建/backlog 删除）")
    parser.add_argument("--print-sql", action="store_true", help="输出可人工复核执行的安全 SQL 后退出")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    purge_dates = [_parse_date(item) for item in (args.purge_dates or [])] or None
    purge_before = _parse_date(args.purge_before) if args.purge_before else None
    if args.print_sql:
        print(safe_sql(purge_dates))
        return 0

    apply = bool(args.apply) and not bool(args.dry_run)
    reference = _parse_date(args.date) if args.date else date.today()
    since = reference - timedelta(days=max(1, args.since_days))

    from bp_ingest.config import load_config, setup_logging  # noqa: PLC0415
    from bp_ingest.db import connect  # noqa: PLC0415

    setup_logging(getattr(load_config(), "log_level", "INFO"))
    app = load_config()
    payload: dict[str, Any] = {"apply": apply, "reference_date": reference.isoformat()}

    with connect(app.db) as conn:
        conn.autocommit = False
        # --- 1) backlog 对账（先做，避免巨量旧条目干扰后续）---
        if not args.skip_backlog:
            plan = plan_backlog_reconcile(
                conn,
                dataset=args.dataset,
                purge_dates=purge_dates,
                purge_before=purge_before,
            )
            payload["backlog_plan"] = plan
            if apply:
                payload["backlog_applied"] = apply_backlog_reconcile(
                    conn,
                    dataset=args.dataset,
                    purge_dates=purge_dates,
                    purge_before=purge_before,
                )
            logger.info("backlog 对账计划: %s", plan)
        # --- 2) clean/资产状态对账 ---
        if not args.skip_clean:
            if args.symbols:
                targets = [str(item) for item in args.symbols]
                stale: list[dict[str, Any]] = []
            else:
                stale = find_stale_symbols(conn, since=since)
                targets = [item["symbol"] for item in stale]
            payload["clean"] = {
                "stale_count": len(stale),
                "targets": targets[:500],
                "targets_total": len(targets),
            }
            if apply and targets:
                payload["clean_applied"] = rebuild_clean_for(conn, targets)
            logger.info("clean 对账: %d 个 symbol 待重建", len(targets))

    import json  # noqa: PLC0415

    print(json.dumps(payload, ensure_ascii=False, default=str, indent=1))
    if not args.json:
        if not apply:
            print("")  # 空行分隔 dry-run 提示
            print("[dry-run] 未写库；确认后加 --apply 执行。安全 SQL 见 --print-sql。")
    return 0


if __name__ == "__main__":
    sys.exit(main())