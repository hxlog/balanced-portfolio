"""Binance USDT 永续合约微观数据采集与分位预计算（P5）。

数据链路::

    本机 Xray（VLESS → 新加坡出口，仅本地 127.0.0.1:10809）
        → Binance FAPI（服务器在上海无法直连，故采集在本机执行、只把结果写入生产库）
        → 本模块 → bp_crypto_contract / bp_crypto_futures_snapshot_5m
                 → bp_crypto_futures_percentile（API 只读预计算表）

采集机需设置 ``HTTPS_PROXY=http://127.0.0.1:10809`` 才能出网到 Binance；
生产服务器上不安装任何代理，也不参与 Binance 抓取。

口径:
  * 合约池 = ``contractType=PERPETUAL`` + ``quoteAsset=USDT`` + ``status=TRADING``，
    按 24h ``quoteVolume`` 倒序取前 30（``oi_notional_rank`` 1..30）。
  * 快照每 5 分钟对齐到 UTC 5 分钟桶，同一桶重复运行幂等 upsert。
  * 缺失即缺失：多空比 / taker 比 / OI 缺失写 NULL，绝不补 0；
    markPrice 缺失则整条合约跳过（无法定价，写入无意义）。
  * 分位公式复用 ``bp_api.quant.valuation.percentile``（中点 rank），
    窗口 30/90/180 个自然日，样本为按 UTC 日聚合后的最后一笔非空值。
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional
from urllib.parse import quote, urlencode

import psycopg
import requests

from bp_api.quant.valuation import percentile

from .config import load_config
from .db import connect
from .http_session import install_hardened_session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

BINANCE_DIRECT_BASE = "https://fapi.binance.com"
PROXY_ENV = "BP_BINANCE_PROXY_URL"

TOP_CONTRACTS = 30
SNAPSHOT_PERIOD = "5m"
PERCENTILE_WINDOWS: tuple[int, ...] = (30, 90, 180)
# 每个窗口要求的最小样本天数：样本不足时宁可不输出，避免「30 个样本冒充 90 天分位」。
MIN_SAMPLE_BY_WINDOW: dict[int, int] = {30: 20, 90: 60, 180: 120}
PERCENTILE_METRICS: tuple[str, ...] = (
    "mark_price",
    "oi_notional",
    "long_short_ratio",
    "taker_buy_sell_ratio",
    "basis_pct",
)

# 与 workers/binance-proxy/src/index.ts 的 ALLOWED_PATHS 保持一致。
# exchangeInfo / ticker/24hr 是 fetch_contracts() 筛选 Top 30 的必需输入；
# 生产无法直连 Binance，故同样经 Worker 转发。
EXCHANGE_INFO = "/fapi/v1/exchangeInfo"
TICKER_24H = "/fapi/v1/ticker/24hr"
PREMIUM_INDEX = "/fapi/v1/premiumIndex"
OPEN_INTEREST = "/fapi/v1/openInterest"
GLOBAL_LONG_SHORT = "/futures/data/globalLongShortAccountRatio"
TAKER_LONG_SHORT = "/futures/data/takerlongshortRatio"
KLINE = "/fapi/v1/klines"
FUNDING_RATE = "/fapi/v1/fundingRate"
TOP_ACCOUNT = "/futures/data/topLongShortAccountRatio"
TOP_POSITION = "/futures/data/topLongShortPositionRatio"
OI_HIST = "/futures/data/openInterestHist"

ALLOWED_PATHS: frozenset[str] = frozenset(
    {
        EXCHANGE_INFO,
        TICKER_24H,
        PREMIUM_INDEX,
        OPEN_INTEREST,
        GLOBAL_LONG_SHORT,
        TAKER_LONG_SHORT,
        OI_HIST,
        KLINE,
        FUNDING_RATE,
    TOP_ACCOUNT,
    TOP_POSITION,
    }
)

_MAX_WORKERS = 4

# 经 SG relay 的 HTTP 代理每次新建连接都要重做 TLS，实测首包 1.5~8s。
# 用线程本地 Session 复用 keep-alive 连接，把 30 个合约 × 5 端点的代价摊薄。
_THREAD_LOCAL = threading.local()


def _session() -> requests.Session:
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        proxy = (os.getenv("BP_BINANCE_HTTP_PROXY") or "").strip()
        session = requests.Session()
        if proxy:
            session.proxies = {"http": proxy, "https": proxy}
        _THREAD_LOCAL.session = session
    return session

# install_hardened_session() 本身幂等但非线程安全；并发抓取前串行化首次安装。
_SESSION_LOCK = threading.Lock()


def _ensure_session() -> None:
    with _SESSION_LOCK:
        install_hardened_session()


# ---------------------------------------------------------------------------
# URL / HTTP
# ---------------------------------------------------------------------------

def _resolve_base_url() -> tuple[str, bool]:
    """返回 ``(base_url, is_proxy)``；代理未配置时直连 Binance。"""
    proxy = (os.getenv(PROXY_ENV) or "").strip()
    if proxy:
        return proxy.rstrip("/"), True
    return BINANCE_DIRECT_BASE, False


def build_request_url(path: str, params: Optional[dict[str, Any]] = None) -> str:
    """构造上游 URL。

    * 代理模式: ``{proxy}/?path=/fapi/v1/...&symbol=BTCUSDT``
    * 直连模式: ``https://fapi.binance.com/fapi/v1/...?symbol=BTCUSDT``

    ``path`` 只允许白名单常量（防止 SSRF / 任意路径转发）。
    """
    if path not in ALLOWED_PATHS:
        raise ValueError(f"unsupported Binance path: {path!r}")
    base, is_proxy = _resolve_base_url()
    query = urlencode(params or {}, doseq=True)
    if is_proxy:
        url = f"{base}/?path={quote(path, safe='/')}"
        return f"{url}&{query}" if query else url
    return f"{base}{path}" + (f"?{query}" if query else "")


def _get_json(
    path: str,
    params: Optional[dict[str, Any]] = None,
    *,
    timeout: float = 30.0,
    retries: int = 2,
) -> Any:
    """GET 上游并返回 JSON。所有网络调用都先安装硬化会话。"""
    _ensure_session()
    url = build_request_url(path, params)
    # 生产服务器直连 Binance 被墙，经本机 relay（systemd bp-relay，127.0.0.1:10809）出网。
    # 只对本模块的请求生效，不污染进程级 HTTP(S)_PROXY（其余数据源仍走直连）。
    proxy = (os.getenv("BP_BINANCE_HTTP_PROXY") or "").strip()
    proxies = {"http": proxy, "https": proxy} if proxy else None
    # 覆盖硬化会话给东财设置的默认 Referer；Binance 请求用自家来源页更自然。
    headers = {
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    last_exc: Optional[Exception] = None
    session = _session()
    for attempt in range(max(1, retries)):
        try:
            response = session.get(
                url,
                timeout=timeout,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # noqa: BLE001 - 经 relay 的偶发抖动重试一次
            last_exc = exc
            if attempt + 1 < max(1, retries):
                time.sleep(1.5)
    assert last_exc is not None
    raise last_exc

def _to_float(value: Any) -> Optional[float]:
    """字符串/数字 → 有限 float；None/空串/NaN/Inf/坏值 → None。"""
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _to_utc_datetime(ms: Any) -> Optional[datetime]:
    value = _to_float(ms)
    if value is None or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _select_top_contracts(
    exchange_info: Any,
    tickers: Any,
    *,
    limit: int = TOP_CONTRACTS,
) -> list[dict[str, Any]]:
    """按 24h quoteVolume 倒序筛选 USDT 永续合约。"""
    if not isinstance(exchange_info, dict):
        return []
    symbols = exchange_info.get("symbols")
    if not isinstance(symbols, list):
        return []

    volumes: dict[str, float] = {}
    if isinstance(tickers, list):
        for ticker in tickers:
            if not isinstance(ticker, dict):
                continue
            symbol = ticker.get("symbol")
            volume = _to_float(ticker.get("quoteVolume"))
            if symbol and volume is not None and volume > 0:
                volumes[symbol] = volume

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in symbols:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        if (
            not symbol
            or symbol in seen
            or item.get("contractType") != "PERPETUAL"
            or item.get("quoteAsset") != "USDT"
            or item.get("status") != "TRADING"
        ):
            continue
        seen.add(symbol)
        volume = volumes.get(symbol)
        if volume is None:
            continue
        candidates.append(
            {
                "contract_code": symbol,
                "symbol": symbol,
                "base_asset": item.get("baseAsset") or "",
                "quote_asset": item.get("quoteAsset") or "USDT",
                "listed_at": _to_utc_datetime(item.get("onboardDate")),
                "is_active": True,
                "_quote_volume": volume,
            }
        )

    candidates.sort(key=lambda c: (-c["_quote_volume"], c["contract_code"]))
    selected = candidates[: max(limit, 0)]
    for rank, contract in enumerate(selected, start=1):
        contract.pop("_quote_volume", None)
        contract["oi_notional_rank"] = rank
    return selected


_UPSERT_CONTRACT_SQL = """
INSERT INTO bp_crypto_contract
    (contract_code, symbol, base_asset, quote_asset, listed_at,
     is_active, oi_notional_rank, provider)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (contract_code) DO UPDATE SET
    symbol = EXCLUDED.symbol,
    base_asset = EXCLUDED.base_asset,
    quote_asset = EXCLUDED.quote_asset,
    listed_at = COALESCE(EXCLUDED.listed_at, bp_crypto_contract.listed_at),
    is_active = EXCLUDED.is_active,
    oi_notional_rank = EXCLUDED.oi_notional_rank,
    provider = EXCLUDED.provider,
    updated_at = now()
