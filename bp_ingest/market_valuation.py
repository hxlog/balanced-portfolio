"""全市场估值快照：免费源（新浪 A 股行情）为主，东财 clist 降级，全失败则优雅降级。

背景
----
原实现只用东财 push2 clist（板块分页 + 中位数/等权 PE、PB），但生产服务器 IP 被
东财长期封禁（RemoteDisconnected），导致市场估值快照停在 2026-11-14 无任何告警。
现在改为：

1. **免费源优先**：新浪行情中心 Market_Center.getHQNodeData（node=hs_a，全 A 股分页，
   含 per(市盈率)/pb(市净率)/mktcap），境内直连可用、无需 token；
2. **东财降级**：保留原 push2 clist 路径作为第二源（本机/非封禁网络可用）；
3. **优雅降级**：两源都失败/样本不足时**绝不写脏数据**，不覆盖历史正确行；写
   bp_data_freshness(dataset='market_valuation') 的 unavailable/stale 状态 + note，
   供 UI 明确「估值快照不可用/已陈旧」信号；返回值带 status 而不是静默成功。

写入口径不变：bp_market_valuation_daily（board, trade_date）主键 UPSERT + 分位（pct_pe/pct_pb），
calc_src 记录实际来源（sina_market_center / eastmoney_snapshot）。

**收盘确认门（P1-3）**：盘中（A 股收盘确认 15:10 前）新浪/东财返回的是实时快照，
绝不能写成任何交易日的收盘行——尤其不能回退写到前一交易日而覆盖历史收盘。
未确认时 `compute` 直接跳过写库，返回 status=skipped + skip_reason=not_closed，并写
bp_data_freshness(unavailable) note；显式传入的 `as_of` 同样校验（未来日期/未收盘的
当日/非交易日一律拒绝）。
"""
from __future__ import annotations

import logging
import statistics
import time
from datetime import date, datetime
from typing import Any, Callable, Iterable, Mapping, Optional

import psycopg
import requests

from .http_session import install_hardened_session

logger = logging.getLogger(__name__)

CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
FIELDS = "f12,f14,f2,f9,f23,f20"  # 代码/名称/现价/动态PE/市净率/总市值
PAGE_SIZE = 6000

#: 新浪行情中心：hs_a = 全部 A 股（含北交所），返回 per/pb/mktcap/nmc 等字段。
SINA_MARKET_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeData"
)
SINA_NODE = "hs_a"
SINA_PAGE_SIZE = 100
SINA_MAX_PAGES = 90  # 防御上限（100×90=9000 只）
SINA_MIN_SAMPLE = 500  # 单板块样本低于此值视为源降级/脏，不写库

BOARD_FILTERS: dict[str, tuple[str, ...]] = {
    "main": ("m:1+t:2", "m:0+t:6"),
    "chinext": ("m:0+t:80",),
    "star": ("m:1+t:23",),
    "bse": ("m:0+t:81+s:2048",),
}

CALC_SRC_SINA = "sina_market_center"
CALC_SRC_EM = "eastmoney_snapshot"

#: A 股收盘确认（15:10 CST）后才把当日行情当收盘快照；可用 BP_CLOSE_CONFIRM_HHMM 覆盖。
DEFAULT_CLOSE_CONFIRM_HHMM = "1510"


class MarketValuationUnavailable(RuntimeError):
    """免费源与降级源全部失败（不写库，记录 unavailable 状态）。"""


# ---------------------------------------------------------------------------
# 时间口径
# ---------------------------------------------------------------------------
def _now_cn(now: datetime | None = None) -> datetime:
    from zoneinfo import ZoneInfo  # noqa: PLC0415

    tz = ZoneInfo("Asia/Shanghai")
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


def _close_confirm_hhmm() -> tuple[int, int]:
    import os  # noqa: PLC0415

    raw = (os.getenv("BP_CLOSE_CONFIRM_HHMM") or DEFAULT_CLOSE_CONFIRM_HHMM).strip()
    if len(raw) == 4 and raw.isdigit():
        return int(raw[:2]), int(raw[2:])
    return 15, 10


