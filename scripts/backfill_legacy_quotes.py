#!/usr/bin/env python3
"""legacy 旧链 raw 缺口回填（优先 v3 ETL / 免费源；含 hfq）→ 再 repair clean。

背景（2026-11-27 第二轮反馈）
-----------------------------
旧指数链（bp_index_config 中 managed_by IS NULL 的配置）在旧 cron 停用后
bfq 尚可推进，但 hfq 长期卡在 11-24：hfq 只对 124 只有配置（universe 287），
且旧 ETL 的 hfq 源（etf_em/etf_tx 等）在东财封禁后不再可用。本脚本对全部
legacy 旧链标的按「先补 raw、再重建 clean」的顺序做缺口回填：

1) v3 ETF（category=etf / source 为 etf_*）：用 bp_etf_quote_daily 的 v3 行情
   （bfq/hfq）按与旧链最后收盘的重叠日因子重锚后写入 bp_index_quote_daily，
   保持旧链复权基准不变（与 scripts/repair_quote_gaps.py 的 bridge 思路一致）；
2) 指数（source 为 cn_index_*/csindex_* / hk_index_*）：复用
   scripts/index_quotes_free.py 的免费源降级链补日线（中证系 930/931/932/H3/950
   走 index-perf JSON → OSS perf.xls → 东财）。指数不复权，hfq 口径按 bfq 价格
   写入（价格指数无复权因子），源/口径原样保留；
3) 无法证明来源的标的（US/GLOBAL 等免费源不可得）：skip 并记录原因，绝不伪造。

最后对受影响 symbol 增量 rebuild bp_quote_clean + 刷新资产状态（可 --skip-clean）。

用法
----
    python scripts/backfill_legacy_quotes.py                     # dry-run：只打印计划
    python scripts/backfill_legacy_quotes.py --apply             # 执行回填 + clean
    python scripts/backfill_legacy_quotes.py --apply --symbols 000300 HSTECH
    python scripts/backfill_legacy_quotes.py --apply --since 2026-11-24
    python scripts/backfill_legacy_quotes.py --apply --skip-clean
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import sys
from datetime import date, timedelta
from typing import Any, Callable, Iterable, Optional, Sequence

logger = logging.getLogger("backfill_legacy_quotes")

# 直接执行 python scripts/backfill_legacy_quotes.py 时 sys.path[0] 是 scripts/，
# 补上仓库根目录以便 import bp_ingest / bp_api / bp_etl。
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

#: 免费源行情抓取脚本（复用 index_quotes_free 的解析/降级链，不重复实现）
IQF_PATH = os.path.join(_ROOT, "scripts", "index_quotes_free.py")
#: 无历史行情时的回填起点（2017 起免费源可覆盖 000985 等指数）
DEFAULT_HISTORY_START = date(2017, 1, 1)
#: 读旧链最后日期时的窗口（天），避免大表全量扫描
LAST_DATE_WINDOW_DAYS = 800


# ---------------------------------------------------------------------------
# 连接 / 口径
# ---------------------------------------------------------------------------
def connect():
    """独立脚本连接（测试可 monkeypatch）。"""
    from bp_ingest.config import load_config
    from bp_ingest.db import connect as _connect

    return _connect(load_config().db)


def target_trade_date(conn: Any, reference: date) -> Optional[date]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(cal_date) FROM bp_trading_calendar"
            " WHERE market = 'CN' AND is_trading AND cal_date <= %s",
            (reference,),
        )
        row = cur.fetchone()
    return row[0] if row and row[0] is not None else None


def legacy_configs(
    conn: Any, symbols: Optional[Sequence[str]] = None
) -> list[dict[str, Any]]:
    """旧链配置（managed_by IS NULL 且未删除），口径与 LegacyIndexRunner.universe 对齐。"""
    sql = (
        "SELECT DISTINCT symbol, source, coalesce(category, ''), adjust_modes,"
        " coalesce(adjust, 'bfq')"
        " FROM bp_index_config"
        " WHERE is_deleted = 0 AND managed_by IS NULL"
    )
    params: list[Any] = []
    wanted = [str(item).strip() for item in (symbols or []) if str(item).strip()]
    if wanted:
        sql += " AND symbol = ANY(%s)"
        params.append(wanted)
    sql += " ORDER BY symbol, source"
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for symbol, source, category, adjust_modes, adjust in rows:
        modes = tuple(mode for mode in (adjust_modes or ()) if mode in ("bfq", "hfq"))
        if not modes:
            modes = (adjust or "bfq",)
        out.append(
            {
                "symbol": symbol,
                "source": source,
                "category": category or "",
                "adjust_modes": modes,
            }
        )
    return out


def last_raw_date(conn: Any, symbol: str, source: str, adjust: str) -> Optional[date]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(trade_date) FROM bp_index_quote_daily"
            " WHERE symbol = %s AND source = %s AND adjust = %s"
            " AND trade_date >= current_date - %s",
            (symbol, source, adjust, LAST_DATE_WINDOW_DAYS),
        )
        row = cur.fetchone()
    return row[0] if row and row[0] is not None else None


def _market_for(symbol: str, source: str) -> Optional[str]:
    """推断免费源市场：HK 指数 / 中证系 / 沪 / 深。"""
    code = (symbol or "").strip()
    if (source or "").startswith("hk_index") or (code.isalpha() and code.isupper()):
        return "HK" if (source or "").startswith("hk_index") else None
    if not code.isdigit():
        return None
    if code.startswith(("930", "931", "932", "950", "H3")):
        return "CSI"
    if code.startswith(("399", "159")):
        return "SZ"
    if code.startswith(("000", "001", "002", "003", "880", "999")):
        # 000985 等中证全指：中证官网源优先（market=CSI），沪指也可由腾讯 sb 前缀取
        return "CSI"
    if code.startswith(("60", "68", "51", "56", "58")):
        return "SH"
    return None


def plan_backfill(
    conn: Any,
    target: date,
    *,
    symbols: Optional[Sequence[str]] = None,
    since: Optional[date] = None,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    """计算回填计划（只读）：{symbol, source, adjust, provider, start, last, reason}。"""
    plans: list[dict[str, Any]] = []
    for config in legacy_configs(conn, symbols):
        symbol = config["symbol"]
        source = config["source"]
        category = config["category"]
        for adjust in config["adjust_modes"]:
            last = last_raw_date(conn, symbol, source, adjust)
            if last is not None and last >= target:
                continue
            start = since or (
                (last + timedelta(days=1)) if last else DEFAULT_HISTORY_START
            )
            if start > target:
                continue
            is_etf = category == "etf" or (source or "").startswith("etf")
            market = _market_for(symbol, source)
            if is_etf:
                provider = "v3_etf"
            elif market in ("CSI", "SH", "SZ", "HK"):
                provider = "free_index"
            else:
                provider = "unsupported"
            plan = {
                "symbol": symbol,
                "source": source,
                "adjust": adjust,
                "category": category,
                "provider": provider,
                "last": last.isoformat() if last else None,
                "start": start.isoformat(),
                "target": target.isoformat(),
                "market": market,
            }
            if provider == "unsupported":
                plan["reason"] = "no_free_source_for_market"
            plans.append(plan)
            if limit is not None and len(plans) >= max(1, int(limit)):
                return plans
    return plans


# ---------------------------------------------------------------------------
# 数据读取（可 monkeypatch 单测）
# ---------------------------------------------------------------------------
def load_v3_etf_rows(
    conn: Any, symbol: str, adjust: str, start: date, target: date
) -> list[tuple]:
    """v3 ETF 行情行 (trade_date, open, high, low, close)。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT trade_date, open, high, low, close FROM bp_etf_quote_daily"
            " WHERE etf_code = %s AND adjust = %s AND close IS NOT NULL"
            " AND trade_date >= %s AND trade_date <= %s ORDER BY trade_date",
            (symbol, adjust, start, target),
        )
        return list(cur.fetchall())


