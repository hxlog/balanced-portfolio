"""场外衍生品 API 请求/响应模型 (pydantic v2)。"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class OtcPriceIn(BaseModel):
    """定价输入。不同品种用到的字段不同, 未用字段忽略即可。"""

    model_config = ConfigDict(extra="ignore")

    # 通用
    product_type: str = Field(description="snowball/phoenix/airbag/barrier")
    direction: str = "buy"                    # buy / sell
    engine: str = "mc"                        # mc / analytic / pde
    underlying_symbol: str
    underlying_source: str = "cn_index_em"

    start_date: date                          # 初始观察日
    maturity_date: date                       # 到期观察日
    valuation_date: Optional[date] = None     # 估值日(默认=初始观察日)

    s0: float = Field(gt=0, description="初始观察日指数点位, 如 6000")
    spot: Optional[float] = Field(default=None, description="估值日点位(缺省由历史推断)")

    r: float = 0.02                           # 无风险利率
    q: float = 0.0                            # 分红率/贴水
    vol: float = Field(gt=0, description="成交波动率")
    notional: float = Field(default=10_000_000.0, gt=0)

    day_count: str = "ACT365"                 # ACT365 / ACT360 / BUS252
    t_step_per_year: int = 252
    n_paths: int = Field(default=500_000, ge=1_000, le=2_000_000)
    mc_batch: int = Field(default=20_000, ge=1_000, le=200_000)
    seed: int = 42
    greeks: bool = True

    # 雪球 / 凤凰
    ko_barrier_pct: Optional[float] = 103.0
    ki_barrier_pct: Optional[float] = 75.0
    ki_strike_pct: Optional[float] = 80.0
    coupon_out: Optional[float] = None        # 敲出票息(年化)
    coupon_div: Optional[float] = None        # 红利/期末票息(年化)
    ko_freq_months: int = 1
    lock_term_months: int = 0
    ko_observation_dates: Optional[list[date]] = None
    already_ki: bool = False
    # 凤凰
    coupon_barrier_pct: Optional[float] = None  # 派息障碍
    period_coupon: Optional[float] = None        # 每期派息(占名义比例)

    # 气囊
    strike_pct: Optional[float] = None
    barrier_pct: Optional[float] = None
    knockin_parti: Optional[float] = None
    call_parti: Optional[float] = None
    reset_call_parti: Optional[float] = None

    # 障碍
    rebate: Optional[float] = None
    parti: Optional[float] = None
    updown: Optional[str] = None              # up / down
    inout: Optional[str] = None              # in / out
    callput: Optional[str] = None            # call / put
    discrete_obs: bool = True

    @field_validator("product_type")
    @classmethod
    def _ptype(cls, v: str) -> str:
        if v not in ("snowball", "phoenix", "airbag", "barrier"):
            raise ValueError(f"未知品种: {v}")
        return v

    @field_validator("direction")
    @classmethod
    def _dir(cls, v: str) -> str:
        if v not in ("buy", "sell"):
            raise ValueError("交易方向须为 buy/sell")
        return v

    @model_validator(mode="after")
    def _defaults_and_checks(self):
        if self.maturity_date <= self.start_date:
            raise ValueError("到期观察日须晚于初始观察日")
        if self.valuation_date is None:
            self.valuation_date = self.start_date
        if self.product_type in ("snowball", "phoenix"):
            if self.coupon_out is None and self.product_type == "snowball":
                raise ValueError("雪球需填写敲出票息 coupon_out")
            if self.coupon_div is None and self.coupon_out is not None:
                self.coupon_div = self.coupon_out
        return self

    def to_spec(self) -> dict:
        """转成定价引擎所需的 spec(保留 date 对象)。"""
        return self.model_dump()

    def to_terms(self) -> dict:
        """转成可入库 JSONB(date→iso)。"""
        return self.model_dump(mode="json")


class ObservationDatesIn(BaseModel):
    start_date: date
    maturity_date: date
    dates: Optional[list[date]] = None       # 显式观察日(优先)
    freq_months: int = 1
    lock_term_months: int = 0


class OtcDealCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    params: OtcPriceIn


class OtcDealUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    params: OtcPriceIn


class ReorderOtcDealsIn(BaseModel):
    ordered_ids: list[int]


class SetExampleIn(BaseModel):
    is_example: bool