def _latest_trading_day(conn: Any, reference: date) -> date | None:
    """<= reference 的最近 A 股交易日（不判断收盘确认）。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(cal_date) FROM bp_trading_calendar"
            " WHERE market = 'CN' AND is_trading AND cal_date <= %s",
            (reference,),
        )
        row = cur.fetchone()
    return row[0] if row and row[0] is not None else None


def is_close_confirmed(trade_date: date, now: datetime | None = None) -> bool:
    """该交易日是否已过收盘确认时点（当日 15:10 前未确认；历史日期恒确认）。"""
    wall = _now_cn(now)
    if trade_date < wall.date():
        return True
    if trade_date > wall.date():
        return False
    hour, minute = _close_confirm_hhmm()
    return (wall.hour, wall.minute) >= (hour, minute)


def resolve_trade_date(conn: Any, *, now: datetime | None = None) -> date | None:
    """应写入的快照交易日：最近**已收盘确认**的 A 股交易日；未确认返回 None。

    P1-3 修复：盘中（15:10 前）不再回退到前一交易日（旧实现会把实时快照写到
    前一交易日、覆盖历史收盘）。未确认时调用方必须跳过写库。
    """
    wall = _now_cn(now)
    candidate = _latest_trading_day(conn, wall.date())
    if candidate is None:
        return None
    if not is_close_confirmed(candidate, wall):
        return None
    return candidate


def validate_as_of(conn: Any, as_of: date, *, now: datetime | None = None) -> str | None:
    """校验显式 `as_of`，返回跳过原因（None=合法）。

    - future_date：晚于今天（未来数据，拒绝）；
    - not_closed：就是今天但未过收盘确认（拒绝，避免盘中快照覆盖当日收盘）；
    - not_trading_day：交易日历明确标记非交易日的日期（日历无该行时不额外阻断）。
    """
    wall = _now_cn(now)
    if as_of > wall.date():
        return "future_date"
    if as_of == wall.date() and not is_close_confirmed(as_of, wall):
        return "not_closed"
    if as_of.weekday() >= 5:
        return "not_trading_day"  # 周末即便日历无该行也绝不写
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT is_trading FROM bp_trading_calendar"
                " WHERE market = 'CN' AND cal_date = %s",
                (as_of,),
            )
            row = cur.fetchone()
    except Exception:  # noqa: BLE001 - 日历不可用时不额外阻断（写库主键仍保证幂等）
        return None
    if row is not None and not bool(row[0]):
        return "not_trading_day"
    return None


# ---------------------------------------------------------------------------
# 免费源 1：新浪行情中心
# ---------------------------------------------------------------------------
def fetch_sina_page(page: int, *, session: Any | None = None) -> list[dict[str, Any]]:
    getter = (session or requests).get
    params = {
        "page": str(page),
        "num": str(SINA_PAGE_SIZE),
        "sort": "symbol",
        "asc": "1",
        "node": SINA_NODE,
        "symbol": "",
        "_s_r_a": "page",
    }
    response = getter(
        SINA_MARKET_URL, params=params, timeout=20,
        headers={"User-Agent": "Mozilla/5.0 Chrome/120.0.0.0 Safari/537.36",
                 "Referer": "https://finance.sina.com.cn/"},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def fetch_sina_all(
    *,
    session: Any | None = None,
    page_sleep: float = 0.12,
    max_pages: int = SINA_MAX_PAGES,
) -> list[dict[str, Any]]:
    """分页拉全部 A 股实时快照（含 PE/PB）。任何一页失败都抛异常（不写半截脏数据）。"""
    rows: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        page_rows = fetch_sina_page(page, session=session)
        if not page_rows:
            break
        rows.extend(page_rows)
        if len(page_rows) < SINA_PAGE_SIZE:
            break
        if page_sleep:
            time.sleep(page_sleep)
    return rows


def classify_board(symbol: str, code: str) -> str:
    """按代码前缀归属板块（与 bp_market_valuation_daily.ck_mkt_board 一致）。"""
    sym = str(symbol or "").lower()
    code = str(code or "")
    if sym.startswith("bj") or code.startswith(("4", "8", "920")):
        return "bse"
    if sym.startswith("sh") and code.startswith(("688", "689")):
        return "star"
    if sym.startswith("sz") and code.startswith(("30",)):
        return "chinext"
    return "main"


def _sina_stats(rows: Iterable[Mapping[str, Any]]) -> tuple[
    float | None, float | None, float | None, float | None, int
]:
    pes: list[float] = []
    pbs: list[float] = []
    for row in rows:
        per = _positive(row.get("per"))
        pb = _positive(row.get("pb"))
        if per is not None:
            pes.append(per)
        if pb is not None:
            pbs.append(pb)
    return (
        statistics.median(pes) if pes else None,
        statistics.fmean(pes) if pes else None,
        statistics.median(pbs) if pbs else None,
        statistics.fmean(pbs) if pbs else None,
        len(pes),
    )


def _positive(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def stats_from_sina(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """按板块分组统计（返回 rows_by_board；样本不足由调用方判定）。"""
    grouped: dict[str, list[dict[str, Any]]] = {board: [] for board in ("main", "chinext", "star", "bse")}
    all_rows: list[dict[str, Any]] = []
    for row in rows:
        all_rows.append(dict(row))
        grouped[classify_board(row.get("symbol", ""), row.get("code", ""))].append(dict(row))
    grouped["all"] = all_rows
    return grouped


# ---------------------------------------------------------------------------
# 免费源 2（降级）：东财 clist（保留原实现）
# ---------------------------------------------------------------------------
def _fetch_board(fs_filter: str) -> list[dict[str, Any]]:
    """分页拉取一个板块的全部个股（push2 单页上限 100）。"""
    rows: list[dict[str, Any]] = []
    page = 1
    total = None
    while page <= 80:
        params = {
            "pn": str(page),
            "pz": "100",
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": fs_filter,
            "fields": FIELDS,
        }
        response = requests.get(CLIST_URL, params=params, timeout=25)
        response.raise_for_status()
        payload = response.json()
        data = (payload.get("data") or {})
        diff = data.get("diff") or []
        if total is None:
            total = int(data.get("total") or 0)
        if not diff:
            break
        rows.extend(row for row in diff if isinstance(row, dict))
        if total is not None and len(rows) >= total:
            break
        page += 1
        time.sleep(0.25)
    return rows


def _stats(rows: Iterable[Mapping[str, Any]]) -> tuple[float | None, float | None, float | None, float | None, int]:
    pes = [float(r["f9"]) for r in rows if isinstance(r.get("f9"), (int, float)) and r["f9"] > 0]
    pbs = [float(r["f23"]) for r in rows if isinstance(r.get("f23"), (int, float)) and r["f23"] > 0]
    return (
        statistics.median(pes) if pes else None,
        statistics.fmean(pes) if pes else None,
        statistics.median(pbs) if pbs else None,
        statistics.fmean(pbs) if pbs else None,
        len(pes),
    )


def payload_from_em() -> list[dict[str, Any]]:
    """东财 clist 全板块快照 -> payload 行（取数失败抛异常由调用方降级）。"""
    rows_by_board: dict[str, list[dict]] = {}
    all_rows: list[dict] = []
    for board, filters in BOARD_FILTERS.items():
        board_rows: list[dict] = []
        for fs_filter in filters:
            board_rows.extend(_fetch_board(fs_filter))
        rows_by_board[board] = board_rows
        all_rows.extend(board_rows)
    rows_by_board["all"] = all_rows
    collected: list[dict[str, Any]] = []
    for board, rows in rows_by_board.items():
        pe_med, pe_eq, pb_med, pb_eq, sample = _stats(rows)
        collected.append({
            "board": board,
            "pe_median": pe_med,
            "pe_equal": pe_eq,
            "pb_median": pb_med,
            "pb_equal": pb_eq,
            "sample_size": sample,
        })
    return collected


# ---------------------------------------------------------------------------
# 落库
# ---------------------------------------------------------------------------
def _write_payload(
    conn: psycopg.Connection,
    trade_date: date,
    payload: list[dict[str, Any]],
    *,
    calc_src: str,
) -> None:
    """写 bp_market_valuation_daily（UPSERT）+ 重算分位。"""
    rows = [dict(item, trade_date=trade_date, calc_src=calc_src) for item in payload]
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO bp_market_valuation_daily
                (board, trade_date, pe_median, pe_equal, pb_median, pb_equal, sample_size, calc_src)
            VALUES (%(board)s, %(trade_date)s, %(pe_median)s, %(pe_equal)s,
                    %(pb_median)s, %(pb_equal)s, %(sample_size)s, %(calc_src)s)
            ON CONFLICT (board, trade_date) DO UPDATE SET
                pe_median = EXCLUDED.pe_median,
                pe_equal = EXCLUDED.pe_equal,
                pb_median = EXCLUDED.pb_median,
                pb_equal = EXCLUDED.pb_equal,
                sample_size = EXCLUDED.sample_size,
                calc_src = EXCLUDED.calc_src,
                captured_at = now()
            """,
            rows,
        )
        from bp_api.quant.valuation import percentile as _pct  # noqa: PLC0415

        for row in rows:
            cur.execute(
                "SELECT pe_median, pb_median FROM bp_market_valuation_daily"
                " WHERE board = %s AND trade_date <= %s",
                (row["board"], trade_date),
            )
            history = cur.fetchall()
            pe_list = [float(v) for v, _ in history if v is not None]
            pb_list = [float(v) for _, v in history if v is not None]
            pe_now = row["pe_median"]
            pb_now = row["pb_median"]
            cur.execute(
                "UPDATE bp_market_valuation_daily SET pct_pe = %s, pct_pb = %s"
                " WHERE board = %s AND trade_date = %s",
                (
                    _pct(pe_list, pe_now) if pe_now is not None else None,
                    _pct(pb_list, pb_now) if pb_now is not None else None,
                    row["board"],
                    trade_date,
                ),
            )
    conn.commit()