def load_legacy_anchor(
    conn: Any, symbol: str, source: str, adjust: str, before: date
) -> tuple[Optional[date], Optional[float]]:
    """旧链在 before 之前最近一根收盘（用于重锚，保证旧基准不变）。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT trade_date, close FROM bp_index_quote_daily"
            " WHERE symbol = %s AND source = %s AND adjust = %s"
            " AND trade_date < %s AND close IS NOT NULL"
            " ORDER BY trade_date DESC LIMIT 1",
            (symbol, source, adjust, before),
        )
        row = cur.fetchone()
    if not row:
        return None, None
    return row[0], float(row[1])


def load_iqf_module():
    """惰性加载 scripts/index_quotes_free.py（复用免费源解析/降级链）。"""
    spec = importlib.util.spec_from_file_location("index_quotes_free", IQF_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - 文件缺失属部署错误
        raise RuntimeError("index_quotes_free.py not found")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("index_quotes_free", module)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def fetch_free_index_rows(
    symbol: str,
    market: str,
    start: date,
    target: date,
    *,
    source: Optional[str] = None,
) -> list[dict[str, Any]]:
    """免费源降级链取指数日线（返回 index_quotes_free 的 bar dict 列表）。

    source 可限定单源（如 cn_index_tx / csindex_oss）；默认按脚本降级链顺序尝试。
    """
    iqf = load_iqf_module()
    meta = iqf.IndexMeta(symbol=symbol, market=market, name=symbol)
    chain = list(iqf.SOURCE_CHAINS[meta.market_group])
    if source and source in iqf.FETCHERS:
        chain = [source] + [item for item in chain if item != source]
    for name in chain:
        fetcher = iqf.FETCHERS.get(name)
        if fetcher is None:
            continue
        try:
            bars = fetcher(symbol, market, start, target)
        except Exception:  # noqa: BLE001 - 换下一个免费源
            continue
        filtered = [bar for bar in bars if start <= bar["trade_date"] <= target]
        if filtered:
            return filtered
    return []


def build_v3_etf_rows(
    symbol: str,
    source: str,
    adjust: str,
    target: date,
    *,
    rows: Sequence[tuple],
    anchor: tuple[Optional[date], Optional[float]],
) -> list[Any]:
    """把 v3 ETF 行情按旧链锚收盘重锚为 bp_index_quote_daily 的 QuoteRow。"""
    from bp_ingest.db import QuoteRow

    if not rows:
        return []
    anchor_date, anchor_close = anchor
    factor = 1.0
    if anchor_date is not None and anchor_close:
        overlap = next((row for row in rows if row[0] == anchor_date), None)
        if overlap is not None and overlap[4]:
            factor = float(anchor_close) / float(overlap[4])
    out: list[Any] = []
    previous = anchor_close
    for trade_date, open_, high, low, close in rows:
        if close is None or close <= 0:
            continue
        scaled_close = float(close) * factor
        pct = (
            (scaled_close / float(previous) - 1.0) * 100.0
            if previous
            else None
        )
        out.append(
            QuoteRow(
                trade_date=trade_date,
                symbol=symbol,
                source=source,
                category="index",
                name=symbol,
                open=None if open_ is None else float(open_) * factor,
                high=None if high is None else float(high) * factor,
                low=None if low is None else float(low) * factor,
                close=scaled_close,
                volume=None,
                amount=None,
                turnover_rate=None,
                pct_change=pct,
                adjust=adjust,
            )
        )
        previous = scaled_close
        if trade_date > target:
            break
    return out


def build_free_index_rows(
    symbol: str,
    source: str,
    adjust: str,
    bars: Sequence[dict[str, Any]],
    *,
    anchor_close: Optional[float],
) -> list[Any]:
    """免费源 bar -> QuoteRow（指数不复权：hfq 口径同样写 bfq 价格）。"""
    from bp_ingest.db import QuoteRow

    out: list[Any] = []
    previous = anchor_close
    for bar in sorted(bars, key=lambda item: item["trade_date"]):
        close = bar.get("close")
        if close is None or close <= 0:
            continue
        pct = (
            (float(close) / float(previous) - 1.0) * 100.0 if previous else None
        )
        out.append(
            QuoteRow(
                trade_date=bar["trade_date"],
                symbol=symbol,
                source=source,
                category="index",
                name=symbol,
                open=bar.get("open"),
                high=bar.get("high"),
                low=bar.get("low"),
                close=float(close),
                volume=bar.get("volume"),
                amount=bar.get("amount"),
                turnover_rate=None,
                pct_change=pct,
                adjust=adjust,
            )
        )
        previous = float(close)
    return out


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------
def execute_plan(
    conn: Any,
    plans: Sequence[dict[str, Any]],
    *,
    writer: Optional[Callable[[Any, Sequence[Any]], int]] = None,
) -> dict[str, Any]:
    """执行回填计划：写 raw 行情（v3 重锚 / 免费源），返回统计。"""
    from bp_ingest.db import upsert_quotes

    write = writer or upsert_quotes
    result: dict[str, Any] = {"rows_written": 0, "plans_done": 0, "skipped": []}
    for plan in plans:
        if plan["provider"] == "unsupported":
            result["skipped"].append(
                {"symbol": plan["symbol"], "adjust": plan["adjust"],
                 "reason": plan.get("reason", "unsupported")}
            )
            continue
        target = date.fromisoformat(plan["target"])
        start = date.fromisoformat(plan["start"])
        symbol = plan["symbol"]
        source = plan["source"]
        adjust = plan["adjust"]
        rows: list[Any] = []
        try:
            if plan["provider"] == "v3_etf":
                v3_rows = load_v3_etf_rows(conn, symbol, adjust, start, target)
                anchor = load_legacy_anchor(conn, symbol, source, adjust, start)
                rows = build_v3_etf_rows(
                    symbol, source, adjust, target, rows=v3_rows, anchor=anchor
                )
            elif plan["provider"] == "free_index":
                market = plan.get("market") or _market_for(symbol, source)
                if market is None:
                    result["skipped"].append(
                        {"symbol": symbol, "adjust": adjust,
                         "reason": "unknown_market"}
                    )
                    continue
                bars = fetch_free_index_rows(symbol, market, start, target)
                anchor = load_legacy_anchor(conn, symbol, source, adjust, start)
                rows = build_free_index_rows(
                    symbol, source, adjust, bars, anchor_close=anchor[1]
                )
        except Exception as exc:  # noqa: BLE001 - 单标的失败不阻断整批
            result["skipped"].append(
                {"symbol": symbol, "adjust": adjust,
                 "reason": f"{type(exc).__name__}: {exc}"[:160]}
            )
            continue
        if not rows:
            result["skipped"].append(
                {"symbol": symbol, "adjust": adjust, "reason": "no_source_rows"}
            )
            continue
        result["rows_written"] += int(write(conn, rows) or 0)
        result["plans_done"] += 1
    return result


def rebuild_clean_for(conn: Any, symbols: Sequence[str]) -> dict[str, Any]:
    """对受影响 symbol 增量 rebuild clean + 刷新资产状态（失败只告警）。"""
    target = [str(item) for item in symbols if str(item)]
    if not target:
        return {"symbols": 0, "written": 0, "status_rows": 0}
    from bp_api.daily_update import refresh_all_asset_status
    from bp_api.quant.cleaning import rebuild_clean
    from bp_etl.cleaning_hook import DbTradingCalendar

    written = rebuild_clean(conn, symbols=target, cal=DbTradingCalendar(conn))
    conn.commit()
    status_rows = refresh_all_asset_status(conn, with_count=False)
    conn.commit()
    return {"symbols": len(target), "written": int(written or 0),
            "status_rows": status_rows}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backfill_legacy_quotes.py",
        description="legacy 旧链 raw 缺口回填（v3 ETL/免费源优先，含 hfq）→ repair clean",
    )
    parser.add_argument("--date", dest="date", default=None,
                        help="参考日 YYYY-MM-DD（默认今天；目标取 <= 该日最近交易日）")
    parser.add_argument("--since", dest="since", default=None,
                        help="回填起始日 YYYY-MM-DD（默认按各标的库内最后日期+1）")
    parser.add_argument("--symbols", nargs="+", default=None, help="只处理指定 symbol")
    parser.add_argument("--limit", type=int, default=0, help="最多处理 N 个回填计划（冒烟）")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不写库（默认）")
    parser.add_argument("--apply", action="store_true", help="真正执行回填 + clean")
    parser.add_argument("--skip-clean", action="store_true", help="只回填 raw，不重建 clean")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    apply = bool(args.apply) and not bool(args.dry_run)
    reference = date.fromisoformat(args.date) if args.date else date.today()
    since = date.fromisoformat(args.since) if args.since else None
    conn = connect()
    payload: dict[str, Any] = {"apply": apply, "reference_date": reference.isoformat()}
    try:
        target = target_trade_date(conn, reference) or reference
        payload["target_date"] = target.isoformat()
        plans = plan_backfill(
            conn, target,
            symbols=args.symbols,
            since=since,
            limit=args.limit or None,
        )
        payload["plan"] = plans
        payload["plan_total"] = len(plans)
        payload["providers"] = {
            provider: sum(1 for plan in plans if plan.get("provider") == provider)
            for provider in {plan.get("provider") for plan in plans}
        }
        if apply:
            payload["applied"] = execute_plan(conn, plans)
            symbols = sorted({
                plan["symbol"] for plan in plans
                if plan.get("provider") != "unsupported"
            })
            if not args.skip_clean:
                payload["clean"] = rebuild_clean_for(conn, symbols)
            conn.commit()
        else:
            conn.rollback()
    finally:
        close = getattr(conn, "close", None)
        if callable(close):
            close()
    text = json.dumps(payload, ensure_ascii=False, default=str, indent=1)
    print(text)
    if not apply:
        print("[dry-run] 未写库；确认后加 --apply 执行。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
