"""旧行情链 dataset runner（P2）：复用 bp_ingest 适配器/降级链，写入 bp_index_quote_daily。

范围：bp_index_config 中全部启用配置（指数/商品/债券/汇率/旧 ETF/个股），即既有
bp_quote_clean 与组合/回测依赖的旧行情链。策略：
- 复用 bp_ingest.ingest.run（多源降级链、交易日护栏、幂等 upsert、last_sync/last_error 维护）；
- 速率由本 runner 覆盖为快速档（app.request_interval≈0），并发 chunk 由 orchestrator 调度；
- 首轮直连；失败标的在配置 relay 时二次经 relay（EM push2his 封禁时的唯一通路）；
- 写回后从表里读回当日 Bar，交给统一质量门/覆盖率/背压体系。
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from typing import Any, Callable, Sequence

from bp_etl.adapters.base import Bar
from bp_etl.channels import ChannelManager
from bp_etl.registry import REGISTRY, DatasetSpec

logger = logging.getLogger(__name__)

CHUNK_SIZE = 50


def parse_configs(rows: Sequence[Sequence[Any]]) -> list[dict[str, Any]]:
    """rows: (symbol, source, adjust_modes, adjust) → 配置字典列表。"""
    out: list[dict[str, Any]] = []
    for symbol, source, adjust_modes, primary_adjust in rows:
        modes = tuple(adjust_modes or ())
        if not modes:
            modes = (primary_adjust or "bfq",)
        out.append({"symbol": symbol, "source": source, "adjust_modes": modes})
    return out


def filter_configs(configs: Sequence[dict[str, Any]], adjust: str) -> list[dict[str, Any]]:
    return [cfg for cfg in configs if adjust in cfg["adjust_modes"]]


class LegacyIndexRunner:
    spec: DatasetSpec = REGISTRY["legacy_index"]

    def __init__(
        self,
        *,
        relay_proxy: str | None = None,
        chunk_size: int = CHUNK_SIZE,
        conn_factory: Callable[[], Any] | None = None,
        ingest: Any | None = None,
        app_config: Any | None = None,
    ) -> None:
        self._relay = relay_proxy
        self._chunk = max(1, chunk_size)
        self._conn_factory = conn_factory
        self._ingest = ingest
        self._app = app_config

    # -- 惰性依赖 -----------------------------------------------------
    def _load(self) -> tuple[Any, Any]:
        if self._ingest is None:
            from bp_ingest import ingest  # noqa: PLC0415

            self._ingest = ingest
        if self._app is None:
            from bp_ingest.config import load_config  # noqa: PLC0415

            base = load_config()
            # 旧链目标已有历史，增量窗口由库内 last_date 决定；把进程内睡眠降到最低，
            # 实际限速由 orchestrator 的通道/并发控制。
            max_retries = int(os.getenv("BP_ETL_LEGACY_MAX_RETRIES", "2") or "2")
            self._app = replace(
                base, request_interval=0.0, request_jitter=0.0, max_retries=max_retries
            )
        return self._ingest, self._app

    @contextmanager
    def _connection(self):
        """统一连接上下文：注入的 conn_factory 直接 yield；生产经 bp_ingest 连接上下文。"""
        if self._conn_factory is not None:
            conn = self._conn_factory()
            try:
                yield conn
            finally:
                close = getattr(conn, "close", None)
                if callable(close):
                    close()
            return
        from bp_ingest.config import load_config  # noqa: PLC0415
        from bp_ingest.db import connect  # noqa: PLC0415

        with connect(load_config().db) as conn:
            yield conn

    def _ensure_session(self) -> None:
        try:
            from bp_ingest.http_session import install_hardened_session  # noqa: PLC0415

            install_hardened_session()
        except Exception:  # noqa: BLE001 - 硬化失败不阻断（降级为普通 requests）
            logger.warning("legacy runner: hardened session 安装失败", exc_info=True)

    # -- DatasetRunner 协议 -------------------------------------------
    def universe(self, conn: Any) -> list[str]:
        symbols_filter = [
            item.strip()
            for item in (os.getenv("BP_ETL_LEGACY_SYMBOLS") or "").split(",")
            if item.strip()
        ]
        # 生产默认 scope=selectable：只维护 builder/回测实际可用的资产 + 汇率源，
        # 避免为不可达的自定义指数（EM 封禁、无降级源）每夜空转 30-60 分钟。
        scope = (os.getenv("BP_ETL_LEGACY_SCOPE") or "all").strip().lower()
        base = "SELECT DISTINCT symbol FROM bp_index_config WHERE is_deleted=0"
        params: list = []
        if scope == "selectable":
            base += " AND (is_selectable = TRUE OR source = 'fx_sina')"
        if symbols_filter:
            base += " AND symbol = ANY(%s)"
            params.append(symbols_filter)
        base += " ORDER BY symbol"
        with conn.cursor() as cur:
            cur.execute(base, params)
            return [row[0] for row in cur.fetchall()]

    def fetch(
        self,
        adjust: str,
        codes: Sequence[str],
        trade_date: date,
        channels: ChannelManager,
    ) -> list[Bar]:
        if adjust not in ("bfq", "hfq"):
            raise ValueError(f"legacy 不支持 adjust: {adjust}")
        ingest, app = self._load()
        if self._conn_factory is None:
            self._ensure_session()  # 生产路径安装硬化会话；测试注入连接时跳过
        with self._connection() as conn:
            configs = self._query_configs(conn, codes)
            units = filter_configs(configs, adjust)
            symbols = list(dict.fromkeys(cfg["symbol"] for cfg in units))
            failed = self._run_chunks(ingest, app, symbols)
            if failed and self._relay:
                failed = self._run_relay_pass(ingest, app, failed)
            return self._readback(conn, symbols, adjust, trade_date)

    # -- 内部步骤 -----------------------------------------------------
    def _query_configs(self, conn: Any, codes: Sequence[str]) -> list[dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT symbol, source, adjust_modes, adjust FROM bp_index_config"
                " WHERE is_deleted=0 AND symbol = ANY(%s) ORDER BY symbol, source",
                (list(codes),),
            )
            rows = cur.fetchall()
        return parse_configs(rows)

    def _run_chunks(self, ingest: Any, app: Any, symbols: Sequence[str]) -> list[str]:
        failed: list[str] = []
        for start in range(0, len(symbols), self._chunk):
            chunk = list(symbols[start:start + self._chunk])
            try:
                results = ingest.run(app, symbols=chunk, refresh_clean=False)
            except Exception:  # noqa: BLE001 - 单 chunk 失败留待 relay 二次
                logger.warning("legacy chunk 失败 start=%d", start, exc_info=True)
                failed.extend(chunk)
                continue
            failed.extend(
                item.symbol for item in results if getattr(item, "status", "") == "error"
            )
        return failed

    def _run_relay_pass(self, ingest: Any, app: Any, symbols: Sequence[str]) -> list[str]:
        """EM 直连被封时经 relay 二次抓取（进程内串行，避免全局 env 串扰）。"""
        proxy = self._relay
        if not proxy:
            return list(symbols)
        previous = os.environ.get("BP_HTTP_PROXY")
        os.environ["BP_HTTP_PROXY"] = proxy
        try:
            return self._run_chunks(ingest, app, symbols)
        finally:
            if previous is None:
                os.environ.pop("BP_HTTP_PROXY", None)
            else:
                os.environ["BP_HTTP_PROXY"] = previous

    def _readback(
        self, conn: Any, symbols: Sequence[str], adjust: str, trade_date: date
    ) -> list[Bar]:
        if not symbols:
            return []
        with conn.cursor() as cur:
            cur.execute(
                "SELECT symbol, source, trade_date, open, high, low, close, volume, amount, pct_change"
                " FROM bp_index_quote_daily"
                " WHERE symbol = ANY(%s) AND adjust = %s AND trade_date = %s",
                (list(symbols), adjust, trade_date),
            )
            rows = cur.fetchall()
        bars: list[Bar] = []
        for symbol, source, day, open_, high, low, close, volume, amount, pct in rows:
            if close is None:
                continue
            bars.append(
                Bar(
                    symbol=symbol,
                    trade_date=day,
                    open=_f(open_),
                    high=_f(high),
                    low=_f(low),
                    close=float(close),
                    volume=int(volume) if volume is not None else None,
                    amount=_f(amount),
                    pct_change=_f(pct),
                    source=source,
                    adjust=adjust,
                )
            )
        return bars


def _f(value: Any) -> float | None:
    return None if value is None else float(value)