def _record_status(
    conn: psycopg.Connection,
    trade_date: date | None,
    status: str,
    note: str,
    *,
    source: str | None = None,
    meta: Mapping[str, Any] | None = None,
) -> None:
    """记录市场估值快照的新鲜度/降级状态（供 UI 不可用信号）；失败不影响主流程。"""
    try:
        from bp_api.freshness import record_freshness  # noqa: PLC0415

        record_freshness(
            conn,
            "market_valuation",
            trade_date,
            status=status,
            note=note[:500],
            source=source or "bp_ingest.market_valuation",
            meta=dict(meta or {}),
        )
        conn.commit()
    except Exception:  # noqa: BLE001 - 状态记录失败不得让任务失败
        logger.warning("记录市场估值新鲜度失败", exc_info=True)


def _skip_note(reason: str) -> tuple[str, str]:
    """跳过写库的 freshness note/status（状态口径供 UI 显示 unavailable）。"""
    if reason == "not_closed":
        hour, minute = _close_confirm_hhmm()
        return (
            f"盘中快照未过收盘确认（{hour:02d}:{minute:02d} 前），跳过写库以免覆盖历史收盘",
            "unavailable",
        )
    if reason == "future_date":
        return ("as_of 晚于今天（未来日期），拒绝写入", "unavailable")
    if reason == "not_trading_day":
        return ("as_of 不是 A 股交易日，拒绝写入", "unavailable")
    return ("无法确定应写入的交易日（交易日历为空）", "unavailable")


