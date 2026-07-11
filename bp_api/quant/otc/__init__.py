"""场外结构化产品定价引擎 (OTC structured-product pricing).

采用 Product / Engine / Process 三层解耦，以纯 numpy/scipy 独立实现。
参数命名参考开源项目 pricelib 的公开接口: barrier_out / barrier_in / coupon_out / coupon_div /
lock_term, Phoenix.barrier_yield/coupon, Airbag.knockin_parti/call_parti,
BarrierOption.updown/inout/callput。

品种: 雪球 Snowball / 凤凰 Phoenix / 气囊 Airbag / 障碍 Barrier
算法: 蒙特卡洛 MC(全品种) + 解析 Analytic(障碍/气囊)
Greeks: bump-and-reprice + 公共随机数 (delta/gamma/vega/theta/rho)
"""

from __future__ import annotations

from .enums import (
    CallPut,
    DayCount,
    DealStatus,
    Direction,
    EngineType,
    InOut,
    ProductType,
    UpDown,
)
from .pricer import PriceResult, price_deal

__all__ = [
    "CallPut",
    "DayCount",
    "DealStatus",
    "Direction",
    "EngineType",
    "InOut",
    "ProductType",
    "UpDown",
    "PriceResult",
    "price_deal",
]
