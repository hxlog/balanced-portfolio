"""全局数据新鲜度：``bp_data_freshness`` 写入/读取 + 匿名 API。

设计约束（见 docs/design/2026-11-27-unified-redesign/implementation-plan.md P0-6）：

- **单一事实源**：8 类数据（a_stock/hk_stock/etf/fund_nav/cffex/index_quotes/
  index_valuation/mvi）的新鲜度由各任务在完成时通过 ``record_freshness`` /
  ``record_freshness_standalone`` 写入 ``bp_data_freshness``；
- **请求路径永不计算**：``GET /api/v1/market/data-freshness`` 只读该表；表行缺失时
  用低成本的源表 MAX 兜底推导 as_of（bp_asset_coverage / CFFEX / 估值 / MVI），
  避免任一写方尚未接入时徽标整块不可用；
- **状态口径**：读取侧按「交易日历的应到日期 expected_date」与 as_of 重算
  ok / lagging / stale；``unavailable`` / ``error`` 由写入方显式标记（如市场估值
  免费源全部失败），读取侧保留该状态并透传 note；
- **60s 进程内缓存**：同一进程内最多每 60 秒查一次库（Redis 缺失也能工作）；
- **匿名可读**：本路由不依赖 auth 依赖（与 /api/v1 其余需 token 的端点不同，
  它是全局徽标，游客也要能看到数据更新到哪天）。
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Optional, Sequence

from fastapi import FastAPI

from . import db

logger = logging.getLogger(__name__)

CN = dt.timezone(dt.timedelta(hours=8))

#: 进程内缓存 TTL（秒）。任务提示要求 60s。
CACHE_TTL_SECONDS = 60


@dataclass(frozen=True)
class DatasetSpec:
    """一类数据的展示与应到日期口径。"""

    key: str
    label: str
    #: 收盘确认时点（CST）：该时点前当日数据不算「应到」
    confirm_hhmm: tuple[int, int]
    #: 兜底推导 as_of 的取值键（见 _derive_as_of）
    derive_key: str
    #: 写入口径描述（透传到 meta.source）
    source: str


#: 8 类数据：顺序即 API 返回顺序（前端 tooltip 依赖稳定顺序）。
DATASETS: tuple[DatasetSpec, ...] = (
    DatasetSpec("a_stock", "A股行情", (15, 10), "a_stock", "bp_etl"),
    DatasetSpec("hk_stock", "港股行情", (16, 15), "hk_stock", "bp_etl"),
    DatasetSpec("etf", "ETF行情", (15, 10), "etf", "bp_etl"),
    DatasetSpec("fund_nav", "基金净值", (20, 0), "fund_nav", "bp_etl"),
    DatasetSpec("cffex", "股指期货", (16, 48), "cffex", "bp_ingest.cffex"),
    DatasetSpec("index_quotes", "指数行情", (15, 10), "index_quotes", "scripts/index_quotes_free.py"),
    DatasetSpec("index_valuation", "指数估值", (21, 0), "index_valuation", "bp_ingest.valuation_ingest"),
    DatasetSpec("mvi", "市场估值指数", (23, 50), "mvi", "scripts/compute_mvi.py"),
)

DATASET_KEYS: tuple[str, ...] = tuple(spec.key for spec in DATASETS)
_SPEC_BY_KEY: dict[str, DatasetSpec] = {spec.key: spec for spec in DATASETS}

#: 不在 8 类徽标内、但同表记录的扩展数据集（meta.extra 暴露给 admin/UI 降级提示）。
EXTRA_DATASETS: tuple[str, ...] = ("market_valuation", "risk_free")
EXTRA_SPECS: dict[str, DatasetSpec] = {
    # 市场估值快照：21:20 抓取（新浪免费源），前端可据此显示 stale/unavailable
    "market_valuation": DatasetSpec(
        "market_valuation", "全市场估值快照", (21, 20), "market_valuation",
        "bp_ingest.market_valuation",
    ),
    # 10Y 国债：21:40 抓取（chinabond -> akshare -> 新浪）
    "risk_free": DatasetSpec(
        "risk_free", "10Y 国债收益率", (21, 40), "risk_free",
        "bp_ingest.risk_free",
    ),
}
EXTRA_LABELS: dict[str, str] = {key: spec.label for key, spec in EXTRA_SPECS.items()}

STATUS_VALUES = frozenset({"ok", "lagging", "stale", "missing", "unavailable", "error"})

#: 状态严重度：读取侧取「写入方状态 / 按应到日重算状态 / 覆盖率判定」三者中最严重者。
#: 覆盖不足时写入方可能仍报 ok（如指数行情仅补了 59% 的跟踪指数），不能只按 lag 判绿。
STATUS_SEVERITY: dict[str, int] = {
    "ok": 0, "lagging": 1, "stale": 2, "missing": 3, "unavailable": 4, "error": 5,
}

#: 覆盖率达标线：低于该比例即使 as_of 追平也应显示 lagging（用户反馈 P0）。
COVERAGE_OK_MIN = 0.99

#: meta 里可能出现的覆盖率字段（各写方历史口径不同，按优先级尝试）。
_COVERAGE_RATIO_KEYS = ("ratio", "coverage")
_COVERAGE_TOTAL_KEYS = ("total", "universe")
_COVERAGE_COVERED_KEYS = ("covered", "db_covered")


def worst_status(*statuses: Optional[str]) -> str:
    """返回若干状态中最严重的一个（忽略 None/非法值；全空按 ok）。"""
    candidates = [item for item in statuses if item in STATUS_SEVERITY]
    if not candidates:
        return "ok"
    return max(candidates, key=lambda item: STATUS_SEVERITY[item])


def _iso_cst(value: Any) -> Optional[str]:
    """日期/时间 -> Asia/Shanghai(+08:00) ISO 字符串。

    - datetime：aware 转 CN；naive 视为已是 CN（DB timestamptz 通常 aware）。
    - date：只回日期字符串（date 无时区）。
    - 其它：原样转字符串（None 保留）。
    """
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        moment = value.astimezone(CN) if value.tzinfo is not None else value.replace(tzinfo=CN)
        return moment.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return text
        # ISO datetime 字符串（如写方把 meta.completed_at 存成 "…+00:00"）同样转 +08:00；
        # 纯日期字符串保持日期语义，不补成午夜时间。
        if "T" in text or " " in text:
            try:
                parsed = dt.datetime.fromisoformat(text)
            except ValueError:
                return text
            moment = (
                parsed.astimezone(CN)
                if parsed.tzinfo is not None
                else parsed.replace(tzinfo=CN)
            )
            return moment.isoformat()
        return text
    return str(value)


def meta_coverage(meta: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """从 bp_data_freshness.meta 提取覆盖率 {covered,total,ratio}（缺失返回 None）。"""
    if not isinstance(meta, dict):
        return None
    ratio: Optional[float] = None
    for key in _COVERAGE_RATIO_KEYS:
        value = meta.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            ratio = float(value)
            break
    total: Optional[int] = None
    for key in _COVERAGE_TOTAL_KEYS:
        value = meta.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total = int(value)
            break
    covered: Optional[int] = None
    for key in _COVERAGE_COVERED_KEYS:
        value = meta.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            covered = int(value)
            break
    if ratio is None and covered is not None and total:
        ratio = covered / total
    if covered is None and ratio is not None and total:
        covered = int(round(ratio * total))
    if ratio is None and covered is None and total is None:
        return None
    return {"covered": covered, "total": total, "ratio": ratio}


def _normalize_meta(meta: Optional[dict[str, Any]]) -> dict[str, Any]:
    """meta 原样透传，但把其中的 completed_at 统一转成 +08:00 的 ISO 字符串。"""
    if not isinstance(meta, dict):
        return {}
    normalized = dict(meta)
    if "completed_at" in normalized:
        normalized["completed_at"] = _iso_cst(normalized.get("completed_at"))
    return normalized


# ---------------------------------------------------------------------------
# 进程内 60s 缓存（Redis 只是可选增强，这里不依赖它）
# ---------------------------------------------------------------------------
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _monotonic() -> float:
    return time.monotonic()


def invalidate_cache() -> None:
    """清空进程内缓存（写方想立即看到新值时可选调用；60s 后自然过期）。"""
    _CACHE.clear()


def _cache_get(now: float | None = None) -> Optional[dict[str, Any]]:
    item = _CACHE.get("freshness")
    if item is None:
        return None
    stored_at, payload = item
    if (now if now is not None else _monotonic()) - stored_at > CACHE_TTL_SECONDS:
        _CACHE.pop("freshness", None)
        return None
    return payload


def _cache_put(payload: dict[str, Any], now: float | None = None) -> None:
    _CACHE["freshness"] = (now if now is not None else _monotonic(), payload)


# ---------------------------------------------------------------------------
# 纯计算：应到交易日 / 状态判定
# ---------------------------------------------------------------------------
def latest_trading_day(
    trading_days: list[dt.date], reference: dt.date
) -> Optional[dt.date]:
    """<= reference 的最近交易日。"""
    candidate = None
    for day in trading_days:
        if day > reference:
            break
        candidate = day
    return candidate


def expected_trade_date(
    spec: DatasetSpec,
    now: dt.datetime,
    trading_days: list[dt.date],
) -> Optional[dt.date]:
    """某类数据「应到」的交易日。

    当日是交易日且现在未过该类的收盘确认时点 -> 前一交易日；否则 -> 最近交易日。
    """
    now = now.astimezone(CN) if now.tzinfo is not None else now.replace(tzinfo=CN)
    candidate = latest_trading_day(trading_days, now.date())
    if candidate is None:
        return None
    if candidate == now.date():
        cutoff = dt.time(*spec.confirm_hhmm)
        if now.timetz().replace(tzinfo=None) < cutoff:
            earlier = latest_trading_day(trading_days, candidate - dt.timedelta(days=1))
            return earlier
    return candidate


def trading_days_between(
    trading_days: list[dt.date], start: dt.date, end: dt.date
) -> list[dt.date]:
    """(start, end] 区间内的交易日（start 当天不计）。"""
    return [day for day in trading_days if start < day <= end]


def classify_status(
    as_of: Optional[dt.date],
    expected: Optional[dt.date],
    trading_days: list[dt.date],
    *,
    stored_status: Optional[str] = None,
    stored_note: Optional[str] = None,
) -> dict[str, Any]:
    """按 as_of / expected 判定状态，并给出 is_stale / lag_trading_days / note。"""
    if stored_status in ("unavailable", "error"):
        return {
            "status": stored_status,
            "is_stale": True,
            "lag_trading_days": None,
            "note": stored_note,
        }
    if as_of is None:
        return {"status": "missing", "is_stale": True, "lag_trading_days": None,
                "note": stored_note or "尚无数据"}
    if expected is None:
        # 没有交易日历（空库/测试）：无法判定落后，按写入方状态透传
        status = stored_status if stored_status in STATUS_VALUES else "ok"
        return {"status": status, "is_stale": status != "ok", "lag_trading_days": None,
                "note": stored_note}
    lag = len(trading_days_between(trading_days, as_of, expected))
    if lag <= 0:
        status = "ok"
    elif lag == 1:
        status = "lagging"
    else:
        status = "stale"
    note = stored_note
    if note is None and status != "ok":
        note = f"落后 {lag} 个交易日（应到 {expected.isoformat()}）"
    return {
        "status": status,
        "is_stale": status != "ok",
        "lag_trading_days": lag,
        "note": note,
    }


# ---------------------------------------------------------------------------
# 数据库读写
# ---------------------------------------------------------------------------
#
# 事务安全（P1-2）：本模块的读写函数经常被**共享写事务**调用（如估值落库
# `run_valuation_ingest` 写完整批数据后收尾调用 `sync_derived_freshness`）。
# 任何辅助查询失败都**只能回滚到 SAVEPOINT**，绝不能 `conn.rollback()` 把
# 调用方已写入的估值/MVI 等主数据整体回滚（更不能把共享事务拖入 aborted）。
@contextmanager
def _read_savepoint(conn: Any, name: str) -> Iterator[None]:
    """只读查询的事务隔离：失败回滚到保存点，成功释放；绝不回滚主事务。"""
    with conn.cursor() as cur:
        cur.execute(f'SAVEPOINT "{name}"')
    try:
        yield
    except Exception:
        try:
            with conn.cursor() as cur:
                cur.execute(f'ROLLBACK TO SAVEPOINT "{name}"')
                cur.execute(f'RELEASE SAVEPOINT "{name}"')
        except Exception:  # noqa: BLE001 - 连接已断等极端情况
            logger.warning("回滚新鲜度只读保存点失败 name=%s", name, exc_info=True)
        raise
    else:
        try:
            with conn.cursor() as cur:
                cur.execute(f'RELEASE SAVEPOINT "{name}"')
        except Exception:  # noqa: BLE001
            logger.warning("释放新鲜度只读保存点失败 name=%s", name, exc_info=True)


def _derive_rows(conn: Any, sql: str, params: tuple = ()) -> list:
    """执行兜底推导查询；用 SAVEPOINT 隔离失败，绝不回滚调用方事务。"""
    try:
        with _read_savepoint(conn, "bp_freshness_derive"):
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())
    except Exception:  # noqa: BLE001 - 兜底推导失败不影响主表口径/主事务
        logger.warning("新鲜度兜底推导查询失败（已回滚保存点，主事务保留）", exc_info=True)
        return []


def _table_exists(conn: Any) -> bool:
    """迁移未应用时优雅降级（不让写入方的事务因 UndefinedTable 中断）。"""
    try:
        with _read_savepoint(conn, "bp_freshness_table"):
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('public.bp_data_freshness')")
                row = cur.fetchone()
        return bool(row and row[0])
    except Exception:  # noqa: BLE001 - 连接异常时同样视为不可写，交由调用方日志
        logger.warning("bp_data_freshness 存在性检查失败", exc_info=True)
        return False


def record_freshness(
    conn: Any,
    dataset: str,
    as_of: Optional[dt.date] = None,
    *,
    status: str = "ok",
    note: Optional[str] = None,
    source: Optional[str] = None,
    expected_date: Optional[dt.date] = None,
    meta: Optional[dict[str, Any]] = None,
) -> bool:
    """UPSERT 一类数据的新鲜度（幂等）。

    - ``as_of`` 只前进不后退（status='ok'/lagging/stale 时保留已推进日期）：
      避免乱序/重放把已推进的日期写回旧值；
    - 表不存在（未跑 79 号迁移）时返回 False 并告警，不抛异常、不中断调用方事务。

    返回是否真正写入。
    """
    key = (dataset or "").strip()
    if not key:
        return False
    status_value = status if status in STATUS_VALUES else "ok"
    spec = _SPEC_BY_KEY.get(key)
    label = spec.label if spec else EXTRA_LABELS.get(key, key)
    if not _table_exists(conn):
        logger.warning("bp_data_freshness 不存在，跳过新鲜度写入 dataset=%s（请先执行 ddl/79）", key)
        return False

    cur = conn.cursor()
    try:
        # SAVEPOINT：新鲜度写入失败只回滚本段，绝不把调用方（ETL/估值）事务拖入 aborted
        cur.execute("SAVEPOINT bp_data_freshness_write")
        cur.execute("SELECT as_of FROM bp_data_freshness WHERE dataset = %s", (key,))
        row = cur.fetchone()
        existing_as_of: Optional[dt.date] = row[0] if row and row[0] is not None else None

        effective_as_of = as_of
        if effective_as_of is None:
            effective_as_of = existing_as_of
        elif existing_as_of is not None and effective_as_of < existing_as_of:
            # 只有显式错误/不可用状态允许回退日期；正常状态只前进
            if status_value in ("ok", "lagging", "stale"):
                effective_as_of = existing_as_of

        cur.execute(
            """
            INSERT INTO bp_data_freshness
                (dataset, label, as_of, expected_date, status, note, source, meta, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
            ON CONFLICT (dataset) DO UPDATE SET
                label = EXCLUDED.label,
                as_of = EXCLUDED.as_of,
                expected_date = COALESCE(EXCLUDED.expected_date, bp_data_freshness.expected_date),
                status = EXCLUDED.status,
                note = EXCLUDED.note,
                source = COALESCE(EXCLUDED.source, bp_data_freshness.source),
                meta = COALESCE(bp_data_freshness.meta, '{}'::jsonb) || COALESCE(EXCLUDED.meta, '{}'::jsonb),
                updated_at = now()
            """,
            (
                key,
                label,
                effective_as_of,
                expected_date,
                status_value,
                note,
                source or (spec.source if spec else None),
                _json_dumps(meta or {}),
            ),
        )
        cur.execute("RELEASE SAVEPOINT bp_data_freshness_write")
        return True
    except Exception:  # noqa: BLE001 - 新鲜度写入失败不阻断主任务
        try:
            cur.execute("ROLLBACK TO SAVEPOINT bp_data_freshness_write")
        except Exception:  # noqa: BLE001 - 连接已断等极端情况
            pass
        logger.warning("写入 bp_data_freshness 失败 dataset=%s", key, exc_info=True)
        return False
    finally:
        try:
            cur.close()
        except Exception:  # noqa: BLE001
            pass


def record_freshness_standalone(
    dataset: str,
    as_of: Optional[dt.date] = None,
    **kwargs: Any,
) -> bool:
    """脚本/独立任务用的写入封装：自建连接 + commit + 吞异常。

    调用方（cron 脚本、一次性任务）不必自己处理连接与迁移缺失。
    """
    try:
        from bp_ingest.config import load_config  # noqa: PLC0415 - 避免 API 进程 import 开销
        from bp_ingest.db import connect  # noqa: PLC0415

        with connect(load_config().db) as conn:
            conn.autocommit = False
            ok = record_freshness(conn, dataset, as_of, **kwargs)
            conn.commit()
        return ok
    except Exception:  # noqa: BLE001 - 新鲜度是增强信号，失败不得让 cron 任务失败
        logger.warning("独立写入数据新鲜度失败 dataset=%s", dataset, exc_info=True)
        return False


def _json_dumps(value: dict[str, Any]) -> str:
    import json  # noqa: PLC0415

    return json.dumps(value, ensure_ascii=False, default=str)


def merge_freshness_meta(conn: Any, dataset: str, patch: dict[str, Any]) -> bool:
    """只合并 meta（不动 as_of/status），供写方补「已知限制/覆盖起点」等说明。

    事务安全：使用 SAVEPOINT，失败只回滚本段，绝不回滚调用方（估值落库）主事务。
    """
    key = (dataset or "").strip()
    if not key or not isinstance(patch, dict) or not patch:
        return False
    if not _table_exists(conn):
        logger.warning("bp_data_freshness 不存在，跳过 meta 合并 dataset=%s（请先执行 ddl/79）", key)
        return False
    cur = conn.cursor()
    try:
        cur.execute("SAVEPOINT bp_data_freshness_meta")
        cur.execute(
            "UPDATE bp_data_freshness"
            " SET meta = COALESCE(meta, '{}'::jsonb) || %s::jsonb, updated_at = now()"
            " WHERE dataset = %s",
            (_json_dumps(patch), key),
        )
        cur.execute("RELEASE SAVEPOINT bp_data_freshness_meta")
        return True
    except Exception:  # noqa: BLE001 - meta 说明是增强信息，失败不阻断主任务
        try:
            cur.execute("ROLLBACK TO SAVEPOINT bp_data_freshness_meta")
        except Exception:  # noqa: BLE001
            pass
        logger.warning("合并 bp_data_freshness.meta 失败 dataset=%s", key, exc_info=True)
        return False
    finally:
        try:
            cur.close()
        except Exception:  # noqa: BLE001
            pass


def sync_derived_freshness(
    conn: Any,
    datasets: Optional[Sequence[str]] = None,
) -> dict[str, bool]:
    """从源表 MAX 推导并写入新鲜度（供估值/MVI/行情等任务收尾一行调用）。

    典型用法（任务完成时）::

        from bp_api.freshness import sync_derived_freshness
        sync_derived_freshness(conn, ("index_valuation", "mvi"))

    与 record_freshness 的关系：后者由写方给出精确 as_of/状态；本函数从
    bp_asset_coverage / bp_index_valuation_daily / bp_market_valuation_index /
    bp_cffex_contract_daily 等源表推导 as_of，供尚未接入写入逻辑的任务（估值、
    MVI 等）便捷同步，避免徽标整块缺失。返回 {dataset: 是否写入}。
    """
    keys = tuple(datasets) if datasets else DATASET_KEYS
    derived = derive_as_of(conn)
    results: dict[str, bool] = {}
    for key in keys:
        value = derived.get(_SPEC_BY_KEY[key].derive_key if key in _SPEC_BY_KEY else key)
        if value is None:
            results[key] = False
            continue
        results[key] = record_freshness(conn, key, value, source="derived")
    return results


def load_stored_rows(conn: Any) -> dict[str, dict[str, Any]]:
    """读 bp_data_freshness（含扩展类别）；表缺失/异常返回空 dict。"""
    if not _table_exists(conn):
        return {}
    rows: dict[str, dict[str, Any]] = {}
    # 只读查询也用 SAVEPOINT：失败不得回滚调用方事务（错误/空表按无数据处理）
    fetched = _derive_rows(
        conn,
        "SELECT dataset, label, as_of, expected_date, status, note, source, updated_at, meta"
        " FROM bp_data_freshness",
    )
    for dataset, label, as_of, expected_date, status, note, source, updated_at, meta in fetched:
        rows[dataset] = {
            "label": label,
            "as_of": as_of,
            "expected_date": expected_date,
            "status": status,
            "note": note,
            "source": source,
            "updated_at": updated_at,
            "meta": meta if isinstance(meta, dict) else {},
        }
    return rows


def _scalar_or_none(conn: Any, sql: str, params: tuple = ()) -> Any:
    """只读兜底查询：单表单列；表不存在/异常时回滚**保存点**并返回 None（不向外抛）。

    关键：绝不 `conn.rollback()` —— 本函数可能在共享写事务中调用（估值/MVI 收尾），
    整体回滚会把已写入的主数据清掉。异常只回滚到 SAVEPOINT。
    """
    try:
        with _read_savepoint(conn, "bp_freshness_scalar"):
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
        return row[0] if row else None
    except Exception:  # noqa: BLE001 - 兜底推导失败不影响主表口径
        return None


def derive_as_of(conn: Any) -> dict[str, Optional[dt.date]]:
    """源表 MAX 兜底推导（低成本，仅 60s 一次）。

    用于写方尚未接入/首次部署时的降级：bp_asset_coverage（a_stock/hk_stock/etf/
    fund_nav/index_quotes）、CFFEX 合约表、指数估值主口径、MVI、扩展类别。
    """
    derived: dict[str, Optional[dt.date]] = {}
    # 1) 资产覆盖快照：kind + code 长度区分 A/HK；index 覆盖指数行情
    # 全部兜底查询都走 _derive_rows/_scalar_or_none（SAVEPOINT 隔离），
    # 任何一张表缺失/查询失败都不会回滚调用方的主数据事务。
    coverage_rows = _derive_rows(
        conn,
        "SELECT kind, (length(code) = 6) AS is_a_share, max(last_date)"
        " FROM bp_asset_coverage"
        " WHERE kind IN ('stock', 'etf', 'fund', 'index')"
        " GROUP BY kind, (length(code) = 6)",
    )
    for kind, is_a_share, last_date in coverage_rows:
        if kind == "stock":
            derived["a_stock" if is_a_share else "hk_stock"] = last_date
        elif kind == "etf":
            derived["etf"] = last_date
        elif kind == "fund":
            derived["fund_nav"] = last_date
        elif kind == "index":
            derived["index_quotes"] = last_date

    # 1b) 新链 4 类：以 bp_etl_dataset_state 的 last_success_date 为准（比 coverage
    #     快照更精确：coverage 是逐标的增量 upsert，可能落后于 state 推进）。
    state_rows = _derive_rows(
        conn,
        "SELECT dataset, max(last_success_date) FROM bp_etl_dataset_state"
        " WHERE dataset IN ('a_stock', 'hk_stock', 'etf', 'fund_nav')"
        " GROUP BY dataset",
    )
    for dataset, last_success in state_rows:
        if last_success is None:
            continue
        if derived.get(dataset) is None or last_success > derived[dataset]:
            derived[dataset] = last_success

    # 2) CFFEX / 指数估值 / MVI / 扩展类别（单表单列 MAX，均有索引）
    fallbacks = (
        ("cffex", "SELECT max(trade_date) FROM bp_cffex_contract_daily"),
        ("index_valuation", "SELECT max(trade_date) FROM bp_index_valuation_daily WHERE is_primary"),
        ("mvi", "SELECT max(as_of) FROM bp_market_valuation_index"),
        ("market_valuation", "SELECT max(trade_date) FROM bp_market_valuation_daily"),
        ("risk_free", "SELECT max(trade_date) FROM bp_macro_series WHERE series_code = 'cn_10y_yield'"),
    )
    for key, sql in fallbacks:
        derived[key] = _scalar_or_none(conn, sql)
    return derived


def _load_trading_days(conn: Any, now: dt.datetime) -> list[dt.date]:
    """读 A 股交易日历（最近 ~2 年，足够算 lag）；缺失时返回空列表。"""
    start = now.date() - dt.timedelta(days=800)
    return [
        row[0]
        for row in _derive_rows(
            conn,
            "SELECT cal_date FROM bp_trading_calendar"
            " WHERE market = 'CN' AND is_trading AND cal_date >= %s AND cal_date <= %s"
            " ORDER BY cal_date",
            (start, now.date() + dt.timedelta(days=1)),
        )
    ]


def _build_item(
    spec: DatasetSpec,
    row: Optional[dict[str, Any]],
    derived_as_of: Optional[dt.date],
    expected: Optional[dt.date],
    trading_days: list[dt.date],
) -> dict[str, Any]:
    stored = row or {}
    stored_as_of = stored.get("as_of")
    as_of = stored_as_of
    if derived_as_of is not None and (as_of is None or derived_as_of > as_of):
        as_of = derived_as_of
    meta = _normalize_meta(stored.get("meta"))
    coverage = meta_coverage(meta)
    state = classify_status(
        as_of,
        expected,
        trading_days,
        stored_status=stored.get("status"),
        stored_note=stored.get("note"),
    )
    # 状态取「写入方状态 / 按应到日重算 / 覆盖率」三者中最严重者：
    # 覆盖率不足时即使 as_of 追平也应显示 lagging（不能只按 lag 判绿）。
    coverage_lagging = bool(
        coverage and coverage.get("ratio") is not None
        and float(coverage["ratio"]) < COVERAGE_OK_MIN
    )
    status = worst_status(state["status"], stored.get("status"),
                          "lagging" if coverage_lagging else None)
    is_stale = status != "ok"
    note = state["note"] or stored.get("note")
    if note is None and coverage_lagging:
        note = _coverage_note(spec, coverage)
    if note is None and is_stale:
        note = f"数据状态 {status}"
    updated_at = stored.get("updated_at")
    completed_at = meta.get("completed_at") if meta else None
    if completed_at is None:
        completed_at = updated_at
    # 前端契约同时给自然日差 lag_days 与交易日差 lag_trading_days（后者供排查）；
    # as_of 超前于应到日（例如估值任务人工补跑）时钳到 0，避免 UI 出现负滞后。
    lag_days = (
        max(0, (expected - as_of).days)
        if as_of is not None and expected is not None
        else None
    )
    return {
        "dataset": spec.key,
        "label": spec.label,
        "as_of": as_of.isoformat() if as_of else None,
        "expected_date": expected.isoformat() if expected else None,
        "status": status,
        "is_stale": is_stale,
        "lag_days": lag_days,
        "lag_trading_days": state["lag_trading_days"],
        "updated_at": (
            updated_at.isoformat()
            if isinstance(updated_at, (dt.datetime, dt.date))
            else updated_at
        ),
        # 完成时间统一 +08:00（CI/服务器时区无关）；优先 meta.completed_at，回退写入时间
        "completed_at": _iso_cst(completed_at),
        "source": stored.get("source") or spec.source,
        "note": note,
        "meta": meta,
        "coverage": coverage,
    }


def _coverage_note(spec: DatasetSpec, coverage: dict[str, Any]) -> str:
    """覆盖率不足时的 note（如「覆盖 284/481（59%）」）。"""
    covered = coverage.get("covered")
    total = coverage.get("total")
    ratio = coverage.get("ratio")
    if covered is not None and total:
        return f"覆盖 {int(covered)}/{int(total)}（{float(ratio or 0) * 100:.0f}%）"
    if ratio is not None:
        return f"覆盖 {float(ratio) * 100:.0f}%（低于 {COVERAGE_OK_MIN:.0%}）"
    return "覆盖率不足"


def _load_index_coverage(
    conn: Any,
    stored_row: Optional[dict[str, Any]],
    expected: Optional[dt.date],
) -> dict[str, Any]:
    """指数行情覆盖率 {covered,total,ratio}（用户反馈：覆盖不足必须可见/显示 lagging）。

    优先读写入方 index_quotes_free.py 写入的 bp_data_freshness.meta（覆盖统计
    与实际采集同口径）；缺失时退化为两条轻量只读聚合（60s 缓存内每进程最多一次）。
    """
    meta = meta_coverage((stored_row or {}).get("meta"))
    if meta and meta.get("ratio") is not None and meta.get("total"):
        return {
            "covered": meta.get("covered"),
            "total": meta.get("total"),
            "ratio": round(float(meta["ratio"]), 4),
            "as_of": _iso_cst((stored_row or {}).get("as_of")),
            "source": "bp_data_freshness.meta",
        }
    total = _scalar_or_none(
        conn, "SELECT count(*) FROM bp_index_master WHERE is_tracked = TRUE"
    )
    total_int = int(total) if total else 0
    covered: Optional[int] = None
    if expected is not None and total_int:
        value = _scalar_or_none(
            conn,
            "SELECT count(DISTINCT q.symbol) FROM bp_index_quote_daily q"
            " JOIN bp_index_master m ON m.index_code = q.symbol AND m.is_tracked = TRUE"
            " WHERE q.adjust = 'bfq' AND q.trade_date = %s",
            (expected,),
        )
        covered = int(value) if value is not None else None
    if covered is None or not total_int:
        return {
            "covered": covered,
            "total": total_int or None,
            "ratio": None,
            "as_of": expected.isoformat() if expected else None,
            "source": "unavailable",
        }
    return {
        "covered": covered,
        "total": total_int,
        "ratio": round(covered / total_int, 4),
        "as_of": expected.isoformat() if expected else None,
        "source": "bp_index_quote_daily",
    }


def _load_source_health(conn: Any) -> dict[str, Any]:
    """bp_etl_source_health 最近 stat_date 的聚合（按 dataset 汇总 attempts/ok/failed）。"""
    latest_rows = _derive_rows(
        conn, "SELECT max(stat_date) FROM bp_etl_source_health"
    )
    latest = latest_rows[0][0] if latest_rows and latest_rows[0] else None
    if latest is None:
        return {}
    fetched = _derive_rows(
        conn,
        "SELECT dataset, source, channel, attempts, ok, failed, banned_count, coverage_today"
        " FROM bp_etl_source_health WHERE stat_date = %s ORDER BY dataset, source, channel",
        (latest,),
    )
    datasets: dict[str, dict[str, Any]] = {}
    for dataset, source, channel, attempts, ok, failed, banned, coverage in fetched:
        item = datasets.setdefault(
            str(dataset),
            {"attempts": 0, "ok": 0, "failed": 0, "banned_count": 0,
             "success_rate": None, "sources": []},
        )
        item["attempts"] += int(attempts or 0)
        item["ok"] += int(ok or 0)
        item["failed"] += int(failed or 0)
        item["banned_count"] += int(banned or 0)
        item["sources"].append(
            {
                "source": source,
                "channel": channel,
                "attempts": int(attempts or 0),
                "ok": int(ok or 0),
                "failed": int(failed or 0),
                "banned_count": int(banned or 0),
                "coverage_today": float(coverage) if coverage is not None else None,
            }
        )
    for item in datasets.values():
        if item["attempts"]:
            item["success_rate"] = round(item["ok"] / item["attempts"], 4)
    return {"stat_date": _iso_cst(latest), "datasets": datasets}


def build_payload(
    conn: Any,
    *,
    now: Optional[dt.datetime] = None,
    cached: bool = False,
) -> dict[str, Any]:
    """组装 API 响应体（{data, meta, error} 信封）。"""
    current = (now or dt.datetime.now(CN)).astimezone(CN)
    trading_days = _load_trading_days(conn, current)
    stored = load_stored_rows(conn)
    derived = derive_as_of(conn)

    items = [
        _build_item(
            spec,
            stored.get(spec.key),
            derived.get(spec.derive_key),
            expected_trade_date(spec, current, trading_days),
            trading_days,
        )
        for spec in DATASETS
    ]

    dated = [dt.date.fromisoformat(item["as_of"]) for item in items if item["as_of"]]
    latest_complete = min(dated) if dated else None
    expected_global = expected_trade_date(DATASETS[0], current, trading_days)
    # 用户反馈：all_complete 必须要求每类 status == ok（覆盖不足/滞后/陈旧都不算齐套），
    # 不能只比较 as_of >= expected_date（否则 index_quotes 覆盖 59% 也被判 complete）。
    all_complete = bool(dated) and all(item["status"] == "ok" for item in items)
    missing = [item["dataset"] for item in items if item["as_of"] is None]
    index_coverage = _load_index_coverage(
        conn,
        stored.get("index_quotes"),
        expected_trade_date(_SPEC_BY_KEY["index_quotes"], current, trading_days),
    )
    source_health = _load_source_health(conn)
    extra: dict[str, Any] = {}
    for key in EXTRA_DATASETS:
        spec = EXTRA_SPECS[key]
        row = stored.get(key)
        if row is None and derived.get(key) is None:
            continue
        built = _build_item(
            spec,
            row,
            derived.get(key),
            expected_trade_date(spec, current, trading_days),
            trading_days,
        )
        extra[key] = {
            "label": spec.label,
            "as_of": built["as_of"],
            "expected_date": built["expected_date"],
            "status": built["status"],
            "is_stale": built["is_stale"],
            "note": built["note"],
        }
    payload = {
        "data": items,
        "meta": {
            "latest_complete_date": latest_complete.isoformat() if latest_complete else None,
            "expected_date": expected_global.isoformat() if expected_global else None,
            "all_complete": all_complete,
            "missing": missing,
            "cached": cached,
            "generated_at": current.isoformat(),
            "extra": extra,
            # 指数行情覆盖率（覆盖不足时对应 item 显示 lagging + note）
            "index_coverage": index_coverage,
            # 最近一个 stat_date 的源健康聚合（bp_etl_source_health）
            "source_health": source_health,
        },
        "error": None,
    }
    return payload


def load_payload_cached(conn: Any, *, now: Optional[dt.datetime] = None) -> dict[str, Any]:
    """60s 进程内缓存的响应体（cache 命中时 meta.cached=True）。"""
    cached = _cache_get()
    if cached is not None:
        payload = dict(cached)
        payload["meta"] = {**cached["meta"], "cached": True}
        return payload
    payload = build_payload(conn, now=now, cached=False)
    _cache_put(payload)
    return payload


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
def register_routes(app: FastAPI) -> None:
    """注册匿名只读端点（由 bp_api/main.py 调用）。

    main.py 需要的注册行::

        from . import freshness
        freshness.register_routes(app)
    """

    @app.get("/api/v1/market/data-freshness", tags=["public-api"])
    def market_data_freshness() -> dict:
        """8 类市场数据的新鲜度（匿名可读，60s 缓存）。

        响应信封与 ``/api/v1`` 其余端点一致：``{data, meta, error}``。
        ``meta.latest_complete_date = min(as_of)`` 即「全局行情数据更新至」；
        ``meta.all_complete`` 表示 8 类是否全部追平各自应到交易日。
        """
        with db.get_conn() as conn:
            return load_payload_cached(conn)