def _validate_payload(payload: list[dict[str, Any]], *, source: str) -> list[str]:
    """样本量校验：任一板块样本不足视为源降级，拒绝写库（不写脏数据）。"""
    problems: list[str] = []
    for row in payload:
        board = row.get("board")
        sample = int(row.get("sample_size") or 0)
        if board == "all":
            threshold = SINA_MIN_SAMPLE * 2
        elif board == "bse":
            threshold = 20  # 北交所样本天然少
        else:
            threshold = SINA_MIN_SAMPLE // 2
        if sample < threshold:
            problems.append(f"{board}:sample={sample}<{threshold}")
    return problems


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def compute(
    conn: psycopg.Connection,
    as_of: date | None = None,
    *,
    now: datetime | None = None,
    fetch_sina: Callable[[], list[dict[str, Any]]] | None = None,
    fetch_em: Callable[[], list[dict[str, Any]]] | None = None,
) -> dict:
    """抓取并写入当日各板块估值；源全部失败时优雅降级（不写库）并返回状态。

    fetch_sina/fetch_em 可注入（单测纯 mock，不触网）。
    """
    install_hardened_session()
    wall = _now_cn(now)
    summary: dict[str, Any] = {
        "status": "unavailable",
        "as_of": None,
        "source": None,
        "boards": {},
        "error": None,
        "generated_at": wall.isoformat(),
    }

    # --- 收盘确认门（P1-3）：未确认绝不写库，避免盘中快照覆盖历史收盘 ---
    skip_reason: str | None = None
    trade_date: date | None = None
    if as_of is not None:
        skip_reason = validate_as_of(conn, as_of, now=wall)
        trade_date = None if skip_reason else as_of
    else:
        candidate = _latest_trading_day(conn, wall.date())
        if candidate is None:
            skip_reason = "no_trade_date"
        elif not is_close_confirmed(candidate, wall):
            skip_reason = "not_closed"
        else:
            trade_date = candidate

    if skip_reason is not None:
        _note, _status = _skip_note(skip_reason)
        # 交易日历为空是真实故障（exit 1 告警）；盘中/非法 as_of 是刻意不写（skipped）。
        summary.update({
            "status": "unavailable" if skip_reason == "no_trade_date" else "skipped",
            "as_of": trade_date.isoformat() if trade_date else None,
            "error": skip_reason,
            "skip_reason": skip_reason,
        })
        _record_status(conn, None, _status, _note)
        return summary

    summary["as_of"] = trade_date.isoformat() if trade_date else None

    failures: list[str] = []
    # --- 免费源 1：新浪行情中心 ---
    try:
        rows = (fetch_sina or fetch_sina_all)()
        if rows:
            grouped = stats_from_sina(rows)
            payload = []
            for board in ("main", "chinext", "star", "bse", "all"):
                pe_med, pe_eq, pb_med, pb_eq, sample = _sina_stats(grouped.get(board, []))
                payload.append({
                    "board": board,
                    "pe_median": pe_med,
                    "pe_equal": pe_eq,
                    "pb_median": pb_med,
                    "pb_equal": pb_eq,
                    "sample_size": sample,
                })
            problems = _validate_payload(payload, source=CALC_SRC_SINA)
            if not problems:
                _write_payload(conn, trade_date, payload, calc_src=CALC_SRC_SINA)
                summary.update({
                    "status": "ok",
                    "source": CALC_SRC_SINA,
                    "boards": {item["board"]: item["sample_size"] for item in payload},
                })
                _record_status(
                    conn, trade_date, "ok", f"新浪行情中心免费源（样本 {payload[-1]['sample_size']}）",
                    source=CALC_SRC_SINA, meta={"boards": summary["boards"]},
                )
                return summary
            failures.append("sina:" + ",".join(problems))
            logger.warning("新浪市场估值样本不足，降级东财: %s", problems)
        else:
            failures.append("sina:empty")
    except Exception as exc:  # noqa: BLE001 - 换降级源
        failures.append(f"sina:{type(exc).__name__}")
        logger.warning("新浪市场估值源失败，降级东财: %s", exc)

    # --- 免费源 2（降级）：东财 clist ---
    try:
        payload = (fetch_em or payload_from_em)()
        payload = [dict(item) for item in payload]
        problems = _validate_payload(payload, source=CALC_SRC_EM)
        if payload and not problems:
            _write_payload(conn, trade_date, payload, calc_src=CALC_SRC_EM)
            summary.update({
                "status": "ok",
                "source": CALC_SRC_EM,
                "boards": {item["board"]: item["sample_size"] for item in payload},
            })
            _record_status(
                conn, trade_date, "ok", "东财 clist 降级源",
                source=CALC_SRC_EM, meta={"boards": summary["boards"]},
            )
            return summary
        failures.append("em:" + (",".join(problems) if problems else "empty"))
    except Exception as exc:  # noqa: BLE001 - 全部失败，优雅降级
        failures.append(f"em:{type(exc).__name__}")
        logger.warning("东财市场估值源失败: %s", exc)

    # --- 两源全失败：不写脏数据，记录 unavailable/stale 供 UI 提示 ---
    note = "市场估值快照源不可用（" + "; ".join(failures) + "）；已保留最近一次成功快照"
    summary["error"] = "; ".join(failures) or "unavailable"
    logger.error(note)
    _record_status(conn, trade_date, "unavailable", note, meta={"failures": failures})
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI（cron 用）：抓取并写入全市场估值快照，失败优雅降级（退出码 1 供告警）。

    用法::

        python -m bp_ingest.market_valuation
        python -m bp_ingest.market_valuation --date 2026-11-27 --json
    """
    import argparse  # noqa: PLC0415
    import json  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        prog="bp_ingest.market_valuation", description="全市场估值快照（新浪免费源为主，东财降级）"
    )
    parser.add_argument("--date", default=None, help="快照交易日 YYYY-MM-DD（默认最近已收盘确认日）")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    )
    from bp_ingest.config import load_config, setup_logging  # noqa: PLC0415
    from bp_ingest.db import connect  # noqa: PLC0415

    setup_logging(getattr(load_config(), "log_level", "INFO"))
    as_of = date.fromisoformat(args.date) if args.date else None
    with connect(load_config().db) as conn:
        conn.autocommit = False
        summary = compute(conn, as_of=as_of)
    print(json.dumps(summary, ensure_ascii=False, default=str, indent=1))
    # skipped（盘中/无效 as_of）是刻意的「本轮不写」，不算任务失败；
    # unavailable（源全部失败/日历为空）返回 1 供 cron 告警。
    return 0 if summary.get("status") in ("ok", "skipped") else 1


if __name__ == "__main__":
    import sys  # noqa: PLC0415

    sys.exit(main())