"""


def _upsert_contracts(conn: psycopg.Connection, contracts: list[dict[str, Any]]) -> int:
    if not contracts:
        return 0
    payload = [
        (
            c["contract_code"],
            c["symbol"],
            c["base_asset"],
            c["quote_asset"],
            c.get("listed_at"),
            bool(c.get("is_active", True)),
            c.get("oi_notional_rank"),
            c.get("provider", "binance"),
        )
        for c in contracts
    ]
    codes = [c["contract_code"] for c in contracts]
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_CONTRACT_SQL, payload)
        # 掉出 Top 30 的合约不再带排名（保留历史行与快照）。
        cur.execute(
            "UPDATE bp_crypto_contract SET oi_notional_rank = NULL, updated_at = now() "
            "WHERE contract_code <> ALL(%s)",
            (codes,),
        )
    return len(payload)


def fetch_contracts(
    conn: Optional[psycopg.Connection] = None,
    *,
    limit: int = TOP_CONTRACTS,
) -> list[dict[str, Any]]:
    """拉取 exchangeInfo + 24h ticker，筛选前 N 个 USDT 永续；conn 非空时落库。"""
    try:
        exchange_info = _get_json(EXCHANGE_INFO)
        tickers = _get_json(TICKER_24H)
    except Exception as exc:  # noqa: BLE001 - 单轮失败不拖垮调度
        logger.error("Binance 合约清单拉取失败: %s", exc)
        return []

    contracts = _select_top_contracts(exchange_info, tickers, limit=limit)
    if conn is not None and contracts:
        _upsert_contracts(conn, contracts)
    logger.info(
        "Binance USDT 永续 Top %d: %s",
        len(contracts),
        [c["contract_code"] for c in contracts],
    )
    return contracts


# ---------------------------------------------------------------------------
# 5 分钟快照
# ---------------------------------------------------------------------------

def _floor_to_5m(ts: datetime) -> datetime:
    """对齐到 UTC 5 分钟桶（快照主键幂等：同一桶重复运行覆盖同一行）。"""
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
    ts = ts.astimezone(timezone.utc)
    return ts.replace(minute=ts.minute - ts.minute % 5, second=0, microsecond=0)


def _latest_item(payload: Any) -> Optional[dict[str, Any]]:
    """Binance ``/futures/data/*`` 返回按时间升序数组；取最后一项。"""
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list) and payload:
        last = payload[-1]
        return last if isinstance(last, dict) else None
    return None


def _parse_snapshot(
    contract_code: str,
    premium_index: Any,
    open_interest: Any,
    long_short: Any,
    taker: Any,
    oi_hist: Any,
    top_account: Any = None,
    top_position: Any = None,
) -> Optional[dict[str, Any]]:
    """把 5 个端点响应归一化为一行快照；缺 markPrice 返回 None（整条跳过）。"""
    premium = premium_index if isinstance(premium_index, dict) else {}
    mark_price = _to_float(premium.get("markPrice"))
    if mark_price is None:
        return None

    index_price = _to_float(premium.get("indexPrice"))
    basis_pct: Optional[float] = None
    if index_price is not None and index_price != 0:
        basis_pct = (mark_price - index_price) / index_price * 100.0

    oi_payload = open_interest if isinstance(open_interest, dict) else {}
    oi_contracts = _to_float(oi_payload.get("openInterest"))
    if oi_contracts is None:
        hist_item = _latest_item(oi_hist)
        if hist_item is not None:
            oi_contracts = _to_float(hist_item.get("sumOpenInterest"))
    oi_notional = oi_contracts * mark_price if oi_contracts is not None else None

    lsr_item = _latest_item(long_short)
    taker_item = _latest_item(taker)

    return {
        "contract_code": contract_code,
        "mark_price": mark_price,
        "index_price": index_price,
        "oi_contracts": oi_contracts,
        "oi_notional": oi_notional,
        "long_short_ratio": (
            _to_float(lsr_item.get("longShortRatio")) if lsr_item else None
        ),
        "taker_buy_sell_ratio": (
            _to_float(taker_item.get("buySellRatio")) if taker_item else None
        ),
        "basis_pct": basis_pct,
        "top_account_ratio": (
            _to_float(_latest_item(top_account).get("longShortRatio"))
            if _latest_item(top_account)
            else None
        ),
        "top_position_ratio": (
            _to_float(_latest_item(top_position).get("longShortRatio"))
            if _latest_item(top_position)
            else None
        ),
    }


_UPSERT_SNAPSHOT_SQL = """
INSERT INTO bp_crypto_futures_snapshot_5m
    (contract_code, captured_at, mark_price, index_price, oi_contracts,
     oi_notional, long_short_ratio, taker_buy_sell_ratio, basis_pct,
     top_account_ratio, top_position_ratio, provider)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (contract_code, captured_at) DO UPDATE SET
    mark_price = EXCLUDED.mark_price,
    index_price = EXCLUDED.index_price,
    oi_contracts = EXCLUDED.oi_contracts,
    oi_notional = EXCLUDED.oi_notional,
    long_short_ratio = EXCLUDED.long_short_ratio,
    taker_buy_sell_ratio = EXCLUDED.taker_buy_sell_ratio,
    basis_pct = EXCLUDED.basis_pct,
    top_account_ratio = EXCLUDED.top_account_ratio,
    top_position_ratio = EXCLUDED.top_position_ratio,
    provider = EXCLUDED.provider
"""


def _upsert_snapshots(conn: psycopg.Connection, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    payload = [
        (
            r["contract_code"],
            r["captured_at"],
            r.get("mark_price"),
            r.get("index_price"),
            r.get("oi_contracts"),
            r.get("oi_notional"),
            r.get("long_short_ratio"),
            r.get("taker_buy_sell_ratio"),
            r.get("basis_pct"),
            r.get("top_account_ratio"),
            r.get("top_position_ratio"),
            r.get("provider", "binance"),
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_SNAPSHOT_SQL, payload)
    return len(payload)


def _fetch_one_snapshot(
    contract_code: str,
    captured_at: datetime,
) -> Optional[dict[str, Any]]:
    """单合约 5 端点抓取。单端点失败降级 NULL；markPrice 失败整条跳过。"""

    def _safe(path: str, params: dict[str, Any]) -> Any:
        try:
            return _get_json(path, params)
        except Exception as exc:  # noqa: BLE001 - 单端点失败不中断整轮
            logger.warning("Binance %s %s 抓取失败: %s", contract_code, path, exc)
            return None

    premium = _safe(PREMIUM_INDEX, {"symbol": contract_code})
    if not isinstance(premium, dict) or _to_float(premium.get("markPrice")) is None:
        return None

    row = _parse_snapshot(
        contract_code,
        premium,
        _safe(OPEN_INTEREST, {"symbol": contract_code}),
        _safe(
            GLOBAL_LONG_SHORT,
            {"symbol": contract_code, "period": SNAPSHOT_PERIOD, "limit": 1},
        ),
        _safe(
            TAKER_LONG_SHORT,
            {"symbol": contract_code, "period": SNAPSHOT_PERIOD, "limit": 1},
        ),
        _safe(
            OI_HIST,
            {"symbol": contract_code, "period": SNAPSHOT_PERIOD, "limit": 1},
        ),
        _safe(
            TOP_ACCOUNT,
            {"symbol": contract_code, "period": SNAPSHOT_PERIOD, "limit": 1},
        ),
        _safe(
            TOP_POSITION,
            {"symbol": contract_code, "period": SNAPSHOT_PERIOD, "limit": 1},
        ),
    )
    if row is not None:
        row["captured_at"] = captured_at
    return row


def fetch_snapshot_5m(
    contracts: Iterable[dict[str, Any]],
    conn: Optional[psycopg.Connection] = None,
    *,
    captured_at: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """并发抓取全部合约的 5 个公开端点，可选落库；返回成功解析的快照行。"""
    codes: list[str] = []
    for contract in contracts:
        code = contract.get("contract_code") if isinstance(contract, dict) else None
        if code and code not in codes:
            codes.append(code)
    if not codes:
        return []

    bucket = _floor_to_5m(captured_at or datetime.now(timezone.utc))
    workers = min(_MAX_WORKERS, len(codes))
    results: list[Optional[dict[str, Any]]] = []
    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="bp-crypto-futures"
    ) as pool:
        futures = [pool.submit(_fetch_one_snapshot, code, bucket) for code in codes]
        for future in futures:
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001 - 防御性兜底
                logger.error("Binance 快照任务异常: %s", exc)
                results.append(None)

    rows = [row for row in results if row is not None]
    rows.sort(key=lambda r: r["contract_code"])
    if conn is not None and rows:
        _upsert_snapshots(conn, rows)
    logger.info(
        "Binance 5m 快照: captured_at=%s success=%d/%d",
        bucket.isoformat(), len(rows), len(codes),
    )
    return rows


# ---------------------------------------------------------------------------
# 分位预计算
# ---------------------------------------------------------------------------

_DAILY_QUERY = """
WITH daily AS (
    SELECT
        s.contract_code,
        (s.captured_at AT TIME ZONE 'UTC')::date AS trade_date,
        (array_agg(s.mark_price ORDER BY s.captured_at DESC)
            FILTER (WHERE s.mark_price IS NOT NULL))[1] AS mark_price,
        (array_agg(s.oi_notional ORDER BY s.captured_at DESC)
            FILTER (WHERE s.oi_notional IS NOT NULL))[1] AS oi_notional,
        (array_agg(s.long_short_ratio ORDER BY s.captured_at DESC)
            FILTER (WHERE s.long_short_ratio IS NOT NULL))[1] AS long_short_ratio,
        (array_agg(s.taker_buy_sell_ratio ORDER BY s.captured_at DESC)
            FILTER (WHERE s.taker_buy_sell_ratio IS NOT NULL))[1] AS taker_buy_sell_ratio,
        (array_agg(s.basis_pct ORDER BY s.captured_at DESC)
            FILTER (WHERE s.basis_pct IS NOT NULL))[1] AS basis_pct
    FROM bp_crypto_futures_snapshot_5m s
    JOIN bp_crypto_contract c ON c.contract_code = s.contract_code
    WHERE s.captured_at >= now() - INTERVAL '181 days'
      AND c.is_active
      AND c.oi_notional_rank IS NOT NULL
      -- provider 不同的历史快照（Binance / Bybit）不可混算分位
      AND s.provider = c.provider
    GROUP BY s.contract_code, trade_date
)
SELECT contract_code, trade_date, mark_price, oi_notional,
       long_short_ratio, taker_buy_sell_ratio, basis_pct
FROM daily
ORDER BY contract_code, trade_date
"""

_UPSERT_PERCENTILE_SQL = """
INSERT INTO bp_crypto_futures_percentile
    (contract_code, metric, window_days, as_of, pct, sample_size)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (contract_code, metric, window_days, as_of) DO UPDATE SET
    pct = EXCLUDED.pct,
    sample_size = EXCLUDED.sample_size,
    computed_at = now()
"""

_METRIC_INDEX = {metric: idx for idx, metric in enumerate(PERCENTILE_METRICS, start=2)}


def _upsert_percentiles(conn: psycopg.Connection, rows: list[tuple]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_PERCENTILE_SQL, rows)
    return len(rows)


def compute_percentiles(
    conn: psycopg.Connection,
    *,
    as_of: Optional[date] = None,
) -> dict[str, Any]:
    """按合约 × 指标 × 30/90/180 日窗口计算分位，落 bp_crypto_futures_percentile。

    数据源是按 UTC 日降采样后的快照最后值（``_DAILY_QUERY``），避免把 5 分钟
    噪声当作独立样本，也让 30/90/180「天」窗口名副其实。分位公式复用
    ``bp_api.quant.valuation.percentile``（``(count(<=x)-0.5*count(==x))/N``）。
    """
    with conn.cursor() as cur:
        cur.execute(_DAILY_QUERY)
        raw_rows = cur.fetchall()

    by_contract: dict[str, dict[str, list[tuple[date, float]]]] = {}
    for row in raw_rows:
        contract_code, trade_date = row[0], row[1]
        if as_of is not None and trade_date > as_of:
            continue
        series_by_metric = by_contract.setdefault(contract_code, {})
        for metric, idx in _METRIC_INDEX.items():
            value = _to_float(row[idx])
            if value is None:
                continue
            series_by_metric.setdefault(metric, []).append((trade_date, value))

    out: list[tuple] = []
    for contract_code, series_by_metric in sorted(by_contract.items()):
        for metric in PERCENTILE_METRICS:
            series = sorted(series_by_metric.get(metric, []))
            if not series:
                continue
            # as_of = 该指标最后一个真实样本日，避免把端点数故障当成「新鲜」。
            metric_as_of = series[-1][0]
            for window_days in PERCENTILE_WINDOWS:
                start = metric_as_of - timedelta(days=window_days - 1)
                values = [
                    value
                    for trade_date, value in series
                    if start <= trade_date <= metric_as_of
                ]
                if not values:
                    continue
                if len(values) < MIN_SAMPLE_BY_WINDOW.get(window_days, 1):
                    continue
                pct = percentile(values, values[-1])
                if pct is None:
                    continue
                out.append(
                    (
                        contract_code,
                        metric,
                        window_days,
                        metric_as_of,
                        round(float(pct), 6),
                        len(values),
                    )
                )

    _upsert_percentiles(conn, out)
    logger.info(
        "Binance 分位预计算: contracts=%d rows=%d as_of=%s",
        len(by_contract), len(out), as_of.isoformat() if as_of else "latest",
    )
    return {"contracts": len(by_contract), "rows": len(out)}


# ---------------------------------------------------------------------------
# 单轮入口
# ---------------------------------------------------------------------------

def run_once() -> dict[str, Any]:
    """一轮完整采集：合约池 → 5m 快照 → 分位；由调度器/Celery 调用。"""
    config = load_config()
    with connect(config.db) as conn:
        contracts = fetch_contracts(conn)
        snapshots = fetch_snapshot_5m(contracts, conn) if contracts else []
        percentiles = compute_percentiles(conn)
    return {
        "contracts": len(contracts),
        "snapshots": len(snapshots),
        "percentile_rows": percentiles["rows"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Binance USDT 永续合约 5 分钟快照 + 分位（P5）"
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("BP_LOG_LEVEL", "INFO"),
        help="日志级别（默认 INFO）",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    print(json.dumps(run_once(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
