"""数据集/源/通道注册表。

约束（设计 §3/§6）：
- 只允许 bfq/hfq 两种 K 线口径；qfq 禁止出现（76 号迁移已停用）。
- 每个 (dataset, adjust) 必须声明唯一锚定源（anchor），回退链只能用于补缺/校验。
- 每个源必须声明出口通道与限速画像；EM push2his 只允许 relay 通道。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time, timedelta
from typing import Mapping

CHANNELS = ("direct", "relay_sg", "relay_prologue")
VALUE_KINDS = ("bar", "nav")
ALLOWED_ADJUST = ("bfq", "hfq")
CLOSE_CONFIRM_KINDS = ("A", "HK", "FUND")
COVERAGE_KINDS = ("stock", "etf", "fund", "index")


class RegistryError(ValueError):
    """注册表配置非法。"""


@dataclass(frozen=True)
class SourceSpec:
    """一个行情源的静态能力声明。"""

    name: str
    adapter: str  # `bp_etl.adapters.<模块>.<函数>` 的短标识
    channel: str  # direct / relay_sg / relay_prologue
    adjust_support: tuple[str, ...]  # 支持的口径（bfq/hfq）或 ("nav",)
    rate_per_sec: float  # 每源全局请求上限（保守）
    concurrency: int
    batch: int = 1
    dataset_kinds: tuple[str, ...] = ()  # 适用的 dataset 名（空=未限定）


@dataclass(frozen=True)
class DatasetSpec:
    """一个数据集的完整 ETL 契约。"""

    name: str
    table: str
    key_column: str
    value_kind: str  # bar / nav
    adjust_modes: tuple[str, ...]  # bar: ('bfq','hfq') 子集；nav: ()
    anchor: Mapping[str, str]  # adjust（或 'nav'）→ 锚定源名
    fallback: Mapping[str, tuple[str, ...]]  # adjust/nav → 回退源名元组
    universe: str  # universe provider 短标识（由 datasets 解析）
    coverage_kind: str  # bp_asset_coverage.kind
    close_confirm: str  # A / HK / FUND
    schedule_start: Mapping[str, time]  # adjust/nav → 首波开始
    target_time: Mapping[str, time]  # adjust/nav → 目标就绪（仅升级告警，不停止）
    escalate_after: timedelta  # 超过目标多久转黄色告警
    coverage_min: float  # 追平阈值（0~1）
    max_workers: int = 4


def _keys(value_kind: str, adjust_modes: tuple[str, ...]) -> tuple[str, ...]:
    return ("nav",) if value_kind == "nav" else tuple(adjust_modes)


def validate_registry(
    registry: Mapping[str, DatasetSpec],
    sources: Mapping[str, SourceSpec],
) -> None:
    """校验注册表完整性；任何问题抛 `RegistryError`（启动即失败，避免带病运行）。"""
    errors: list[str] = []
    if not registry:
        raise RegistryError("注册表为空")
    for name, spec in registry.items():
        where = f"dataset[{name}]"
        if spec.value_kind not in VALUE_KINDS:
            errors.append(f"{where}: value_kind 非法 {spec.value_kind!r}")
            continue
        if spec.coverage_kind not in COVERAGE_KINDS:
            errors.append(f"{where}: coverage_kind 非法 {spec.coverage_kind!r}")
        if spec.close_confirm not in CLOSE_CONFIRM_KINDS:
            errors.append(f"{where}: close_confirm 非法 {spec.close_confirm!r}")
        if not (0.0 < spec.coverage_min <= 1.0):
            errors.append(f"{where}: coverage_min 必须在 (0,1]")
        if spec.value_kind == "bar":
            if not spec.adjust_modes:
                errors.append(f"{where}: bar 数据集必须声明 adjust_modes")
            if "qfq" in spec.adjust_modes:
                errors.append(f"{where}: qfq 已停用，不得出现在 adjust_modes")
            bad = [a for a in spec.adjust_modes if a not in ALLOWED_ADJUST]
            if bad:
                errors.append(f"{where}: 非法 adjust {bad}")
        elif spec.adjust_modes:
            errors.append(f"{where}: nav 数据集不得声明 adjust_modes")
        keys = _keys(spec.value_kind, spec.adjust_modes)
        for key in keys:
            anchor = spec.anchor.get(key)
            if not anchor:
                errors.append(f"{where}: {key} 缺少锚定源")
            elif anchor not in sources:
                errors.append(f"{where}: {key} 锚定源 {anchor!r} 未注册")
            else:
                src = sources[anchor]
                if spec.value_kind == "bar" and key not in src.adjust_support:
                    errors.append(f"{where}: 锚定源 {anchor!r} 不支持口径 {key}")
                if spec.value_kind == "nav" and "nav" not in src.adjust_support:
                    errors.append(f"{where}: 锚定源 {anchor!r} 不是净值源")
            for fb in spec.fallback.get(key, ()):
                if fb not in sources:
                    errors.append(f"{where}: {key} 回退源 {fb!r} 未注册")
                elif fb == anchor:
                    errors.append(f"{where}: {key} 回退源与锚定源相同 {fb!r}")
        for key in keys:
            if key not in spec.schedule_start or key not in spec.target_time:
                errors.append(f"{where}: {key} 缺少 schedule_start/target_time")
        if sources:
            for src in sources.values():
                if src.channel not in CHANNELS:
                    errors.append(f"source[{src.name}]: channel 非法 {src.channel!r}")
                if src.rate_per_sec <= 0 or src.concurrency <= 0 or src.batch <= 0:
                    errors.append(f"source[{src.name}]: rate/concurrency/batch 必须为正")
    if errors:
        raise RegistryError("注册表校验失败：\n- " + "\n- ".join(errors))


# ---------------------------------------------------------------------------
# P1 四个数据集（与既有历史基准保持一致：A股 hfq=新浪、ETF/HK hfq=腾讯、bfq=腾讯 qt）
# ---------------------------------------------------------------------------
SOURCES: dict[str, SourceSpec] = {
    "tencent_qt": SourceSpec(
        name="tencent_qt", adapter="tencent.qt_batch", channel="direct",
        adjust_support=("bfq",), rate_per_sec=8.0, concurrency=6, batch=60,
        dataset_kinds=("a_stock", "etf"),
    ),
    "tencent_kline": SourceSpec(
        name="tencent_kline", adapter="tencent.kline_a_etf", channel="direct",
        adjust_support=("bfq", "hfq"), rate_per_sec=6.0, concurrency=6,
        dataset_kinds=("a_stock", "etf"),
    ),
    "tencent_hk_kline": SourceSpec(
        name="tencent_hk_kline", adapter="tencent.kline_hk", channel="direct",
        adjust_support=("bfq", "hfq"), rate_per_sec=6.0, concurrency=6,
        dataset_kinds=("hk_stock",),
    ),
    "sina_kline": SourceSpec(
        name="sina_kline", adapter="sina.a_stock", channel="direct",
        adjust_support=("bfq", "hfq"), rate_per_sec=4.0, concurrency=4,
        dataset_kinds=("a_stock",),
    ),
    "sina_hk_kline": SourceSpec(
        name="sina_hk_kline", adapter="sina.hk_daily", channel="direct",
        adjust_support=("bfq",), rate_per_sec=4.0, concurrency=4,
        dataset_kinds=("hk_stock",),
    ),
    "sina_etf_kline": SourceSpec(
        name="sina_etf_kline", adapter="sina.etf_daily", channel="direct",
        adjust_support=("bfq",), rate_per_sec=4.0, concurrency=4,
        dataset_kinds=("etf",),
    ),
    "em_kline": SourceSpec(
        name="em_kline", adapter="eastmoney.kline", channel="relay_sg",
        adjust_support=("bfq", "hfq"), rate_per_sec=2.5, concurrency=4,
        dataset_kinds=("a_stock", "hk_stock", "etf"),
    ),
    "em_rankhandler": SourceSpec(
        name="em_rankhandler", adapter="eastmoney.fund_rank", channel="direct",
        adjust_support=("nav",), rate_per_sec=2.0, concurrency=2,
        dataset_kinds=("fund_nav",),
    ),
    "legacy_multi": SourceSpec(
        # 旧行情链（指数/商品/债券/汇率/旧 ETF/个股配置）：由 bp_ingest 适配器多源+降级链负责，
        # 本 source 仅作为 registry 锚定占位；实际行 source 由 OLD 配置源的名称写入。
        name="legacy_multi", adapter="legacy.multi", channel="direct",
        adjust_support=("bfq", "hfq"), rate_per_sec=8.0, concurrency=4,
        dataset_kinds=("legacy_index",),
    ),
    "em_lsjz": SourceSpec(
        name="em_lsjz", adapter="eastmoney.fund_lsjz", channel="direct",
        adjust_support=("nav",), rate_per_sec=12.0, concurrency=6,
        dataset_kinds=("fund_nav",),
    ),
}

_MID = time(23, 30)  # 用于 nav 的“目标就绪”；实际以管理页/SLA 校准

REGISTRY: dict[str, DatasetSpec] = {
    "a_stock": DatasetSpec(
        name="a_stock", table="bp_stock_quote_daily", key_column="symbol",
        value_kind="bar", adjust_modes=("bfq", "hfq"),
        anchor={"bfq": "tencent_qt", "hfq": "sina_kline"},
        fallback={"bfq": ("sina_kline",), "hfq": ("tencent_kline", "em_kline")},
        universe="a_stock_master", coverage_kind="stock", close_confirm="A",
        schedule_start={"bfq": time(15, 15), "hfq": time(15, 20)},
        target_time={"bfq": time(15, 30), "hfq": time(16, 30)},
        escalate_after=timedelta(hours=2), coverage_min=0.995, max_workers=6,
    ),
    "hk_stock": DatasetSpec(
        name="hk_stock", table="bp_stock_quote_daily", key_column="symbol",
        value_kind="bar", adjust_modes=("bfq", "hfq"),
        anchor={"bfq": "sina_hk_kline", "hfq": "tencent_hk_kline"},
        fallback={"bfq": ("tencent_hk_kline",), "hfq": ("em_kline",)},
        universe="hk_stock_master", coverage_kind="stock", close_confirm="HK",
        schedule_start={"bfq": time(16, 15), "hfq": time(16, 15)},
        target_time={"bfq": time(16, 30), "hfq": time(17, 30)},
        escalate_after=timedelta(hours=2), coverage_min=0.99, max_workers=6,
    ),
    "etf": DatasetSpec(
        name="etf", table="bp_etf_quote_daily", key_column="etf_code",
        value_kind="bar", adjust_modes=("bfq", "hfq"),
        anchor={"bfq": "tencent_qt", "hfq": "tencent_kline"},
        fallback={"bfq": ("sina_etf_kline",), "hfq": ("em_kline",)},
        universe="etf_master", coverage_kind="etf", close_confirm="A",
        schedule_start={"bfq": time(15, 15), "hfq": time(15, 20)},
        target_time={"bfq": time(15, 30), "hfq": time(16, 30)},
        escalate_after=timedelta(hours=2), coverage_min=0.995, max_workers=6,
    ),
    "legacy_index": DatasetSpec(
        name="legacy_index", table="bp_index_quote_daily", key_column="symbol",
        value_kind="bar", adjust_modes=("bfq", "hfq"),
        anchor={"bfq": "legacy_multi", "hfq": "legacy_multi"},
        fallback={"bfq": (), "hfq": ()},
        universe="legacy_config", coverage_kind="index", close_confirm="A",
        schedule_start={"bfq": time(16, 10), "hfq": time(16, 10)},
        target_time={"bfq": time(16, 40), "hfq": time(16, 40)},
        escalate_after=timedelta(hours=2), coverage_min=0.90, max_workers=4,
    ),
    "fund_nav": DatasetSpec(
        name="fund_nav", table="bp_fund_nav_daily", key_column="fund_code",
        value_kind="nav", adjust_modes=(),
        anchor={"nav": "em_rankhandler"},
        fallback={"nav": ("em_lsjz",)},
        universe="fund_master", coverage_kind="fund", close_confirm="FUND",
        schedule_start={"nav": time(20, 0)},
        target_time={"nav": _MID},
        escalate_after=timedelta(hours=1), coverage_min=0.99, max_workers=6,
    ),
}

validate_registry(REGISTRY, SOURCES)