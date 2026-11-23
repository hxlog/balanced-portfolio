"""出口通道管理：direct / relay_sg / relay_prologue + 源级熔断。

每个 SourceSpec 对应一个 Channel：
- 通道（直连 / SG relay / prologue relay）决定代理与指纹；
- 每源独立全局限速（令牌桶）与失败熔断（连续 3 次连接级失败 → 冷却 5 分钟）；
- 指标按源聚合，供 bp_etl_source_health 落库与管理页展示。
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from bp_etl.config import EtlConfig
from bp_etl.rate_limit import TokenBucket
from bp_etl.registry import SOURCES, SourceSpec

logger = logging.getLogger(__name__)

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_REFERER_BY_SOURCE = {
    "tencent_qt": "https://gu.qq.com/",
    "tencent_kline": "https://gu.qq.com/",
    "tencent_hk_kline": "https://gu.qq.com/",
    "sina_kline": "https://finance.sina.com.cn/",
    "sina_hk_kline": "https://finance.sina.com.cn/",
    "sina_etf_kline": "https://finance.sina.com.cn/",
    "em_kline": "https://quote.eastmoney.com/",
    "em_rankhandler": "https://fund.eastmoney.com/data/fundranking.html",
    "em_lsjz": "https://fundf10.eastmoney.com/",
}

FAILURE_THRESHOLD = 3
COOLDOWN_SECONDS = 300.0


class ChannelBanned(RuntimeError):
    """通道处于熔断冷却期；调用方应换源或等待。"""


@dataclass
class SourceMetrics:
    attempts: int = 0
    ok: int = 0
    failed: int = 0
    banned_count: int = 0
    latencies_ms: deque[float] = field(default_factory=lambda: deque(maxlen=500))
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, *, ok: bool, latency_s: float, banned: bool = False) -> None:
        with self._lock:
            self.attempts += 1
            if banned:
                # 熔断拒绝不是"源失败"，单独计数：ok/failed 仍反映真实网络结果
                self.banned_count += 1
                return
            if ok:
                self.ok += 1
            else:
                self.failed += 1
            self.latencies_ms.append(latency_s * 1000.0)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            latencies = sorted(self.latencies_ms)
            p95 = latencies[int(len(latencies) * 0.95) - 1] if latencies else None
            avg = round(sum(latencies) / len(latencies), 1) if latencies else None
            return {
                "attempts": self.attempts,
                "ok": self.ok,
                "failed": self.failed,
                "banned_count": self.banned_count,
                "avg_latency_ms": avg,
                "p95_latency_ms": round(p95, 1) if p95 is not None else None,
            }


class Channel:
    """单源通道：限速 + 熔断 + 指标。transport 可注入（测试）。"""

    def __init__(
        self,
        source: str,
        *,
        channel_kind: str,
        proxy: str | None,
        rate_per_sec: float,
        timeout: float = 20.0,
        max_failures: int = FAILURE_THRESHOLD,
        cooldown: float = COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        transport: Any | None = None,
    ) -> None:
        self.source = source
        self.channel_kind = channel_kind
        self.proxy = proxy
        self.timeout = timeout
        self.metrics = SourceMetrics()
        self._max_failures = max_failures
        self._cooldown = cooldown
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._failures = 0
        self._banned_until = 0.0
        self._bucket = TokenBucket(rate_per_sec, clock=clock, sleep=sleep)
        self._transport = transport if transport is not None else self._build_transport(proxy)

    # -- transport -----------------------------------------------------
    def _build_transport(self, proxy: str | None) -> Any:
        try:
            from curl_cffi import requests as curl_requests  # type: ignore

            session = curl_requests.Session(
                impersonate="chrome120",
                proxies={"http": proxy, "https": proxy} if proxy else None,
            )
        except Exception:  # pragma: no cover - curl_cffi 缺失时降级 requests
            import requests

            session = requests.Session()
            session.trust_env = False
            if proxy:
                session.proxies = {"http": proxy, "https": proxy}
        session.headers.update(_DEFAULT_HEADERS)
        referer = _REFERER_BY_SOURCE.get(self.source)
        if referer:
            session.headers.setdefault("Referer", referer)
        return session

    # -- circuit breaker ----------------------------------------------
    def _check_ban(self) -> None:
        now = self._clock()
        with self._lock:
            if now < self._banned_until:
                self.metrics.record(ok=False, latency_s=0.0, banned=True)
                raise ChannelBanned(
                    f"source={self.source} channel={self.channel_kind} "
                    f"熔断中（{self._banned_until - now:.0f}s）"
                )
            if self._banned_until and now >= self._banned_until:
                # 半开：冷却结束后允许探测，失败会再次熔断
                self._failures = 0
                self._banned_until = 0.0

    def _fail(self, latency_s: float, reason: str) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._max_failures:
                self._banned_until = self._clock() + self._cooldown
                logger.warning(
                    "[%s] %s 连续失败 %d 次，熔断 %.0fs: %s",
                    self.channel_kind, self.source, self._failures, self._cooldown, reason,
                )
        self.metrics.record(ok=False, latency_s=latency_s)

    # -- request ------------------------------------------------------
    def throttle(self) -> float:
        """仅按源全局限速获取令牌（供 akshare 等自建 HTTP 的适配器复用限速）。"""
        self._check_ban()
        return self._bucket.acquire()

    def get(self, url: str, *, timeout: float | None = None, **kw: Any) -> Any:
        self._check_ban()
        self._bucket.acquire()
        started = self._clock()
        try:
            response = self._transport.get(url, timeout=timeout or self.timeout, **kw)
        except Exception as exc:  # noqa: BLE001 - 连接级失败统一熔断计数
            self._fail(self._clock() - started, type(exc).__name__)
            raise
        latency = self._clock() - started
        status = int(getattr(response, "status_code", 200) or 200)
        if status == 429 or status >= 500:
            self._fail(latency, f"http {status}")
            return response
        with self._lock:
            self._failures = 0
        self.metrics.record(ok=True, latency_s=latency)
        return response


class ChannelManager:
    """按源构建 Channel；relay 未配置时降级 direct 并告警。"""

    _CHANNEL_BY_KIND = {
        "direct": None,
        "relay_sg": "relay_sg",
        "relay_prologue": "relay_prologue",
    }

    def __init__(
        self,
        config: EtlConfig,
        sources: Mapping[str, SourceSpec] | None = None,
        *,
        rl_source: Any | None = None,
    ) -> None:
        self._config = config
        self._sources = dict(sources or SOURCES)
        self._channels: dict[str, Channel] = {}
        self._proxy_for = {
            "direct": None,
            "relay_sg": config.relay_sg,
            "relay_prologue": config.relay_prologue,
        }

    def _proxy(self, channel_kind: str) -> tuple[str | None, str]:
        proxy = self._proxy_for.get(channel_kind)
        if channel_kind != "direct" and not proxy:
            logger.warning("relay 未配置（%s），降级直连", channel_kind)
            return None, "direct"
        return proxy, channel_kind if proxy else "direct"

    def get(self, source: str) -> Channel:
        channel = self._channels.get(source)
        if channel is not None:
            return channel
        spec = self._sources.get(source)
        if spec is None:
            raise KeyError(f"未注册源: {source}")
        proxy, kind = self._proxy(spec.channel)
        channel = Channel(
            spec.name,
            channel_kind=kind,
            proxy=proxy,
            rate_per_sec=spec.rate_per_sec,
        )
        self._channels[source] = channel
        return channel

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            name: {"channel": ch.channel_kind, **ch.metrics.snapshot()}
            for name, ch in self._channels.items()
        }
