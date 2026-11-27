"""10Y 国债收益率（无风险利率）免费源采集：chinabond -> akshare -> 新浪。

背景
----
10Y 国债在库里（bp_macro_series.series_code='cn_10y_yield'）曾停在 2026-11-20，
且无 owner 调度。本模块补齐数据源与降级链：

1. **中债（chinabond）公开接口**：yield.chinabond.com.cn historyQuery，返回中债
   国债收益率曲线日频 3M~30Y（含 10年 列）；境内直连可用；
2. **akshare bond_zh_us_rate** 降级：东方财富数据中心中美国债收益率（10年列）；
3. **新浪 CN10YT** 兜底：bond.finance.cn 中国 10 年期国债日 K。

失败时**不写脏数据、不覆盖历史正确值**，写 bp_data_freshness(dataset='risk_free')
unavailable/stale + note，并保留上一交易日值（读侧 /api/v1/market/bond-yield 不变）。

写入表：bp_macro_series(series_code='cn_10y_yield', trade_date, value, unit='%', source)
（先 grep 确认的现有 10Y 表/字段：public_api._fetch_bond_yield 读 series_code='cn_10y_yield'）。

用法::

    python -m bp_ingest.risk_free                 # 增量：最近 30 天
    python -m bp_ingest.risk_free --days 400       # 回填约 1 年
    python -m bp_ingest.risk_free --start 2026-11-01 --end 2026-11-27
    python -m bp_ingest.risk_free --dry-run --json
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timedelta
from io import StringIO
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

import psycopg
import requests

logger = logging.getLogger(__name__)

CN = ZoneInfo("Asia/Shanghai")
SERIES_CODE = "cn_10y_yield"
UNIT = "%"
DEFAULT_DAYS = 30
#: 合理区间：中债 10Y 国债历史约 1%~5.5%，留宽但拒绝明显脏值（0/None/99）。
VALUE_MIN, VALUE_MAX = 0.2, 12.0

CHINABOND_URL = "https://yield.chinabond.com.cn/cbweb-pbc-web/pbc/historyQuery"
SINA_CN10Y_URL = "https://bond.finance.sina.com.cn/hq/gb/daily?symbol=CN10YT"
EM_TREASURY_URL = "https://datacenter.eastmoney.com/api/data/get"
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://yield.chinabond.com.cn/",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}


class RiskFreeUnavailable(RuntimeError):
    """全部免费源取数失败（不写库，记录 unavailable 状态）。"""


# ---------------------------------------------------------------------------
# 解析/校验（纯函数）
# ---------------------------------------------------------------------------
def _valid_value(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not (VALUE_MIN <= number <= VALUE_MAX):
        return None
    return round(number, 6)


def _valid_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def normalize_rows(rows: Iterable[Mapping[str, Any]], *, source: str) -> list[dict[str, Any]]:
    """统一为 [{trade_date, value, source}]：校验日期/值域、去重排序。"""
    seen: dict[date, dict[str, Any]] = {}
    for row in rows:
        day = _valid_date(row.get("trade_date") or row.get("date"))
        value = _valid_value(row.get("value"))
        if day is None or value is None:
            continue
        seen[day] = {"trade_date": day, "value": value, "source": source}
    return [seen[day] for day in sorted(seen)]


# ---------------------------------------------------------------------------
# 免费源 1：中债 chinabond
# ---------------------------------------------------------------------------
def fetch_chinabond(start: date, end: date) -> list[dict[str, Any]]:
    """中债国债收益率曲线（historyQuery HTML 表格，含 10年 列）。"""
    import pandas as pd  # noqa: PLC0415 - 惰性导入

    params = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "gjqx": "0",
        "qxId": "ycqx",
        "locale": "cn_ZH",
    }
    response = requests.get(CHINABOND_URL, params=params, headers=HTTP_HEADERS, timeout=30)
    response.raise_for_status()
    text = response.text.replace("&nbsp", "")
    try:
        tables = pd.read_html(StringIO(text), header=0)
    except ValueError as exc:  # 无表格（WAF/维护页）
        raise RiskFreeUnavailable(f"chinabond 无数据表: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for table in tables:
        if "日期" not in table.columns or "10年" not in table.columns:
            continue
        frame = table
        if "曲线名称" in frame.columns:
            frame = frame[frame["曲线名称"].astype(str).str.contains("国债", na=False)]
        for _, item in frame.iterrows():
            rows.append({"trade_date": item.get("日期"), "value": item.get("10年")})
    if not rows:
        raise RiskFreeUnavailable("chinabond 表格未包含国债 10年 列")
    return normalize_rows(rows, source="chinabond")


# ---------------------------------------------------------------------------
# 免费源 2（降级）：akshare bond_zh_us_rate（东财数据中心中美国债收益率）
# ---------------------------------------------------------------------------
def fetch_akshare(start: date, end: date) -> list[dict[str, Any]]:
    """akshare bond_zh_us_rate 的 10 年中国国债列（东财数据中心）。"""
    import akshare as ak  # noqa: PLC0415 - 重依赖，惰性导入

    frame = ak.bond_zh_us_rate(start_date=start.strftime("%Y%m%d"))
    if frame is None or getattr(frame, "empty", True):
        raise RiskFreeUnavailable("akshare bond_zh_us_rate 返回空")
    rows: list[dict[str, Any]] = []
    for _, item in frame.iterrows():
        rows.append({
            "trade_date": item.get("日期"),
            "value": item.get("中国国债收益率10年"),
        })
    return normalize_rows(rows, source="akshare_bond_zh_us_rate")


# ---------------------------------------------------------------------------
# 免费源 3（兜底）：新浪中国 10 年期国债
# ---------------------------------------------------------------------------
def fetch_sina(start: date, end: date) -> list[dict[str, Any]]:
    response = requests.get(SINA_CN10Y_URL, headers=HTTP_HEADERS, timeout=25)
    response.raise_for_status()
    payload = response.json()
    data = (payload.get("result") or {}).get("data") or []
    rows: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        rows.append({"trade_date": item.get("d"), "value": item.get("c")})
    if not rows:
        raise RiskFreeUnavailable("新浪 CN10YT 无数据")
    return normalize_rows(rows, source="sina_cn10yt")


FETCHERS: dict[str, Callable[[date, date], list[dict[str, Any]]]] = {
    "chinabond": fetch_chinabond,
    "akshare": fetch_akshare,
    "sina": fetch_sina,
}
SOURCE_ORDER: tuple[str, ...] = ("chinabond", "akshare", "sina")


# ---------------------------------------------------------------------------
# 落库 / 新鲜度
# ---------------------------------------------------------------------------
def last_stored_date(conn: psycopg.Connection) -> Optional[date]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(trade_date) FROM bp_macro_series WHERE series_code = %s",
            (SERIES_CODE,),
        )
        row = cur.fetchone()
    return row[0] if row and row[0] is not None else None


def upsert_rows(conn: psycopg.Connection, rows: Sequence[Mapping[str, Any]]) -> int:
    if not rows:
        return 0
    payload = [
        (SERIES_CODE, row["trade_date"], row["value"], UNIT, row["source"])
        for row in rows
    ]
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO bp_macro_series (series_code, trade_date, value, unit, source)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (series_code, trade_date) DO UPDATE SET
                value = EXCLUDED.value,
                unit = EXCLUDED.unit,
                source = EXCLUDED.source,
                captured_at = now()
            """,
            payload,
        )
    conn.commit()
    return len(payload)


