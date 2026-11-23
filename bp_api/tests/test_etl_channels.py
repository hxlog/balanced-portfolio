"""通道/限速/熔断/deadline 测试（T3）。"""
from __future__ import annotations

import pytest

from bp_etl.channels import Channel, ChannelBanned, ChannelManager
from bp_etl.config import EtlConfig
from bp_etl.rate_limit import TokenBucket
from bp_etl.retry import DeadlineExceeded, Deadline, with_deadline


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "ok") -> None:
        self.status_code = status_code
        self.text = text


class FakeTransport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def get(self, url: str, **kw: object) -> FakeResponse:
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item  # type: ignore[return-value]


def test_token_bucket_waits_at_configured_rate() -> None:
    fc = FakeClock()
    bucket = TokenBucket(10.0, clock=fc.clock, sleep=fc.sleep)
    assert bucket.acquire() == 0.0
    first = bucket.acquire()
    second = bucket.acquire()
    assert first > 0 and second > 0
    assert sum(fc.sleeps) == pytest.approx(0.2, abs=1e-6)


def test_channel_opens_circuit_after_consecutive_failures() -> None:
    fc = FakeClock()
    transport = FakeTransport([ConnectionError("reset")] * 3 + [FakeResponse()])
    channel = Channel(
        "sina_kline", channel_kind="direct", proxy=None, rate_per_sec=1000.0,
        clock=fc.clock, sleep=fc.sleep, transport=transport,
    )
    for _ in range(3):
        with pytest.raises(ConnectionError):
            channel.get("https://example.com/x")
    with pytest.raises(ChannelBanned):
        channel.get("https://example.com/x")
    # 冷却结束后半开探测通过
    fc.now += 301
    resp = channel.get("https://example.com/x")
    assert resp.status_code == 200
    snap = channel.metrics.snapshot()
    assert snap["failed"] == 3
    assert snap["banned_count"] == 1  # 熔断拒绝单独计数，不算源失败
    assert snap["ok"] == 1


def test_channel_metrics_latency_recorded() -> None:
    fc = FakeClock()
    transport = FakeTransport([FakeResponse()])
    channel = Channel(
        "tencent_qt", channel_kind="direct", proxy=None, rate_per_sec=1000.0,
        clock=fc.clock, sleep=fc.sleep, transport=transport,
    )
    channel.get("https://example.com/x")
    snap = channel.metrics.snapshot()
    assert snap["attempts"] == 1 and snap["ok"] == 1
    assert snap["avg_latency_ms"] is not None


def test_deadline_exceeded() -> None:
    fc = FakeClock()
    deadline = Deadline(1.0, clock=fc.clock)
    deadline.check()
    fc.now += 2.0
    with pytest.raises(DeadlineExceeded):
        deadline.check()
    with pytest.raises(DeadlineExceeded):
        with_deadline(1.0, lambda: fc.sleep(2.0), clock=fc.clock)


def _config(**overrides: object) -> EtlConfig:
    base = EtlConfig(
        db=object(),  # type: ignore[arg-type]
        mode="on",
        workers=4,
        relay_sg=None,
        relay_prologue=None,
        log_level="INFO",
        rebuild_window=(__import__("datetime").time(1, 0), __import__("datetime").time(5, 0)),
    )
    return base.__class__(**{**base.__dict__, **overrides})  # type: ignore[arg-type]


def test_channel_manager_falls_back_to_direct_without_relay() -> None:
    manager = ChannelManager(_config())
    channel = manager.get("em_kline")  # 注册表要求 relay_sg
    assert channel.channel_kind == "direct"
    assert channel.proxy is None


def test_channel_manager_uses_configured_relay() -> None:
    manager = ChannelManager(_config(relay_sg="http://127.0.0.1:10809"))
    channel = manager.get("em_kline")
    assert channel.channel_kind == "relay_sg"
    assert channel.proxy == "http://127.0.0.1:10809"
    assert manager.snapshot().get("em_kline", {}).get("channel") == "relay_sg"
