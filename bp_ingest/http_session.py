"""全局 HTTP 会话硬化: 反爬加固(Chrome TLS 指纹 + 持久 cookie + 页面预热)。

【逆向结论】东方财富 `push2his.eastmoney.com` 掐断连接(`RemoteDisconnected`)基于
**TLS 指纹(JA3)**——Python `requests` 与 `curl` 均被掐(http:000), 真实浏览器可访问。
单纯改 header/Referer 无效(TLS 仍是 Python 指纹)。`curl_cffi` `impersonate="chrome120"`
复刻 Chrome 的 TLS(JA3)/HTTP-2/默认头, 是绕过 JA3 校验的关键(不引入真实浏览器的最强指纹)。

【为何之前无效】akshare 每次 `requests.get` 新建 Session → cookie 不持久, 预热 cookie 无法
继承到 API 调用。本模块用**全局持久会话** + **预热主页种 cookie** + **monkeypatch
`requests.get/post` 路由到全局会话**, 让所有数据源继承 Chrome 指纹 + 持久 cookie。

【仍被掐时】若 curl_cffi + 预热 cookie 仍 http:000 → IP 信誉限速 → 走
`fetch_with_fallback` 的 em→sina 源降级(ETF 不降级); 本机 IP 直连, 不走代理。
HTTP 429/5xx 走长退避(30-60s × 次数, 匹配 EM 5min 封禁窗); 间隔/抖动由
`BP_REQUEST_INTERVAL`/`BP_REQUEST_JITTER` 控制; 真实浏览器 cookie 按 host 精准注入
(`BP_EM_COOKIE`→东财, `BP_SINA_COOKIE`→新浪; 比无 JS 预热更有效); 限流统计按 host 计数, 每 5min/退出时打印。

调用 `install_hardened_session()` 幂等; 在进程启动处调用一次(CLI 与 API)。
"""

from __future__ import annotations

import atexit
import collections
import logging
import os
import random
import threading
import time
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover
    from requests.packages.urllib3.util.retry import Retry  # type: ignore

try:
    import curl_cffi.requests as _cc_requests  # type: ignore
    _HAS_CURL_CFFI = True
except Exception:  # pragma: no cover
    _HAS_CURL_CFFI = False

logger = logging.getLogger(__name__)

# 真实浏览器 UA 池(不同 OS/浏览器/版本); 每进程随机选一
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
]

# 各源 API 主机对应的浏览器来源页(Referer)
_REFERER_DEFAULT = "https://quote.eastmoney.com/"
_REFERER_BY_HOST = {
    "push2his.eastmoney.com": "https://quote.eastmoney.com/",
    "push2.eastmoney.com": "https://quote.eastmoney.com/",
    "82.push2.eastmoney.com": "https://quote.eastmoney.com/",
    "36.push2.eastmoney.com": "https://quote.eastmoney.com/",
    "datacenter-web.eastmoney.com": "https://data.eastmoney.com/",
    "data.eastmoney.com": "https://data.eastmoney.com/",
    "fundf10.eastmoney.com": "https://fundf10.eastmoney.com/",
    "hq.sinajs.cn": "https://finance.sina.com.cn/",
    "money.finance.sina.com.cn": "https://finance.sina.com.cn/",
    "stock.finance.sina.com.cn": "https://finance.sina.com.cn/",
    "qt.gtimg.cn": "https://gu.qq.com/",
    "web.ifzq.gtimg.cn": "https://gu.qq.com/",
}

# 预热页(模拟浏览器渲染主页, 种反爬 cookie 到全局 jar)
_WARMUP_PAGES = [
    "https://quote.eastmoney.com/",
    "https://data.eastmoney.com/",
    "https://finance.sina.com.cn/",
    "https://gu.qq.com/",
]

_IMPERSONATE = "chrome120"  # curl_cffi 复刻的 Chrome 指纹

