"""平安证券指数估值数据采集器.

接口与字段口径见 ``docs/index-valuation/01-recon-and-data-dictionary.md`` §2.1/§2.2.
本模块只负责 HTTP 抓取、压缩串解析与字段归一化, **不写数据库**; 后续 ingest 任务
消费 :func:`fetch_all` 的原始行, 再落 ``bp_index_*`` 估值表。

抓取约定:
  - ``POST`` form-urlencoded, 匿名可访问, 需移动端 UA + Referer + X-Requested-With;
  - 复用 ``bp_ingest.http_session.install_hardened_session()`` 的硬化会话;
  - 全局限速 2.5 req/s, 超时 30s, 失败重试 3 次 (指数退避 1/2/4s);
  - 所有公开函数返回 Python 原生类型 (list/dict/date/float), 不返回 DataFrame。
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Sequence

import requests

logger = logging.getLogger(__name__)

BASE = "https://m.stock.pingan.com/omm/v2/http/mop/vault/query"
TRACKER_FUND_URL = "https://m.stock.pingan.com/omm/v2/http/shelf/queryOnsiteFundInfoList"

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)
REFERER = "https://m.stock.pingan.com/omm/phonex/indexZone/light.html"
HEADERS: dict[str, str] = {
    "User-Agent": MOBILE_UA,
    "Accept": "application/json",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Referer": REFERER,
    "X-Requested-With": "XMLHttpRequest",
}

REQUEST_TIMEOUT = 30.0
MAX_RETRIES = 3
BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)
RATE_LIMIT_RPS = 2.5
PAGE_SIZE = 1000
DETAIL_BATCH_SIZE = 10

# 各数据视图的 fields (与页面实际请求一致; INDEX_DATA_V2 为 184/185 两批字段的并集)。
INDEX_DATA_FIELDS: tuple[str, ...] = (
    "pbPercen",
    "indexName",
    "dividendRate",
    "dividendLevel",
    "volatility",
    "peLevel",
    "pbRatio",
    "volatilityLevel",
    "sharpRatio",
    "sharpLevel",
    "peg",
    "pegLevel",
    "roe",
    "roeLevel",
    "otcFund",
    "etfFund",
    "profitBar",
    "peBar",
    "stockList",
    "updateDate",
    "riseLastday",
    "riseWeek",
    "riseMonth",
    "rise3Months",
    "rise6Months",
    "riseYear",
    "indexIntro",
    "indexType",
    "peRatio",
    "pePercen",
    "pbLevel",
)
INDEX_DETAIL_FIELDS: tuple[str, ...] = (
    "indexName",
    "indexIntro",
    "indexType",
    "peRatio",
    "pePercen",
    "peLevel",
    "isPb",
    "pbRatio",
    "pbPercen",
    "pbLevel",
    "dividendRate",
    "dividendLevel",
    "volatility",
    "volatilityLevel",
    "sharpRatio",
    "sharpLevel",
    "peg",
    "pegLevel",
    "roe",
    "roeLevel",
    "otcFund",
    "etfFund",
    "profitBar",
    "peBar",
    "pbBar",
    "stockList",
    "updateDate",
    "riseLastday",
    "riseWeek",
    "riseMonth",
    "rise3Months",
    "rise6Months",
    "riseYear",
    "highPe",
    "lowPe",
    "lowPE",
    "profitTrace",
    "roeTrace",
    "profitExpection",
    "incomeY1",
    "profitY1",
    "marketShow",
    "roeTtm",
    "roeGrow",
    "roeGrowlv",
    "roeGpercent",
    "didPercent",
    "lowDid",
    "didHis",
    "highDid",
    "bond10",
)
DESCRIPTION_FIELDS: tuple[str, ...] = (
    "code",
    "sInfoWindCode",
    "indexIntro",
    "sInfoCompany",
    "sInfoIndexBaseper",
    "weightTypeName",
    "sInfoIncomeMethod",
    "sInfoIndexBasept",
    "sInfoIndexType",
    "sInfoPublisher",
    "sInfoIndexWeightsrule",
)
VALUATION_FIELDS: tuple[str, ...] = ("code", "sInfoWind", "conNum", "mvTotal")
PERFORMANCE_FIELDS: tuple[str, ...] = (
    "code",
    "sInfoWindcode",
    "pctChgRecent1w",
    "pctChgRecent1m",
    "pctChgRecent3m",
    "pctChgRecent6m",
    "pctChgRecent1y",
    "pctChgRecent2y",
    "pctChgRecent3y",
    "siPctChg",
    "stdDev1y",
    "stdDev2y",
    "stdDev3y",
    "sharpratio1y",
    "sharpratio2y",
    "sharpratio3y",
)
BOND10_FIELDS: tuple[str, ...] = ("tradeDt", "bAnalyield")


class _RateLimiter:
    """线程安全的全局限速器 (默认 2.5 req/s)。"""

    def __init__(self, rps: float) -> None:
        self._interval = 1.0 / rps
        self._lock = threading.Lock()
        self._next_at = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._next_at - now
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            self._next_at = now + self._interval


_GLOBAL_LIMITER = _RateLimiter(RATE_LIMIT_RPS)
_session_ready = False
_session_lock = threading.Lock()

# ---------------------------------------------------------------------------
# 全局 deadline 与熔断：避免源端持续超时把一次抓取拖成数十分钟
# ---------------------------------------------------------------------------
FETCH_DEADLINE_SECONDS = 600.0  # 单次 fetch_all 的硬上限
CIRCUIT_BREAK_THRESHOLD = 6     # 连续 N 个请求（含重试）彻底失败即熔断


class FetchDeadlineExceeded(RuntimeError):
    """整批抓取超过全局 deadline。"""


class FetchCircuitOpen(RuntimeError):
    """连续失败过多触发熔断。"""


_deadline_at: float | None = None
_consecutive_failures = 0
_failure_lock = threading.Lock()


def _set_deadline(seconds: float) -> None:
    global _deadline_at
    _deadline_at = time.monotonic() + seconds


def _clear_deadline() -> None:
    global _deadline_at
    _deadline_at = None


def _check_deadline() -> None:
    if _deadline_at is not None and time.monotonic() > _deadline_at:
        raise FetchDeadlineExceeded("fetch deadline exceeded")


def _record_failure() -> None:
    global _consecutive_failures
    with _failure_lock:
        _consecutive_failures += 1
        if _consecutive_failures >= CIRCUIT_BREAK_THRESHOLD:
            raise FetchCircuitOpen(f"circuit open after {_consecutive_failures} failures")


def _record_success() -> None:
    global _consecutive_failures
    with _failure_lock:
        _consecutive_failures = 0


def _ensure_hardened_session() -> None:
    """惰性安装项目硬化会话 (curl_cffi Chrome 指纹优先, 失败则退回 requests)。"""
    global _session_ready
    if _session_ready:
        return
    with _session_lock:
        if _session_ready:
            return
        try:
            from .http_session import install_hardened_session

            install_hardened_session()
        except Exception as exc:  # noqa: BLE001 - 硬化会话是可选增强
            logger.warning("硬化 HTTP 会话不可用, 回退 requests: %s", exc)
        _session_ready = True


def _post_form(url: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """POST form 并返回 JSON body; 429/5xx/网络错误按 1/2/4s 退避重试。"""
    _ensure_hardened_session()

    for attempt in range(MAX_RETRIES + 1):
        _check_deadline()
        _GLOBAL_LIMITER.acquire()
        try:
            response = requests.post(
                url,
                data=dict(payload),
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
        except Exception:  # noqa: BLE001 - curl_cffi 与 requests 异常体系不同
            if attempt >= MAX_RETRIES:
                _record_failure()
                raise
            time.sleep(BACKOFF_SECONDS[attempt])
            continue

        status = getattr(response, "status_code", 200) or 200
        if status == 429 or 500 <= status < 600:
            if attempt >= MAX_RETRIES:
                response.raise_for_status()
            time.sleep(BACKOFF_SECONDS[attempt])
            continue

        response.raise_for_status()
        try:
            body = response.json()
        except ValueError:
            if attempt >= MAX_RETRIES:
                raise
            time.sleep(BACKOFF_SECONDS[attempt])
            continue

        if not isinstance(body, dict):
            raise ValueError(f"平安接口返回非对象 JSON: {type(body).__name__}")
        code = str(body.get("responseCode", "0"))
        if code not in ("0", "200", ""):
            _record_failure()
            raise RuntimeError(f"平安接口 responseCode={code}: {url}")
        _record_success()
        return body

    raise RuntimeError(f"平安接口请求失败: {url}")  # pragma: no cover - 循环内必返回或抛出


def _response_rows(body: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = body.get("rows")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _response_data(body: Mapping[str, Any]) -> list[dict[str, Any]]:
    data = body.get("data")
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _chunks(values: Sequence[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


def _fetch_paged(
    key: str,
    fields: Sequence[str],
    *,
    page_size: int | None = None,
    extra: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """按 curPage/pageSize 翻页拉全量; total 已知时以 total 为准, 否则以空页/短页终止。"""
    size = PAGE_SIZE if page_size is None else page_size
    rows: list[dict[str, Any]] = []
    page = 1

    while True:
        payload: dict[str, Any] = {
            "key": key,
            "fields": ",".join(fields),
            "curPage": page,
            "pageSize": size,
        }
        if extra:
            payload.update(extra)

        body = _post_form(BASE, payload)
        batch = _response_rows(body)
        rows.extend(batch)

        total = _as_int(body.get("total"))
        if not batch:
            break
        if total is not None:
            if len(rows) >= total:
                break
        elif len(batch) < size:
            break
        page += 1
        if page > 1000:
            raise RuntimeError(f"平安接口 {key} 翻页超过 1000 页, 疑似分页参数无效")

    return rows


# ---------------------------------------------------------------------------
# 抓取入口
# ---------------------------------------------------------------------------


def fetch_index_universe() -> list[dict[str, Any]]:
    """INDEX_DATA: 全市场指数主指标 (实测 521 行, pageSize=999)。"""
    return _fetch_paged(
        "INDEX_DATA",
        INDEX_DATA_FIELDS,
        page_size=999,
        extra={"method": ""},
    )


def fetch_index_detail(codes: Sequence[str]) -> list[dict[str, Any]]:
    """INDEX_DATA_V2: 按 codes 批量拉指数全字段, 每批 10 个。"""
    clean = _dedupe(str(code) for code in codes if code)
    rows: list[dict[str, Any]] = []
    for batch in _chunks(clean, DETAIL_BATCH_SIZE):
        body = _post_form(
            BASE,
            {
                "key": "INDEX_DATA_V2",
                "codes": ",".join(batch),
                "fields": ",".join(INDEX_DETAIL_FIELDS),
            },
        )
        rows.extend(_response_rows(body))
    return rows


def fetch_index_description() -> list[dict[str, Any]]:
    """A_INDEX_DESCRIPTION: 指数简介/基日/编制方等 (约 1398 行)。"""
    return _fetch_paged("A_INDEX_DESCRIPTION", DESCRIPTION_FIELDS)


def fetch_index_valuation_meta() -> list[dict[str, Any]]:
    """A_INDEX_VALUATION: 成分股数量与总市值 (约 494 行)。"""
    return _fetch_paged("A_INDEX_VALUATION", VALUATION_FIELDS)


def fetch_index_performance() -> list[dict[str, Any]]:
    """S_INDEX_PERFORMANCE: 阶段收益/波动/夏普 (约 439 行)。"""
    return _fetch_paged("S_INDEX_PERFORMANCE", PERFORMANCE_FIELDS)


def fetch_bond10_history() -> list[dict[str, Any]]:
    """BOND10_TREND: 十年期国债到期收益率全历史 (2017 至今, 约 1463 行)。"""
    return _fetch_paged(
        "BOND10_TREND",
        BOND10_FIELDS,
        extra={"orderBy": "tradeDt", "orderType": "asc"},
    )


def fetch_tracker_funds(codes: Sequence[str]) -> list[dict[str, Any]]:
    """queryOnsiteFundInfoList: 跟踪 ETF/联接基金全字段, 按 codeList 批量。"""
    clean = _dedupe(str(code) for code in codes if code)
    rows: list[dict[str, Any]] = []
    for batch in _chunks(clean, DETAIL_BATCH_SIZE):
        body = _post_form(TRACKER_FUND_URL, {"codeList": ",".join(batch)})
        rows.extend(_response_data(body))
    return rows


def fetch_all(deadline_seconds: float = FETCH_DEADLINE_SECONDS) -> dict[str, Any]:
    """汇总全量抓取结果 (供后续 ingest 消费; 不写数据库)。

    关键约束:
    - 全局 deadline (默认 10 分钟): 超时后不再发起新请求, 已取到的部分照常返回;
    - 熔断: 连续 CIRCUIT_BREAK_THRESHOLD 个请求彻底失败后中止;
    - 部分失败不丢整体: 每个数据视图独立 try/except, 失败记入 errors。
    """
    _set_deadline(deadline_seconds)
    errors: list[str] = []
    payload: dict[str, Any] = {
        "index_universe": [],
        "index_detail": [],
        "index_description": [],
        "index_valuation_meta": [],
        "index_performance": [],
        "bond10_history": [],
        "tracker_funds": [],
        "errors": errors,
    }

    def run(label: str, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except (FetchDeadlineExceeded, FetchCircuitOpen) as exc:
            errors.append(f"{label}: {exc}")
            return None
        except Exception as exc:  # noqa: BLE001 - 单个视图失败不影响其余
            errors.append(f"{label}: {type(exc).__name__}: {exc}")
            return None

    try:
        universe = run("index_universe", fetch_index_universe) or []
        payload["index_universe"] = universe
        codes = [str(row["code"]) for row in universe if row.get("code")]

        detail = run("index_detail", lambda: fetch_index_detail(codes)) or []
        payload["index_detail"] = detail

        fund_codes: list[str] = []
        for row in detail:
            fund_codes.extend(_split_codes(row.get("etfFund")))

        payload["index_description"] = run("index_description", fetch_index_description) or []
        payload["index_valuation_meta"] = run("index_valuation_meta", fetch_index_valuation_meta) or []
        payload["index_performance"] = run("index_performance", fetch_index_performance) or []
        payload["bond10_history"] = run("bond10_history", fetch_bond10_history) or []
        if fund_codes:
            payload["tracker_funds"] = run("tracker_funds", lambda: fetch_tracker_funds(fund_codes)) or []
    finally:
        _clear_deadline()
    return payload


# ---------------------------------------------------------------------------
# 压缩串解析
# ---------------------------------------------------------------------------


def parse_series(s: str | None) -> list[tuple[date, float]]:
    """解析 ``date,value|date,value`` (peBar/pbBar/didHis)。

    非法日期或非法数值的条目直接跳过; 空串/None 返回空列表。
    """
    if not isinstance(s, str) or not s.strip():
        return []

    result: list[tuple[date, float]] = []
    for chunk in s.split("|"):
        parts = chunk.split(",")
        if len(parts) < 2:
            continue
        trade_date = _parse_date(parts[0])
        value = _to_float(parts[1])
        if trade_date is None or value is None:
            continue
        result.append((trade_date, value))
    return result


def parse_stock_list(s: str | None) -> list[dict[str, Any]]:
    """解析 ``code,name,weight%|...`` 为成分股列表。

    ``code`` 拆为 ``stock_code`` + ``market`` (如 ``SZ000538`` -> ``000538``/``SZ``);
    权重缺失或非法时为 None, 代码或名称缺失的条目跳过。
    """
    if not isinstance(s, str) or not s.strip():
        return []

    result: list[dict[str, Any]] = []
    for chunk in s.split("|"):
        parts = [part.strip() for part in chunk.split(",")]
        if len(parts) < 3:
            continue
        vendor_code, name, weight_raw = parts[0], parts[1], parts[2]
        if not vendor_code or not name:
            continue
        _, stock_code, market = _split_vendor_code(vendor_code)
        if not stock_code:
            continue
        result.append(
            {
                "vendor_code": vendor_code,
                "stock_code": stock_code,
                "market": market,
                "name": name,
                "weight": _to_float(weight_raw),
            }
        )
    return result


def parse_trace(s: str | None) -> list[dict[str, Any]]:
    """解析 ``year,a,b|...`` (roeTrace/profitTrace)。

    年份缺失的条目跳过; a/b 缺失或非法时为 None。
    """
    if not isinstance(s, str) or not s.strip():
        return []

    result: list[dict[str, Any]] = []
    for chunk in s.split("|"):
        parts = [part.strip() for part in chunk.split(",")]
        if len(parts) < 3:
            continue
        year = parts[0]
        if not year:
            continue
        result.append({"year": year, "a": _to_float(parts[1]), "b": _to_float(parts[2])})
    return result


# ---------------------------------------------------------------------------
# 字段归一化
# ---------------------------------------------------------------------------

_PREFIX_TO_MARKET: dict[str, str] = {
    "ZI": "CSI",   # 中证（含 ZI / ZIH / ZICES）
    "SH": "SH",
    "SZ": "SZ",
    "BJ": "BJ",
    "HK": "HK",
    "IX": "US",    # 美股/全球指数
    # 商品、富时、新交所、郑商所、标普合资等：统一归入 GLOBAL，避免丢弃
    "FI": "GLOBAL",  # 富时 (FTSE)
    "IN": "GLOBAL",  # 上期能源 (INE)
    "SG": "GLOBAL",  # 新交所 / 上海金
    "CZ": "GLOBAL",  # 郑商所易盛
    "CI": "GLOBAL",  # 标普/中证合资
    "XI": "GLOBAL",  # 富时中国 A50
    "DC": "GLOBAL",  # 大商所
}


# 仅这些前缀后面跟的是「标准 6 位/字母指数代码」，可以安全剥离；
# 其余族（富时 FI / 新交所 SG / 郑商所 CZ / 标普合资 CI / 大商所 DC / INE / 美股 IX 等）
# 的 vendor code 本身就是标识，剥离会破坏唯一性，故原样保留。
_STRIP_PREFIXES: frozenset[str] = frozenset({"ZI", "SH", "SZ", "BJ", "HK", "IX"})


def _split_vendor_code(code: object) -> tuple[str | None, str | None, str | None]:
    """拆分平安代码前缀 -> (vendor_code, index_code, market)。

    例: ``ZI930641`` -> ``("ZI930641", "930641", "CSI")``;
    ``FI888888`` -> ``("FI888888", "FI888888", "GLOBAL")``（不剥离，避免身份被改坏）。
    """
    if code is None:
        return None, None, None
    text = str(code).strip()
    if not text:
        return None, None, None

    prefix = text[:2].upper()
    market = _PREFIX_TO_MARKET.get(prefix)
    if market is None:
        # 2 位字母前缀且非已知族 -> 归 GLOBAL 并保留完整 vendor code；
        # 纯数字/无前缀代码无法判定市场，返回 None 交给调用方决定（不猜测）。
        if prefix.isalpha() and len(text) > 2:
            return text, text, "GLOBAL"
        return text, text, None
    if prefix in _STRIP_PREFIXES and len(text) > 2:
        return text, text[2:], market
    return text, text, market


def _to_float(value: Any) -> float | None:
    """宽容数值解析: 去 %/千分位, 空值/占位符/NaN/Inf 一律 None。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None

    text = str(value).strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1].strip()
    if text.lower() in {"", "-", "--", "—", "none", "null", "nan", "n/a"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    return int(number) if number is not None else None


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_date(value: Any) -> date | None:
    """解析 YYYYMMDD / ISO 日期; 非法返回 None。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None

    text = str(value).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _split_codes(value: Any) -> list[str]:
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def normalize_index_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """把 INDEX_DATA / INDEX_DATA_V2 原始行归一化为 snake_case 原生类型。

    缺失/异常字段不抛错: 数值为 None, 列表为 []。百分比保留「百分数」口径
    (``3.68%`` -> ``3.68``), 与数据字典一致。
    """
    vendor_code, index_code, market = _split_vendor_code(row.get("code"))

    return {
        "vendor_code": vendor_code,
        "index_code": index_code,
        "market": market,
        "name": _to_text(row.get("indexName")),
        "index_type": _to_text(row.get("indexType")),
        "intro": _to_text(row.get("indexIntro")),
        "pe_ratio": _to_float(row.get("peRatio")),
        "pe_percentile": _to_float(row.get("pePercen")),
        "pe_level": _to_text(row.get("peLevel")),
        "pb_ratio": _to_float(row.get("pbRatio")),
        "pb_percentile": _to_float(row.get("pbPercen")),
        "pb_level": _to_text(row.get("pbLevel")),
        "is_pb": _to_int(row.get("isPb")),
        "dividend_rate": _to_float(row.get("dividendRate")),
        "dividend_percentile": _to_float(row.get("didPercent")),
        "dividend_level": _to_text(row.get("dividendLevel")),
        "high_dividend": _to_float(row.get("highDid")),
        "low_dividend": _to_float(row.get("lowDid")),
        "peg": _to_float(row.get("peg")),
        "peg_level": _to_text(row.get("pegLevel")),
        "roe": _to_float(row.get("roe")),
        "roe_level": _to_text(row.get("roeLevel")),
        "roe_ttm": _to_float(row.get("roeTtm")),
        "roe_growth": _to_float(row.get("roeGrow")),
        "roe_growth_percent": _to_float(row.get("roeGpercent")),
        "volatility": _to_float(row.get("volatility")),
        "volatility_level": _to_text(row.get("volatilityLevel")),
        "sharp_ratio": _to_float(row.get("sharpRatio")),
        "sharp_level": _to_text(row.get("sharpLevel")),
        "bond10": _to_float(row.get("bond10")),
        "high_pe": _to_float(row.get("highPe")),
        "low_pe": _to_float(row.get("lowPe") or row.get("lowPE")),
        "rise_last_day": _to_float(row.get("riseLastday")),
        "rise_week": _to_float(row.get("riseWeek")),
        "rise_month": _to_float(row.get("riseMonth")),
        "rise_3_months": _to_float(row.get("rise3Months")),
        "rise_6_months": _to_float(row.get("rise6Months")),
        "rise_year": _to_float(row.get("riseYear")),
        "income_yoy": _to_float(row.get("incomeY1")),
        "profit_yoy": _to_float(row.get("profitY1")),
        "market_show": _to_int(row.get("marketShow")),
        "update_date": _parse_date(row.get("updateDate")),
        "pe_bar": parse_series(row.get("peBar")),
        "pb_bar": parse_series(row.get("pbBar")),
        "dividend_history": parse_series(row.get("didHis")),
        "stock_list": parse_stock_list(row.get("stockList")),
        "etf_fund": _split_codes(row.get("etfFund")),
        "otc_fund": _split_codes(row.get("otcFund")),
        "roe_trace": parse_trace(row.get("roeTrace")),
        "profit_trace": parse_trace(row.get("profitTrace")),
        "profit_expectation": parse_trace(row.get("profitExpection")),
    }
