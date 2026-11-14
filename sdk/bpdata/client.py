"""对外数据 API ``/api/v1`` 的 Python 客户端。

设计要点：

- 仅使用标准库；安装了 ``requests`` 时优先使用，否则回退到 ``urllib``。
- 统一解析 ``{"data", "meta", "error"}`` 信封，方法直接返回 ``data``；
  最近一次响应的 ``meta`` 保存在 ``Client.last_meta``（可据此检查
  ``truncated`` / ``as_of``）。
- ``429`` 与 ``5xx`` 自动指数退避（最多重试 3 次）；``429`` 优先尊重
  ``Retry-After``；``401`` / ``403`` 不重试。
- SDK 始终请求 JSON，不使用 ``?format=csv``。
"""

from __future__ import annotations

import datetime as dt
import json
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any, Mapping, Sequence
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .errors import BpApiError, BpAuthError, BpRateLimitError

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型检查，运行时不强依赖 pandas
    import pandas as pd

try:  # requests 是可选依赖
    import requests as _requests
except ImportError:  # pragma: no cover - 取决于运行环境
    _requests = None


__all__ = ["Client"]

_VERSION = "0.1.0"
_DEFAULT_BASE_URL = "https://xushilu.com"
_DEFAULT_TIMEOUT = 30.0
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0
_BACKOFF_CAP = 60.0
_ADJUST_MODES = frozenset({"bfq", "qfq", "hfq"})

CodeInput = str | Sequence[str]
ListInput = str | Sequence[str] | None
DateInput = str | dt.date | dt.datetime | None


@dataclass(frozen=True)
class _HttpResponse:
    """把 requests / urllib 的响应归一化后的最小结构。"""

    status: int
    headers: Mapping[str, str]
    body: bytes