# host 后缀 → 对应 cookie 环境变量; 按 host 精准注入, 避免东财 cookie 发到新浪(反之亦然)
_COOKIE_ENV_BY_HOST: list[tuple[str, str]] = [
    ("eastmoney.com", "BP_EM_COOKIE"),
    ("sinajs.cn", "BP_SINA_COOKIE"),
    ("sina.com.cn", "BP_SINA_COOKIE"),
    ("sina.com", "BP_SINA_COOKIE"),
]


def _cookie_for_host(host: str) -> str:
    """按请求 host 取对应数据源的 cookie 串(从环境变量); 无匹配/未设置则返回空串。"""
    host = (host or "").lower()
    for suffix, env in _COOKIE_ENV_BY_HOST:
        if host == suffix or host.endswith("." + suffix):
            return os.getenv(env, "").strip()
    return ""


def _browser_headers() -> dict[str, str]:
    """贴近真实浏览器 XHR 的请求头(curl_cffi 已自带默认头, 这里补强/统一)。

    Cookie 不在此全局设置——按 host 精准注入(见 _cookie_for_host / _apply_cookie),
    否则东财 cookie 会被发到新浪等其它源。
    """
    ua = random.choice(_UA_POOL)
    h: dict[str, str] = {
        "User-Agent": ua,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": _REFERER_DEFAULT,
        "Sec-Fetch-Site": "same-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    if "Chrome" in ua:
        h["sec-ch-ua"] = '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"'
        h["sec-ch-ua-mobile"] = "?0"
        h["sec-ch-ua-platform"] = '"Windows"'
    return h


def _build_retry_adapter() -> HTTPAdapter:
    return HTTPAdapter(
        max_retries=Retry(
            total=4, connect=3, read=3, backoff_factor=2.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET", "HEAD", "OPTIONS", "POST"]),
            respect_retry_after_header=True, raise_on_status=False,
        )
    )


class _HardenedSession:
    """全局持久会话: curl_cffi(Chrome TLS) 优先, 回退 requests。
    持久 cookie jar 跨请求继承(预热种下的 cookie 自动带到 API 调用)。
    """

    def __init__(self) -> None:
        if _HAS_CURL_CFFI:
            self._sess = _cc_requests.Session(impersonate=_IMPERSONATE)
            self._engine = "curl_cffi:" + _IMPERSONATE
        else:
            self._sess = requests.Session()
            self._sess.mount("https://", _build_retry_adapter())
            self._sess.mount("http://", _build_retry_adapter())
            self._engine = "requests"
        # 统一浏览器头(curl_cffi 已有默认, 这里覆盖关键项); Cookie 不在此设, 按 host 精准注入
        try:
            self._sess.headers.update(_browser_headers())
        except Exception:  # noqa: BLE001
            pass
        # 限流可观测性: 按 host 统计
        self._stats: dict[str, dict[str, int]] = collections.defaultdict(
            lambda: {"total": 0, "conn_err": 0, "http_429": 0, "http_5xx": 0}
        )
        self._stats_lock = threading.Lock()

    def _apply_referer(self, url: str, kw: dict) -> None:
        try:
            host = (urlsplit(url).hostname or "").lower()
            ref = _REFERER_BY_HOST.get(host) or _REFERER_DEFAULT
            headers = kw.setdefault("headers", {})
            if not any(k.lower() == "referer" for k in headers):
                headers["Referer"] = ref
        except Exception:  # noqa: BLE001
            pass

    def _apply_cookie(self, url: str, kw: dict) -> None:
        """按 url host 注入对应数据源 cookie(仅当调用方未显式设置 Cookie 头)。"""
        try:
            host = (urlsplit(url).hostname or "").lower()
            cookie = _cookie_for_host(host)
            if not cookie:
                return
            headers = kw.setdefault("headers", {})
            if not any(k.lower() == "cookie" for k in headers):
                headers["Cookie"] = cookie
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _is_transient(exc: Exception) -> bool:
        """连接级错误(RemoteDisconnected/超时/连接重置)才重试; 4xx/5xx 不在此重试。"""
        name = type(exc).__name__
        return any(
            s in name
            for s in ("ConnectionError", "RemoteDisconnected", "Timeout", "ConnectionReset", "Chunked")
        )

    def _bump(self, host: str, key: str) -> None:
        try:
            with self._stats_lock:
                self._stats[host][key] += 1
        except Exception:  # noqa: BLE001
            pass

    def _request_with_retry(self, method: str, url: str, **kw):
        """统一重试: 连接级异常短退避; HTTP 429/503 长退避(匹配 EM 5min 封禁窗)。

        - 连接级(RemoteDisconnected/Timeout): random.uniform(0.8,2.0)*(i+1) 秒
        - HTTP 429(限流): random.uniform(30,60)*(i+1) 秒
        - HTTP 5xx(服务端): random.uniform(5,15)*(i+1) 秒
        attempts 由 BP_HTTP_RETRY(默认 4) 控制。
        """
        attempts = int(os.getenv("BP_HTTP_RETRY", "4") or "4")
        host = (urlsplit(url).hostname or "").lower()
        self._bump(host, "total")
        resp = None
        for i in range(attempts):
            try:
                resp = getattr(self._sess, method)(url, **kw)
            except Exception as exc:  # noqa: BLE001
                self._bump(host, "conn_err")
                if not self._is_transient(exc) or i == attempts - 1:
                    raise
                time.sleep(random.uniform(0.8, 2.0) * (i + 1))
                continue
            # HTTP 限流/服务端错误重试(curl_cffi 路径无 urllib3 Retry, 需手动)
            sc = getattr(resp, "status_code", 200) or 200
            if sc == 429:
                self._bump(host, "http_429")
                if i < attempts - 1:
                    time.sleep(random.uniform(30, 60) * (i + 1))
                    continue
            elif sc in (500, 502, 503, 504):
                self._bump(host, "http_5xx")
                if i < attempts - 1:
                    time.sleep(random.uniform(5, 15) * (i + 1))
                    continue
            return resp
        return resp

    def get(self, url, **kw):
        self._apply_referer(url, kw)
        self._apply_cookie(url, kw)
        return self._request_with_retry("get", url, **kw)

    def post(self, url, **kw):
        self._apply_referer(url, kw)
        self._apply_cookie(url, kw)
        return self._request_with_retry("post", url, **kw)

    @property
    def cookies(self):
        return self._sess.cookies

    @property
    def engine(self) -> str:
        return self._engine

    @property
    def stats(self) -> dict[str, dict[str, int]]:
        with self._stats_lock:
            return dict(self._stats)


_GLOBAL: _HardenedSession | None = None
_installed = False
_orig_get = None
_orig_post = None
_orig_session_init = None
_orig_session_request = None
_warmup_thread: threading.Thread | None = None


def _warmup() -> None:
    """对各源主页 GET 一次, 把反爬 cookie 种入全局 jar(模拟浏览器先渲染页面再调 API)。"""
    if _GLOBAL is None:
        return
    for page in _WARMUP_PAGES:
        try:
            _GLOBAL.get(page, timeout=10)
            logger.debug("预热 cookie: %s", page)
        except Exception as exc:  # noqa: BLE001 - 预热失败不阻断
            logger.debug("预热 %s 失败(忽略): %s", page, exc)


def _warmup_loop(stop: threading.Event) -> None:
    """后台守护线程: 每 15 分钟重刷 cookie(防过期); BP_COOKIE_REFRESH_MIN 可调。"""
    interval = float(os.getenv("BP_COOKIE_REFRESH_MIN", "15") or "15") * 60
    while not stop.wait(interval):
        _warmup()


def _log_stats() -> None:
    """打印限流统计摘要(按 host: total/conn_err/http_429/http_5xx), 助运维调间隔。"""
    if _GLOBAL is None:
        return
    stats = _GLOBAL.stats
    if not stats:
        return
    parts = []
    for host, s in sorted(stats.items()):
        parts.append(f"{host}: total={s['total']} conn_err={s['conn_err']} http_429={s['http_429']} http_5xx={s['http_5xx']}")
    logger.info("[anti-crawler] %s", " | ".join(parts))


def _stats_loop(stop: threading.Event) -> None:
    """每 5 分钟打印一次限流统计。"""
    while not stop.wait(300):
        _log_stats()


def install_hardened_session() -> None:
    """全局硬化 HTTP 会话(幂等): curl_cffi Chrome 指纹 + 持久 cookie + 预热 + 刷 cookie。"""
    global _GLOBAL, _installed, _orig_get, _orig_post, _orig_session_init, _orig_session_request, _warmup_thread
    if _installed:
        return

    _GLOBAL = _HardenedSession()
    _warmup()  # 启动即种 cookie

    # 后台刷 cookie 线程
    stop = threading.Event()
    _warmup_thread = threading.Thread(target=_warmup_loop, args=(stop,), daemon=True, name="bp-cookie-refresh")
    _warmup_thread.start()

    # 限流统计: 每 5min 打印 + 进程退出时打印
    _stats_thread = threading.Thread(target=_stats_loop, args=(stop,), daemon=True, name="bp-anti-crawler-stats")
    _stats_thread.start()
    atexit.register(_log_stats)

    # monkeypatch 模块级 requests.get/post → 路由到全局会话(akshare 用 requests.get)
    _orig_get = requests.get
    _orig_post = requests.post
    requests.get = lambda url, *a, **kw: _GLOBAL.get(url, **kw)  # type: ignore[assignment]
    requests.post = lambda url, *a, **kw: _GLOBAL.post(url, **kw)  # type: ignore[assignment]

    # 兜底: 非 akshare 的 requests.Session() 用户也注入浏览器头 + Retry + Referer + 按 host cookie
    _orig_session_init = requests.sessions.Session.__init__
    _orig_session_request = requests.sessions.Session.request

    def _patched_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        _orig_session_init(self, *args, **kwargs)
        try:
            self.headers.update(_browser_headers())
            adapter = _build_retry_adapter()
            self.mount("https://", adapter)
            self.mount("http://", adapter)
            # 本机 IP 直连, 不读环境代理变量(HTTP_PROXY/HTTPS_PROXY 等)
            self.trust_env = False
        except Exception:  # noqa: BLE001
            pass

    def _patched_request(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
        try:
            host = (urlsplit(url).hostname or "").lower()
            headers = kwargs.setdefault("headers", {})
            ref = _REFERER_BY_HOST.get(host) or _REFERER_DEFAULT
            if not any(k.lower() == "referer" for k in headers):
                headers["Referer"] = ref
            cookie = _cookie_for_host(host)
            if cookie and not any(k.lower() == "cookie" for k in headers):
                headers["Cookie"] = cookie
        except Exception:  # noqa: BLE001
            pass
        return _orig_session_request(self, method, url, **kwargs)

    requests.sessions.Session.__init__ = _patched_init  # type: ignore[assignment]
    requests.sessions.Session.request = _patched_request  # type: ignore[assignment]
    _installed = True
    em_on = bool(os.getenv("BP_EM_COOKIE", "").strip())
    sina_on = bool(os.getenv("BP_SINA_COOKIE", "").strip())
    cookie_parts = [name for name, on in (("BP_EM_COOKIE", em_on), ("BP_SINA_COOKIE", sina_on)) if on]
    cookie_note = (" + 按 host 注入 " + " ".join(cookie_parts)) if cookie_parts else " (无手动 cookie)"
    logger.info("HTTP 会话已硬化: %s + 持久 cookie + 预热%s (本机 IP 直连, 无代理)", _GLOBAL.engine, cookie_note)