def _record_status(
    conn: psycopg.Connection,
    as_of: Optional[date],
    status: str,
    note: str,
    *,
    source: Optional[str] = None,
    meta: Optional[Mapping[str, Any]] = None,
) -> None:
    try:
        from bp_api.freshness import record_freshness  # noqa: PLC0415

        record_freshness(
            conn, "risk_free", as_of, status=status, note=note[:500],
            source=source or "bp_ingest.risk_free", meta=dict(meta or {}),
        )
        conn.commit()
    except Exception:  # noqa: BLE001
        logger.warning("记录 10Y 国债新鲜度失败", exc_info=True)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def run(
    conn: psycopg.Connection,
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
    days: int = DEFAULT_DAYS,
    now: Optional[datetime] = None,
    fetchers: Optional[Mapping[str, Callable[[date, date], list[dict[str, Any]]]]] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """抓取 10Y 国债并 upsert；失败不写库、记录 unavailable 状态。"""
    wall = datetime.now(CN) if now is None else now
    if wall.tzinfo is None:
        wall = wall.replace(tzinfo=CN)
    end_date = end or wall.date()
    if start is not None:
        start_date = start
    else:
        last = last_stored_date(conn)
        # 增量：从库内最后日期前 10 天起（覆盖数据修订），至少回看 days 天
        candidate = end_date - timedelta(days=max(1, days))
        if last is not None:
            candidate = min(candidate, last - timedelta(days=10))
        start_date = candidate
    fetch_map = dict(fetchers or FETCHERS)
    summary: dict[str, Any] = {
        "status": "unavailable",
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "source": None,
        "rows_fetched": 0,
        "rows_written": 0,
        "latest_date": None,
        "dry_run": dry_run,
        "failures": [],
    }
    for name in SOURCE_ORDER:
        fetcher = fetch_map.get(name)
        if fetcher is None:
            continue
        try:
            rows = fetcher(start_date, end_date)
        except Exception as exc:  # noqa: BLE001 - 换下一个源
            summary["failures"].append(f"{name}:{type(exc).__name__}")
            logger.warning("10Y 国债源 %s 失败，换下一个源: %s", name, exc)
            continue
        rows = [row for row in rows if start_date <= row["trade_date"] <= end_date]
        if not rows:
            summary["failures"].append(f"{name}:empty")
            continue
        summary["source"] = name
        summary["rows_fetched"] = len(rows)
        summary["latest_date"] = rows[-1]["trade_date"].isoformat()
        if not dry_run:
            summary["rows_written"] = upsert_rows(conn, rows)
            _record_status(
                conn, rows[-1]["trade_date"], "ok",
                f"10Y 国债源 {name}（{len(rows)} 行，最新 {rows[-1]['trade_date']}）",
                source=name,
                meta={"rows": len(rows), "start": start_date.isoformat(),
                      "end": end_date.isoformat()},
            )
        summary["status"] = "ok"
        return summary

    note = "10Y 国债全部免费源不可用（" + "; ".join(summary["failures"]) + "）；保留最近一次成功值"
    logger.error(note)
    if not dry_run:
        _record_status(conn, None, "unavailable", note,
                       meta={"failures": summary["failures"]})
    summary["error"] = note
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog="bp_ingest.risk_free", description="10Y 国债收益率免费源采集")
    parser.add_argument("--start", default=None, help="起始日 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="结束日 YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"默认回看天数（{DEFAULT_DAYS}）")
    parser.add_argument("--dry-run", action="store_true", help="只抓取不写库")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    from bp_ingest.config import load_config, setup_logging  # noqa: PLC0415
    from bp_ingest.db import connect  # noqa: PLC0415
    from bp_ingest.http_session import install_hardened_session  # noqa: PLC0415

    setup_logging(getattr(load_config(), "log_level", "INFO"))
    install_hardened_session()
    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None
    with connect(load_config().db) as conn:
        conn.autocommit = False
        summary = run(conn, start=start, end=end, days=args.days, dry_run=args.dry_run)
    print(json.dumps(summary, ensure_ascii=False, default=str, indent=1))
    return 0 if summary["status"] == "ok" or args.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