def _http_get(
    url: str,
    params: Mapping[str, str],
    headers: Mapping[str, str],
    timeout: float,
) -> _HttpResponse:
    """执行一次 GET；requests 缺失时回退到 urllib。"""
    if _requests is not None:
        response = _requests.get(
            url,
            params=dict(params),
            headers=dict(headers),
            timeout=timeout,
        )
        return _HttpResponse(
            status=int(response.status_code),
            headers=dict(response.headers),
            body=response.content,
        )

    query = urlencode(dict(params))
    full_url = f"{url}?{query}" if query else url
    request = Request(full_url, headers=dict(headers), method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", None)
            if status is None:  # Python < 3.9 的兼容路径
                status = response.getcode()
            return _HttpResponse(
                status=int(status),
                headers=dict(response.headers.items()),
                body=response.read(),
            )
    except HTTPError as exc:  # 4xx / 5xx 在 urllib 中会以异常形式出现
        return _HttpResponse(
            status=int(exc.code),
            headers=dict(exc.headers.items()) if exc.headers else {},
            body=exc.read(),
        )


def _decode_json(body: bytes) -> Any:
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _payload_dict(payload: Any) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if str(key).lower() == wanted:
            return str(value)
    return None


def _parse_retry_after(value: str | None) -> float | None:
    """解析 ``Retry-After``：既支持秒数，也支持 HTTP-date。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except ValueError:
        try:
            when = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.timezone.utc)
        seconds = (when - dt.datetime.now(dt.timezone.utc)).total_seconds()
    return max(0.0, seconds)


def _backoff(attempt: int) -> float:
    return min(_BACKOFF_CAP, _BACKOFF_BASE * (2**attempt))


def _raw_message(body: bytes) -> str | None:
    if not body:
        return None
    text = body.decode("utf-8", errors="replace").strip()
    if not text or text.startswith("<"):
        return None
    return text[:500]


def _extract_error(
    status: int, payload: Any, body: bytes
) -> tuple[str, str]:
    """从错误信封中提取稳定的 ``code`` 与可读 ``message``。"""
    if status == 401:
        default_code, default_message = "unauthorized", "缺少或无效的 API Token"
    elif status == 403:
        default_code, default_message = "forbidden", "Token 缺少所需权限"
    elif status == 404:
        default_code, default_message = "not_found", "请求的资源不存在"
    elif status == 422:
        default_code, default_message = "validation_error", "参数校验失败"
    elif status == 429:
        default_code, default_message = "rate_limited", "请求过于频繁"
    elif status >= 500:
        default_code, default_message = "server_error", f"服务端错误 HTTP {status}"
    else:
        default_code, default_message = "http_error", f"HTTP {status}"

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            code = error.get("code") or default_code
            message = error.get("message") or error.get("detail") or default_message
            return str(code), str(message)
        if isinstance(error, str) and error.strip():
            return default_code, error.strip()

    raw = _raw_message(body)
    return default_code, raw or default_message


def _join_values(value: str | Sequence[str], field: str) -> str:
    """把 ``["a", "b"]`` 或 ``"a,b"`` 统一成 ``"a,b"``。"""
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",") if item.strip()]
    else:
        items = [str(item).strip() for item in value if str(item).strip()]
    if not items:
        raise ValueError(f"{field} 不能为空")
    return ",".join(items)


def _optional_values(value: ListInput, field: str) -> str | None:
    if value is None:
        return None
    return _join_values(value, field)


def _date_value(value: DateInput, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return dt.date.fromisoformat(text).isoformat()
        except ValueError as exc:
            raise ValueError(f"{field} 必须是 ISO 日期 YYYY-MM-DD") from exc
    raise TypeError(f"{field} 必须是 str、date 或 datetime")


def _single_code(code: str) -> str:
    if not isinstance(code, str) or not code.strip():
        raise ValueError("code 不能为空")
    return code.strip()


def _normalize_adjust(adjust: str) -> str:
    value = str(adjust).strip().lower()
    if value not in _ADJUST_MODES:
        raise ValueError("adjust 仅支持 bfq / qfq / hfq")
    return value


def _clean_params(params: Mapping[str, Any]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in params.items():
        if value is None:
            continue
        text = str(value).strip()
        if text:
            cleaned[key] = text
    return cleaned


def _require_pandas() -> Any:
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - 由单元测试覆盖
        raise ImportError(
            "daily_frame()/valuation_frame() 需要 pandas。"
            "请先执行 `pip install pandas`，或改用 daily()/valuation() 获取 list[dict]。"
        ) from exc
    return pd


class Client:
    """对外数据 API 客户端。

    Args:
        token: ``bp_live_...`` API Token。
        base_url: API 主域名（不含 ``/api/v1``），默认 ``https://xushilu.com``。
        timeout: 单次 HTTP 请求超时秒数，默认 30。

    Example:
        >>> client = Client("bp_live_xxx")
        >>> rows = client.daily(["000300"], start="2024-01-01", end="2024-12-31")
    """

    def __init__(
        self,
        token: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        if not isinstance(token, str) or not token.strip():
            raise ValueError("token 不能为空")
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("base_url 不能为空")

        self.token = token.strip()
        self.base_url = base_url.strip().rstrip("/")
        self.timeout = float(timeout)
        if self.timeout <= 0:
            raise ValueError("timeout 必须大于 0")

        self.last_meta: dict[str, Any] = {}
        self._headers: dict[str, str] = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": f"bpdata-python/{_VERSION}",
        }

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------
    def daily(
        self,
        codes: CodeInput,
        start: DateInput = None,
        end: DateInput = None,
        adjust: str = "hfq",
    ) -> list[dict[str, Any]]:
        """拉取日行情（``GET /api/v1/market/daily``）。

        Returns:
            行列表，字段为 ``code, source, date, open, high, low, close, ret``。
        """
        data = self._get(
            "/api/v1/market/daily",
            {
                "codes": _join_values(codes, "codes"),
                "start": _date_value(start, "start"),
                "end": _date_value(end, "end"),
                "adjust": _normalize_adjust(adjust),
            },
        )
        return self._expect_list(data)

    def valuation(
        self,
        codes: CodeInput,
        start: DateInput = None,
        end: DateInput = None,
        fields: ListInput = None,
    ) -> list[dict[str, Any]]:
        """拉取指数日频估值（``GET /api/v1/index/valuation``）。

        Returns:
            行列表，字段为 ``code, date`` + 所请求的估值字段。
        """
        data = self._get(
            "/api/v1/index/valuation",
            {
                "codes": _join_values(codes, "codes"),
                "start": _date_value(start, "start"),
                "end": _date_value(end, "end"),
                "fields": _optional_values(fields, "fields"),
            },
        )
        return self._expect_list(data)

    def percentile(
        self,
        codes: CodeInput,
        metrics: ListInput = None,
        windows: ListInput = None,
    ) -> list[dict[str, Any]]:
        """拉取指数估值分位（``GET /api/v1/index/percentile``）。

        Returns:
            每个 ``(code, metric, window)`` 最新一行；``pct`` 为 **0~100 百分数**（与 API/DB 一致）。
        """
        data = self._get(
            "/api/v1/index/percentile",
            {
                "codes": _join_values(codes, "codes"),
                "metrics": _optional_values(metrics, "metrics"),
                "windows": _optional_values(windows, "windows"),
            },
        )
        return self._expect_list(data)

    def detail(self, code: str) -> dict[str, Any]:
        """拉取指数画像、成分股与跟踪基金（``GET /api/v1/index/detail``）。"""
        data = self._get(
            "/api/v1/index/detail",
            {"code": _single_code(code)},
        )
        return self._expect_dict(data)

    def bond_yield(
        self,
        start: DateInput = None,
        end: DateInput = None,
    ) -> list[dict[str, Any]]:
        """拉取 10Y 国债收益率（``GET /api/v1/market/bond-yield``）。

        Returns:
            行列表，字段为 ``date, value, unit, source``。
        """
        data = self._get(
            "/api/v1/market/bond-yield",
            {
                "start": _date_value(start, "start"),
                "end": _date_value(end, "end"),
            },
        )
        return self._expect_list(data)

    def daily_frame(
        self,
        codes: CodeInput,
        start: DateInput = None,
        end: DateInput = None,
        adjust: str = "hfq",
    ) -> pd.DataFrame:
        """同 :meth:`daily`，但返回 ``pandas.DataFrame``（需安装 pandas）。"""
        pd = _require_pandas()
        return pd.DataFrame(
            self.daily(codes, start=start, end=end, adjust=adjust)
        )

    def valuation_frame(
        self,
        codes: CodeInput,
        start: DateInput = None,
        end: DateInput = None,
        fields: ListInput = None,
    ) -> pd.DataFrame:
        """同 :meth:`valuation`，但返回 ``pandas.DataFrame``（需安装 pandas）。"""
        pd = _require_pandas()
        return pd.DataFrame(
            self.valuation(codes, start=start, end=end, fields=fields)
        )

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    def _get(self, path: str, params: Mapping[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        query = _clean_params(params)
        attempts = _MAX_RETRIES + 1
        self.last_meta = {}

        for attempt in range(attempts):
            response = _http_get(url, query, self._headers, self.timeout)
            status = int(response.status)
            payload = _decode_json(response.body)
            payload_dict = _payload_dict(payload)

            if status in (401, 403):
                code, message = _extract_error(status, payload, response.body)
                raise BpAuthError(
                    status, code, message, payload=payload_dict
                )

            if status == 429:
                retry_after = _parse_retry_after(
                    _header_value(response.headers, "Retry-After")
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(
                        retry_after
                        if retry_after is not None
                        else _backoff(attempt)
                    )
                    continue
                code, message = _extract_error(status, payload, response.body)
                raise BpRateLimitError(
                    status,
                    code,
                    message,
                    retry_after=retry_after,
                    payload=payload_dict,
                )

            if status >= 500:
                if attempt < _MAX_RETRIES:
                    retry_after = _parse_retry_after(
                        _header_value(response.headers, "Retry-After")
                    )
                    time.sleep(
                        retry_after
                        if retry_after is not None
                        else _backoff(attempt)
                    )
                    continue
                code, message = _extract_error(status, payload, response.body)
                raise BpApiError(
                    status, code, message, payload=payload_dict
                )

            if status >= 400:
                code, message = _extract_error(status, payload, response.body)
                raise BpApiError(
                    status, code, message, payload=payload_dict
                )

            if not 200 <= status < 300:
                code, message = _extract_error(status, payload, response.body)
                raise BpApiError(
                    status, code, message, payload=payload_dict
                )

            return self._parse_success(status, payload, response.body)

        raise AssertionError("unreachable")  # pragma: no cover

    def _parse_success(
        self, status: int, payload: Any, body: bytes
    ) -> Any:
        if payload is None:
            if not body:
                self.last_meta = {}
                return None
            raise BpApiError(
                status,
                "invalid_response",
                "响应不是合法 JSON",
                payload={},
            )

        if isinstance(payload, dict):
            error = payload.get("error")
            if error:
                code, message = _extract_error(status, payload, body)
                raise BpApiError(
                    status, code, message, payload=dict(payload)
                )

            meta = payload.get("meta")
            self.last_meta = dict(meta) if isinstance(meta, dict) else {}
            if "data" in payload:
                return payload["data"]
            return payload

        self.last_meta = {}
        return payload

    @staticmethod
    def _expect_list(data: Any) -> list[dict[str, Any]]:
        if data is None:
            return []
        if isinstance(data, list):
            return data
        raise TypeError("API 响应中的 data 不是数组")

    @staticmethod
    def _expect_dict(data: Any) -> dict[str, Any]:
        if isinstance(data, dict):
            return data
        raise TypeError("API 响应中的 data 不是对象")
